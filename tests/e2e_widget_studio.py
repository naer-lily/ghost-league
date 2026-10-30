#!/usr/bin/env python3
"""Playwright E2E for Widget Studio.

Run explicitly with the shared UI environment::

    /opt/ui-venv/bin/python tests/e2e_widget_studio.py

It boots a temporary FastAPI/PWA instance (no TLS, no new service), drives the
real editor, checks that pointermove never PUTs, verifies persisted JSON and the
public PNG endpoint, and writes screenshots under ``artifacts/``.
"""

from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
TOKEN = "widget-studio-e2e-token"
NOW = datetime(2026, 10, 30, 12, 0, 0)
SERVER_SCRIPT = """
import sys
from datetime import datetime
from pathlib import Path

root = Path({root!r})
sys.path.insert(0, str(root))

from ghost_league.accounts import AccountsStore
from ghost_league.api import create_app
from ghost_league.pwa import mount_web
from ghost_league.schedule import TZ

base = Path({base!r})
api_dir = base / "api"
api_dir.mkdir(parents=True, exist_ok=True)
now = datetime(2026, 10, 30, 12, 0, 0, tzinfo=TZ)
store = AccountsStore(api_dir / "accounts.db", now_fn=lambda: now)
store.initialize()
store.create("owner", "You", token={token!r})
app = create_app(
    game_db_path=api_dir / "league.db",
    cache_path=base / "cache.json",
    avatars_path=api_dir / "avatars.json",
    api_dir=api_dir,
    accounts_db=api_dir / "accounts.db",
    social_db=api_dir / "social.db",
    webhooks_db=api_dir / "webhooks.db",
    start_webhook_worker=False,
    widgets_dir=base / "widgets",
    widget_web_root=root / "web",
    now_fn=lambda: now,
)
mount_web(app)

import uvicorn

uvicorn.run(app, host="127.0.0.1", port={port}, log_level="warning")
"""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def write_image(path: Path, color: tuple[int, int, int]) -> None:
    image = Image.new("RGB", (800, 500), color)
    image.paste((255, 255, 255), (0, 0, 80, 80))
    image.save(path, format="PNG")


def server_python() -> str:
    candidates = [
        os.environ.get("GHOST_LEAGUE_PYTHON"),
        "/usr/local/lib/hermes-agent/venv/bin/python",
        sys.executable,
        "/usr/bin/python3",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        check = subprocess.run(
            [candidate, "-c", "import fastapi, PIL, uvicorn, ghost_league"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if check.returncode == 0:
            return candidate
    raise RuntimeError("no Python with FastAPI/Pillow/uvicorn/ghost_league was found")


def start_server(base: Path, port: int) -> subprocess.Popen:
    script = base / "e2e_server.py"
    script.write_text(
        textwrap.dedent(SERVER_SCRIPT).format(root=str(ROOT), base=str(base), token=TOKEN, port=port),
        encoding="utf-8",
    )
    log = open(base / "server.log", "w", encoding="utf-8")
    process = subprocess.Popen(
        [server_python(), str(script)],
        cwd=ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(ROOT)},
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        if process.poll() is not None:
            log.close()
            raise RuntimeError(f"server exited early:\n{(base / 'server.log').read_text(encoding='utf-8')}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                if response.status == 200:
                    return process
        except OSError:
            time.sleep(0.1)
    process.terminate()
    log.close()
    raise RuntimeError(f"server did not become healthy:\n{(base / 'server.log').read_text(encoding='utf-8')}")


def stop_server(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def launch_browser(playwright):
    system_chrome = next(
        (path for path in ("/usr/bin/chromium", "/usr/bin/google-chrome") if Path(path).is_file()),
        None,
    )
    options = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
    if system_chrome:
        options["executable_path"] = system_chrome
    return playwright.chromium.launch(**options)


def wait_saved(page) -> None:
    page.wait_for_function(
        "document.querySelector('#sync-status').textContent.startsWith('已同步到')",
        timeout=15000,
    )


def background_count(page) -> int:
    return page.locator(".bg-card").count()


def main() -> int:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    temp = tempfile.TemporaryDirectory()
    base = Path(temp.name)
    port = free_port()
    server = start_server(base, port)
    origin = f"http://127.0.0.1:{port}"

    images = []
    for name, color in (
        ("morning.png", (255, 170, 60)),
        ("streak.png", (60, 190, 230)),
        ("night.png", (40, 45, 90)),
    ):
        path = base / name
        write_image(path, color)
        images.append(path)

    try:
        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            context.add_init_script(
                f"localStorage.setItem('gl.token.v1', {json.dumps(TOKEN)});"
            )
            page = context.new_page()
            put_requests: list[str] = []
            page.on(
                "request",
                lambda request: put_requests.append(request.url)
                if request.method == "PUT"
                else None,
            )
            page.goto(f"{origin}/widget-studio/", wait_until="networkidle")
            page.wait_for_selector("#template-modal:not([hidden])")
            page.fill("#template-name-input", "Nijika E2E")
            page.click("#template-modal-confirm")
            page.wait_for_function(
                "document.querySelector('#template-select').value === 'nijika-e2e'",
                timeout=15000,
            )
            wait_saved(page)
            print("PASS new template")

            page.set_input_files("#bg-file-input", [str(path) for path in images])
            page.wait_for_function(
                "document.querySelectorAll('.bg-card').length === 4", timeout=20000
            )
            wait_saved(page)
            print("PASS uploaded 3 backgrounds")

            page.click("#library-open")
            page.wait_for_selector("#library-modal:not([hidden])")
            page.click('.library-item[data-src="ghost:assets/tiers/card/bronze.png"]')
            page.wait_for_function(
                "document.querySelectorAll('.bg-card').length === 5", timeout=10000
            )
            wait_saved(page)
            print("PASS added Ghost library background")

            page.click('.bg-card[data-bg-id="bg-morning"] .bg-card-head')
            page.select_option("#cond-hour-preset", "5-11")
            page.select_option("#cond-weekday-preset", "workdays")
            page.fill("#bg-priority", "50")
            page.wait_for_function(
                "document.querySelector('.bg-card[data-bg-id=\"bg-morning\"] .bg-summary').textContent.includes('05–11')",
                timeout=5000,
            )
            wait_saved(page)

            page.click('.bg-card[data-bg-id="bg-tiers-card-bronze"] .bg-card-head')
            page.fill("#cond-league", "bronze")
            wait_saved(page)
            print("PASS edited conditions")

            page.fill("#preview-hour", "8")
            page.select_option("#preview-weekday", "1")
            page.wait_for_function(
                "document.querySelector('#bg-match-badge').textContent.includes('bg-morning')",
                timeout=5000,
            )
            pixel_morning = page.evaluate(
                "() => [...document.getElementById('studio-canvas').getContext('2d').getImageData(768, 100, 1, 1).data]"
            )
            page.fill("#preview-hour", "15")
            page.wait_for_function(
                "document.querySelector('#bg-match-badge').textContent.includes('fallback')",
                timeout=5000,
            )
            pixel_fallback = page.evaluate(
                "() => [...document.getElementById('studio-canvas').getContext('2d').getImageData(768, 100, 1, 1).data]"
            )
            assert pixel_morning != pixel_fallback, (pixel_morning, pixel_fallback)
            page.fill("#preview-league", "bronze")
            page.wait_for_function(
                "document.querySelector('#bg-match-badge').textContent.includes('bg-tiers-card-bronze')",
                timeout=5000,
            )
            print("PASS preview context switches background")
            page.fill("#preview-league", "")

            page.click('.layer-item[data-layer-id="label-1"]')
            old_x = float(page.input_value("#layer-x"))
            old_y = float(page.input_value("#layer-y"))
            box = page.locator("#studio-canvas").bounding_box()
            assert box is not None
            scale = box["width"] / 1536
            start_x = box["x"] + (old_x + 260) * scale
            start_y = box["y"] + (old_y + 50) * (box["height"] / 914)
            put_requests.clear()
            page.mouse.move(start_x, start_y)
            page.mouse.down()
            page.mouse.move(start_x + 40, start_y + 10, steps=6)
            page.wait_for_timeout(650)
            assert not put_requests, "pointermove must not trigger PUT"
            page.mouse.move(start_x + 90, start_y + 40, steps=8)
            page.wait_for_timeout(250)
            assert not put_requests, "pointer drag must stay local before pointerup"
            page.mouse.up()
            page.wait_for_timeout(900)
            assert put_requests, "pointerup must schedule a PUT within 400ms"
            wait_saved(page)
            new_x = float(page.input_value("#layer-x"))
            new_y = float(page.input_value("#layer-y"))
            assert new_x > old_x + 50, (old_x, new_x)
            assert new_y > old_y + 10, (old_y, new_y)
            print("PASS drag stays local, PUT only after pointerup")

            request = context.request.get(
                f"{origin}/v1/widget-studio/templates/nijika-e2e",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
            assert request.status == 200, request.text()
            saved = request.json()
            label = next(layer for layer in saved["layers"] if layer["id"] == "label-1")
            assert abs(label["x"] - new_x) < 0.5, (label, new_x)
            assert abs(label["y"] - new_y) < 0.5, (label, new_y)
            morning = next(bg for bg in saved["backgrounds"] if bg["id"] == "bg-morning")
            assert morning["when"] == {"hour_from": 5, "hour_to": 11, "weekdays": [1, 2, 3, 4, 5]}
            assert morning["priority"] == 50
            bronze = next(bg for bg in saved["backgrounds"] if bg["id"] == "bg-tiers-card-bronze")
            assert bronze["src"] == "ghost:assets/tiers/card/bronze.png"
            assert bronze["when"] == {"league": "bronze"}
            assert len(saved["backgrounds"]) == 5
            print("PASS persisted JSON has geometry, backgrounds and conditions")

            page.reload(wait_until="networkidle")
            page.wait_for_function(
                "document.querySelector('#template-select').value === 'nijika-e2e'",
                timeout=10000,
            )
            page.wait_for_function(
                "document.querySelectorAll('.bg-card').length === 5", timeout=10000
            )
            assert float(page.input_value("#layer-x")) == new_x
            assert float(page.input_value("#layer-y")) == new_y
            page.wait_for_function(
                "document.querySelector('.bg-card[data-bg-id=\"bg-morning\"] .bg-summary').textContent.includes('05–11 点 · 工作日')",
                timeout=5000,
            )
            print("PASS reload restores template, positions and conditions")

            page.fill("#preview-hour", "15")
            page.wait_for_function(
                "document.querySelector('#bg-match-badge').textContent.includes('fallback')",
                timeout=5000,
            )
            page.click("#production-preview-btn")
            page.wait_for_selector("#preview-modal:not([hidden])")
            page.wait_for_function(
                "document.querySelector('#production-image').complete && document.querySelector('#production-image').naturalWidth > 0",
                timeout=15000,
            )
            production_url = page.input_value("#production-url")
            assert "token=" in production_url and "Bearer" not in production_url
            with urllib.request.urlopen(production_url, timeout=20) as response:
                assert response.status == 200
                assert response.headers["X-Widget-Background"] == "bg-default", response.headers
                assert response.headers["Cache-Control"] == "no-store"
                image = Image.open(io.BytesIO(response.read()))
                assert image.size == (1536, 914), image.size
            page.click("#preview-close")
            print("PASS production preview 200 / 1536x914 / X-Widget-Background")

            page.screenshot(path=str(ARTIFACTS / "widget-studio-1440.png"), full_page=False)
            desktop_box = page.locator("#studio-canvas").bounding_box()
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(400)
            mobile_box = page.locator("#studio-canvas").bounding_box()
            assert mobile_box is not None and 0 < mobile_box["width"] <= 390
            assert page.is_visible("#new-template-btn")
            page.screenshot(path=str(ARTIFACTS / "widget-studio-390.png"), full_page=False)
            print("PASS desktop/mobile screenshots")
            print(f"  desktop canvas {desktop_box}")
            print(f"  mobile canvas {mobile_box}")
            browser.close()
    finally:
        stop_server(server)
        temp.cleanup()
    print("E2E OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
