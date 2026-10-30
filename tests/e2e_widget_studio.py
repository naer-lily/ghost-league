#!/usr/bin/env python3
"""Playwright E2E for Widget Studio (schema v3, explicit save).

Run explicitly with the shared UI environment::

    /opt/ui-venv/bin/python tests/e2e_widget_studio.py

It boots a temporary FastAPI/PWA instance (no TLS, no new service), drives the
real editor, checks that drags/typing never PUT (even after >1.5s), saves only
on Ctrl+S / the save button, verifies per-background text variants and
positions, and writes screenshots under ``artifacts/``.
"""

from __future__ import annotations

import json
import os
import re
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
        "document.querySelector('#sync-status').textContent.startsWith('已保存 ·')",
        timeout=15000,
    )


def wait_dirty(page) -> None:
    page.wait_for_function(
        "document.querySelector('#sync-status').textContent === '未保存'",
        timeout=5000,
    )


def canvas_point(page, x: float, y: float) -> tuple[float, float]:
    box = page.locator("#studio-canvas").bounding_box()
    assert box is not None
    return (
        box["x"] + x * (box["width"] / 1536),
        box["y"] + y * (box["height"] / 914),
    )


def drag_element(page, x: float, y: float, dx: float, dy: float) -> None:
    start = canvas_point(page, x, y)
    page.mouse.move(*start)
    page.mouse.down()
    page.mouse.move(start[0] + dx, start[1] + dy, steps=8)
    page.mouse.up()


def fetch_template(context, origin: str, template_id: str) -> dict:
    response = context.request.get(
        f"{origin}/v1/widget-studio/templates/{template_id}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status == 200, response.text()
    return response.json()


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
            assert page.locator("#save-template-btn").is_disabled()
            fixed_url = f"{origin}/v1/widgets/owner/nijika-e2e.png"
            assert page.input_value("#widget-fixed-url") == fixed_url
            assert page.inner_text("#widget-user-id") == "owner"
            assert page.inner_text("#widget-template-id") == "nijika-e2e"
            print("PASS editor shows the fixed user_id + template_id URL")

            # Uploads only write files; they mark the in-memory template dirty
            # and never PUT on their own.
            put_requests.clear()
            page.set_input_files("#bg-file-input", [str(path) for path in images])
            page.wait_for_function(
                "document.querySelectorAll('.bg-card').length === 4", timeout=20000
            )
            wait_dirty(page)
            page.wait_for_timeout(1600)
            assert not put_requests, "uploads must not auto-PUT"
            assert page.input_value("#widget-fixed-url") == fixed_url
            saved_after_upload = fetch_template(context, origin, "nijika-e2e")
            assert len(saved_after_upload["backgrounds"]) == 1, saved_after_upload
            page.click("#save-template-btn")
            page.wait_for_function("document.querySelectorAll('.bg-card').length === 4")
            wait_saved(page)
            assert put_requests, "save button must PUT"
            print("PASS uploads mark dirty, no auto-PUT, explicit save persists")

            # Second template for the switch-confirmation test.
            page.click("#new-template-btn")
            page.wait_for_selector("#template-modal:not([hidden])")
            page.fill("#template-name-input", "Second E2E")
            page.click("#template-modal-confirm")
            page.wait_for_function(
                "document.querySelector('#template-select').value === 'second-e2e'",
                timeout=15000,
            )
            wait_saved(page)
            page.wait_for_function(
                "document.querySelector('#widget-fixed-url').value.endsWith('/v1/widgets/owner/second-e2e.png')",
                timeout=15000,
            )
            assert page.input_value("#widget-fixed-url") == f"{origin}/v1/widgets/owner/second-e2e.png"
            page.select_option("#template-select", "nijika-e2e")
            page.wait_for_function(
                "document.querySelector('#template-select').value === 'nijika-e2e'",
                timeout=15000,
            )
            page.wait_for_function(
                "document.querySelector('#widget-fixed-url').value.endsWith('/v1/widgets/owner/nijika-e2e.png')",
                timeout=15000,
            )
            wait_saved(page)
            assert page.input_value("#widget-fixed-url") == fixed_url
            print("PASS changing the outer template changes template_id in the URL")

            # Condition edits stay local until an explicit save.
            page.click('.bg-card[data-bg-id="bg-morning"] .bg-card-head')
            page.select_option("#cond-hour-preset", "5-11")
            page.select_option("#cond-weekday-preset", "workdays")
            page.fill("#bg-priority", "50")
            page.wait_for_function(
                "document.querySelector('.bg-card[data-bg-id=\"bg-morning\"] .bg-summary').textContent.includes('05–11')",
                timeout=5000,
            )
            wait_dirty(page)
            assert page.input_value("#widget-fixed-url") == fixed_url
            put_requests.clear()
            page.wait_for_timeout(1600)
            assert not put_requests, "condition edits must not auto-PUT"
            page.click("#save-template-btn")
            wait_saved(page)
            assert page.input_value("#widget-fixed-url") == fixed_url
            print("PASS condition edits wait for explicit save and keep the URL fixed")

            # Drag text, streak number and flame: each stays local for >1.5s.
            page.click('.text-item[data-text-id="text-1"]')
            old_x = float(page.input_value("#text-x"))
            old_y = float(page.input_value("#text-y"))
            put_requests.clear()
            drag_element(page, old_x + 120, old_y + 50, 90, 40)
            wait_dirty(page)
            page.wait_for_timeout(1700)
            assert not put_requests, "text drag must not auto-PUT"
            assert float(page.input_value("#text-x")) > old_x + 50
            print("PASS text drag local for >1.5s, 0 PUT")

            put_requests.clear()
            drag_element(page, 940, 390, -60, 50)
            page.wait_for_timeout(1700)
            assert not put_requests, "streak drag must not auto-PUT"
            streak_x = float(page.input_value("#streak-x"))
            print("PASS streak drag local for >1.5s, 0 PUT")

            put_requests.clear()
            drag_element(page, 720, 350, 40, -20)
            page.wait_for_timeout(1700)
            assert not put_requests, "flame drag must not auto-PUT"
            print("PASS flame drag local for >1.5s, 0 PUT")

            put_requests.clear()
            page.keyboard.press("Control+s")
            page.wait_for_function("document.querySelector('#save-template-btn').disabled === true")
            wait_saved(page)
            assert put_requests, "Ctrl+S must PUT"
            saved = fetch_template(context, origin, "nijika-e2e")
            morning = next(bg for bg in saved["backgrounds"] if bg["id"] == "bg-morning")
            assert abs(morning["layout"]["texts"][0]["x"] - float(page.input_value("#text-x"))) < 0.5
            assert abs(morning["layout"]["streak"]["x"] - streak_x) < 0.5
            print("PASS Ctrl+S PUTs and status goes 未保存 -> 已保存")

            # Text content / condition change: no PUT, confirm on switch/reload.
            page.click('.text-item[data-text-id="text-1"]')
            page.fill("#text-content", "测试文字A")
            page.fill("#bg-priority", "55")
            wait_dirty(page)
            put_requests.clear()
            page.wait_for_timeout(1600)
            assert not put_requests, "text/condition edits must not auto-PUT"

            dialogs: list[str] = []

            def dismiss(dialog):
                dialogs.append(dialog.message)
                dialog.dismiss()

            page.once("dialog", dismiss)
            try:
                page.select_option("#template-select", "second-e2e", timeout=4000)
            except Exception:
                pass
            page.wait_for_timeout(400)
            assert dialogs and "未保存" in dialogs[0], dialogs
            assert page.input_value("#template-select") == "nijika-e2e"
            wait_dirty(page)
            print("PASS switch with dirty state asks for confirmation and cancels")

            dialogs.clear()
            page.once("dialog", dismiss)
            try:
                page.reload(wait_until="domcontentloaded", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(500)
            assert dialogs, "reload must show a beforeunload confirmation"
            assert page.locator("#sync-status").inner_text() == "未保存"
            print("PASS reload with dirty state asks for confirmation and cancels")

            page.keyboard.press("Control+s")
            wait_saved(page)
            saved = fetch_template(context, origin, "nijika-e2e")
            morning = next(bg for bg in saved["backgrounds"] if bg["id"] == "bg-morning")
            assert morning["layout"]["texts"][0]["text"] == "测试文字A"
            assert morning["priority"] == 55
            print("PASS explicit save persisted text and condition")

            # Two more text variants on the same background.
            page.click('.bg-card[data-bg-id="bg-morning"] .bg-card-head')
            page.click("#add-text-variant")
            page.fill("#text-content", "第二条")
            page.fill("#text-x", "100")
            page.fill("#text-y", "120")
            page.click("#add-text-variant")
            page.fill("#text-content", "第三条")
            page.fill("#text-x", "200")
            page.fill("#text-y", "220")
            wait_dirty(page)
            page.click("#save-template-btn")
            wait_saved(page)
            saved = fetch_template(context, origin, "nijika-e2e")
            morning = next(bg for bg in saved["backgrounds"] if bg["id"] == "bg-morning")
            text_ids = [item["id"] for item in morning["layout"]["texts"]]
            assert text_ids == ["text-1", "text-2", "text-3"], text_ids
            assert page.input_value("#widget-fixed-url") == fixed_url
            print("PASS added two text variants without changing the URL")

            # Fixed URL: no data query, and the headers belong to the saved
            # background that the server selected for this user.
            saved = fetch_template(context, origin, "nijika-e2e")
            backgrounds = {bg["id"]: bg for bg in saved["backgrounds"]}
            fixed = f"{origin}/v1/widgets/owner/nijika-e2e.png"
            assert "?" not in fixed
            seen_texts: list[str] = []
            for _ in range(12):
                response = context.request.get(fixed)
                assert response.status == 200, response.text()
                bg_id = response.headers["x-widget-background"]
                text_id = response.headers["x-widget-text"]
                assert bg_id in backgrounds, bg_id
                assert text_id in [
                    item["id"] for item in backgrounds[bg_id]["layout"]["texts"]
                ], text_id
                seen_texts.append(text_id)
            print(f"PASS fixed URL returns headers in its own background ({sorted(set(seen_texts))})")

            page.fill("#preview-hour", "8")
            page.select_option("#preview-weekday", "1")
            page.fill("#preview-league", "")
            page.fill("#preview-event", "")
            page.wait_for_function(
                "document.querySelector('#bg-match-badge').textContent.includes('bg-morning')",
                timeout=5000,
            )
            page.click("#random-preview-btn")
            page.wait_for_selector("#preview-modal:not([hidden])")
            page.wait_for_function(
                "document.querySelector('#preview-meta').textContent.includes('随机刷新')",
                timeout=10000,
            )
            assert page.input_value("#production-url") == fixed
            meta = page.locator("#preview-meta").inner_text()
            match = re.search(r"底图 (\S+) · 文字 (\S+)", meta)
            assert match and match.group(1) in backgrounds, meta
            assert match.group(2) in [
                item["id"] for item in backgrounds[match.group(1)]["layout"]["texts"]
            ], meta
            page.click("#preview-close")
            print("PASS production preview uses the fixed URL without a query")

            # Background B has independent coordinates; both survive reload.
            page.click('.bg-card[data-bg-id="bg-night"] .bg-card-head')
            page.fill("#text-content", "夜晚文字")
            page.fill("#text-x", "320")
            page.fill("#text-y", "360")
            page.fill("#streak-x", "300")
            page.fill("#streak-y", "200")
            page.fill("#flame-x", "260")
            page.fill("#flame-y", "180")
            wait_dirty(page)
            page.click("#save-template-btn")
            wait_saved(page)
            saved = fetch_template(context, origin, "nijika-e2e")
            night = next(bg for bg in saved["backgrounds"] if bg["id"] == "bg-night")
            morning = next(bg for bg in saved["backgrounds"] if bg["id"] == "bg-morning")
            assert night["layout"]["texts"][0]["x"] == 320
            assert night["layout"]["texts"][0]["y"] == 360
            assert night["layout"]["streak"] == {"x": 300, "y": 200}
            assert night["layout"]["flame"] == {"x": 260, "y": 180}
            assert morning["layout"]["texts"][0]["x"] != 320
            assert morning["layout"]["streak"]["x"] != 300
            print("PASS background B stores different coordinates than A")

            page.reload(wait_until="networkidle")
            page.wait_for_function(
                "document.querySelector('#template-select').value === 'nijika-e2e'",
                timeout=10000,
            )
            page.click('.bg-card[data-bg-id="bg-night"] .bg-card-head')
            assert float(page.input_value("#text-x")) == 320
            assert float(page.input_value("#text-y")) == 360
            assert float(page.input_value("#streak-x")) == 300
            assert float(page.input_value("#flame-x")) == 260
            page.click('.bg-card[data-bg-id="bg-morning"] .bg-card-head')
            page.click('.text-item[data-text-id="text-2"]')
            assert float(page.input_value("#text-x")) == 100
            assert float(page.input_value("#text-y")) == 120
            assert page.input_value("#widget-fixed-url") == fixed_url
            print("PASS reload restores per-background coordinates and the fixed URL")

            # Open the fixed URL directly, with no data query.
            direct = context.new_page()
            direct_response = direct.goto(fixed_url, wait_until="load")
            assert direct_response is not None
            assert direct_response.status == 200
            assert direct_response.headers.get("content-type", "").startswith("image/png")
            assert "?" not in direct.url
            direct.close()
            print("PASS direct fixed URL opens without a query")

            # Final view for screenshots: three readable text variants on A.
            page.wait_for_timeout(300)
            page.screenshot(path=str(ARTIFACTS / "widget-studio-1440.png"), full_page=False)
            desktop_box = page.locator("#studio-canvas").bounding_box()
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(500)
            mobile_box = page.locator("#studio-canvas").bounding_box()
            assert mobile_box is not None and 0 < mobile_box["width"] <= 390
            assert page.is_visible("#new-template-btn")
            assert page.is_visible("#widget-fixed-url")
            assert page.locator("#text-variant-list .text-item").count() == 3
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
