from __future__ import annotations

import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

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


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def png_bytes(
    size: tuple[int, int] = (320, 180),
    color: tuple[int, int, int] = (40, 120, 200),
) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


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
        template = response.json()["template"]
        return template

    def put(self, template: dict) -> dict:
        response = self.client.put(
            f"/v1/widget-studio/templates/{template['id']}",
            headers=auth(),
            json=template,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def render(self, template: dict, **params):
        query = {"token": template["render_token"], **params}
        response = self.client.get(f"/v1/widgets/{template['id']}.png", params=query)
        return response

    # -- tests --------------------------------------------------------
    def test_01_create_read_update_list_delete(self) -> None:
        template = self.create_template()
        self.assertEqual(template["id"], "nijika")
        self.assertEqual(template["version"], 2)
        self.assertRegex(template["render_token"], r"^[0-9a-f]{32}$")
        self.assertEqual(template["canvas"]["width"], 1536)
        self.assertEqual(len(template["backgrounds"]), 1)
        self.assertEqual(template["backgrounds"][0]["when"], {})

        listing = self.client.get("/v1/widget-studio/templates", headers=auth())
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()[0]["background_count"], 1)
        self.assertEqual(listing.json()[0]["layer_count"], len(template["layers"]))

        fetched = self.client.get(
            f"/v1/widget-studio/templates/{template['id']}", headers=auth()
        )
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["id"], "nijika")

        self.clock["now"] = datetime(2026, 10, 30, 12, 5, 0, tzinfo=TZ)
        template["name"] = "Nijika Frame"
        template["layers"][0]["text"] = "今日连胜"
        updated = self.put(template)
        self.assertEqual(updated["name"], "Nijika Frame")
        self.assertEqual(updated["layers"][0]["text"], "今日连胜")
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

    def test_02_upload_three_backgrounds_and_flame(self) -> None:
        template = self.create_template()
        for index, bg_id in enumerate(("bg-morning", "bg-night", "bg-streak")):
            response = self.upload(
                template["id"],
                "background",
                bg_id=bg_id,
                name=f"底图 {index}",
                data=png_bytes(color=(20 + index * 60, 110, 190)),
                filename=f"{bg_id}.png",
            )
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            self.assertEqual(payload["src"], f"backgrounds/{bg_id}.png")
            stored = self.widgets_dir / template["id"] / payload["src"]
            self.assertTrue(stored.is_file())
            with Image.open(stored) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (320, 180))
            template = payload["template"]
        self.assertEqual(len(template["backgrounds"]), 4)

        flame = png_bytes(size=(120, 140), color=(255, 120, 30))
        response = self.upload(
            template["id"], "flame", data=flame, filename="flame-source.png"
        )
        self.assertEqual(response.status_code, 200, response.text)
        template = response.json()["template"]
        flame_layer = next(layer for layer in template["layers"] if layer["role"] == "flame")
        self.assertEqual(flame_layer["src"], "flame.png")
        self.assertTrue((self.widgets_dir / template["id"] / "flame.png").is_file())

        asset = self.client.get(
            f"/v1/widget-studio/templates/{template['id']}/assets/flame.png"
        )
        self.assertEqual(asset.status_code, 200)
        self.assertEqual(asset.headers["cache-control"], "no-store")
        self.assertIn("image/png", asset.headers["content-type"])

        thumb = self.client.get(
            f"/v1/widget-studio/templates/{template['id']}/backgrounds/bg-morning/thumb?w=240"
        )
        self.assertEqual(thumb.status_code, 200)
        self.assertEqual(thumb.headers["cache-control"], "no-store")
        with Image.open(io.BytesIO(thumb.content)) as image:
            self.assertEqual(image.width, 240)

    def test_03_ghost_library_reference(self) -> None:
        library = self.client.get("/v1/widget-studio/library")
        self.assertEqual(library.status_code, 200)
        items = library.json()
        bronze = next(item for item in items if item["id"] == "tiers/card/bronze")
        self.assertEqual(bronze["src"], "ghost:assets/tiers/card/bronze.png")
        self.assertTrue(any(item["id"] == "frames/frame_ember" for item in items))

        template = self.create_template()
        template["backgrounds"].append(
            {
                "id": "bg-bronze",
                "name": "青铜段位",
                "src": bronze["src"],
                "when": {"league": "bronze"},
                "priority": 20,
                "fit": "cover",
                "offsetX": 0,
                "offsetY": 0,
                "scale": 1,
            }
        )
        template = self.put(template)
        ghost_bg = next(bg for bg in template["backgrounds"] if bg["id"] == "bg-bronze")
        self.assertEqual(ghost_bg["src"], bronze["src"])

        thumb = self.client.get(
            f"/v1/widget-studio/templates/{template['id']}/backgrounds/bg-bronze/thumb?w=120"
        )
        self.assertEqual(thumb.status_code, 200)

    def test_04_conditions_priority_fallback_and_override(self) -> None:
        template = self.create_template()
        specs = [
            ("bg-hour", {"hour_from": 5, "hour_to": 11}, 100),
            ("bg-weekday", {"weekdays": [1]}, 90),
            ("bg-streak", {"streak_min": 7, "streak_max": 29}, 80),
            ("bg-completed", {"completed_today": True}, 70),
            ("bg-league", {"league": "bronze"}, 60),
            ("bg-tie-a", {"event": "tie"}, 55),
            ("bg-tie-b", {"event": "tie"}, 55),
            ("bg-event", {"event": "rush"}, 50),
        ]
        for bg_id, _, _ in specs:
            template = self.add_local_background(template, bg_id, name=bg_id)

        backgrounds = [
            {
                "id": "bg-fallback",
                "name": "默认",
                "src": template["backgrounds"][0]["src"],
                "when": {},
                "priority": 0,
                "fit": "cover",
                "offsetX": 0,
                "offsetY": 0,
                "scale": 1,
            }
        ]
        for bg_id, when, priority in specs:
            backgrounds.append(
                {
                    "id": bg_id,
                    "name": bg_id,
                    "src": f"backgrounds/{bg_id}.png",
                    "when": when,
                    "priority": priority,
                    "fit": "cover",
                    "offsetX": 0,
                    "offsetY": 0,
                    "scale": 1,
                }
            )
        template["backgrounds"] = backgrounds
        template = self.put(template)

        cases = [
            ({"hour": 6, "weekday": 2, "streak": 0, "completed": 0, "league": "gold", "event": "x"}, "bg-hour"),
            ({"hour": 12, "weekday": 1, "streak": 0, "completed": 0, "league": "gold", "event": "x"}, "bg-weekday"),
            ({"hour": 12, "weekday": 2, "streak": 12, "completed": 0, "league": "gold", "event": "x"}, "bg-streak"),
            ({"hour": 12, "weekday": 2, "streak": 0, "completed": 1, "league": "gold", "event": "x"}, "bg-completed"),
            ({"hour": 12, "weekday": 2, "streak": 0, "completed": 0, "league": "bronze", "event": "x"}, "bg-league"),
            ({"hour": 12, "weekday": 2, "streak": 0, "completed": 0, "league": "gold", "event": "rush"}, "bg-event"),
            ({"hour": 12, "weekday": 2, "streak": 0, "completed": 0, "league": "gold", "event": "tie"}, "bg-tie-a"),
            ({"hour": 12, "weekday": 2, "streak": 0, "completed": 0, "league": "gold", "event": ""}, "bg-fallback"),
            (
                {"hour": 6, "weekday": 1, "streak": 12, "completed": 1, "league": "bronze", "event": "rush"},
                "bg-hour",
            ),
        ]
        for params, expected in cases:
            response = self.render(template, **params)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.headers["x-widget-background"], expected, params)

        forced = self.render(template, bg="bg-event")
        self.assertEqual(forced.status_code, 200)
        self.assertEqual(forced.headers["x-widget-background"], "bg-event")
        self.assertEqual(forced.headers["cache-control"], "no-store")

        bad_bg = self.render(template, bg="bg-missing")
        self.assertEqual(bad_bg.status_code, 404)

    def test_05_render_size_alpha_and_token(self) -> None:
        template = self.create_template()
        response = self.render(template, streak=12, xp=345, rank=3, name="那尔")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["x-widget-background"], "bg-default")
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

        wrong = self.client.get(
            f"/v1/widgets/{template['id']}.png", params={"token": "0" * 32}
        )
        self.assertEqual(wrong.status_code, 404)
        missing = self.client.get(f"/v1/widgets/{template['id']}.png")
        self.assertEqual(missing.status_code, 404)
        unknown = self.client.get(
            "/v1/widgets/does-not-exist.png", params={"token": "0" * 32}
        )
        self.assertEqual(unknown.status_code, 404)
        invalid_size = self.render(template, size="2x")
        self.assertEqual(invalid_size.status_code, 400)

    def test_06_disk_edit_is_live_without_restart(self) -> None:
        template = self.create_template()
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
        special_response = self.render(template, event="special")
        self.assertEqual(special_response.headers["x-widget-background"], "bg-default")

    def test_07_invalid_inputs_are_4xx(self) -> None:
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

        duplicate = self.upload(template["id"], "background", bg_id="bg-default")
        self.assertEqual(duplicate.status_code, 409)

        no_fallback = json.loads(json.dumps(template))
        no_fallback["backgrounds"][0]["when"] = {"event": "only"}
        response = self.client.put(
            f"/v1/widget-studio/templates/{template['id']}",
            headers=auth(),
            json=no_fallback,
        )
        self.assertEqual(response.status_code, 422)

        duplicate_bg = json.loads(json.dumps(template))
        duplicate_bg["backgrounds"].append(json.loads(json.dumps(template["backgrounds"][0])))
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

    def test_08_bad_json_is_skipped_in_list(self) -> None:
        template = self.create_template()
        broken = self.widgets_dir / "broken-template"
        broken.mkdir(parents=True)
        (broken / "template.json").write_text("{not json", encoding="utf-8")
        listing = self.client.get("/v1/widget-studio/templates", headers=auth())
        self.assertEqual(listing.status_code, 200)
        ids = [item["id"] for item in listing.json()]
        self.assertEqual(ids, [template["id"]])

    def test_09_editor_is_served_by_the_existing_pwa_mount(self) -> None:
        app = FastAPI()

        @app.get("/v1/ping")
        def ping() -> dict:
            return {"ok": True}

        mount_web(app)
        with TestClient(app) as client:
            page = client.get("/widget-studio/")
            self.assertEqual(page.status_code, 200)
            self.assertIn("Widget Studio", page.text)
            self.assertIn("/widget-studio/app.js", page.text)
            script = client.get("/widget-studio/app.js")
            self.assertEqual(script.status_code, 200)
            self.assertIn("javascript", script.headers["content-type"])
            style = client.get("/widget-studio/styles.css")
            self.assertEqual(style.status_code, 200)
            self.assertEqual(client.get("/v1/ping").json(), {"ok": True})

    def test_10_cross_night_and_weekday_selection(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
