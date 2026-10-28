from __future__ import annotations

import io
import json
import re
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from ghost_league.accounts import AccountsStore, hash_token
from ghost_league.api import create_app
from ghost_league.badge import (
    BADGE_GEOMETRIES,
    MATERIAL_ICON_SIZES,
    TIER_SLUGS,
    render_badge,
    render_embed,
    xml_escape,
)
from ghost_league.schedule import TZ

TOKEN = "test-token-only"
FRIEND_TOKEN = "friend-token-only"
FRIEND2_TOKEN = "friend-two-token-only"
CHANNEL_TOKEN = "test-channel-token"
CHANNEL = "test-channel"
NOW = datetime(2026, 10, 26, 18, 36, 0, tzinfo=TZ)
WEEK_START = "2026-10-26"


def image_bytes(
    fmt: str = "PNG",
    size: tuple[int, int] = (320, 180),
    color: tuple[int, int, int] = (40, 120, 200),
) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return buffer.getvalue()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def write_cache(path: Path, *, rows: int = 40) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    users = [
        {
            "id": f"anchor-{index:03d}",
            "seconds": 500_000 - index * 10_000,
            "rank": index + 1,
        }
        for index in range(rows)
    ]
    path.write_text(
        json.dumps({"source": "test", "users": users}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


class APITestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.api_dir = self.base / "api"
        self.api_dir.mkdir(parents=True)
        self.cache_path = write_cache(self.base / "cache.json")
        self.game_db_path = self.api_dir / "league.db"
        self.clock = {"now": NOW}
        self.accounts_db = self.api_dir / "accounts.db"
        self.store = AccountsStore(
            self.accounts_db, now_fn=lambda: self.clock["now"]
        )
        self.store.initialize()
        self.store.create("owner", "You", token=TOKEN)

    def add_account(self, user_id: str, name: str, token: str) -> str:
        self.store.create(user_id, name, token=token)
        return token

    def app(self, *, token: str | None = TOKEN):
        return create_app(
            game_db_path=self.game_db_path,
            cache_path=self.cache_path,
            avatars_path=self.api_dir / "avatars.json",
            api_dir=self.api_dir,
            accounts_db=self.accounts_db,
            social_db=self.api_dir / "social.db",
            webhooks_db=self.api_dir / "webhooks.db",
            start_webhook_worker=False,
            token=token,
            channel_token=CHANNEL_TOKEN,
            now_fn=lambda: self.clock["now"],
        )

    def seed_channel_roster(self, client: TestClient, *, players: int = 14) -> None:
        response = client.post(
            f"/v1/channels/{CHANNEL}/roster",
            headers=auth(CHANNEL_TOKEN),
            json={
                "players": [
                    {"player_ref": f"channel-ai-{index:02d}", "kind": "ai"}
                    for index in range(players)
                ]
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    @contextmanager
    def client(self, *, token: str | None = TOKEN, seed_roster: bool = True):
        with TestClient(self.app(token=token)) as client:
            if seed_roster:
                self.seed_channel_roster(client)
            yield client

    def post_increment(
        self,
        client: TestClient,
        *,
        token: str = TOKEN,
        **overrides,
    ):
        payload = {
            "event_id": "draw-test-001",
            "seconds": 137,
            "occurred_at": self.clock["now"].isoformat(),
        }
        payload.update(overrides)
        return client.post(
            "/v1/me/increments",
            headers=auth(token),
            json=payload,
        )


class AuthAndHealthTests(APITestBase):
    def test_01_missing_or_wrong_token_is_401(self) -> None:
        with self.client() as client:
            self.assertEqual(client.get("/v1/me/status").status_code, 401)
            self.assertEqual(
                client.get(
                    "/v1/me/status",
                    headers={"Authorization": "Bearer wrong"},
                ).status_code,
                401,
            )
            response = client.post(
                "/v1/me/increments",
                json={"event_id": "x", "seconds": 1},
            )
            self.assertEqual(response.status_code, 401)

    def test_02_health_is_public_and_lists_no_accounts(self) -> None:
        with self.client() as client:
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(TOKEN, response.text)
            payload = response.json()
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["current_week"], WEEK_START)
            self.assertEqual(set(payload), {"status", "current_week", "timezone"})

    def test_03_bearer_scheme_is_case_insensitive(self) -> None:
        with self.client() as client:
            response = client.get(
                "/v1/me/league",
                headers={"Authorization": f"bearer {TOKEN}"},
            )
            self.assertEqual(response.status_code, 200)

    def test_08_public_surface_is_hardened(self) -> None:
        with self.client() as client:
            for path in ("/docs", "/redoc", "/openapi.json"):
                self.assertEqual(client.get(path).status_code, 404, path)
            health = client.get("/health")
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.headers["x-content-type-options"], "nosniff")
            self.assertEqual(
                health.headers["referrer-policy"],
                "strict-origin-when-cross-origin",
            )
            self.assertEqual(health.headers["x-frame-options"], "DENY")
            self.assertIn(
                "frame-ancestors 'none'", health.headers["content-security-policy"]
            )
            anonymous = client.get("/v1/me/profile")
            self.assertEqual(anonymous.status_code, 401)
            self.assertEqual(anonymous.headers["www-authenticate"], "Bearer")
            self.assertEqual(anonymous.headers["x-content-type-options"], "nosniff")
            self.assertNotIn("access-control-allow-origin", anonymous.headers)

    def test_09_token_rotation_returns_a_working_token_once(self) -> None:
        with self.client() as client:
            rotated = client.post("/v1/me/token/rotate", headers=auth(TOKEN))
            self.assertEqual(rotated.status_code, 200)
            payload = rotated.json()
            self.assertEqual(payload["user_id"], "owner")
            new_token = payload["token"]
            self.assertNotEqual(new_token, TOKEN)
            self.assertEqual(
                client.get("/v1/me/status", headers=auth(TOKEN)).status_code,
                401,
            )
            self.assertEqual(
                client.get("/v1/me/status", headers=auth(new_token)).status_code,
                200,
            )
        with self.accounts_db.open("rb") as handle:
            self.assertNotIn(TOKEN.encode(), handle.read())
        self.assertIn(hash_token(new_token), self._token_hashes())

    def _token_hashes(self) -> str:
        import sqlite3

        with sqlite3.connect(self.accounts_db) as connection:
            return " ".join(row[0] for row in connection.execute("SELECT token_hash FROM users"))


class AccountIdentityTests(APITestBase):
    def test_04_each_token_maps_to_its_own_account(self) -> None:
        self.add_account("friend-1", "Friend", FRIEND_TOKEN)
        with self.client() as client:
            mine = self.post_increment(client, event_id="mine", seconds=137)
            theirs = self.post_increment(
                client,
                token=FRIEND_TOKEN,
                event_id="theirs",
                seconds=137,
            )
            self.assertEqual(mine.status_code, 200)
            self.assertEqual(theirs.status_code, 200)
            self.assertEqual(
                client.get("/v1/me/status", headers=auth(TOKEN)).json()["user_id"],
                "owner",
            )
            self.assertEqual(
                client.get(
                    "/v1/me/status", headers=auth(FRIEND_TOKEN)
                ).json()["user_id"],
                "friend-1",
            )

    def test_05_same_event_id_is_independent_per_account(self) -> None:
        self.add_account("friend-1", "Friend", FRIEND_TOKEN)
        with self.client() as client:
            first = self.post_increment(client, event_id="shared", seconds=60)
            second = self.post_increment(
                client,
                token=FRIEND_TOKEN,
                event_id="shared",
                seconds=60,
            )
            self.assertFalse(first.json()["duplicate"])
            self.assertFalse(second.json()["duplicate"])
            replay = self.post_increment(client, event_id="shared", seconds=60)
            self.assertTrue(replay.json()["duplicate"])

    def test_06_account_add_does_not_change_current_user_token(self) -> None:
        with self.client() as client:
            self.assertEqual(
                client.get("/v1/me/status", headers=auth(TOKEN)).status_code,
                200,
            )
            self.add_account("friend-1", "Friend", FRIEND_TOKEN)
            self.assertEqual(
                client.get("/v1/me/status", headers=auth(TOKEN)).status_code,
                200,
            )
            self.assertEqual(
                client.get(
                    "/v1/me/status", headers=auth(FRIEND_TOKEN)
                ).status_code,
                200,
            )


class ProfileTests(APITestBase):
    def test_26_profile_update_and_only_self(self) -> None:
        self.add_account("friend-1", "Friend", FRIEND_TOKEN)
        with self.client() as client:
            updated = client.patch(
                "/v1/me/profile",
                headers=auth(TOKEN),
                json={
                    "display_name": "New Name",
                    "activity_label": "骑行",
                    "icon_theme": "material",
                },
            )
            self.assertEqual(updated.status_code, 200)
            payload = updated.json()
            self.assertEqual(payload["display_name"], "New Name")
            self.assertEqual(payload["activity_label"], "骑行")
            self.assertEqual(payload["icon_theme"], "material")
            self.assertIn("tier", payload)
            self.assertIn("group_id", payload)
            friend = client.get("/v1/me/profile", headers=auth(FRIEND_TOKEN)).json()
            self.assertEqual(friend["display_name"], "Friend")
            self.assertEqual(friend["activity_label"], "练习")

    def test_27_profile_rejects_blank_and_overlong_names(self) -> None:
        with self.client() as client:
            for payload in (
                {"display_name": ""},
                {"display_name": "   "},
                {"display_name": "x" * 33},
            ):
                response = client.patch(
                    "/v1/me/profile", headers=auth(TOKEN), json=payload
                )
                self.assertEqual(response.status_code, 422, payload)
            self.assertEqual(
                client.get("/v1/me/profile", headers=auth(TOKEN)).json()[
                    "display_name"
                ],
                "You",
            )


class IconThemeTests(APITestBase):
    def test_profile_icon_theme_round_trip_and_badge(self) -> None:
        with self.client() as client:
            response = client.patch(
                "/v1/me/profile",
                headers=auth(TOKEN),
                json={"icon_theme": "material"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["icon_theme"], "material")
            badge = client.get("/badge/owner.svg")
            self.assertEqual(badge.status_code, 200)
            self.assertIn('viewBox="0 0 880 280"', badge.text)

    def test_illegal_icon_theme_is_422_and_does_not_change_profile(self) -> None:
        with self.client() as client:
            response = client.patch(
                "/v1/me/profile",
                headers=auth(TOKEN),
                json={"icon_theme": "neon"},
            )
            self.assertEqual(response.status_code, 422)
            profile = client.get("/v1/me/profile", headers=auth(TOKEN)).json()
            self.assertEqual(profile["icon_theme"], "classic")


class AvatarTests(APITestBase):
    def test_28_png_avatar_is_cropped_and_served(self) -> None:
        with self.client() as client:
            response = client.post(
                "/v1/me/avatar",
                headers=auth(TOKEN),
                files={"file": ("avatar.png", image_bytes(), "image/png")},
            )
            self.assertEqual(response.status_code, 200)
            url = response.json()["avatar_url"]
            self.assertEqual(url, "/avatars/owner")
            served = client.get(url)
            self.assertEqual(served.status_code, 200)
            with Image.open(io.BytesIO(served.content)) as image:
                self.assertEqual(image.size, (256, 256))
            profile = client.get("/v1/me/profile", headers=auth(TOKEN)).json()
            self.assertEqual(profile["avatar_url"], url)

    def test_29_jpeg_webp_and_user_avatar_isolation(self) -> None:
        self.add_account("friend-1", "Friend", FRIEND_TOKEN)
        with self.client() as client:
            for fmt, content_type in (
                ("JPEG", "image/jpeg"),
                ("WEBP", "image/webp"),
            ):
                response = client.post(
                    "/v1/me/avatar",
                    headers=auth(TOKEN),
                    files={
                        "file": (
                            f"avatar.{fmt.lower()}",
                            image_bytes(fmt),
                            content_type,
                        )
                    },
                )
                self.assertEqual(response.status_code, 200, fmt)
            self.assertEqual(
                client.get("/avatars/friend-1").status_code, 404
            )
            friend = client.post(
                "/v1/me/avatar",
                headers=auth(FRIEND_TOKEN),
                files={"file": ("friend.png", image_bytes(), "image/png")},
            )
            self.assertEqual(friend.status_code, 200)
            self.assertEqual(
                client.get("/avatars/friend-1").status_code, 200
            )

    def test_30_rejects_fake_and_oversized_avatar(self) -> None:
        with self.client() as client:
            fake = client.post(
                "/v1/me/avatar",
                headers=auth(TOKEN),
                files={"file": ("fake.png", b"not an image", "image/png")},
            )
            self.assertEqual(fake.status_code, 415)
            too_big = client.post(
                "/v1/me/avatar",
                headers=auth(TOKEN),
                files={
                    "file": (
                        "big.png",
                        b"x" * (2 * 1024 * 1024 + 1),
                        "image/png",
                    )
                },
            )
            self.assertEqual(too_big.status_code, 413)

    def test_31_avatar_auth_404_and_traversal(self) -> None:
        with self.client() as client:
            self.assertEqual(client.get("/avatars/owner").status_code, 404)
            self.assertEqual(client.get("/avatars/..%2Faccounts.db").status_code, 404)
            self.assertEqual(
                client.post(
                    "/v1/me/avatar",
                    files={"file": ("avatar.png", image_bytes(), "image/png")},
                ).status_code,
                401,
            )


class BadgeAndEmbedTests(APITestBase):
    def _status(self, **overrides):
        base = {
            "user_id": "badge",
            "display_name": "Badge",
            "activity_label": "练习",
            "tier": "Bronze",
            "group": {"id": 1, "no": 1, "tier": "Bronze", "size": 15},
            "xp": 121,
            "today_seconds": 730,
            "today_xp": 121,
            "required_xp": 100,
            "checkin": "verified",
            "streak": {"current": 2},
            "rank": 3,
            "group_size": 15,
            "updated_at": "2026-10-26T18:36:00+08:00",
        }
        base.update(overrides)
        return base

    def test_badge_is_public_svg_with_new_status(self) -> None:
        with self.client() as client:
            increment = self.post_increment(
                client, event_id="badge-event", seconds=600
            )
            self.assertEqual(increment.status_code, 200)
            response = client.get("/badge/owner.svg")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("image/svg+xml"))
        self.assertEqual(response.headers["cache-control"], "no-store, max-age=0")
        self.assertEqual(response.headers["cdn-cache-control"], "no-store")
        self.assertEqual(
            response.headers["cloudflare-cdn-cache-control"], "no-store"
        )
        self.assertEqual(response.headers["access-control-allow-origin"], "*")
        self.assertIn("联赛状态", response.text)
        self.assertIn("青铜", response.text)
        self.assertIn("本周", response.text)
        self.assertIn("组内排名", response.text)
        self.assertIn("当前连胜", response.text)
        self.assertIn("今日 100 / 100 XP", response.text)
        self.assertIn("100 XP", response.text)
        self.assertIn("已打卡", response.text)
        self.assertNotIn(TOKEN, response.text)
        self.assertNotIn("kind", response.text)
        self.assertNotIn("raw", response.text)
        viewbox = re.search(r'viewBox="0 0 (\d+) (\d+)"', response.text)
        self.assertIsNotNone(viewbox)
        assert viewbox is not None
        self.assertEqual(viewbox.group(1), "880")
        self.assertEqual(viewbox.group(2), "260")

    def test_badge_draws_equipped_frame_and_keeps_title(self) -> None:
        import xml.etree.ElementTree as ET

        status = {
            **self._status(),
            "frame_id": "frame_ember",
            "equipped_title": "点火",
            "equipped_title_id": "title_ignition",
        }
        badge = render_badge(status)
        ET.fromstring(badge)
        self.assertIn('class="badge-frame" data-frame="frame_ember"', badge)
        self.assertIn('class="badge-frame-image"', badge)
        self.assertIn('href="data:image/png;base64,', badge)
        self.assertIn('fill="url(#badge-frame-glow)"', badge)
        frame = re.search(
            r'class="badge-frame-image"[^>]*width="([0-9.]+)" height="([0-9.]+)"',
            badge,
        )
        icon = re.search(
            r'<image x="[0-9.]+" y="[0-9.]+" width="([0-9.]+)" '
            r'height="[0-9.]+" preserveAspectRatio="xMidYMid meet" '
            r'href="data:image/png;base64,',
            badge,
        )
        glow = re.search(
            r'<circle cx="[0-9.]+" cy="[0-9.]+" r="([0-9.]+)" '
            r'fill="url\(#badge-frame-glow\)"',
            badge,
        )
        self.assertIsNotNone(frame)
        self.assertIsNotNone(icon)
        self.assertIsNotNone(glow)
        assert frame is not None and icon is not None and glow is not None
        frame_size = float(frame.group(1))
        self.assertAlmostEqual(frame_size, float(frame.group(2)), places=1)
        self.assertAlmostEqual(frame_size / float(icon.group(1)), 1.36, places=2)
        self.assertAlmostEqual(float(glow.group(1)) * 2 / frame_size, 1.08, places=2)
        self.assertIn("称号 · 点火", badge)
        self.assertIn("青铜", badge)
        self.assertNotIn('href="http', badge)
        self.assertNotIn("xlink:href", badge)

        plain = render_badge(self._status())
        ET.fromstring(plain)
        self.assertNotIn("badge-frame", plain)
        self.assertNotIn('class="badge-frame-image"', plain)

        unknown = render_badge({**self._status(), "frame_id": "frame_missing"})
        ET.fromstring(unknown)
        self.assertNotIn("badge-frame", unknown)

    def test_badge_uses_xp_and_progress_uses_seconds(self) -> None:
        def fill_width(badge: str) -> float:
            matches = re.findall(
                r'<rect x="\d+" y="\d+" width="([0-9.]+)" '
                r'height="14" rx="7" fill="#[0-9a-f]+"/>',
                badge,
            )
            self.assertGreaterEqual(len(matches), 2)
            return float(matches[-1])

        for theme in ("classic", "material"):
            with self.subTest(theme=theme):
                badge = render_badge({**self._status(), "icon_theme": theme})
                self.assertIn("今日 121 / 100 XP", badge)
                self.assertNotIn("分钟", badge)

                nine_xp = render_badge(
                    {
                        **self._status(),
                        "icon_theme": theme,
                        "today_seconds": 599,
                        "today_xp": 99,
                    }
                )
                self.assertIn("今日 99 / 100 XP", nine_xp)

                capped = render_badge(
                    {
                        **self._status(),
                        "icon_theme": theme,
                        "today_seconds": 659,
                        "today_xp": 109,
                    }
                )
                self.assertEqual(
                    fill_width(capped), BADGE_GEOMETRIES[theme].bar_width
                )

                seconds_based = render_badge(
                    {
                        **self._status(),
                        "icon_theme": theme,
                        "today_seconds": 659,
                        "today_xp": 109,
                        "required_xp": 200,
                    }
                )
                self.assertIn("今日 109 / 200 XP", seconds_based)
                self.assertAlmostEqual(fill_width(seconds_based), 288.9)
        self.assertNotIn("分钟", render_embed("badge"))

    def test_badge_geometry_is_selected_per_icon_theme(self) -> None:
        rendered: dict[str, str] = {}
        for theme, expected in (
            ("classic", (260, 144, 36, 26)),
            ("material", (280, 172, 22, 12)),
        ):
            expected_height, expected_icon_size, expected_x, expected_y = expected
            badge = render_badge({**self._status(), "icon_theme": theme})
            rendered[theme] = badge
            self.assertIn(
                f'viewBox="0 0 880 {expected_height}" '
                f'width="880" height="{expected_height}"',
                badge,
            )
            image_tag = re.search(
                r'<image[^>]*x="(\d+)"[^>]*y="(\d+)" '
                r'width="(\d+)" height="(\d+)"',
                badge,
            )
            self.assertIsNotNone(image_tag)
            assert image_tag is not None
            self.assertEqual(image_tag.group(1), str(expected_x))
            self.assertEqual(image_tag.group(2), str(expected_y))
            self.assertEqual(image_tag.group(3), str(expected_icon_size))
            self.assertEqual(image_tag.group(4), str(expected_icon_size))
        unknown = render_badge({**self._status(), "icon_theme": "unknown"})
        self.assertEqual(unknown, rendered["classic"])

    def test_material_badge_visible_area_matches_classic(self) -> None:
        import base64

        def visible_alpha_area(badge: str) -> tuple[int, float]:
            image_tag = re.search(
                r'<image[^>]*width="(\d+)" height="(\d+)"[^>]*'
                r'href="data:image/png;base64,([^"]+)"',
                badge,
            )
            self.assertIsNotNone(image_tag)
            assert image_tag is not None
            display_size = int(image_tag.group(1))
            with Image.open(io.BytesIO(base64.b64decode(image_tag.group(3)))) as icon:
                alpha = icon.convert("RGBA").getchannel("A")
                alpha_sum = sum(
                    value * count for value, count in enumerate(alpha.histogram())
                ) / 255
                source_size = icon.size[0]
            return display_size, alpha_sum * (display_size / source_size) ** 2

        for tier, slug in TIER_SLUGS.items():
            with self.subTest(tier=tier):
                classic_size, classic_area = visible_alpha_area(
                    render_badge({**self._status(), "tier": tier, "icon_theme": "classic"})
                )
                material_size, material_area = visible_alpha_area(
                    render_badge({**self._status(), "tier": tier, "icon_theme": "material"})
                )
                self.assertEqual(classic_size, 144)
                self.assertEqual(material_size, MATERIAL_ICON_SIZES[slug])
                self.assertLessEqual(
                    abs(material_area - classic_area) / classic_area, 0.20
                )

    def test_unknown_badge_user_is_404(self) -> None:
        with self.client() as client:
            response = client.get("/badge/unknown-user.svg")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "user not found")

    def test_badge_falls_back_to_ring_when_icon_is_unavailable(self) -> None:
        from unittest.mock import patch

        with patch("ghost_league.badge._tier_icon_data_uri", return_value=None):
            with self.client() as client:
                response = client.get("/badge/owner.svg")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("<image", response.text)
        self.assertNotIn(">B<", response.text)
        self.assertIn('stroke="#d08a5a"', response.text)

    def test_embed_page_refreshes_and_can_be_framed(self) -> None:
        with self.client() as client:
            response = client.get("/embed/owner")
            health = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        self.assertIn('src="/badge/owner.svg"', response.text)
        self.assertIn('<meta http-equiv="refresh" content="60">', response.text)
        self.assertIn('width="880" alt="联赛状态"', response.text)
        self.assertNotIn("X-Frame-Options", response.headers)
        self.assertIn("frame-ancestors *", response.headers["content-security-policy"])
        self.assertEqual(health.headers["x-frame-options"], "DENY")

    def test_unknown_embed_user_is_404(self) -> None:
        with self.client() as client:
            response = client.get("/embed/unknown-user")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "user not found")

    def test_badge_escapes_xml_special_characters(self) -> None:
        badge = render_badge(
            {
                **self._status(),
                "display_name": 'A&B <C> "D"',
                "activity_label": "draw <&>",
            }
        )
        self.assertIn("A&amp;B &lt;C&gt; &quot;D&quot;", badge)
        self.assertIn("draw &lt;&amp;&gt;", badge)
        self.assertNotIn("A&B <C>", badge)
        self.assertEqual(
            xml_escape('a&b<c>"d\''),
            "a&amp;b&lt;c&gt;&quot;d&apos;",
        )


if __name__ == "__main__":
    unittest.main()
