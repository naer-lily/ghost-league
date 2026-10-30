from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from ghost_league.accounts import AccountsStore
from ghost_league.api import create_app
from ghost_league.pwa import mount_web
from ghost_league.schedule import TZ
from ghost_league.widget_studio.schema import select_background

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "widget-studio-test-token"
NOW = datetime(2026, 10, 30, 12, 0, 0, tzinfo=TZ)
WEDNESDAY = datetime(2026, 10, 28, 12, 0, 0, tzinfo=TZ)
WEDNESDAY_MORNING = datetime(2026, 10, 28, 6, 0, 0, tzinfo=TZ)
UNSET = object()


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def png_bytes(
    size: tuple[int, int] = (320, 180),
    color: tuple[int, int, int] = (40, 120, 200),
) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def default_styles() -> dict:
    return {
        "label": {
            "width": 520,
            "height": 100,
            "fontSize": 64,
            "fontWeight": 400,
            "letterSpacing": 0,
            "strokeWidth": 0,
            "strokeColor": "#17324d",
            "color": "#17324d",
            "align": "left",
            "lineHeight": 1.15,
            "shadow": {"color": "rgba(255,255,255,0.65)", "blur": 0, "offsetX": 0, "offsetY": 2},
        },
        "counter": {
            "scale": 1.0,
            "gap": 30,
            "flame": {"width": 120, "height": 140, "opacity": 1},
            "number": {
                "width": 360,
                "height": 180,
                "fontSize": 132,
                "fontWeight": 400,
                "color": "#ffb020",
                "align": "left",
                "lineHeight": 1,
                "shadow": {"color": "rgba(255,255,255,0.75)", "blur": 0, "offsetX": 0, "offsetY": 3},
            },
        },
    }


def default_layout(
    text: str = "连续学习",
    *,
    x: float = 760,
    y: float = 540,
    counter: tuple[float, float] = (660, 280),
) -> dict:
    return {
        "counter": {"x": counter[0], "y": counter[1]},
        "texts": [{"id": "text-1", "text": text, "x": x, "y": y}],
    }


def background(
    bg_id: str,
    src: str,
    *,
    when: dict | None = None,
    priority: int = 0,
    layout: dict | None = None,
    styles: dict | None = None,
) -> dict:
    return {
        "id": bg_id,
        "name": bg_id,
        "src": src,
        "when": when or {},
        "priority": priority,
        "fit": "cover",
        "offsetX": 0,
        "offsetY": 0,
        "scale": 1,
        "styles": styles or default_styles(),
        "layout": layout or default_layout(),
    }


def color_bbox(
    image: Image.Image,
    box: tuple[int, int, int, int],
    predicate,
) -> tuple[int, int, int, int, int] | None:
    """Return (left, top, right, bottom, count) for matching pixels in ``box``."""

    left, top, right, bottom = box
    pixels = image.load()
    min_x, min_y, max_x, max_y = right, bottom, left, top
    count = 0
    for y in range(top, bottom):
        for x in range(left, right):
            r, g, b, a = pixels[x, y]
            if not predicate(r, g, b, a):
                continue
            count += 1
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
    if count == 0:
        return None
    return min_x, min_y, max_x + 1, max_y + 1, count


def orange_pixel(r: int, g: int, b: int, a: int) -> bool:
    return a > 0 and r > 200 and g > 80 and b < 140 and r - b > 80


def gray_pixel(r: int, g: int, b: int, a: int) -> bool:
    return a > 0 and max(r, g, b) - min(r, g, b) <= 2 and 60 <= r <= 245


def white_pixel(r: int, g: int, b: int, a: int) -> bool:
    return a > 0 and r > 245 and g > 245 and b > 245


class WidgetStudioAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.api_dir = self.base / "api"
        self.api_dir.mkdir(parents=True)
        self.widgets_dir = self.base / "widgets"
        self.clock = {"now": NOW}
        self.accounts = AccountsStore(
            self.api_dir / "accounts.db", now_fn=lambda: self.clock["now"]
        )
        self.accounts.initialize()
        self.accounts.create("owner", "You", token=TOKEN)
        self.app = create_app(
            game_db_path=self.api_dir / "league.db",
            cache_path=self.base / "cache.json",
            avatars_path=self.api_dir / "avatars.json",
            api_dir=self.api_dir,
            accounts_db=self.api_dir / "accounts.db",
            social_db=self.api_dir / "social.db",
            webhooks_db=self.api_dir / "webhooks.db",
            start_webhook_worker=False,
            widgets_dir=self.widgets_dir,
            widget_web_root=ROOT / "web",
            now_fn=lambda: self.clock["now"],
        )
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    # -- helpers ------------------------------------------------------
    def create_template(self, name: str = "Nijika") -> dict:
        response = self.client.post(
            "/v1/widget-studio/templates", headers=auth(), json={"name": name}
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def upload(
        self,
        template_id: str,
        kind: str,
        *,
        bg_id: str | None = None,
        name: str | None = None,
        data: bytes | None = None,
        filename: str = "upload.png",
    ):
        form = {}
        if bg_id:
            form["bg_id"] = bg_id
        if name:
            form["name"] = name
        return self.client.post(
            f"/v1/widget-studio/templates/{template_id}/assets/{kind}",
            headers=auth(),
            files={"file": (filename, data or png_bytes(), "image/png")},
            data=form,
        )

    def add_local_background(
        self, template: dict, bg_id: str, *, name: str | None = None
    ) -> dict:
        response = self.upload(template["id"], "background", bg_id=bg_id, name=name or bg_id)
        self.assertEqual(response.status_code, 200, response.text)
        src = response.json()["src"]
        template["backgrounds"].append(background(bg_id, src))
        return self.put(template)

    def put(self, template: dict) -> dict:
        response = self.client.put(
            f"/v1/widget-studio/templates/{template['id']}",
            headers=auth(),
            json=template,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def status(self, **overrides) -> dict:
        payload = {
            "user_id": "owner",
            "display_name": "那尔",
            "tier": "Bronze",
            "streak": {
                "current": 12,
                "longest": 20,
                "clean_current": 12,
                "last_checked_date": "2026-10-30",
            },
            "xp": 345,
            "rank": 3,
            "checkin": None,
            "today_xp": 0,
            "required_xp": 100,
        }
        payload.update(overrides)
        if isinstance(payload["streak"], int):
            current = payload["streak"]
            payload["streak"] = {
                "current": current,
                "longest": max(current, 20),
                "clean_current": current,
                "last_checked_date": "2026-10-30",
            }
        return payload

    def render(
        self,
        template: dict,
        *,
        user_id: str = "owner",
        status=UNSET,
        params: dict | None = None,
        size: str | None = None,
    ):
        payload = self.status() if status is UNSET else status
        suffix = "-1x" if size == "1x" else ""
        url = f"/v1/widgets/{user_id}/{template['id']}{suffix}.png"
        with patch.object(
            self.app.state.game_service,
            "status_for_user",
            return_value=payload,
        ):
            return self.client.get(url, params=params)

    # -- tests --------------------------------------------------------
    def test_01_create_read_update_list_delete(self) -> None:
        template = self.create_template()
        self.assertEqual(template["id"], "nijika")
        self.assertEqual(template["version"], 4)
        self.assertNotIn("render_token", template)
        self.assertNotIn("styles", template)
        self.assertEqual(template["canvas"]["width"], 1536)
        background_item = template["backgrounds"][0]
        self.assertEqual(set(background_item["styles"]), {"label", "counter"})
        self.assertEqual(background_item["styles"]["label"]["fontSize"], 64)
        self.assertEqual(background_item["styles"]["label"]["letterSpacing"], 0)
        self.assertEqual(background_item["styles"]["label"]["strokeWidth"], 0)
        self.assertEqual(
            background_item["styles"]["label"]["strokeColor"],
            background_item["styles"]["label"]["color"],
        )
        self.assertEqual(background_item["styles"]["counter"]["scale"], 1.0)
        self.assertEqual(background_item["styles"]["counter"]["gap"], 30.0)
        self.assertEqual(background_item["when"], {})
        self.assertEqual(len(background_item["layout"]["texts"]), 1)
        self.assertEqual(background_item["layout"]["counter"], {"x": 660.0, "y": 280.0})
        self.assertNotIn("streak", background_item["layout"])
        self.assertNotIn("flame", background_item["layout"])
        self.assertNotIn("layers", template)

        listing = self.client.get("/v1/widget-studio/templates", headers=auth())
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()[0]["background_count"], 1)
        self.assertEqual(listing.json()[0]["text_count"], 1)
        self.assertNotIn("layer_count", listing.json()[0])
        self.assertNotIn("render_token", listing.json()[0])

        fetched = self.client.get(
            f"/v1/widget-studio/templates/{template['id']}", headers=auth()
        )
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["id"], "nijika")

        self.clock["now"] = datetime(2026, 10, 30, 12, 5, 0, tzinfo=TZ)
        template["name"] = "Nijika Frame"
        template["backgrounds"][0]["layout"]["texts"][0]["text"] = "今日连胜"
        template["backgrounds"][0]["styles"]["counter"]["gap"] = 72
        updated = self.put(template)
        self.assertEqual(updated["name"], "Nijika Frame")
        self.assertEqual(
            updated["backgrounds"][0]["layout"]["texts"][0]["text"], "今日连胜"
        )
        self.assertEqual(updated["backgrounds"][0]["styles"]["counter"]["gap"], 72.0)
        self.assertNotEqual(updated["updated_at"], template["updated_at"])

        listing = self.client.get("/v1/widget-studio/templates", headers=auth()).json()
        self.assertEqual(listing[0]["name"], "Nijika Frame")

        deleted = self.client.delete(
            f"/v1/widget-studio/templates/{template['id']}", headers=auth()
        )
        self.assertEqual(deleted.status_code, 200)
        missing = self.client.get(
            f"/v1/widget-studio/templates/{template['id']}", headers=auth()
        )
        self.assertEqual(missing.status_code, 404)

    def test_02_upload_only_writes_files_and_keeps_json(self) -> None:
        template = self.create_template()
        before = self.client.get(
            f"/v1/widget-studio/templates/{template['id']}", headers=auth()
        ).json()

        response = self.upload(
            template["id"],
            "background",
            bg_id="bg-morning",
            name="早晨",
            data=png_bytes(color=(20, 110, 190)),
            filename="morning.png",
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"src": "backgrounds/bg-morning.png"})
        stored = self.widgets_dir / template["id"] / "backgrounds" / "bg-morning.png"
        self.assertTrue(stored.is_file())
        with Image.open(stored) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (320, 180))

        after = self.client.get(
            f"/v1/widget-studio/templates/{template['id']}", headers=auth()
        ).json()
        self.assertEqual(after, before)
        self.assertEqual(len(after["backgrounds"]), 1)

        flame = png_bytes(size=(120, 140), color=(255, 120, 30))
        response = self.upload(
            template["id"], "flame", data=flame, filename="flame-source.png"
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"src": "flame.png"})
        self.assertTrue((self.widgets_dir / template["id"] / "flame.png").is_file())
        after_flame = self.client.get(
            f"/v1/widget-studio/templates/{template['id']}", headers=auth()
        ).json()
        self.assertEqual(after_flame, before)

        template = self.put(
            {
                **after,
                "backgrounds": [
                    *after["backgrounds"],
                    background("bg-morning", "backgrounds/bg-morning.png"),
                ],
            }
        )
        thumb = self.client.get(
            f"/v1/widget-studio/templates/{template['id']}/backgrounds/bg-morning/thumb?w=240"
        )
        self.assertEqual(thumb.status_code, 200)
        self.assertEqual(thumb.headers["cache-control"], "no-store")
        with Image.open(io.BytesIO(thumb.content)) as image:
            self.assertEqual(image.width, 240)

        asset = self.client.get(
            f"/v1/widget-studio/templates/{template['id']}/assets/flame.png"
        )
        self.assertEqual(asset.status_code, 200)
        self.assertIn("image/png", asset.headers["content-type"])

    def test_03_v4_schema_validation_and_v3_migration_hint(self) -> None:
        template = self.create_template()
        cases: list[tuple[str, dict]] = []

        def variant(label: str, mutator) -> None:
            copy = json.loads(json.dumps(template))
            mutator(copy)
            cases.append((label, copy))

        variant("no version", lambda item: item.pop("version"))
        variant("v2", lambda item: item.update(version=2))
        variant("top-level styles", lambda item: item.update(styles=default_styles()))
        variant("no background styles", lambda item: item["backgrounds"][0].pop("styles"))
        variant("no label", lambda item: item["backgrounds"][0]["styles"].pop("label"))
        variant("no counter", lambda item: item["backgrounds"][0]["styles"].pop("counter"))
        variant("no layout", lambda item: item["backgrounds"][0].pop("layout"))
        variant(
            "empty texts",
            lambda item: item["backgrounds"][0]["layout"].update(texts=[]),
        )
        variant(
            "no counter anchor",
            lambda item: item["backgrounds"][0]["layout"].pop("counter"),
        )
        variant(
            "old streak field",
            lambda item: item["backgrounds"][0]["layout"].update(streak={"x": 1, "y": 2}),
        )
        variant(
            "old flame field",
            lambda item: item["backgrounds"][0]["layout"].update(flame={"x": 1, "y": 2}),
        )
        variant(
            "text without x",
            lambda item: item["backgrounds"][0]["layout"]["texts"][0].pop("x"),
        )
        variant(
            "duplicate text id",
            lambda item: item["backgrounds"][0]["layout"]["texts"].append(
                {"id": "text-1", "text": "dup", "x": 1, "y": 2}
            ),
        )
        variant("legacy layers", lambda item: item.update(layers=[]))
        variant(
            "scale too small",
            lambda item: item["backgrounds"][0]["styles"]["counter"].update(scale=0.4),
        )
        variant(
            "scale too large",
            lambda item: item["backgrounds"][0]["styles"]["counter"].update(scale=2.1),
        )
        variant(
            "negative gap",
            lambda item: item["backgrounds"][0]["styles"]["counter"].update(gap=-1),
        )
        variant(
            "gap too large",
            lambda item: item["backgrounds"][0]["styles"]["counter"].update(gap=161),
        )
        variant(
            "letter spacing too large",
            lambda item: item["backgrounds"][0]["styles"]["label"].update(letterSpacing=41),
        )
        variant(
            "stroke too wide",
            lambda item: item["backgrounds"][0]["styles"]["label"].update(strokeWidth=13),
        )
        variant(
            "font weight out of range",
            lambda item: item["backgrounds"][0]["styles"]["label"].update(fontWeight=50),
        )
        for label, payload in cases:
            response = self.client.put(
                f"/v1/widget-studio/templates/{template['id']}",
                headers=auth(),
                json=payload,
            )
            self.assertEqual(response.status_code, 422, label)

        # Legacy v3 JSON is rejected with an actionable migration hint instead
        # of being silently half-read.
        legacy = json.loads(json.dumps(template))
        legacy["version"] = 3
        legacy["styles"] = default_styles()
        for item in legacy["backgrounds"]:
            item.pop("styles")
            item["layout"]["streak"] = {"x": 1, "y": 2}
            item["layout"]["flame"] = {"x": 3, "y": 4}
        response = self.client.put(
            f"/v1/widget-studio/templates/{template['id']}",
            headers=auth(),
            json=legacy,
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("migrate_widget_template_v4.py", response.json()["detail"])

        # The disk file was never rewritten by the rejected PUTs.
        stored = self.client.get(
            f"/v1/widget-studio/templates/{template['id']}", headers=auth()
        ).json()
        self.assertEqual(stored["version"], 4)
        self.assertEqual(stored["id"], template["id"])

    def test_04_conditions_priority_and_fallback_from_status(self) -> None:
        template = self.create_template()
        specs = [
            ("bg-hour", {"hour_from": 5, "hour_to": 11}, 100),
            ("bg-weekday", {"weekdays": [5]}, 90),
            ("bg-streak", {"streak_min": 7, "streak_max": 29}, 80),
            ("bg-completed", {"completed_today": True}, 70),
            ("bg-league", {"league": "bronze"}, 60),
        ]
        for bg_id, _, _ in specs:
            template = self.add_local_background(template, bg_id, name=bg_id)

        backgrounds = [background("bg-fallback", template["backgrounds"][0]["src"])]
        for bg_id, when, priority in specs:
            backgrounds.append(
                background(
                    bg_id,
                    f"backgrounds/{bg_id}.png",
                    when=when,
                    priority=priority,
                    layout=default_layout(
                        text=bg_id,
                        x=100 + priority,
                        y=120,
                        counter=(300 + priority, 320),
                    ),
                )
            )
        template["backgrounds"] = backgrounds
        template = self.put(template)

        cases = [
            (self.status(streak=0, tier="Gold"), WEDNESDAY, "bg-fallback"),
            (self.status(streak=12, tier="Gold"), WEDNESDAY, "bg-streak"),
            (self.status(streak=0, tier="Gold", checkin="verified"), WEDNESDAY, "bg-completed"),
            (self.status(streak=0, tier="Bronze"), WEDNESDAY, "bg-league"),
            (
                self.status(streak=0, tier="Gold"),
                WEDNESDAY_MORNING,
                "bg-hour",
            ),
            (
                self.status(streak=0, tier="Gold"),
                NOW,
                "bg-weekday",
            ),
            (
                self.status(streak=12, tier="Bronze", checkin="verified"),
                WEDNESDAY_MORNING,
                "bg-hour",
            ),
        ]
        for payload, when, expected in cases:
            self.clock["now"] = when
            response = self.render(template, status=payload)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.headers["x-widget-background"], expected, when)

        # Unknown check-in shapes fall back to today_xp >= required_xp.
        self.clock["now"] = WEDNESDAY
        completed = self.render(
            template,
            status=self.status(
                streak=0,
                tier="Gold",
                checkin={"unexpected": True},
                today_xp=100,
                required_xp=100,
            ),
        )
        self.assertEqual(completed.headers["x-widget-background"], "bg-completed")
        incomplete = self.render(
            template,
            status=self.status(
                streak=0,
                tier="Gold",
                checkin={"unexpected": True},
                today_xp=99,
                required_xp=100,
            ),
        )
        self.assertEqual(incomplete.headers["x-widget-background"], "bg-fallback")

        # Event data is never accepted from the URL or status.
        selected, _ = select_background(template, {"event": "rush", "hour": 12})
        self.assertEqual(selected["id"], "bg-fallback")

    def test_05_text_variants_random_and_per_background_positions(self) -> None:
        template = self.create_template()
        layout_a = default_layout(
            text="第一条",
            x=700,
            y=500,
            counter=(620, 240),
        )
        layout_a["texts"] = [
            {"id": "text-1", "text": "第一条", "x": 700, "y": 500},
            {"id": "text-2", "text": "第二条", "x": 720, "y": 520},
            {"id": "text-3", "text": "第三条", "x": 740, "y": 540},
        ]
        template["backgrounds"][0]["layout"] = layout_a
        template = self.put(template)

        for index, text_id in enumerate(("text-1", "text-2", "text-3")):
            with patch(
                "ghost_league.widget_studio.renderer.random.choice",
                side_effect=lambda entries, index=index: entries[index],
            ):
                response = self.render(template)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.headers["x-widget-background"], "bg-default")
            self.assertEqual(response.headers["x-widget-text"], text_id)
            self.assertIn(
                text_id,
                [
                    item["id"]
                    for item in template["backgrounds"][0]["layout"]["texts"]
                ],
            )

        with patch(
            "ghost_league.widget_studio.renderer.random.choice",
            side_effect=lambda entries: entries[1],
        ):
            first = self.render(template)
            second = self.render(template)
        self.assertEqual(first.headers["x-widget-text"], "text-2")
        self.assertEqual(second.headers["x-widget-text"], "text-2")

        # Different backgrounds carry different streaks/flames/text positions.
        template = self.add_local_background(template, "bg-other")
        default = next(bg for bg in template["backgrounds"] if bg["id"] == "bg-default")
        other = next(bg for bg in template["backgrounds"] if bg["id"] == "bg-other")
        default["when"] = {"hour_from": 5, "hour_to": 11}
        default["priority"] = 50
        other["when"] = {}
        other["priority"] = 0
        other["layout"] = default_layout(
            text="另一张",
            x=120,
            y=160,
            counter=(160, 200),
        )
        template = self.put(template)

        self.clock["now"] = datetime(2026, 10, 30, 6, 0, 0, tzinfo=TZ)
        with patch(
            "ghost_league.widget_studio.renderer.random.choice",
            side_effect=lambda entries: entries[0],
        ):
            morning = self.render(template)
            self.clock["now"] = datetime(2026, 10, 30, 12, 0, 0, tzinfo=TZ)
            evening = self.render(template)
        self.assertEqual(morning.headers["x-widget-background"], "bg-default")
        self.assertEqual(evening.headers["x-widget-background"], "bg-other")
        self.assertEqual(morning.headers["x-widget-text"], "text-1")
        self.assertEqual(evening.headers["x-widget-text"], "text-1")
        self.assertNotEqual(morning.content, evening.content)

    def test_06_fixed_url_size_alpha_and_404s(self) -> None:
        template = self.create_template()
        response = self.render(template)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["x-widget-background"], "bg-default")
        self.assertEqual(response.headers["x-widget-text"], "text-1")
        self.assertEqual(response.headers["cache-control"], "no-store")
        with Image.open(io.BytesIO(response.content)) as image:
            self.assertEqual(image.size, (1536, 914))
            self.assertEqual(image.mode, "RGBA")
            for point in ((0, 0), (1535, 0), (0, 913), (1535, 913)):
                self.assertEqual(image.getpixel(point)[3], 0, point)
            self.assertGreater(image.getpixel((768, 457))[3], 0)

        small = self.render(template, size="1x")
        self.assertEqual(small.status_code, 200)
        with Image.open(io.BytesIO(small.content)) as image:
            self.assertEqual(image.size, (368, 219))

        noisy = {
            "streak": "999",
            "xp": "999",
            "rank": "999",
            "name": "evil",
            "hour": "23",
            "weekday": "7",
            "completed": "1",
            "league": "diamond",
            "event": "rush",
            "token": "0" * 32,
            "size": "1x",
            "bg": "bg-missing",
            "text": "text-missing",
        }
        ignored = self.render(template, params=noisy)
        self.assertEqual(ignored.status_code, 200, ignored.text)
        self.assertEqual(ignored.content, response.content)
        self.assertEqual(ignored.headers["x-widget-background"], "bg-default")
        self.assertEqual(ignored.headers["x-widget-text"], "text-1")
        with Image.open(io.BytesIO(ignored.content)) as image:
            self.assertEqual(image.size, (1536, 914))

        unknown_user = self.render(template, user_id="ghost-user", status=None)
        self.assertEqual(unknown_user.status_code, 404)
        unknown_template = self.render(
            {"id": "does-not-exist"}, status=self.status()
        )
        self.assertEqual(unknown_template.status_code, 404)
        bad_user = self.client.get("/v1/widgets/bad!user/nijika.png")
        self.assertEqual(bad_user.status_code, 404)
        bad_template = self.client.get("/v1/widgets/owner/bad!id.png")
        self.assertEqual(bad_template.status_code, 404)
        missing_suffix = self.client.get("/v1/widgets/owner/nijika")
        self.assertEqual(missing_suffix.status_code, 404)

        broken = self.widgets_dir / "broken-template"
        broken.mkdir(parents=True)
        (broken / "template.json").write_text("{not json", encoding="utf-8")
        corrupt = self.render({"id": "broken-template"}, status=self.status())
        self.assertEqual(corrupt.status_code, 404)

    def test_07_status_and_template_edits_change_same_url(self) -> None:
        template = self.create_template()
        first = self.render(template, status=self.status(streak=12))
        second = self.render(template, status=self.status(streak=99))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(first.content, second.content)

        template = self.add_local_background(template, "bg-special")
        path = self.widgets_dir / template["id"] / "template.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        default = next(bg for bg in raw["backgrounds"] if bg["id"] == "bg-default")
        special = next(bg for bg in raw["backgrounds"] if bg["id"] == "bg-special")
        default["when"] = {"event": "special"}
        default["priority"] = 50
        special["when"] = {}
        special["priority"] = 0
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

        ordinary = self.render(template)
        self.assertEqual(ordinary.headers["x-widget-background"], "bg-special")

        raw["backgrounds"] = [
            background(
                "bg-default",
                next(bg for bg in raw["backgrounds"] if bg["id"] == "bg-default")["src"],
                layout=default_layout(text="新底图文字"),
            ),
            background(
                "bg-special",
                next(bg for bg in raw["backgrounds"] if bg["id"] == "bg-special")["src"],
                when={"hour_from": 0, "hour_to": 1},
            ),
        ]
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        changed_condition = self.render(template)
        self.assertEqual(changed_condition.headers["x-widget-background"], "bg-default")
        self.assertNotEqual(changed_condition.content, ordinary.content)

        text_changed = json.loads(path.read_text(encoding="utf-8"))
        text_changed["backgrounds"][0]["layout"]["texts"][0]["text"] = "又一条"
        path.write_text(json.dumps(text_changed, ensure_ascii=False), encoding="utf-8")
        after_text = self.render(template)
        self.assertNotEqual(after_text.content, changed_condition.content)

        self.upload(
            template["id"],
            "background",
            bg_id="bg-default",
            data=png_bytes(color=(250, 30, 90)),
        )
        after_image = self.render(template)
        self.assertNotEqual(after_image.content, after_text.content)

    def test_08_invalid_inputs_are_4xx(self) -> None:
        self.assertEqual(
            self.client.get("/v1/widget-studio/templates", headers={}).status_code, 401
        )
        self.assertEqual(
            self.client.post(
                "/v1/widget-studio/templates", json={"name": "Anonymous"}
            ).status_code,
            401,
        )
        template = self.create_template()
        self.assertEqual(
            self.client.get(
                "/v1/widget-studio/templates/bad!id", headers=auth()
            ).status_code,
            422,
        )
        traversal = self.client.get(
            "/v1/widget-studio/templates/..%2F..%2Fetc", headers=auth()
        )
        self.assertIn(traversal.status_code, (404, 422))

        bad_image = self.client.post(
            f"/v1/widget-studio/templates/{template['id']}/assets/background",
            headers=auth(),
            files={"file": ("bad.png", b"not an image", "image/png")},
            data={"bg_id": "bg-bad"},
        )
        self.assertIn(bad_image.status_code, (400, 415))

        oversized = self.client.post(
            f"/v1/widget-studio/templates/{template['id']}/assets/background",
            headers=auth(),
            files={"file": ("huge.png", b"x" * (15 * 1024 * 1024 + 1), "image/png")},
            data={"bg_id": "bg-huge"},
        )
        self.assertEqual(oversized.status_code, 413)

        unknown_kind = self.upload(template["id"], "sticker", bg_id="bg-x")
        self.assertIn(unknown_kind.status_code, (400, 415))

        no_fallback = json.loads(json.dumps(template))
        no_fallback["backgrounds"][0]["when"] = {"event": "only"}
        response = self.client.put(
            f"/v1/widget-studio/templates/{template['id']}",
            headers=auth(),
            json=no_fallback,
        )
        self.assertEqual(response.status_code, 422)

        duplicate_bg = json.loads(json.dumps(template))
        duplicate_bg["backgrounds"].append(
            json.loads(json.dumps(template["backgrounds"][0]))
        )
        response = self.client.put(
            f"/v1/widget-studio/templates/{template['id']}",
            headers=auth(),
            json=duplicate_bg,
        )
        self.assertEqual(response.status_code, 422)

        for bad_src in (
            "../escape.png",
            "/etc/passwd",
            "https://example.com/a.png",
            "ghost:../../etc/passwd",
            "ghost:/etc/passwd",
            "ghost:assets/../secret.png",
        ):
            invalid = json.loads(json.dumps(template))
            invalid["backgrounds"][0]["src"] = bad_src
            response = self.client.put(
                f"/v1/widget-studio/templates/{template['id']}",
                headers=auth(),
                json=invalid,
            )
            self.assertEqual(response.status_code, 422, bad_src)

        traversal_asset = self.client.get(
            f"/v1/widget-studio/templates/{template['id']}/assets/..%2Ftemplate.json"
        )
        self.assertEqual(traversal_asset.status_code, 404)

    def test_09_bad_json_is_skipped_in_list(self) -> None:
        template = self.create_template()
        broken = self.widgets_dir / "broken-template"
        broken.mkdir(parents=True)
        (broken / "template.json").write_text("{not json", encoding="utf-8")
        listing = self.client.get("/v1/widget-studio/templates", headers=auth())
        self.assertEqual(listing.status_code, 200)
        ids = [item["id"] for item in listing.json()]
        self.assertEqual(ids, [template["id"]])

    def test_10_editor_is_served_by_the_existing_pwa_mount(self) -> None:
        app = FastAPI()

        @app.get("/v1/ping")
        def ping() -> dict:
            return {"ok": True}

        mount_web(app)
        with TestClient(app) as client:
            page = client.get("/widget-studio/")
            self.assertEqual(page.status_code, 200)
            self.assertIn("Widget Studio", page.text)
            self.assertIn("我的小组件", page.text)
            self.assertIn("widget-fixed-url", page.text)
            self.assertIn("/widget-studio/app.js", page.text)
            script = client.get("/widget-studio/app.js")
            self.assertEqual(script.status_code, 200)
            self.assertIn("javascript", script.headers["content-type"])
            style = client.get("/widget-studio/styles.css")
            self.assertEqual(style.status_code, 200)
            self.assertEqual(client.get("/v1/ping").json(), {"ok": True})

    def test_11_cross_night_and_weekday_selection(self) -> None:
        backgrounds = [
            {
                "id": "bg-night",
                "when": {"hour_from": 22, "hour_to": 5},
                "priority": 10,
            },
            {"id": "bg-fallback", "when": {}, "priority": 0},
        ]
        template = {"backgrounds": backgrounds}
        for hour, expected in ((23, "bg-night"), (2, "bg-night"), (5, "bg-fallback"), (12, "bg-fallback")):
            selected, fallback = select_background(template, {"hour": hour})
            self.assertEqual(selected["id"], expected)
            self.assertEqual(fallback, expected == "bg-fallback")

    def test_12_nijika_ref_proportions_and_completed_grayscale(self) -> None:
        source = ROOT / "data" / "widgets" / "nijika-ref"
        if not source.is_dir():
            self.skipTest("nijika-ref template is not present")
        shutil.copytree(source, self.widgets_dir / "nijika-ref")
        template = {"id": "nijika-ref"}
        flame_box = (1000, 60, 1255, 350)
        digit_box = (1255, 120, 1520, 350)
        label_box = (1000, 330, 1536, 500)

        with patch(
            "ghost_league.widget_studio.renderer.random.choice",
            side_effect=lambda entries: entries[0],
        ):
            completed = self.render(
                template, status=self.status(streak=12, checkin="verified")
            )
            incomplete = self.render(
                template, status=self.status(streak=12, checkin=None)
            )

        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertEqual(incomplete.status_code, 200, incomplete.text)
        self.assertEqual(completed.headers["x-widget-completed"], "1")
        self.assertEqual(incomplete.headers["x-widget-completed"], "0")

        with Image.open(io.BytesIO(completed.content)) as raw:
            completed_image = raw.convert("RGBA")
        with Image.open(io.BytesIO(incomplete.content)) as raw:
            incomplete_image = raw.convert("RGBA")

        completed_flame = color_bbox(completed_image, flame_box, orange_pixel)
        completed_digit = color_bbox(completed_image, digit_box, orange_pixel)
        completed_label = color_bbox(completed_image, label_box, white_pixel)
        self.assertIsNotNone(completed_flame)
        self.assertIsNotNone(completed_digit)
        self.assertIsNotNone(completed_label)
        assert completed_flame and completed_digit and completed_label

        flame_height = completed_flame[3] - completed_flame[1]
        digit_height = completed_digit[3] - completed_digit[1]
        self.assertGreaterEqual(flame_height, 190)
        self.assertLessEqual(flame_height, 210)
        self.assertGreaterEqual(flame_height / digit_height, 1.8)
        self.assertLessEqual(completed_flame[2], completed_digit[0])
        self.assertGreater(completed_label[1], completed_digit[3])

        incomplete_flame = color_bbox(incomplete_image, flame_box, gray_pixel)
        incomplete_digit = color_bbox(incomplete_image, digit_box, gray_pixel)
        incomplete_label = color_bbox(incomplete_image, label_box, white_pixel)
        self.assertIsNotNone(incomplete_flame)
        self.assertIsNotNone(incomplete_digit)
        self.assertIsNotNone(incomplete_label)
        assert incomplete_flame and incomplete_digit and incomplete_label

        for orange in (
            color_bbox(incomplete_image, flame_box, orange_pixel),
            color_bbox(incomplete_image, digit_box, orange_pixel),
        ):
            self.assertIsNone(orange)
        incomplete_flame_height = incomplete_flame[3] - incomplete_flame[1]
        incomplete_digit_height = incomplete_digit[3] - incomplete_digit[1]
        self.assertGreaterEqual(incomplete_flame_height / incomplete_digit_height, 1.8)
        for before, after in zip(completed_flame[:4], incomplete_flame[:4]):
            self.assertLessEqual(abs(before - after), 3)
        self.assertLessEqual(incomplete_flame[2], incomplete_digit[0])
        self.assertGreater(incomplete_label[1], incomplete_digit[3])
        self.assertEqual(completed_label, incomplete_label)

        pixels = incomplete_image.load()
        gray_digit_pixels = sum(
            1
            for y in range(digit_box[1], digit_box[3])
            for x in range(digit_box[0], digit_box[2])
            if pixels[x, y] == (154, 154, 154, 255)
        )
        self.assertGreater(gray_digit_pixels, 1000)
        self.assertGreater(incomplete_flame[4], 1000)
        self.assertGreater(incomplete_label[4], 1000)

    def test_13_migration_script_builds_v4_idempotently(self) -> None:
        import importlib.util

        script_path = ROOT / "scripts" / "migrate_widget_template_v4.py"
        spec = importlib.util.spec_from_file_location("migrate_widget_v4", script_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        raw_v3 = {
            "version": 3,
            "id": "legacy",
            "name": "Legacy",
            "render_token": "a" * 32,
            "updated_at": "2026-10-30T12:00:00",
            "canvas": {"width": 1536, "height": 914, "radius": 128},
            "styles": {
                "label": {
                    "width": 520,
                    "height": 100,
                    "fontSize": 64,
                    "fontWeight": 400,
                    "color": "#17324d",
                    "align": "left",
                    "lineHeight": 1.15,
                    "shadow": None,
                },
                "streak": {
                    "width": 360,
                    "height": 180,
                    "fontSize": 132,
                    "fontWeight": 400,
                    "color": "#ffb020",
                    "align": "left",
                    "lineHeight": 1,
                    "shadow": None,
                },
                "flame": {"width": 120, "height": 140, "opacity": 1},
            },
            "backgrounds": [
                {
                    "id": "bg-default",
                    "name": "默认",
                    "src": "backgrounds/bg-default.png",
                    "when": {},
                    "priority": 0,
                    "fit": "cover",
                    "offsetX": 0,
                    "offsetY": 0,
                    "scale": 1,
                    "layout": {
                        "texts": [
                            {"id": "text-1", "text": "连续学习", "x": 760, "y": 540}
                        ],
                        "streak": {"x": 760, "y": 300},
                        "flame": {"x": 660, "y": 280},
                    },
                },
                {
                    "id": "bg-night",
                    "name": "夜晚",
                    "src": "backgrounds/bg-night.png",
                    "when": {"hour_from": 22, "hour_to": 5},
                    "priority": 10,
                    "fit": "cover",
                    "offsetX": 0,
                    "offsetY": 0,
                    "scale": 1,
                    "layout": {
                        "texts": [
                            {"id": "text-1", "text": "夜晚", "x": 200, "y": 300}
                        ],
                        "streak": {"x": 300, "y": 200},
                        "flame": {"x": 260, "y": 180},
                    },
                },
            ],
        }
        migrated = module.migrate(raw_v3)
        self.assertEqual(migrated["version"], 4)
        self.assertNotIn("layers", migrated)
        self.assertNotIn("render_token", migrated)
        self.assertNotIn("styles", migrated)
        self.assertEqual(len(migrated["backgrounds"]), 2)
        first = migrated["backgrounds"][0]
        second = migrated["backgrounds"][1]
        self.assertEqual(first["styles"]["label"]["fontSize"], 64)
        self.assertEqual(first["styles"]["label"]["letterSpacing"], 0)
        self.assertEqual(first["styles"]["label"]["strokeWidth"], 0)
        self.assertEqual(first["styles"]["label"]["strokeColor"], "#17324d")
        self.assertEqual(first["styles"]["counter"]["scale"], 1.0)
        self.assertEqual(first["styles"]["counter"]["gap"], 30)
        self.assertEqual(first["styles"]["counter"]["flame"]["width"], 120)
        self.assertEqual(first["styles"]["counter"]["number"]["fontSize"], 132)
        self.assertEqual(
            first["layout"]["texts"], [{"id": "text-1", "text": "连续学习", "x": 760, "y": 540}]
        )
        self.assertEqual(first["layout"]["counter"], {"x": 660, "y": 280})
        self.assertEqual(second["layout"]["counter"], {"x": 260, "y": 180})
        self.assertNotIn("streak", first["layout"])
        self.assertNotIn("flame", first["layout"])

        # Every background owns an independent copy of the old global styles.
        first["styles"]["counter"]["gap"] = 99
        self.assertEqual(second["styles"]["counter"]["gap"], 30)

        # Running the migration again is a no-op.
        self.assertEqual(module.migrate(migrated), migrated)
        with self.assertRaises(ValueError):
            module.migrate({"version": 2, "id": "legacy", "name": "Legacy"})

    def _flat_template(self, *, text: str = "连续学习") -> dict:
        """A template with a flat dark background and an orange flame."""

        template = self.create_template("Flat")
        self.upload(
            template["id"],
            "background",
            bg_id="bg-flat",
            data=png_bytes(color=(12, 18, 40)),
        )
        self.upload(
            template["id"],
            "flame",
            data=png_bytes(size=(120, 140), color=(255, 120, 30)),
        )
        template["backgrounds"] = [
            background(
                "bg-flat",
                "backgrounds/bg-flat.png",
                layout=default_layout(text=text, x=100, y=100, counter=(700, 260)),
            )
        ]
        return self.put(template)

    def test_14_per_background_styles_are_independent(self) -> None:
        template = self._flat_template()
        template = self.add_local_background(template, "bg-alt")
        fallback = template["backgrounds"][0]
        alternate = template["backgrounds"][1]
        fallback["when"] = {}
        alternate["when"] = {"hour_from": 0, "hour_to": 12}
        alternate["priority"] = 50
        fallback["styles"] = default_styles()
        fallback["styles"]["counter"].update(scale=1.0, gap=30)
        fallback["styles"]["counter"]["number"].update(fontSize=132, color="#ff2020")
        alternate["styles"] = default_styles()
        alternate["styles"]["counter"].update(scale=1.5, gap=100)
        alternate["styles"]["counter"]["number"].update(fontSize=80, color="#20ff20")
        template["backgrounds"] = [fallback, alternate]
        template = self.put(template)

        with patch(
            "ghost_league.widget_studio.renderer.random.choice",
            side_effect=lambda entries: entries[0],
        ):
            self.clock["now"] = datetime(2026, 10, 30, 6, 0, 0, tzinfo=TZ)
            morning = self.render(template, status=self.status(checkin="verified"))
            self.clock["now"] = datetime(2026, 10, 30, 20, 0, 0, tzinfo=TZ)
            evening = self.render(template, status=self.status(checkin="verified"))
        self.assertEqual(morning.headers["x-widget-background"], "bg-alt")
        self.assertEqual(evening.headers["x-widget-background"], "bg-flat")
        self.assertNotEqual(morning.content, evening.content)

        with Image.open(io.BytesIO(morning.content)) as raw:
            morning_image = raw.convert("RGBA")
        with Image.open(io.BytesIO(evening.content)) as raw:
            evening_image = raw.convert("RGBA")
        green = color_bbox(
            morning_image,
            (0, 0, 1536, 914),
            lambda r, g, b, a: a > 0 and g > 180 and r < 100 and b < 100,
        )
        red = color_bbox(
            evening_image,
            (0, 0, 1536, 914),
            lambda r, g, b, a: a > 0 and r > 180 and g < 100 and b < 100,
        )
        self.assertIsNotNone(green)
        self.assertIsNotNone(red)
        assert green and red
        # The alternate background's larger scale pushes its flame right, its
        # larger gap moves the number further right, and the independent copy
        # means the fallback keeps its own geometry.
        self.assertGreater(green[0], red[0] + 40)
        self.assertLess(green[0], 1536)
        self.assertLess(green[3] - green[1], red[3] - red[1])

        # Re-rendering the fallback never picks up the alternate background's
        # styles.
        self.clock["now"] = datetime(2026, 10, 30, 20, 0, 0, tzinfo=TZ)
        with patch(
            "ghost_league.widget_studio.renderer.random.choice",
            side_effect=lambda entries: entries[0],
        ):
            again = self.render(template, status=self.status(checkin="verified"))
        with Image.open(io.BytesIO(again.content)) as raw:
            again_image = raw.convert("RGBA")
        again_red = color_bbox(
            again_image,
            (0, 0, 1536, 914),
            lambda r, g, b, a: a > 0 and r > 180 and g < 100 and b < 100,
        )
        self.assertEqual(again_red, red)

    def test_15_gap_moves_only_the_number(self) -> None:
        template = self._flat_template()
        template["backgrounds"][0]["styles"]["counter"]["number"]["color"] = "#ff2020"
        template = self.put(template)
        style = template["backgrounds"][0]["styles"]["counter"]

        with patch(
            "ghost_league.widget_studio.renderer.random.choice",
            side_effect=lambda entries: entries[0],
        ):
            first = self.render(template, status=self.status(checkin="verified"))
            style["gap"] = 120
            template = self.put(template)
            second = self.render(template, status=self.status(checkin="verified"))

        def red_box(response):
            with Image.open(io.BytesIO(response.content)) as raw:
                image = raw.convert("RGBA")
            return color_bbox(
                image,
                (0, 0, 1536, 914),
                lambda r, g, b, a: a > 0 and r > 180 and g < 100 and b < 100,
            )

        def orange_box(response):
            with Image.open(io.BytesIO(response.content)) as raw:
                image = raw.convert("RGBA")
            return color_bbox(
                image,
                (0, 0, 1536, 914),
                lambda r, g, b, a: a > 0 and r > 200 and g >= 100 and b < 80,
            )

        first_digit = red_box(first)
        second_digit = red_box(second)
        first_flame = orange_box(first)
        second_flame = orange_box(second)
        assert first_digit and second_digit and first_flame and second_flame
        self.assertGreater(second_digit[0], first_digit[0] + 80)
        self.assertGreater(second_digit[2], first_digit[2] + 80)
        self.assertEqual(first_flame, second_flame)

    def test_16_text_weight_spacing_and_stroke_change_pixels(self) -> None:
        template = self._flat_template(text="Weight AB")
        background_item = template["backgrounds"][0]
        style = background_item["styles"]["label"]
        style.update(
            width=1200,
            height=200,
            fontSize=120,
            fontWeight=400,
            letterSpacing=0,
            strokeWidth=0,
            strokeColor="#ff0000",
            color="#ffffff",
            shadow=None,
        )
        background_item["layout"]["texts"][0].update(x=100, y=100)
        background_item["layout"]["counter"] = {"x": -800, "y": -800}
        template = self.put(template)
        style = template["backgrounds"][0]["styles"]["label"]

        def render_label() -> Image.Image:
            with patch(
                "ghost_league.widget_studio.renderer.random.choice",
                side_effect=lambda entries: entries[0],
            ):
                response = self.render(template, status=self.status(checkin="verified"))
            self.assertEqual(response.status_code, 200, response.text)
            with Image.open(io.BytesIO(response.content)) as raw:
                return raw.convert("RGBA")

        def white_box(image: Image.Image):
            return color_bbox(image, (0, 0, 1400, 400), white_pixel)

        def red_box(image: Image.Image):
            return color_bbox(
                image,
                (0, 0, 1400, 400),
                lambda r, g, b, a: a > 0 and r > 180 and g < 100 and b < 100,
            )

        regular = render_label()
        regular_white = white_box(regular)
        assert regular_white
        self.assertIsNone(red_box(regular))

        style["fontWeight"] = 900
        template = self.put(template)
        style = template["backgrounds"][0]["styles"]["label"]
        bold = render_label()
        bold_white = white_box(bold)
        assert bold_white
        self.assertGreater(bold_white[4], regular_white[4] * 1.08)

        style["letterSpacing"] = 30
        template = self.put(template)
        style = template["backgrounds"][0]["styles"]["label"]
        spaced = render_label()
        spaced_white = white_box(spaced)
        assert spaced_white
        self.assertGreater(
            spaced_white[2] - spaced_white[0],
            (bold_white[2] - bold_white[0]) * 1.1,
        )

        style["strokeWidth"] = 10
        style["strokeColor"] = "#ff0000"
        template = self.put(template)
        style = template["backgrounds"][0]["styles"]["label"]
        stroked = render_label()
        stroke_red = red_box(stroked)
        self.assertIsNotNone(stroke_red)
        assert stroke_red
        self.assertGreater(stroke_red[4], 1000)

    def test_17_legacy_v3_file_reads_as_422_with_migration_hint(self) -> None:
        legacy_dir = self.widgets_dir / "legacy-v3"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "template.json").write_text(
            json.dumps(
                {
                    "version": 3,
                    "id": "legacy-v3",
                    "name": "Legacy V3",
                    "canvas": {"width": 1536, "height": 914, "radius": 128},
                    "styles": default_styles(),
                    "backgrounds": [
                        background("bg-default", "backgrounds/bg-default.png")
                    ],
                }
            ),
            encoding="utf-8",
        )
        response = self.client.get(
            "/v1/widget-studio/templates/legacy-v3", headers=auth()
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("migrate_widget_template_v4.py", response.json()["detail"])
        production = self.render({"id": "legacy-v3"})
        self.assertEqual(production.status_code, 404)

if __name__ == "__main__":
    unittest.main()
