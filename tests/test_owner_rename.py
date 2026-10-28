from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from ghost_league import accounts as accounts_module
from ghost_league.accounts import AccountsStore
from ghost_league.api import create_app
from ghost_league.schedule import TZ
from ghost_league.webhooks import WebhookService
from tests.test_webhooks import make_fixture as make_api_fixture

TOKEN = "rename-owner-token"
NOW = datetime(2026, 10, 26, 18, 36, 0, tzinfo=TZ)
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def build_rename_fixture(base: Path) -> tuple[AccountsStore, Path]:
    api_dir = base / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    store = AccountsStore(api_dir / "accounts.db", now_fn=lambda: NOW)
    store.initialize()
    store.create(
        "owner",
        "Owner",
        token=TOKEN,
        activity_label="画画",
    )
    store.set_avatar_url("owner", "avatars/owner.webp")
    avatar_dir = api_dir / "avatars"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    (avatar_dir / "owner.webp").write_bytes(b"avatar-bytes")

    membership = {
        "owner": {
            "user_id": "owner",
            "tier": "Bronze",
            "group_id": "Bronze-W53-G01",
            "joined_week": 53,
            "ghost_ids": ["ghost-1", "ghost-2"],
        }
    }
    (api_dir / "membership.json").write_text(json.dumps(membership), encoding="utf-8")

    with sqlite3.connect(api_dir / "events.db") as connection:
        connection.execute(
            "CREATE TABLE drawing_events ("
            "user_id TEXT NOT NULL, event_id TEXT NOT NULL, seconds INTEGER NOT NULL, "
            "occurred_at TEXT NOT NULL, week_start TEXT NOT NULL, created_at TEXT NOT NULL, "
            "PRIMARY KEY (user_id, event_id))"
        )
        connection.execute(
            "INSERT INTO drawing_events VALUES (?, ?, ?, ?, ?, ?)",
            ("owner", "e1", 600, NOW.isoformat(), "2026-10-26", NOW.isoformat()),
        )
        connection.execute(
            "INSERT INTO drawing_events VALUES (?, ?, ?, ?, ?, ?)",
            ("owner", "e2", 120, NOW.isoformat(), "2026-10-26", NOW.isoformat()),
        )

    webhooks = WebhookService(api_dir / "webhooks.db", now_fn=lambda: NOW)
    webhooks.initialize()
    webhooks.create_webhook(
        "owner",
        "http://198.51.100.10:9999/hook",
        ["checkin.completed"],
        force=True,
    )
    return store, api_dir


class OwnerEnvironmentTests(unittest.TestCase):
    def test_01_owner_default_and_override(self) -> None:
        root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env.pop("GHOST_LEAGUE_OWNER_ID", None)
        default = subprocess.run(
            [
                sys.executable,
                "-c",
                "import ghost_league.accounts as a; print(a.OWNER_USER_ID); print(a.CURRENT_USER_ID)",
            ],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertEqual(default.stdout.strip().splitlines(), ["owner", "owner"])

        env["GHOST_LEAGUE_OWNER_ID"] = "  sample-user  "
        overridden = subprocess.run(
            [
                sys.executable,
                "-c",
                "import ghost_league.accounts as a; print(a.OWNER_USER_ID); print(a.CURRENT_USER_ID)",
            ],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(overridden.returncode, 0, overridden.stderr)
        self.assertEqual(overridden.stdout.strip().splitlines(), ["sample-user", "sample-user"])

    def test_02_ensure_current_user_uses_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AccountsStore(Path(temp_dir) / "accounts.db", now_fn=lambda: NOW)
            with patch.object(accounts_module, "OWNER_USER_ID", "sample-user"):
                account = store.ensure_current_user(token=TOKEN)
            self.assertIsNotNone(account)
            self.assertIsNotNone(store.get("sample-user"))
            self.assertIsNone(store.get("owner"))


class OwnerRenameTests(unittest.TestCase):
    def test_03_rename_migrates_all_local_stores(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, api_dir = build_rename_fixture(Path(temp_dir))
            token_hash_before = store.authenticate(TOKEN)["user_id"]
            self.assertEqual(token_hash_before, "owner")
            result = store.rename("owner", "sample-user")
            self.assertFalse(result["dry_run"])
            self.assertEqual(result["membership"], 1)
            self.assertEqual(result["events"], 2)
            self.assertEqual(result["webhooks"], 1)
            self.assertEqual(result["avatar"], 1)

            self.assertIsNone(store.get("owner"))
            target = store.get("sample-user")
            self.assertIsNotNone(target)
            self.assertEqual(target["display_name"], "Owner")
            self.assertEqual(target["activity_label"], "画画")
            self.assertEqual(target["avatar_url"], "avatars/sample-user.webp")
            self.assertEqual(store.authenticate(TOKEN)["user_id"], "sample-user")
            self.assertEqual(target["created_at"], NOW.isoformat(timespec="seconds"))

            membership = json.loads((api_dir / "membership.json").read_text())
            self.assertNotIn("owner", membership)
            self.assertEqual(membership["sample-user"]["user_id"], "sample-user")
            self.assertEqual(
                membership["sample-user"]["ghost_ids"], ["ghost-1", "ghost-2"]
            )
            with sqlite3.connect(api_dir / "events.db") as connection:
                counts = connection.execute(
                    "SELECT user_id, COUNT(*) FROM drawing_events GROUP BY user_id"
                ).fetchall()
            self.assertEqual(counts, [("sample-user", 2)])
            with sqlite3.connect(api_dir / "webhooks.db") as connection:
                counts = connection.execute(
                    "SELECT user_id, COUNT(*) FROM webhooks GROUP BY user_id"
                ).fetchall()
            self.assertEqual(counts, [("sample-user", 1)])
            self.assertTrue((api_dir / "avatars" / "sample-user.webp").is_file())
            self.assertFalse((api_dir / "avatars" / "owner.webp").exists())

    def test_04_dry_run_and_cli_do_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, api_dir = build_rename_fixture(Path(temp_dir))
            before = {
                name: hashlib.sha256((api_dir / name).read_bytes()).hexdigest()
                for name in ("accounts.db", "membership.json", "events.db", "webhooks.db")
            }
            avatar_before = (api_dir / "avatars" / "owner.webp").read_bytes()
            result = store.rename("owner", "sample-user", dry_run=True)
            self.assertTrue(result["dry_run"])
            self.assertEqual(result["events"], 2)
            for name, digest in before.items():
                self.assertEqual(
                    hashlib.sha256((api_dir / name).read_bytes()).hexdigest(), digest
                )
            self.assertTrue((api_dir / "avatars" / "owner.webp").is_file())
            self.assertFalse((api_dir / "avatars" / "sample-user.webp").exists())
            self.assertIsNotNone(store.get("owner"))
            self.assertIsNone(store.get("sample-user"))
            self.assertEqual(
                (api_dir / "avatars" / "owner.webp").read_bytes(), avatar_before
            )

            root = Path(__file__).resolve().parents[1]
            env = os.environ.copy()
            env["GHOST_LEAGUE_ACCOUNTS_DB"] = str(api_dir / "accounts.db")
            dry = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ghost_league.accounts",
                    "--db",
                    str(api_dir / "accounts.db"),
                    "rename",
                    "--from",
                    "owner",
                    "--to",
                    "sample-user",
                    "--dry-run",
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertIn("dry-run:", dry.stdout)
            self.assertIn("events=2", dry.stdout)
            self.assertIsNone(store.get("sample-user"))

            real = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ghost_league.accounts",
                    "--db",
                    str(api_dir / "accounts.db"),
                    "rename",
                    "--from",
                    "owner",
                    "--to",
                    "sample-user",
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(real.returncode, 0, real.stderr)
            self.assertIn("renamed:", real.stdout)
            self.assertNotIn(TOKEN, real.stdout + real.stderr)
            self.assertIsNotNone(store.get("sample-user"))

    def test_05_conflicts_and_missing_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, _ = build_rename_fixture(Path(temp_dir))
            store.create("sample-user", "Existing", token="target-token")
            with self.assertRaises(ValueError):
                store.rename("owner", "sample-user")
            self.assertIsNotNone(store.get("owner"))
            with self.assertRaises(ValueError):
                store.rename("missing-user", "another-user")
            with self.assertRaises(ValueError):
                store.rename("owner", "bad id")

    def test_06_failure_rolls_back_every_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, api_dir = build_rename_fixture(Path(temp_dir))
            before = {
                name: (api_dir / name).read_bytes()
                for name in ("accounts.db", "membership.json", "events.db", "webhooks.db")
            }
            avatar_before = (api_dir / "avatars" / "owner.webp").read_bytes()
            real_replace = os.replace

            def fail_membership_replace(source: str | Path, destination: str | Path):
                if str(destination).endswith("membership.json"):
                    raise OSError("injected failure")
                return real_replace(source, destination)

            with patch("ghost_league.accounts.os.replace", side_effect=fail_membership_replace):
                with self.assertRaises(ValueError):
                    store.rename("owner", "sample-user")

            self.assertIsNotNone(store.get("owner"))
            self.assertIsNone(store.get("sample-user"))
            for name, content in before.items():
                self.assertEqual((api_dir / name).read_bytes(), content, name)
            self.assertEqual(
                (api_dir / "avatars" / "owner.webp").read_bytes(), avatar_before
            )
            self.assertFalse((api_dir / "avatars" / "sample-user.webp").exists())
            self.assertFalse(list(api_dir.glob(".rename-*")))


class APIOwnerTests(unittest.TestCase):
    def test_07_api_seeds_configured_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            state_path, cache_path, accounts_db, webhooks_db, _ = make_api_fixture(base)
            accounts_db.unlink()
            with patch.object(accounts_module, "OWNER_USER_ID", "sample-user"):
                with patch("ghost_league.api.OWNER_USER_ID", "sample-user"):
                    app = create_app(
                        game_db_path=base / "league.db",
                        state_path=state_path,
                        cache_path=cache_path,
                        avatars_path=base / "avatars.json",
                        api_dir=base / "api",
                        accounts_db=accounts_db,
                        webhooks_db=webhooks_db,
                        start_webhook_worker=False,
                        token=TOKEN,
                        now_fn=lambda: NOW,
                    )
                    with TestClient(app) as client:
                        response = client.get("/v1/me/profile", headers=AUTH)
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json()["user_id"], "sample-user")
            store = AccountsStore(accounts_db)
            self.assertIsNotNone(store.get("sample-user"))
            self.assertIsNone(store.get("owner"))


if __name__ == "__main__":
    unittest.main()
