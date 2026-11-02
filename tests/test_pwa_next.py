from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ghost_league.pwa import ACTIVE_WEB_ROOT, WEB_ROOT, mount_web

ROOT = Path(__file__).resolve().parents[1]
NEXT_BUILD_ROOT = WEB_ROOT.parent / "web-next"


class PWANextFallbackTests(unittest.TestCase):
    def test_spa_deep_links_keep_assets_and_api_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text(
                "<!doctype html><title>下一个星图</title>",
                encoding="utf-8",
            )
            (root / "assets").mkdir()
            (root / "assets" / "app.js").write_text(
                "console.log('app');",
                encoding="utf-8",
            )

            app = FastAPI()

            @app.get("/v1/ping")
            def ping() -> dict[str, bool]:
                return {"ok": True}

            mount_web(app, root)
            with TestClient(app) as client:
                deep_link = client.get("/shop")
                self.assertEqual(deep_link.status_code, 200)
                self.assertIn("下一个星图", deep_link.text)

                asset = client.get("/assets/app.js")
                self.assertEqual(asset.status_code, 200)
                self.assertIn("console.log", asset.text)

                missing_asset = client.get("/assets/missing.js")
                self.assertEqual(missing_asset.status_code, 404)

                api = client.get("/v1/ping")
                self.assertEqual(api.status_code, 200)
                self.assertEqual(api.json(), {"ok": True})

                missing_api = client.get("/v1/not-a-route")
                self.assertEqual(missing_api.status_code, 404)
                self.assertNotIn("下一个星图", missing_api.text)

    def test_built_web_next_root_when_present(self) -> None:
        build_index = NEXT_BUILD_ROOT / "index.html"
        if not build_index.is_file():
            self.skipTest("web-next has not been built in this environment")

        self.assertTrue(ACTIVE_WEB_ROOT.is_dir(), ACTIVE_WEB_ROOT)
        self.assertTrue((ACTIVE_WEB_ROOT / "index.html").is_file())
        for name in ("manifest.webmanifest", "sw.js"):
            self.assertTrue((NEXT_BUILD_ROOT / name).is_file(), name)
        self.assertTrue((NEXT_BUILD_ROOT / "assets").is_dir())


if __name__ == "__main__":
    unittest.main()
