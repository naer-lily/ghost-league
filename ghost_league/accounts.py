"""Multi-account registry and CLI for the personal Ghost League API.

Tokens are generated locally, shown once by the CLI, and stored only as SHA-256
hashes.  The API resolves a Bearer token to one account and never exposes the
account list over HTTP.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import sys
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from .schedule import TZ
from .themes import (
    DEFAULT_ICON_THEME,
    ICON_THEMES,
    icon_theme_or_default,
    normalize_icon_theme,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_DIR = PROJECT_ROOT / "data" / "api"
DEFAULT_ACCOUNTS_DB = DEFAULT_API_DIR / "accounts.db"
DEFAULT_TOKEN_FILE = Path(
    os.environ.get("GHOST_LEAGUE_TOKEN_FILE", str(DEFAULT_API_DIR / "token"))
)
DEFAULT_SECRET_PATH = DEFAULT_TOKEN_FILE
OWNER_USER_ID = (
    os.environ.get("GHOST_LEAGUE_OWNER_ID", "owner").strip()
    or "owner"
)
# Deprecated alias kept for existing imports/tests.
CURRENT_USER_ID = OWNER_USER_ID
USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DEFAULT_ACTIVITY_LABEL = "练习"
LEGACY_ACTIVITY_LABEL = "画画"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def normalize_activity_label(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("activity_label must be a string")
    cleaned = value.strip()
    if not 1 <= len(cleaned) <= 16:
        raise ValueError("activity_label must be 1-16 characters")
    if any(unicodedata.category(char).startswith("C") for char in cleaned):
        raise ValueError("activity_label cannot contain control characters")
    return cleaned


def validate_user_id(user_id: str) -> str:
    if not isinstance(user_id, str) or not USER_ID_PATTERN.fullmatch(user_id):
        raise ValueError(
            "user_id must be 1-64 characters: letters, digits, dot, underscore or dash"
        )
    return user_id


class AccountsStore:
    """Small SQLite account store; never stores plaintext tokens."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_ACCOUNTS_DB,
        *,
        secret_path: str | Path = DEFAULT_SECRET_PATH,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.secret_path = Path(secret_path)
        self._now_fn = now_fn or (lambda: datetime.now(TZ))

    def now(self) -> datetime:
        return self._now_fn()

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    avatar_url TEXT,
                    activity_label TEXT,
                    profile_revision INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT,
                    icon_theme TEXT NOT NULL DEFAULT 'classic'
                )
                """
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(users)").fetchall()
            }
            additions = {
                "avatar_url": "TEXT",
                "activity_label": "TEXT",
                "profile_revision": "INTEGER NOT NULL DEFAULT 0",
                "updated_at": "TEXT",
                "icon_theme": "TEXT NOT NULL DEFAULT 'classic'",
            }
            for column, definition in additions.items():
                if column not in columns:
                    connection.execute(
                        f"ALTER TABLE users ADD COLUMN {column} {definition}"
                    )
            connection.execute(
                "UPDATE users SET updated_at = created_at WHERE updated_at IS NULL"
            )
            connection.execute(
                "UPDATE users SET activity_label = ? "
                "WHERE activity_label IS NULL OR trim(activity_label) = ''",
                (LEGACY_ACTIVITY_LABEL,),
            )

    def count(self) -> int:
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            row = connection.execute("SELECT COUNT(*) FROM users").fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def _account_from_row(row: sqlite3.Row) -> dict[str, Any]:
        account = dict(row)
        account["icon_theme"] = icon_theme_or_default(account.get("icon_theme"))
        return account

    def create(
        self,
        user_id: str,
        display_name: str,
        *,
        token: str | None = None,
        activity_label: str = DEFAULT_ACTIVITY_LABEL,
        icon_theme: str | None = DEFAULT_ICON_THEME,
    ) -> tuple[dict[str, Any], str]:
        validate_user_id(user_id)
        if not isinstance(display_name, str) or not display_name:
            raise ValueError("display_name must be a non-empty string")
        plaintext = token or generate_token()
        if not isinstance(plaintext, str) or not plaintext:
            raise ValueError("token must be a non-empty string")
        activity = normalize_activity_label(activity_label)
        theme = (
            DEFAULT_ICON_THEME
            if icon_theme is None
            else normalize_icon_theme(icon_theme)
        )
        created_at = self.now().isoformat(timespec="seconds")
        try:
            with sqlite3.connect(self.db_path, timeout=10) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute(
                    "INSERT INTO users "
                    "(user_id, display_name, token_hash, created_at, is_active, "
                    "avatar_url, activity_label, profile_revision, updated_at, icon_theme) "
                    "VALUES (?, ?, ?, ?, 1, NULL, ?, 0, ?, ?)",
                    (
                        user_id,
                        display_name,
                        hash_token(plaintext),
                        created_at,
                        activity,
                        created_at,
                        theme,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"account {user_id!r} already exists") from exc
        return {
            "user_id": user_id,
            "display_name": display_name,
            "created_at": created_at,
            "is_active": True,
            "avatar_url": None,
            "activity_label": activity,
            "profile_revision": 0,
            "updated_at": created_at,
            "icon_theme": theme,
        }, plaintext

    def get(self, user_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT user_id, display_name, created_at, is_active, avatar_url, "
                "activity_label, profile_revision, updated_at, icon_theme "
                "FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return self._account_from_row(row) if row else None

    def authenticate(self, token: str) -> dict[str, Any] | None:
        if not isinstance(token, str) or not token:
            return None
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT user_id, display_name, created_at, is_active, avatar_url, "
                "activity_label, profile_revision, updated_at, icon_theme FROM users "
                "WHERE token_hash = ? AND is_active = 1",
                (hash_token(token),),
            ).fetchone()
        return self._account_from_row(row) if row else None

    def list_accounts(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT user_id, display_name, created_at "
                "FROM users ORDER BY created_at, user_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def update_profile(
        self,
        user_id: str,
        display_name: str | None = None,
        activity_label: str | None = None,
        icon_theme: str | None = None,
    ) -> dict[str, Any]:
        assignments: list[str] = []
        parameters: list[Any] = []
        if display_name is not None:
            cleaned = display_name.strip() if isinstance(display_name, str) else ""
            if not cleaned or len(cleaned) > 32:
                raise ValueError("display_name must be 1-32 non-whitespace characters")
            assignments.append("display_name = ?")
            parameters.append(cleaned)
        if activity_label is not None:
            assignments.append("activity_label = ?")
            parameters.append(normalize_activity_label(activity_label))
        if icon_theme is not None:
            assignments.append("icon_theme = ?")
            parameters.append(normalize_icon_theme(icon_theme))
        if not assignments:
            raise ValueError("at least one profile field is required")
        updated_at = self.now().isoformat(timespec="seconds")
        assignments.extend(
            ["profile_revision = profile_revision + 1", "updated_at = ?"]
        )
        parameters.extend([updated_at, user_id])
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            cursor = connection.execute(
                f"UPDATE users SET {', '.join(assignments)} WHERE user_id = ?",
                parameters,
            )
            if cursor.rowcount != 1:
                raise ValueError(f"account {user_id!r} does not exist")
        account = self.get(user_id)
        assert account is not None
        return account

    def set_avatar_url(self, user_id: str, avatar_url: str) -> dict[str, Any]:
        if not isinstance(avatar_url, str) or not avatar_url:
            raise ValueError("avatar_url must be a non-empty string")
        updated_at = self.now().isoformat(timespec="seconds")
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            cursor = connection.execute(
                "UPDATE users SET avatar_url = ?, "
                "profile_revision = profile_revision + 1, updated_at = ? "
                "WHERE user_id = ?",
                (avatar_url, updated_at, user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"account {user_id!r} does not exist")
        account = self.get(user_id)
        assert account is not None
        return account

    def rotate(self, user_id: str) -> tuple[dict[str, Any], str]:
        account = self.get(user_id)
        if account is None:
            raise ValueError(f"account {user_id!r} does not exist")
        plaintext = generate_token()
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            cursor = connection.execute(
                "UPDATE users SET token_hash = ? WHERE user_id = ?",
                (hash_token(plaintext), user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"account {user_id!r} does not exist")
        return account, plaintext

    # -- owner rename --------------------------------------------------
    @staticmethod
    def _checkpoint(path: Path) -> None:
        try:
            with sqlite3.connect(path, timeout=10) as connection:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass

    @staticmethod
    def _db_user_counts(
        path: Path, table: str, from_id: str, to_id: str
    ) -> tuple[int, int]:
        if not path.exists():
            return 0, 0
        try:
            with sqlite3.connect(path, timeout=10) as connection:
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
                if exists is None:
                    return 0, 0
                source = connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (from_id,)
                ).fetchone()[0]
                target = connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (to_id,)
                ).fetchone()[0]
            return int(source), int(target)
        except sqlite3.Error as exc:
            raise ValueError(f"could not inspect {path.name}: {exc}") from exc

    @staticmethod
    def _restore_backup(path: Path, backup: Path) -> None:
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(path) + suffix)
            if sidecar.exists():
                sidecar.unlink()
        if path.exists():
            path.unlink()
        shutil.copy2(backup, path)

    def rename(
        self,
        from_id: str,
        to_id: str,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Rename the local owner across accounts, league, events and webhooks.

        Cross-database writes cannot share one SQLite transaction, so each DB
        uses its own transaction and all touched files are backed up first.
        Any failure restores every file and removes the newly created target
        avatar.
        """

        validate_user_id(from_id)
        validate_user_id(to_id)
        if from_id == to_id:
            raise ValueError("from and to user ids must differ")
        if not self.db_path.exists():
            raise ValueError("accounts database does not exist")
        try:
            with sqlite3.connect(self.db_path, timeout=10) as connection:
                connection.row_factory = sqlite3.Row
                table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
                ).fetchone()
                if table is None:
                    raise ValueError("accounts database has no users table")
                columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(users)").fetchall()
                }
                avatar_select = "avatar_url" if "avatar_url" in columns else "NULL AS avatar_url"
                source = connection.execute(
                    f"SELECT user_id, {avatar_select} FROM users WHERE user_id = ?",
                    (from_id,),
                ).fetchone()
                target = connection.execute(
                    "SELECT user_id FROM users WHERE user_id = ?",
                    (to_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise ValueError(f"could not inspect accounts database: {exc}") from exc
        if source is None:
            raise ValueError(f"source account {from_id!r} does not exist")
        if target is not None:
            raise ValueError(f"target account {to_id!r} already exists")

        api_dir = self.db_path.parent
        membership_path = api_dir / "membership.json"
        events_path = api_dir / "events.db"
        webhooks_path = api_dir / "webhooks.db"
        avatar_from = api_dir / "avatars" / f"{from_id}.webp"
        avatar_to = api_dir / "avatars" / f"{to_id}.webp"

        membership_payload: dict[str, Any] | None = None
        membership_count = 0
        if membership_path.exists():
            try:
                loaded = json.loads(membership_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError(f"could not read membership.json: {exc}") from exc
            if not isinstance(loaded, dict):
                raise ValueError("membership.json must be an object")
            if to_id in loaded:
                raise ValueError(f"target membership {to_id!r} already exists")
            if from_id in loaded:
                if not isinstance(loaded[from_id], dict):
                    raise ValueError("source membership entry is invalid")
                membership_payload = loaded
                membership_count = 1

        events_count, target_events = self._db_user_counts(
            events_path, "drawing_events", from_id, to_id
        )
        if target_events:
            raise ValueError(f"target account has {target_events} existing events")
        webhooks_count, target_webhooks = self._db_user_counts(
            webhooks_path, "webhooks", from_id, to_id
        )
        if target_webhooks:
            raise ValueError(f"target account has {target_webhooks} existing webhooks")

        avatar_count = 0
        if avatar_from.exists():
            if avatar_to.exists():
                raise ValueError(f"target avatar file already exists: {avatar_to.name}")
            avatar_count = 1

        summary = {
            "from": from_id,
            "to": to_id,
            "accounts": 1,
            "membership": membership_count,
            "events": events_count,
            "webhooks": webhooks_count,
            "avatar": avatar_count,
        }
        if dry_run:
            return {"dry_run": True, **summary}

        backup_dir = Path(tempfile.mkdtemp(prefix=".rename-", dir=api_dir))
        backups: list[tuple[Path, Path]] = []
        try:
            for path in (
                self.db_path,
                membership_path,
                events_path,
                webhooks_path,
                avatar_from,
            ):
                if not path.exists():
                    continue
                if path.suffix == ".db":
                    self._checkpoint(path)
                backup = backup_dir / path.name
                shutil.copy2(path, backup)
                backups.append((path, backup))

            new_avatar_url = (
                f"avatars/{to_id}.webp"
                if source["avatar_url"] == f"avatars/{from_id}.webp"
                else None
            )
            try:
                with sqlite3.connect(self.db_path, timeout=10) as connection:
                    if "avatar_url" in columns:
                        cursor = connection.execute(
                            "UPDATE users SET user_id = ?, "
                            "avatar_url = CASE WHEN avatar_url = ? THEN ? ELSE avatar_url END "
                            "WHERE user_id = ?",
                            (
                                to_id,
                                f"avatars/{from_id}.webp",
                                new_avatar_url,
                                from_id,
                            ),
                        )
                    else:
                        cursor = connection.execute(
                            "UPDATE users SET user_id = ? WHERE user_id = ?",
                            (to_id, from_id),
                        )
                    if cursor.rowcount != 1:
                        raise ValueError("accounts update affected no rows")
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"accounts rename conflict: {exc}") from exc

            if membership_payload is not None:
                record = membership_payload.pop(from_id)
                record["user_id"] = to_id
                membership_payload[to_id] = record
                temporary = membership_path.with_suffix(".rename.tmp")
                temporary.write_text(
                    json.dumps(
                        membership_payload,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                os.replace(temporary, membership_path)

            if events_count:
                with sqlite3.connect(events_path, timeout=10) as connection:
                    cursor = connection.execute(
                        "UPDATE drawing_events SET user_id = ? WHERE user_id = ?",
                        (to_id, from_id),
                    )
                    if cursor.rowcount != events_count:
                        raise ValueError("events update row count changed")
            if webhooks_count:
                with sqlite3.connect(webhooks_path, timeout=10) as connection:
                    cursor = connection.execute(
                        "UPDATE webhooks SET user_id = ? WHERE user_id = ?",
                        (to_id, from_id),
                    )
                    if cursor.rowcount != webhooks_count:
                        raise ValueError("webhooks update row count changed")
            if avatar_count:
                os.replace(avatar_from, avatar_to)
        except Exception as exc:
            for path, backup in backups:
                try:
                    self._restore_backup(path, backup)
                except OSError:
                    pass
            temporary = membership_path.with_suffix(".rename.tmp")
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass
            if avatar_count and avatar_to.exists():
                try:
                    avatar_to.unlink()
                except OSError:
                    pass
            raise ValueError(f"rename failed and rolled back: {exc}") from exc
        finally:
            shutil.rmtree(backup_dir, ignore_errors=True)

        return {"dry_run": False, **summary}

    def ensure_current_user(self, *, token: str | None = None) -> dict[str, Any] | None:
        """Seed the configured owner once, using the local secret when needed.

        This is migration only: it never prints or returns the plaintext token
        to callers that did not supply one themselves.
        """

        self.initialize()
        existing = self.get(OWNER_USER_ID)
        if existing is not None:
            return existing
        if token is None:
            try:
                token = self.secret_path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise RuntimeError(
                    "accounts database is empty and the migration secret is unavailable"
                ) from exc
        if not token:
            raise RuntimeError("account migration token is empty")
        account, _ = self.create(
            OWNER_USER_ID,
            "You",
            token=token,
            activity_label=LEGACY_ACTIVITY_LABEL,
        )
        return account


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ghost_league.accounts",
        description="Manage local Ghost League API accounts.",
    )
    parser.add_argument(
        "--db",
        default=os.environ.get("GHOST_LEAGUE_ACCOUNTS_DB", str(DEFAULT_ACCOUNTS_DB)),
        help="accounts SQLite path (default: GHOST_LEAGUE_ACCOUNTS_DB or data/api/accounts.db)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("add", help="create an account and print its token once")
    add.add_argument("--user-id", required=True)
    add.add_argument("--name", required=True)
    add.add_argument(
        "--activity",
        default=DEFAULT_ACTIVITY_LABEL,
        help="activity label (1-16 characters, default: 练习)",
    )

    subparsers.add_parser("list", help="list accounts without tokens")

    rotate = subparsers.add_parser("rotate", help="rotate an account token")
    rotate.add_argument("--user-id", required=True)

    rename = subparsers.add_parser("rename", help="rename a local owner account")
    rename.add_argument("--from", dest="from_id", required=True)
    rename.add_argument("--to", dest="to_id", required=True)
    rename.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    store = AccountsStore(args.db)
    try:
        if args.command == "rename":
            result = store.rename(
                args.from_id,
                args.to_id,
                dry_run=args.dry_run,
            )
            prefix = "dry-run:" if result["dry_run"] else "renamed:"
            print(f"{prefix} {result['from']} -> {result['to']}")
            print(
                f"accounts={result['accounts']} membership={result['membership']} "
                f"events={result['events']} webhooks={result['webhooks']} "
                f"avatar={result['avatar']}"
            )
            return 0

        store.initialize()
        if args.command == "add":
            _, token = store.create(
                args.user_id,
                args.name,
                activity_label=args.activity,
            )
            print(token)
        elif args.command == "list":
            print("user_id\tname\tcreated_at")
            for account in store.list_accounts():
                print(
                    f"{account['user_id']}\t{account['display_name']}\t"
                    f"{account['created_at']}"
                )
        elif args.command == "rotate":
            _, token = store.rotate(args.user_id)
            print(token)
        else:  # pragma: no cover
            raise ValueError(f"unknown command {args.command}")
    except (OSError, ValueError) as exc:
        print(f"accounts: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "CURRENT_USER_ID",
    "DEFAULT_ACCOUNTS_DB",
    "OWNER_USER_ID",
    "DEFAULT_ACTIVITY_LABEL",
    "DEFAULT_ICON_THEME",
    "ICON_THEMES",
    "DEFAULT_API_DIR",
    "DEFAULT_SECRET_PATH",
    "DEFAULT_TOKEN_FILE",
    "LEGACY_ACTIVITY_LABEL",
    "AccountsStore",
    "generate_token",
    "hash_token",
    "icon_theme_or_default",
    "normalize_activity_label",
    "normalize_icon_theme",
    "validate_user_id",
    "main",
]
