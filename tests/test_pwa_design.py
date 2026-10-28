from __future__ import annotations

import re
import unittest

from ghost_league.pwa import WEB_ROOT


class PWADesignMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        cls.js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
        cls.css = (WEB_ROOT / "style.css").read_text(encoding="utf-8")
        cls.sw = (WEB_ROOT / "sw.js").read_text(encoding="utf-8")

    def test_01_motion_tokens_are_declared_and_bounded(self) -> None:
        for token in (
            "--motion-fast: 140ms;",
            "--motion-base: 240ms;",
            "--motion-slow: 420ms;",
            "--motion-score: 620ms;",
            "--motion-celebrate: 900ms;",
            "--ease-standard:",
            "--ease-out:",
            "--ease-spring:",
        ):
            self.assertIn(token, self.css)
        self.assertIn("const SCORE_MS = 620;", self.js)
        self.assertIn('const EASE_OUT = "cubic-bezier(0.22, 1, 0.36, 1)";', self.js)
        # Celebrations must be finite. The canvas burst is capped and time-boxed.
        self.assertIn("Math.min(64, Math.max(24", self.js)
        self.assertIn("const duration = 1300;", self.js)
        self.assertIn("confettiFrame = requestAnimationFrame(draw);", self.js)
        self.assertNotIn("  requestAnimationFrame(draw);", self.js)
        self.assertNotIn("@keyframes float", self.css)

    def test_02_feedback_state_machine_is_interruptible(self) -> None:
        for hook in (
            "function cancelTransientFeedback()",
            "function applyProgressFeedback(",
            "function showMoment(",
            "function hideMoment()",
            "function stopConfetti()",
            "function settleMotionState()",
            "activeNumberNodes",
            "numberAnimations",
            "momentHideTimer",
        ):
            self.assertIn(hook, self.js)
        self.assertIn("cancelTransientFeedback();", self.js)
        self.assertIn('el["moment-overlay"].hidden = true;', self.js)
        # A second update must cancel the old number/ring/confetti cues.
        self.assertIn("cancelAnimationFrame(active.frame)", self.js)
        self.assertIn("ringAnimation.cancel()", self.js)
        self.assertIn("cancelAnimationFrame(confettiFrame)", self.js)
        self.assertIn("if (!confettiVisible) return;", self.js)

    def test_03_reduced_motion_and_visibility_have_static_fallbacks(self) -> None:
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.css)
        self.assertIn(".confetti-canvas { display: none; }", self.css)
        self.assertIn(
            ".page, .standing-row, .delta-chip, .moment-card, .ring-card, .rank-card, .streak-card .flame {",
            self.css,
        )
        animate_block = self.js[
            self.js.index("function animateNumber"):self.js.index("function setRingProgress")
        ]
        self.assertIn("if (reducedMotionQuery.matches)", animate_block)
        self.assertIn("settleNumber(node);", animate_block)
        confetti_block = self.js[
            self.js.index("function runConfetti"):self.js.index("function init()")
        ]
        self.assertIn('if (reducedMotionQuery.matches || document.visibilityState === "hidden") return;', confetti_block)
        self.assertIn('document.body.classList.add("is-page-hidden")', self.js)
        self.assertIn("settleMotionState();", self.js)
        self.assertIn(".is-page-hidden .spinner,", self.css)
        self.assertIn("animation-play-state: paused;", self.css)

    def test_04_feedback_surfaces_exist_and_rank_direction_differs(self) -> None:
        for element_id in (
            "refresh-button",
            "sync-status",
            "ring-card",
            "today-progress",
            "xp-delta",
            "rank-change",
            "streak-delta",
            "tier-rail-summary",
            "moment-overlay",
            "moment-kicker",
            "moment-title",
            "moment-copy",
            "live-status",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn('aria-live="assertive"', self.html)
        self.assertIn('role="progressbar" aria-label="今日打卡进度"', self.html)
        self.assertIn('role="status"', self.html)
        self.assertIn("rankDelta > 0 ? \"is-up\" : \"is-down\"", self.js)
        self.assertIn(".rank-card.is-rank-up", self.css)
        self.assertIn(".rank-card.is-rank-down", self.css)
        self.assertIn("@keyframes rank-rise", self.css)
        self.assertIn("@keyframes rank-fall", self.css)
        self.assertIn(".delta-chip.is-down", self.css)
        # A rank fall uses a muted gold cue, not a red flash.
        down_rule = self.css[
            self.css.index(".delta-chip.is-down"):self.css.index(".delta-chip.is-neutral")
        ]
        self.assertIn("#ffda8e", down_rule)
        self.assertNotIn("var(--danger)", down_rule)

    def test_05_tier_rail_keeps_scroll_and_updates_summary(self) -> None:
        rail_block = self.js[
            self.js.index("function renderTierSlots"):self.js.index("function renderLeagueHero")
        ]
        self.assertIn("const renderKey = `${safeTier}|${safeTheme}`;", rail_block)
        self.assertIn("if (container.dataset.renderKey === renderKey", rail_block)
        self.assertIn("const scrollRatio = previousMaxScroll > 0", rail_block)
        self.assertIn("container.scrollLeft = scrollRatio * maxScroll;", rail_block)
        self.assertIn("已解锁 ${currentIndex + 1} / ${TIER_ORDER.length}", self.js)
        self.assertIn('role="list"', self.html)
        self.assertIn('aria-current", "step"', rail_block)
        self.assertNotIn(".league-tier-slots::before", self.css)
        self.assertNotIn(".league-tier-slots::after", self.css)

    def test_06_responsive_and_focus_styles_remain(self) -> None:
        for declaration in (
            ":focus-visible",
            "min-width: 0;",
            "text-overflow: ellipsis;",
            "white-space: nowrap;",
            "overflow-x: auto;",
            "@media (max-width: 460px)",
            "@media (min-width: 680px)",
            "@media (min-width: 1100px)",
        ):
            self.assertIn(declaration, self.css)
        me_layout = self.css[
            self.css.index(".me-layout"):self.css.index(".me-overview-card")
        ]
        self.assertIn("display: grid", me_layout)
        self.assertIn(".danger-zone", self.css)
        self.assertIn(".preference-card, .account-card", self.css)
        # No horizontal page overflow from long list names.
        self.assertIn("minmax(0, 1fr)", self.css)

    def test_07_shell_cache_is_bumped_without_removing_previous_marker(self) -> None:
        self.assertIn('const CACHE_VERSION = "gl-shell-v31-2026-10-28";', self.sw)
        self.assertIn("gl-shell-v30-2026-10-28", self.sw)
        self.assertIn("gl-shell-v29-2026-10-28", self.sw)
        self.assertIn("gl-shell-v28-2026-10-28", self.sw)
        self.assertIn("gl-shell-v27-2026-10-28", self.sw)
        self.assertIn("gl-shell-v26-2026-10-28", self.sw)
        self.assertIn("gl-shell-v25-2026-10-27", self.sw)
        self.assertIn("caches.delete", self.sw)
        self.assertIn("/style.css?v=31", self.sw)
        self.assertIn("/app.js?v=31", self.sw)

    def test_09_ember_and_repair_surfaces_keep_mobile_layout(self) -> None:
        for element_id in (
            "home-ember-balance",
            "repair-date",
            "repair-button",
            "ember-balance",
            "ember-ledger",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        for declaration in (
            ".embers-layout { display: grid;",
            ".ember-ledger-row { display: flex;",
            ".repair-controls { display: flex; flex-wrap: wrap;",
            "grid-template-columns: repeat(5, 1fr);",
        ):
            self.assertIn(declaration, self.css)
        self.assertIn("每 2,000 XP 获得 1 枚", self.html)
        self.assertIn("补签 1 天消耗 1 枚", self.html)
        self.assertIn("function renderEmbers()", self.js)
        self.assertIn("function renderDailyActions()", self.js)
        self.assertIn("async function repairSelectedDay()", self.js)

    def test_08_browser_evidence_is_not_required_by_unit_tests(self) -> None:
        # Browser evidence lives in artifacts/final/report.json; guard only that
        # the dedicated check did not accidentally become a production asset.
        self.assertFalse((WEB_ROOT / "ui-check").exists())
        self.assertFalse((WEB_ROOT / "artifacts").exists())
        self.assertFalse(re.search(r"ui-check-token|ui-evidence-token", self.html + self.js))


if __name__ == "__main__":
    unittest.main()
