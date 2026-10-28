from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from ghost_league.pwa import WEB_ROOT, mount_web

ROOT = Path(__file__).resolve().parents[1]


class PWAStaticTests(unittest.TestCase):
    def test_01_manifest_and_icons(self) -> None:
        manifest = json.loads((WEB_ROOT / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "活动联赛")
        self.assertEqual(manifest["start_url"], "/")
        self.assertEqual(manifest["scope"], "/")
        self.assertEqual(manifest["display"], "standalone")
        self.assertIn("short_name", manifest)
        icons = {icon["src"]: icon for icon in manifest["icons"]}
        self.assertIn("/icons/icon-192.png", icons)
        self.assertIn("/icons/icon-512.png", icons)
        for path in ("/icons/icon-192.png", "/icons/icon-512.png", "/icons/maskable-512.png"):
            self.assertTrue((WEB_ROOT / path.lstrip("/")).is_file(), path)
        with Image.open(WEB_ROOT / "icons/icon-192.png") as icon:
            self.assertEqual(icon.size, (192, 192))
        with Image.open(WEB_ROOT / "icons/icon-512.png") as icon:
            self.assertEqual(icon.size, (512, 512))

    def test_01b_tier_icons_are_local_and_fully_mapped(self) -> None:
        slugs = (
            "bronze",
            "silver",
            "gold",
            "sapphire",
            "ruby",
            "emerald",
            "amethyst",
            "pearl",
            "obsidian",
            "diamond",
        )
        assets = WEB_ROOT / "assets" / "tiers"
        for slug in slugs:
            icon = assets / f"{slug}.png"
            self.assertTrue(icon.is_file(), icon)
            with Image.open(icon) as image:
                self.assertEqual(image.size, (1024, 1024))
            material_icon = assets / "material" / f"{slug}.png"
            self.assertTrue(material_icon.is_file(), material_icon)
            with Image.open(material_icon) as image:
                self.assertIn("A", image.getbands())
                self.assertEqual(image.width, image.height)
                self.assertLess(image.width, 512)
                bbox = image.getchannel("A").getbbox()
                self.assertIsNotNone(bbox)
                content_width = bbox[2] - bbox[0]
                content_height = bbox[3] - bbox[1]
                margin = max(1, round(min(content_width, content_height) * 0.04))
                self.assertEqual(
                    image.width,
                    max(content_width, content_height) + margin * 2,
                )
            card_icon = assets / "card" / "material" / f"{slug}.png"
            self.assertTrue(card_icon.is_file(), card_icon)
            with Image.open(card_icon) as image:
                self.assertIn("A", image.getbands())
                self.assertEqual(image.width, image.height)
                self.assertLess(image.width, 160)
        js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
        meta_block = js[js.index("const TIER_META"):js.index("const TIER_LABELS")]
        theme_block = js[js.index("const TIER_THEMES"):js.index("const TIER_META")]
        self.assertEqual(meta_block.count("slug:"), 10)
        self.assertNotIn("icon:", meta_block)
        self.assertIn('classic: { label: "经典", directory: "" }', theme_block)
        self.assertIn('material: { label: "Material", directory: "material" }', theme_block)
        self.assertIn("function tierIconUrl(slug, theme = DEFAULT_ICON_THEME)", js)
        self.assertIn("return `/assets/tiers/${selected.directory", js)
        render_block = js[js.index("function renderTierSlots"):js.index("function renderLeagueHero")]
        self.assertIn("tierIconUrl(info.slug, safeTheme)", render_block)
        self.assertNotIn("info.icon", render_block)
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        for element_id in (
            "league-tier-icon",
            "league-tier-name",
            "league-group-meta",
            "league-days-left",
            "league-tier-slots",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertNotIn("◆", html + js)
        css = (WEB_ROOT / "style.css").read_text(encoding="utf-8")
        self.assertIn("grayscale(1) brightness(0.55)", css)
        for marker in (
            "is-promotion",
            "is-demotion",
            "rank-medal",
            "standing-zone",
            "league-tier-slot",
        ):
            self.assertIn(marker, js + css)

    def test_01c_tier_rail_renders_all_tiers_with_fog(self) -> None:
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
        css = (WEB_ROOT / "style.css").read_text(encoding="utf-8")
        self.assertIn('aria-label="段位进度，左右滑动查看"', html)
        self.assertIn("10 个段位 · 左右滑动查看", html)
        self.assertIn('container.setAttribute("aria-label", "段位进度，左右滑动查看")', js)
        render_block = js[js.index("function renderTierSlots"):js.index("function renderLeagueHero")]
        self.assertIn("TIER_ORDER.forEach", render_block)
        self.assertNotIn("offset < 3", render_block)
        for marker in ("is-current", "is-reached", "is-fogged"):
            self.assertIn(marker, render_block)
        self.assertIn('label.textContent = isFogged ? "未解锁" : tierLabel(slotTier)', render_block)
        self.assertIn('slot.title = "未解锁"', render_block)
        self.assertIn('slot.setAttribute("aria-label", "未解锁段位")', render_block)
        for declaration in (
            "display: flex",
            "width: 100%",
            "max-width: none",
            "overflow-x: auto",
            "scroll-snap-type: x mandatory",
            "-webkit-overflow-scrolling: touch",
            "flex: 0 0 auto",
            "width: clamp(5rem, 19vw, 5.5rem)",
            "scroll-snap-align: center",
        ):
            self.assertIn(declaration, css)
        self.assertNotIn(".league-tier-slots::before", css)
        self.assertNotIn(".league-tier-slots::after", css)
        self.assertNotIn("max-width: 28rem", css)
        center_block = js[js.index("function centerTierRail"):js.index("function setupTierRailScroll")]
        self.assertIn("target = 0", center_block)
        self.assertIn("target = maxScroll", center_block)
        self.assertIn("Math.max(0, Math.min(maxScroll", center_block)
        self.assertIn("centerTierRail", js)

    def test_02_shell_has_local_assets_and_pwa_hooks(self) -> None:
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn('rel="manifest"', html)
        self.assertIn('href="/style.css?v=33"', html)
        self.assertIn('src="/app.js?v=33"', html)
        self.assertIn('id="icon-theme-options"', html)
        self.assertIn('name="icon_theme"', html)
        self.assertIn(">经典<", html)
        self.assertIn(">Material<", html)
        self.assertEqual(html.count('class="theme-preview"'), 6)
        for slug in ("bronze", "gold", "diamond"):
            self.assertIn(f'src="/assets/tiers/{slug}.png"', html)
            self.assertIn(f'src="/assets/tiers/material/{slug}.png"', html)
        self.assertIn("function tierIconUrl(slug, theme = DEFAULT_ICON_THEME)", js)
        self.assertIn("function renderThemePicker()", js)
        self.assertIn("profile.icon_theme", js)
        self.assertIn("json: {", js)
        self.assertIn("icon_theme: iconTheme", js)
        self.assertIn("renderTierSlots(", js)
        submit_block = js[
            js.index('el["profile-form"].addEventListener'):
            js.index('el["choose-avatar-button"].addEventListener')
        ]
        self.assertNotIn("location.reload()", submit_block)
        self.assertNotIn("function xp(seconds)", js)
        self.assertNotIn("Number(seconds) || 0) / 6", js)
        self.assertNotIn("function minutes(", js)
        self.assertNotIn("minutes(", js)
        self.assertIn("满 100 XP", html)
        self.assertNotIn("满 10 XP", html + js)
        self.assertIn("今日目标 100 XP", html)
        self.assertIn("const goal = requiredXp(status);", js)
        self.assertIn("const ratio = Math.min(1, todayXp / goal);", js)
        self.assertIn("status.today_xp", js)
        self.assertIn("status.xp", js)
        self.assertIn("status?.checkin", js)
        self.assertIn("status?.streak?.current", js)
        self.assertIn("required_xp", js)
        self.assertIn("beforeinstallprompt", js)
        self.assertIn('serviceWorker.register("/sw.js")', js)
        self.assertIn("localStorage", js)
        self.assertIn("cache: \"no-store\"", js)
        self.assertIn("AudioContext", js)
        self.assertIn("prefers-reduced-motion", js)
        self.assertIn("还没有结束的赛季", html)
        self.assertIn('content="联赛"', html)
        for heading in ("你的每周联赛", "今日打卡", "本周", "我的小组", "联赛", "个人", "历史", "余烬"):
            self.assertIn(heading, html)
        for english in ("YOUR WEEKLY LEAGUE", "MY TIER", "TODAY'S CHECK-IN", "THIS WEEK", "MY GROUP", "PROFILE", "SEASONS"):
            self.assertNotIn(english, html)
            self.assertNotIn(english, js)
        self.assertNotIn("Bronze", html)
        self.assertIn('id="share-card-button"', html)
        self.assertIn('id="activity-label-input"', html)
        self.assertIn('活动（填动词）', html)
        self.assertIn("activityLabel", js)
        self.assertIn("activity_label", js)
        self.assertIn("shareActivityLabel", js)
        self.assertIn("buildShareCard", js)
        self.assertIn("shareCard", js)
        self.assertIn("1080", js)
        self.assertIn("1440", js)
        self.assertIn("navigator.share", js)
        self.assertIn("navigator.canShare", js)
        self.assertIn("downloadBlob", js)
        self.assertIn("league-", js)
        for card_text in (
            "第 ${rank} 名 / ${groupSize}",
            "${streakDays} 天连胜",
            "还差 ${remaining} XP 打卡",
            "我的每周${shareActivityLabel()}联赛",
            "canvas.width = SHARE_WIDTH",
        ):
            self.assertIn(card_text, js)
        build_block = js[js.index("async function buildShareCard"):js.index("function downloadBlob")]
        self.assertNotIn("api(", build_block)
        self.assertNotIn("fetch(", build_block)
        self.assertIn("TIER_LABELS", js)
        visible = html + js
        self.assertNotIn("绘画", visible)
        for hardcoded in ("画满", "继续画", "绘画联赛"):
            self.assertNotIn(hardcoded, visible)
        for forbidden in (
            "对手 · 整点",
            "你 · 实时",
            "小组实时排名",
            "每次刷新",
            "你的累计实时更新",
        ):
            self.assertNotIn(forbidden, visible)
        # The API integration page intentionally documents seconds in its JSON
        # and curl examples; the league UI itself displays XP.
        shell_html = html[:html.index('data-page="integration"')] + html[html.index('data-page="history"'):]
        self.assertNotIn("秒", shell_html + js)
        self.assertNotIn("分钟", html)
        self.assertIn("XP", html)
        self.assertNotIn("小时", js)
        style = (WEB_ROOT / "style.css").read_text(encoding="utf-8")
        self.assertIn(".theme-options { display: grid;", style)
        self.assertIn(".theme-option.is-selected", style)
        self.assertIn(".theme-option-state", style)
        self.assertIn(".theme-preview", style)
        self.assertIn("height: 11rem;", style)
        self.assertIn("height: 12rem;", style)
        self.assertIn("@media (max-width: 460px)", style)
        self.assertNotIn("week-bar", style)
        self.assertIn("grid-template-columns: repeat(5, 1fr);", style)
        desktop = style[style.rindex("@media (min-width: 1100px)"):]
        self.assertIn("grid-template-columns: minmax(0, 1fr);", desktop)
        self.assertIn(".nav-button { width: 100%;", desktop)
        self.assertIn("groupLabel", js)
        for label in ("青铜", "白银", "黄金", "蓝宝石", "红宝石", "翡翠", "紫水晶", "珍珠", "黑曜石", "钻石"):
            self.assertIn(label, js)
        for route in (
            '"/v1/me/profile"',
            '"/v1/me/avatar"',
            '"/v1/me/status"',
            '"/v1/me/league"',
            '"/v1/league/standings"',
            '"/v1/league/history"',
            '"/v1/me/embers"',
            '"/v1/me/repair"',
            "/v1/me/checkins?week_start=",
            '"/v1/me/collection"',
            '"/v1/me/loadout"',
        ):
            self.assertIn(route, js)
        for old_field in (
            "week_total_seconds",
            "today_seconds",
            "checked_in_today",
            "current_streak",
            "next_checkin_at",
            "snapshot_hour",
            "payload.history",
        ):
            self.assertNotIn(old_field, js)
        self.assertNotIn('"/v1/me/streak"', js)
        self.assertIn("30_000", js)
        self.assertIn("visibilitychange", js)
        self.assertNotIn("location.search", js)
        html_urls = re.findall(r"https?://[^\s\"'<>]+", html)
        self.assertTrue(html_urls)
        for url in html_urls:
            self.assertTrue(url.startswith("https://your-host.example"), url)
        self.assertNotIn("cdn.", html.lower())
        self.assertNotIn("synthetic", (html + js).lower())
        self.assertNotIn("模拟", html + js)
        self.assertNotIn("真人", html)
        self.assertNotIn("伪实时", html + js)

    def test_02b_icon_theme_sizes_are_scoped_by_css_marker(self) -> None:
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
        css = (WEB_ROOT / "style.css").read_text(encoding="utf-8")
        self.assertIn('<html lang="zh-CN" data-icon-theme="classic">', html)
        self.assertIn(
            "document.documentElement.dataset.iconTheme = normalizeIconTheme(theme);",
            js,
        )
        self.assertIn("applyIconTheme(selected);", js)
        for declaration in (
            ':root[data-icon-theme="classic"] .tier-icon { width: 4.4rem; height: 4.4rem; }',
            ':root[data-icon-theme="material"] .tier-icon { width: 5rem; height: 5rem; }',
            ':root[data-icon-theme="classic"] .league-tier-emblem { width: clamp(84px, 24vw, 112px); }',
            ':root[data-icon-theme="material"] .league-tier-emblem { width: clamp(120px, 30vw, 132px); }',
            ':root[data-icon-theme="classic"] .league-tier-slot-icon { width: clamp(42px, 12vw, 54px); height: clamp(42px, 12vw, 54px); }',
            ':root[data-icon-theme="material"] .league-tier-slot-icon { width: clamp(58px, 15vw, 64px); height: clamp(58px, 15vw, 64px); }',
        ):
            self.assertIn(declaration, css)

    def test_03_service_worker_policy(self) -> None:
        sw = (WEB_ROOT / "sw.js").read_text(encoding="utf-8")
        self.assertIn("CACHE_VERSION", sw)
        self.assertIn("skipWaiting", sw)
        self.assertIn("clients.claim", sw)
        self.assertIn("request.mode === \"navigate\"", sw)
        self.assertIn("fetch(request)", sw)
        self.assertIn("isApiRequest", sw)
        self.assertIn("url.pathname.startsWith(\"/v1/\")", sw)
        self.assertIn("url.pathname.startsWith(\"/avatars/\")", sw)
        self.assertIn("caches.delete", sw)
        self.assertIn("/assets/frames/frame_ember.png", sw)
        self.assertIn('const CACHE_VERSION = "gl-shell-v33-2026-10-29";', sw)
        # Historical cache generation comment is kept for rollback context.
        self.assertIn("gl-shell-v32-2026-10-28", sw)
        self.assertIn("gl-shell-v28-2026-10-28", sw)
        self.assertIn("gl-shell-v27-2026-10-28", sw)
        self.assertIn("gl-shell-v26-2026-10-28", sw)
        self.assertIn("gl-shell-v25-2026-10-27", sw)
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("/style.css?v=33", sw)
        self.assertIn("/app.js?v=33", sw)
        self.assertIn('href="/style.css?v=33"', html)
        self.assertIn('src="/app.js?v=33"', html)
        self.assertNotIn("/style.css?v=28", sw)
        self.assertNotIn("/app.js?v=28", sw)
        self.assertNotIn('href="/style.css?v=28"', html)
        self.assertNotIn('src="/app.js?v=28"', html)
        for slug in (
            "bronze",
            "silver",
            "gold",
            "sapphire",
            "ruby",
            "emerald",
            "amethyst",
            "pearl",
            "obsidian",
            "diamond",
        ):
            self.assertIn(f"/assets/tiers/{slug}.png", sw)
            self.assertIn(f"/assets/tiers/material/{slug}.png", sw)

    def test_03a_current_tier_is_not_duplicated(self) -> None:
        js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
        overview = js[
            js.index("function renderMeOverview"):
            js.index("function renderUserDetail")
        ]
        self.assertIn(
            'el["me-tier"].textContent = groupLabel(status.group);',
            overview,
        )
        self.assertIn('el["me-week-xp"].textContent = `${number(status.xp)} XP`;', overview)
        group_block = js[js.index("function groupLabel"):js.index("function groupCode")]
        self.assertIn(
            "return `${TIER_LABELS[match[1]] || match[1]} · ${match[2]}`;",
            group_block,
        )
        self.assertIn(
            'return `${tierLabel(group.tier)} · ${groupCode(group)}`;',
            group_block,
        )
        people_block = js[js.index("function renderPeople"):js.index("async function loadPeople")]
        self.assertIn("bits.push(`${number(person.xp)} XP`);", people_block)

    @unittest.skipUnless(shutil.which("node"), "node is not available")
    def test_03b_group_label_includes_tier_and_group_code_once(self) -> None:
        js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
        labels = re.search(r"const TIER_LABELS = \{.*?\};", js, re.DOTALL)
        self.assertIsNotNone(labels)
        group_block = js[js.index("function groupLabel"):js.index("function groupCode")]
        completed = subprocess.run(
            [
                "node",
                "-e",
                f"{labels.group(0)}\n{group_block}\n"
                "process.stdout.write(groupLabel('Bronze-W53-G01'));",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "青铜 · W53-G01")

    def test_03c_new_game_api_mapping_is_explicit(self) -> None:
        js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        for field in (
            "status.xp",
            "status.today_xp",
            "status.rank",
            "status.group_size",
            "status.group",
            "status?.streak",
            "status?.required_xp",
            "state.standings?.standings",
            "payload.results",
            "embers.balance",
            "embers.ledger",
            "embers.earned_this_week",
            "repairCandidates",
        ):
            self.assertIn(field, js)
        for hidden in (
            "week_total_seconds",
            "today_seconds",
            "checked_in_today",
            "current_streak",
            "raw_seconds",
            "effective_seconds",
            "target_seconds",
            "anchor_seconds",
        ):
            self.assertNotIn(hidden, js)
        self.assertNotIn("kind", js[js.index("function standingMeta"):js.index("function appendZoneDivider")])
        for element_id in (
            "home-ember-button",
            "home-ember-balance",
            "repair-box",
            "repair-date",
            "repair-button",
            "ember-balance",
            "ember-ledger",
            "ember-ledger-empty",
        ):
            self.assertIn(f'id="{element_id}"', html)
        for text in ("余烬", "补签", "每 2,000 XP 获得 1 枚", "每周最多", "持有上限"):
            self.assertIn(text, html)

    def test_03d_no_ai_labels_or_markup_and_waiting_empty_state(self) -> None:
        shell = {
            path: (WEB_ROOT / path).read_text(encoding="utf-8")
            for path in ("app.js", "index.html", "style.css", "sw.js", "manifest.webmanifest")
        }
        js = shell["app.js"]
        html = shell["index.html"]
        for forbidden in (
            "isAiMember",
            "ai-tag",
            "user-detail-ai",
            "is_ai",
            "AI 玩家",
            "机器人",
            ">AI<",
            "AI-",
        ):
            for path, text in shell.items():
                self.assertNotIn(forbidden, text, f"{forbidden!r} leaked into {path}")
        for path, text in shell.items():
            self.assertNotRegex(text, r"(?<![A-Za-z])AI(?![A-Za-z])", path)
        self.assertIn("等待数据", js)
        self.assertIn("等待数据", html)
        profile_block = js[js.index("function renderProfile"):js.index("function renderHome")]
        self.assertIn('? groupLabel(status.group)', profile_block)
        self.assertNotIn("profile.group_no", profile_block)
        standings_block = js[js.index("function renderStandings"):js.index("async function loadFriendsStandings")]
        self.assertIn("const hasGroup = Boolean(payload.group);", standings_block)
        self.assertIn('? snapshotLabel(payload)', standings_block)
        self.assertIn('"等待数据"', standings_block)

    def test_04_no_remote_urls_in_shell(self) -> None:
        for path in ("index.html", "app.js", "style.css", "sw.js", "manifest.webmanifest"):
            text = (WEB_ROOT / path).read_text(encoding="utf-8")
            for url in re.findall(r"https?://[^\s\"'<>]+", text):
                self.assertTrue(url.startswith("https://your-host.example"), (path, url))

    def test_05_mount_serves_shell_and_keeps_api_priority(self) -> None:
        app = FastAPI()

        @app.get("/v1/ping")
        def ping() -> dict:
            return {"ok": True}

        mount_web(app)
        with TestClient(app) as client:
            root = client.get("/")
            self.assertEqual(root.status_code, 200)
            self.assertIn("联赛", root.text)
            manifest = client.get("/manifest.webmanifest")
            self.assertEqual(manifest.status_code, 200)
            self.assertIn("manifest+json", manifest.headers["content-type"])
            tier_icon = client.get("/assets/tiers/bronze.png")
            self.assertEqual(tier_icon.status_code, 200)
            self.assertIn("image/png", tier_icon.headers["content-type"])
            sw = client.get("/sw.js")
            self.assertEqual(sw.status_code, 200)
            self.assertIn("javascript", sw.headers["content-type"])
            api = client.get("/v1/ping")
            self.assertEqual(api.status_code, 200)
            self.assertEqual(api.json(), {"ok": True})

    def test_06_launcher_and_service_template(self) -> None:
        launcher = ROOT / "scripts" / "run_pwa.sh"
        unit = ROOT / "deploy" / "ghost-league-web.service"
        self.assertTrue(launcher.is_file())
        self.assertTrue(unit.is_file())
        self.assertTrue(launcher.stat().st_mode & 0o100)
        script = launcher.read_text(encoding="utf-8")
        service = unit.read_text(encoding="utf-8")
        self.assertIn('PORT="${GHOST_LEAGUE_WEB_PORT:-8445}"', script)
        self.assertIn('HOST="${GHOST_LEAGUE_WEB_HOST:-127.0.0.1}"', script)
        self.assertIn("--ssl-certfile", script)
        self.assertIn("--ssl-keyfile", script)
        self.assertIn("ghost_league.pwa:app", script)
        self.assertNotIn("GHOST_LEAGUE_TOKEN=", script)
        self.assertNotIn("198.51.100.10", script)
        self.assertIn("ExecStart=/srv/ghost-league/scripts/run_pwa.sh", service)
        self.assertIn("deploy/tls/", (ROOT / ".gitignore").read_text(encoding="utf-8"))

    def test_08_integration_docs_page_is_mobile_friendly_and_generic(self) -> None:
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
        css = (WEB_ROOT / "style.css").read_text(encoding="utf-8")
        self.assertIn('id="integration-docs-row"', html)
        self.assertIn('data-page="integration"', html)
        start = html.index('data-page="integration"')
        end = html.index('data-page="history"', start)
        page = html[start:end]
        for required in (
            "Authorization: Bearer $GHOST_LEAGUE_TOKEN",
            "POST /v1/me/increments",
            '"event_id": "unique-event-id"',
            '"seconds": 137',
            "GET /v1/me/status",
            "GET /v1/me/league",
            "GET /v1/league/standings",
            "GET /v1/league/history",
            "GET /v1/me/embers",
            "POST /v1/me/repair",
            "GET /v1/me/checkins?week_start=",
            "GET /v1/me/friends/standings",
            "window.location.origin",
            "https://your-host.example",
            "data-copy-code",
            "event_id",
        ):
            self.assertIn(required, page)
        for forbidden in ("幽灵", "synthetic", "模拟", "伪实时", "10.19.", "/root/", "sample-user"):
            self.assertNotIn(forbidden, page.lower())
        self.assertIn('id="rotate-token-button"', html)
        self.assertIn('"/v1/me/token/rotate"', js)
        self.assertIn("navigator.clipboard", js)
        self.assertIn("overflow-x: auto", css)
        self.assertIn("min-width: 0", css)

    @unittest.skipUnless(shutil.which("node"), "node is not available")
    def test_07_javascript_syntax(self) -> None:
        for filename in ("app.js", "sw.js"):
            completed = subprocess.run(
                ["node", "--check", str(WEB_ROOT / filename)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
