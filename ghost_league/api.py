"""FastAPI surface for the Phase 1 game core.

The API is a thin, authenticated projection of :class:`GameStore`.  Accounts
remain the identity/source for humans, while every league number (week, XP,
rank, check-in, streak, embers) comes from ``league.db``.  Legacy league state,
memberships and their response shapes are deliberately not loaded here.
"""

from __future__ import annotations

import hmac
import io
import logging
import os
import re
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from .accounts import (
    DEFAULT_ACCOUNTS_DB,
    DEFAULT_SECRET_PATH,
    OWNER_USER_ID,
    AccountsStore,
)
from .badge import render_badge, render_embed
from .game import calendar as cal
from .game.feed import FEED_EMOJIS
from .game.roster import ensure_all_groups
from .game.rules import (
    CHECKIN_XP,
    EMBER_BALANCE_CAP,
    ChannelRosterMissing,
    DuplicateIdempotencyKey,
    GameError,
    RepairRejected,
    WeekLocked,
    earned_embers_for_week,
    xp_for_seconds,
)
from .game.store import DEFAULT_DB_PATH, SOURCE_CHANNEL, SOURCE_HUMAN, GameStore
from .schedule import TZ
from .social import FollowStore
from .themes import icon_theme_or_default
from .webhooks import STREAK_MILESTONES, WebhookService

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_PATH = PROJECT_ROOT / "data" / "league" / "state.json"
DEFAULT_CACHE_PATH = PROJECT_ROOT / "data" / "cache" / "cn-978.json"
DEFAULT_AVATARS_PATH = PROJECT_ROOT / "data" / "cache" / "avatars.json"
DEFAULT_API_DIR = PROJECT_ROOT / "data" / "api"
DEFAULT_WAKATIME_CACHE_PATH = PROJECT_ROOT / "data" / "cache" / "wakatime-profiles.json"
MAX_AVATAR_BYTES = 2 * 1024 * 1024
AVATAR_SIZE = 256
ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG", "WEBP"}
SAFE_USER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class FutureTimestampError(ValueError):
    """Raised when an increment is timestamped in the future."""


class AvatarValidationError(ValueError):
    """Raised when an uploaded file is not a supported avatar image."""


class DrawingIncrementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=200)
    seconds: int = Field(strict=True, gt=0)
    occurred_at: datetime | None = None


class ChannelProfileSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    avatar_url: str | None = Field(default=None, min_length=1, max_length=500)


class ChannelRosterPlayer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_ref: str = Field(min_length=1, max_length=200)
    kind: Literal["human", "ai"]
    profile: ChannelProfileSnapshot | None = None


class ChannelRosterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    players: list[ChannelRosterPlayer] = Field(min_length=1, max_length=1000)


class ChannelIncrementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_ref: str = Field(min_length=1, max_length=200)
    event_id: str = Field(min_length=1, max_length=200)
    seconds: int = Field(strict=True, gt=0)
    occurred_at: datetime


class RepairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    idempotency_key: str = Field(min_length=1, max_length=200)


class LoadoutPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title_id: str | None = None
    frame_id: str | None = None
    backdrop_id: str | None = None
    badge_accent_id: str | None = None


class FeedReactionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    emoji: str = Field(min_length=1, max_length=10)


class TokenRotateResponse(BaseModel):
    user_id: str
    token: str


class WebhookCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    events: list[str]
    transport: str = "generic"


class WebhookPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str | None = None
    events: list[str] | None = None
    transport: str | None = None
    active: bool | None = None


class WebhookResponse(BaseModel):
    id: int
    user_id: str
    url: str
    events: list[str]
    transport: str
    active: bool
    created_at: str
    updated_at: str
    last_status: str | None
    last_attempt_at: str | None
    last_success_at: str | None
    failure_count: int
    latest_delivery: dict[str, Any] | None


class WebhookCreateResponse(WebhookResponse):
    secret: str


class WebhookTestResponse(BaseModel):
    delivery_id: int
    status: str
    attempts: int
    last_error: str | None


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    activity_label: str | None = None
    icon_theme: str | None = None
    activity: str | None = None


class AvatarResponse(BaseModel):
    avatar_url: str


class HealthResponse(BaseModel):
    status: str
    current_week: str
    timezone: str


def _local(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=TZ)
    return value.astimezone(TZ)


def _iso(value: datetime) -> str:
    return _local(value).isoformat(timespec="seconds")


def _week_start(value: date | datetime | str) -> date:
    return cal.week_start(value)


def _account_joined_week(account: dict[str, Any], fallback: date) -> date:
    raw = account.get("created_at")
    if isinstance(raw, str):
        try:
            return _week_start(datetime.fromisoformat(raw))
        except ValueError:
            pass
    return fallback


def _streak_change_specs(
    *,
    user_id: str,
    day: date,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    crossed_checkin: bool,
) -> list[tuple[str, str, dict[str, Any]]]:
    if not crossed_checkin or not after:
        return []
    specs: list[tuple[str, str, dict[str, Any]]] = []
    current = int(after.get("current_streak") or 0)
    if current in STREAK_MILESTONES:
        specs.append(
            (
                "streak.milestone",
                f"streak.milestone:{user_id}:{day.isoformat()}:{current}",
                {
                    "date": day.isoformat(),
                    "milestone": current,
                    "current_streak": current,
                },
            )
        )
    previous_raw = before.get("last_checkin_date") if before else None
    if isinstance(previous_raw, str) and previous_raw:
        try:
            previous = date.fromisoformat(previous_raw)
        except ValueError:
            previous = None
        if previous is not None and previous < day - timedelta(days=1):
            specs.append(
                (
                    "streak.broken",
                    f"streak.broken:{user_id}:{day.isoformat()}:{previous.isoformat()}",
                    {
                        "date": day.isoformat(),
                        "previous_last_checkin_date": previous.isoformat(),
                        "gap_days": (day - previous).days,
                    },
                )
            )
    return specs


def _rank_change_specs(
    *,
    user_id: str,
    occurrence_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> list[tuple[str, str, dict[str, Any]]]:
    if not before or not after:
        return []
    before_rank = before.get("rank")
    after_rank = after.get("rank")
    if before_rank is None or after_rank is None:
        return []
    before_rank = int(before_rank)
    after_rank = int(after_rank)
    group_size = int(after.get("group_size") or 0)
    week_start = str(after.get("week_start") or "")
    specs: list[tuple[str, str, dict[str, Any]]] = []
    if before_rank > 3 and after_rank <= 3:
        specs.append(
            (
                "rank.top3",
                f"rank.top3:{user_id}:{week_start}:{after_rank}:{occurrence_id}",
                {
                    "week_start": week_start,
                    "previous_rank": before_rank,
                    "rank": after_rank,
                    "group_size": group_size,
                },
            )
        )
    bottom_threshold = group_size - 3
    if before_rank <= bottom_threshold and after_rank > bottom_threshold:
        specs.append(
            (
                "rank.bottom3",
                f"rank.bottom3:{user_id}:{week_start}:{after_rank}:{occurrence_id}",
                {
                    "week_start": week_start,
                    "previous_rank": before_rank,
                    "rank": after_rank,
                    "group_size": group_size,
                },
            )
        )
    return specs


class GameService:
    """Accounts + GameStore application service."""

    def __init__(
        self,
        *,
        game_db_path: str | Path = DEFAULT_DB_PATH,
        cache_path: str | Path = DEFAULT_CACHE_PATH,
        avatars_path: str | Path = DEFAULT_AVATARS_PATH,
        api_dir: str | Path = DEFAULT_API_DIR,
        accounts_db: str | Path | None = None,
        social_db: str | Path | None = None,
        token: str | None = None,
        bootstrap_token: str | None = None,
        channel_token: str | None = None,
        secret_path: str | Path = DEFAULT_SECRET_PATH,
        now_fn: Callable[[], datetime] | None = None,
        game_now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.game_db_path = Path(game_db_path)
        self.cache_path = Path(cache_path)
        self.avatars_path = Path(avatars_path)
        self.api_dir = Path(api_dir)
        self._now_fn = now_fn or (lambda: datetime.now(TZ))
        self._game_now_fn = game_now_fn
        self.social_db_path = (
            Path(social_db) if social_db is not None else self.api_dir / "social.db"
        )
        self.avatar_dir = self.api_dir / "avatars"
        self.accounts = AccountsStore(
            accounts_db or self.api_dir / "accounts.db",
            secret_path=secret_path,
            now_fn=self._now_fn,
        )
        self.follows = FollowStore(self.social_db_path, now_fn=self.now)
        self._bootstrap_token = bootstrap_token if bootstrap_token is not None else token
        self.channel_token = (
            channel_token
            if channel_token is not None
            else os.environ.get("GHOST_LEAGUE_CHANNEL_TOKEN")
        ) or None
        self.store: GameStore | None = None
        self._week_iso: str | None = None
        self._lock = threading.RLock()
        self._initialized = False
        self._infrastructure_ready = False

    # -- setup ---------------------------------------------------------
    def now(self) -> datetime:
        value = self._game_now_fn() if self._game_now_fn is not None else self._now_fn()
        if not isinstance(value, datetime):
            raise TypeError("game_now_fn must return a datetime")
        return _local(value)

    def _initialize_infrastructure(self) -> None:
        if self._infrastructure_ready:
            return
        self.api_dir.mkdir(parents=True, exist_ok=True)
        self.avatar_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.avatar_dir.chmod(0o700)
        except OSError:
            pass
        self.accounts.initialize()
        # First-start migration may seed the configured owner from the local
        # secret.  Once any account exists, a missing owner is an operator
        # error: never fabricate a fallback account such as current-user.
        if self.accounts.count() == 0:
            self.accounts.ensure_current_user(token=self._bootstrap_token)
        self.follows.initialize()
        if self.store is None:
            self.store = GameStore(
                self.game_db_path,
                epoch_reason="api-start",
            )
        self._infrastructure_ready = True

    def _initialize_channels(self) -> None:
        """Prepare only the generic store; no accounts, roster or AI work."""

        with self._lock:
            if self.store is None:
                self.store = GameStore(
                    self.game_db_path,
                    epoch_reason="api-start",
                    epoch_started_at=self.now(),
                )
            self.store.ensure_week(_week_start(self.now()))

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._initialize_infrastructure()
            self._bootstrap_week(self.now())
            self._initialized = True

    def _bootstrap_week(self, now: datetime) -> None:
        """Create the week and ensure the configured owner only.

        Rosters, AI and groups are owned by Channel ingest.  Starting the API
        must never read the leaderboard cache, project AI activity, place
        players before a Channel announces who is competing, or turn every
        local account into a league human.
        """

        assert self.store is not None
        owner = self.accounts.get(OWNER_USER_ID)
        if owner is None:
            raise RuntimeError(
                f"owner account {OWNER_USER_ID!r} does not exist; "
                "create it before starting the API"
            )
        week = _week_start(now)
        self.store.ensure_week(week)
        self._ensure_human(owner, week, now)
        self._week_iso = week.isoformat()

    def _ensure_human(
        self, account: dict[str, Any], week: date, now: datetime
    ) -> dict[str, Any]:
        assert self.store is not None
        user_id = str(account["user_id"])
        return self.store.ensure_human_player(
            user_id,
            display_name=str(account["display_name"]),
            joined_week=_account_joined_week(account, week),
            now=now,
        )

    def _has_channel_roster(self, week: date) -> bool:
        """True once any Channel has announced this week's participants."""

        assert self.store is not None
        return bool(self.store.list_channel_week_players(week))

    def _prepare_read(self, account: dict[str, Any]) -> tuple[datetime, date]:
        self.initialize()
        assert self.store is not None
        now = self.now()
        week = _week_start(now)
        if self._week_iso != week.isoformat():
            with self._lock:
                if self._week_iso != week.isoformat():
                    self._bootstrap_week(now)
        self._ensure_human(account, week, now)
        user_id = str(account["user_id"])
        if (
            self.store.group_for_player(user_id, week) is None
            and self._has_channel_roster(week)
        ):
            ensure_all_groups(self.store, week, now=now)
        return now, week

    def _prepare_player(self, account: dict[str, Any]) -> tuple[datetime, date]:
        self.initialize()
        assert self.store is not None
        now = self.now()
        week = _week_start(now)
        self._ensure_human(account, week, now)
        return now, week

    def _group_payload(
        self, group: dict[str, Any] | None, *, size: int
    ) -> dict[str, Any] | None:
        if group is None:
            return None
        return {
            "id": int(group["id"]),
            "no": int(group["group_no"]),
            "tier": str(group["tier"]),
            "week_start": str(group["week_start"]),
            "size": size,
        }

    def _ember_summary(
        self, player_id: str, week: date, week_seconds: int
    ) -> dict[str, Any]:
        assert self.store is not None
        row = self.store.get_ember_balance(player_id)
        balance = int(row["balance"]) if row else 0
        stored = (
            int(row["week_earned"])
            if row and str(row["week_start"]) == week.isoformat()
            else 0
        )
        earned = max(stored, earned_embers_for_week(week_seconds))
        return {
            "balance": balance,
            "cap": EMBER_BALANCE_CAP,
            "earned_this_week": min(earned, earned_embers_for_week(week_seconds)),
        }

    def _avatar_public_url(self, account: dict[str, Any] | None) -> str | None:
        if account is None or not account.get("avatar_url"):
            return None
        return f"/avatars/{account['user_id']}"

    @staticmethod
    def _profile_avatar_url(profile: dict[str, Any] | None) -> str | None:
        avatar_url = (profile or {}).get("avatar_url")
        if isinstance(avatar_url, str) and avatar_url.strip():
            return avatar_url.strip()
        return None

    def _avatar_for_player(self, player_id: str, *, is_ai: bool) -> str | None:
        """Local account avatars win for humans; AI use the Channel profile."""

        if is_ai:
            assert self.store is not None
            return self._profile_avatar_url(
                self.store.channel_profile_for_player(player_id)
            )
        return self._avatar_public_url(self.accounts.get(player_id))

    def _decorate_feed_item(self, item: dict[str, Any]) -> dict[str, Any]:
        author = item.get("author")
        if isinstance(author, dict):
            player_id = str(author.get("id") or "")
            author["avatar_url"] = self._avatar_for_player(
                player_id, is_ai=bool(author.get("is_ai"))
            )
            # ``kind`` is an internal identity/audit field.  It must never be
            # visible in the public feed payload.
            author.pop("is_ai", None)
        return item

    def _status_payload(
        self, account: dict[str, Any], now: datetime, week: date
    ) -> dict[str, Any]:
        assert self.store is not None
        user_id = str(account["user_id"])
        try:
            self.store.refresh_streak(user_id, today=now.date(), now=now)
        except Exception:
            logging.getLogger(__name__).warning(
                "could not refresh streak for %s", user_id, exc_info=True
            )
        snapshot = self.store.player_status(user_id, week=week, now=now)
        group = snapshot.get("group")
        size = int(snapshot.get("group_size") or 0)
        week_seconds = int(snapshot.get("seconds") or 0)
        loadout = self.store.loadout_view(user_id)
        streak = snapshot.get("streak") or {
            "current": 0,
            "longest": 0,
            "clean_current": 0,
            "last_checked_date": None,
        }
        return {
            "user_id": user_id,
            "display_name": str(account["display_name"]),
            "avatar_url": self._avatar_public_url(account),
            "activity_label": account.get("activity_label") or "练习",
            "icon_theme": icon_theme_or_default(account.get("icon_theme")),
            "tier": snapshot.get("tier") or "Bronze",
            "group": self._group_payload(group, size=size),
            "group_id": int(group["id"]) if group else None,
            "group_size": size,
            "week_start": str(snapshot["week_start"]),
            "seconds": week_seconds,
            "xp": int(snapshot.get("xp") or 0),
            "rank": snapshot.get("rank"),
            "today_seconds": int(snapshot.get("today_seconds") or 0),
            "today_xp": int(snapshot.get("today_xp") or 0),
            "required_xp": CHECKIN_XP,
            "checkin": snapshot.get("checkin"),
            "streak": {
                "current": int(streak.get("current") or 0),
                "longest": int(streak.get("longest") or 0),
                "clean_current": int(streak.get("clean_current") or 0),
                "last_checked_date": streak.get("last_checked_date"),
            },
            "embers": self._ember_summary(user_id, week, week_seconds),
            "equipped_title": loadout["title"],
            "equipped_title_id": loadout["title_id"],
            "frame": loadout["frame"],
            "frame_id": loadout["frame_id"],
            "backdrop": loadout["backdrop"],
            "badge_accent": loadout["badge_accent"],
            "next_settlement_at": _iso(cal.week_end_at(week)),
            "updated_at": _iso(now),
        }

    def status_for(self, account: dict[str, Any]) -> dict[str, Any]:
        now, week = self._prepare_read(account)
        return self._status_payload(account, now, week)

    def status_for_user(self, user_id: str) -> dict[str, Any] | None:
        """Return the badge snapshot for a local account or a Channel player.

        Public badges are addressable by any player id, not only accounts.
        Channel players have no account row, so their display snapshot comes
        from ``channel_players`` while scoring/loadout still come from the
        normal game store.  ``kind`` stays internal and is never projected.
        """

        account = self.accounts.get(user_id)
        if account is not None:
            return self.status_for(account)
        self.initialize()
        assert self.store is not None
        try:
            player = self.store.get_player(user_id)
        except GameError:
            return None
        now = self.now()
        week = _week_start(now)
        if self._week_iso != week.isoformat():
            with self._lock:
                if self._week_iso != week.isoformat():
                    self._bootstrap_week(now)
        if (
            self.store.group_for_player(user_id, week) is None
            and self._has_channel_roster(week)
        ):
            ensure_all_groups(self.store, week, now=now)
        snapshot = self.store.player_status(user_id, week=week, now=now)
        group = snapshot.get("group")
        size = int(snapshot.get("group_size") or 0)
        week_seconds = int(snapshot.get("seconds") or 0)
        loadout = self.store.loadout_view(user_id)
        profile = self.store.channel_profile_for_player(user_id)
        streak = snapshot.get("streak") or {
            "current": 0,
            "longest": 0,
            "clean_current": 0,
            "last_checked_date": None,
        }
        return {
            "user_id": user_id,
            "display_name": str(player["display_name"]),
            "avatar_url": self._profile_avatar_url(profile),
            "activity_label": (profile or {}).get("activity_label") or "练习",
            "icon_theme": icon_theme_or_default((profile or {}).get("icon_theme")),
            "tier": snapshot.get("tier") or "Bronze",
            "group": self._group_payload(group, size=size),
            "group_id": int(group["id"]) if group else None,
            "group_size": size,
            "week_start": str(snapshot["week_start"]),
            "seconds": week_seconds,
            "xp": int(snapshot.get("xp") or 0),
            "rank": snapshot.get("rank"),
            "today_seconds": int(snapshot.get("today_seconds") or 0),
            "today_xp": int(snapshot.get("today_xp") or 0),
            "required_xp": CHECKIN_XP,
            "checkin": snapshot.get("checkin"),
            "streak": {
                "current": int(streak.get("current") or 0),
                "longest": int(streak.get("longest") or 0),
                "clean_current": int(streak.get("clean_current") or 0),
                "last_checked_date": streak.get("last_checked_date"),
            },
            "embers": self._ember_summary(user_id, week, week_seconds),
            "equipped_title": loadout["title"],
            "equipped_title_id": loadout["title_id"],
            "frame": loadout["frame"],
            "frame_id": loadout["frame_id"],
            "backdrop": loadout["backdrop"],
            "badge_accent": loadout["badge_accent"],
            "next_settlement_at": _iso(cal.week_end_at(week)),
            "updated_at": _iso(now),
        }

    def _standings_payload(
        self, account: dict[str, Any], now: datetime, week: date
    ) -> dict[str, Any]:
        assert self.store is not None
        user_id = str(account["user_id"])
        group = self.store.group_for_player(user_id, week)
        if group is None and self._has_channel_roster(week):
            ensure_all_groups(self.store, week, now=now)
            group = self.store.group_for_player(user_id, week)
        if group is None:
            return {
                "week_start": week.isoformat(),
                "group": None,
                "group_id": None,
                "group_size": 0,
                "me": None,
                "standings": [],
            }
        rows = self.store.standings(week, group_id=int(group["id"]), now=now)
        channel_profiles = self.store.channel_profiles_for_players(
            str(row["player_id"]) for row in rows if bool(row.get("is_ai"))
        )
        standings: list[dict[str, Any]] = []
        for row in rows:
            player_id = str(row["player_id"])
            player_account = self.accounts.get(player_id)
            loadout = self.store.loadout_view(player_id)
            is_ai = bool(row.get("is_ai"))
            standings.append(
                {
                    "rank": int(row["rank"]),
                    "user_id": player_id,
                    "display_name": str(row["display_name"]),
                    "avatar_url": (
                        self._profile_avatar_url(channel_profiles.get(player_id))
                        if is_ai
                        else self._avatar_public_url(player_account)
                    ),
                    "is_me": player_id == user_id,
                    "xp": int(row["xp"]),
                    "checkin": row.get("checkin"),
                    "streak": int(row.get("streak") or 0),
                    "title": loadout["title"],
                    "frame": loadout["frame"],
                    "frame_id": loadout["frame_id"],
                    "backdrop": loadout["backdrop"],
                }
            )
        standings.sort(key=lambda item: (item["rank"], item["user_id"]))
        group_payload = self._group_payload(group, size=len(standings))
        me = next((item for item in standings if item["is_me"]), None)
        return {
            "week_start": week.isoformat(),
            "group": group_payload,
            "group_id": int(group["id"]),
            "group_size": len(standings),
            "me": (
                {"rank": int(me["rank"]), "xp": int(me["xp"])}
                if me is not None
                else None
            ),
            "standings": standings,
        }

    def league_for(self, account: dict[str, Any]) -> dict[str, Any]:
        now, week = self._prepare_read(account)
        return self._standings_payload(account, now, week)

    def standings_for(self, account: dict[str, Any]) -> dict[str, Any]:
        return self.league_for(account)

    def feed_for(self, account: dict[str, Any], *, limit: int = 20) -> dict[str, Any]:
        now, week = self._prepare_read(account)
        assert self.store is not None
        user_id = str(account["user_id"])
        has_group = self.store.group_for_player(user_id, week) is not None
        items = self.store.feed_for(
            user_id,
            limit=limit,
            followed_ids=(
                self.follows.following_ids(user_id) if has_group else []
            ),
            include_groups=has_group,
        )
        for item in items:
            self._decorate_feed_item(item)
        return {
            "week_start": week.isoformat(),
            "items": items,
            "generated_at": _iso(now),
        }

    def add_feed_reaction(
        self,
        account: dict[str, Any],
        *,
        event_id: int,
        emoji: str,
    ) -> dict[str, Any]:
        now, week = self._prepare_read(account)
        assert self.store is not None
        user_id = str(account["user_id"])
        if emoji not in FEED_EMOJIS:
            raise ValueError("unknown emoji")
        has_group = self.store.group_for_player(user_id, week) is not None
        item = self.store.add_feed_reaction(
            user_id,
            event_id,
            emoji,
            followed_ids=(
                self.follows.following_ids(user_id) if has_group else []
            ),
            include_groups=has_group,
            now=now,
        )
        if item is None:
            raise LookupError(event_id)
        return self._decorate_feed_item(item)

    def history_for(self, account: dict[str, Any]) -> dict[str, Any]:
        now, week = self._prepare_read(account)
        assert self.store is not None
        user_id = str(account["user_id"])
        rows = self.store.history(user_id)
        return {
            "user_id": user_id,
            "week_start": week.isoformat(),
            "results": [
                {
                    "week_start": str(row["week_start"]),
                    "group_id": int(row["group_id"]),
                    "tier": str(row["tier"]),
                    "rank": int(row["rank"]),
                    "xp": int(row["xp"]),
                    "promoted": bool(row["promoted"]),
                    "demoted": bool(row["demoted"]),
                    "repaired_days": int(row["repaired_days"]),
                    "clean_checkins": int(row["clean_checkins"]),
                    "settled_at": str(row["settled_at"]),
                }
                for row in rows
            ],
            "generated_at": _iso(now),
        }

    # -- writes --------------------------------------------------------
    def increment(
        self,
        account: dict[str, Any],
        *,
        event_id: str,
        seconds: int,
        occurred_at: datetime | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        now, _ = self._prepare_player(account)
        at = _local(occurred_at) if occurred_at is not None else now
        if at > now:
            raise FutureTimestampError("occurred_at must not be in the future")
        assert self.store is not None
        user_id = str(account["user_id"])
        before = self.hook_snapshot(user_id, at)
        result = self.store.ingest_activity(
            user_id,
            event_id=event_id,
            seconds=seconds,
            occurred_at=at,
            source=SOURCE_HUMAN,
            now=now,
        )
        after = self.hook_snapshot(user_id, at)
        return result, before, after

    def channel_roster(
        self,
        channel_id: str,
        players: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create/update the Channel mapping and replace this week's manifest.

        The manifest is the authoritative list of players who may compete for
        the current ``(channel_id, week_start)``.  Identity rows and earlier
        weeks are never deleted; a ref missing from this call simply does not
        participate this week.
        """

        self._initialize_channels()
        assert self.store is not None
        now = self.now()
        week = _week_start(now)
        week_iso = week.isoformat()
        results: list[dict[str, Any]] = []
        seen_refs: set[str] = set()
        created_count = 0
        with self._lock:
            for item in players:
                player_ref = str(item["player_ref"])
                if player_ref in seen_refs:
                    continue
                seen_refs.add(player_ref)
                profile = item.get("profile")
                player, created = self.store.upsert_channel_player(
                    channel_id,
                    player_ref,
                    kind=str(item["kind"]),
                    profile=profile,
                    joined_week=week,
                    now=now,
                )
                if created:
                    created_count += 1
                results.append(
                    {
                        "player_ref": player_ref,
                        "player_id": str(player["id"]),
                        "kind": str(item["kind"]),
                        "profile": profile or {},
                        "created": created,
                    }
                )
            self.store.replace_channel_week_roster(
                channel_id,
                week,
                results,
                now=now,
            )
            # A complete roster is the signal to build this week's groups.
            # Existing local humans are always part of the same pass, so a
            # Channel that arrives first cannot strand them.
            ensure_all_groups(self.store, week, now=now)
        existing_count = len(results) - created_count
        return {
            "channel_id": channel_id,
            "week_start": week_iso,
            "count": len(results),
            "created": created_count,
            "existing": existing_count,
            # Kept for clients written against the task95 response shape.
            "updated": existing_count,
            "players": results,
        }

    def channel_increment(
        self,
        channel_id: str,
        *,
        player_ref: str,
        event_id: str,
        seconds: int,
        occurred_at: datetime,
    ) -> dict[str, Any]:
        """Apply one Channel increment through the normal score/check-in path."""

        self._initialize_channels()
        assert self.store is not None
        now = self.now()
        at = _local(occurred_at)
        if at > now:
            raise FutureTimestampError("occurred_at must not be in the future")
        with self._lock:
            mapping = self.store.get_channel_player(channel_id, player_ref)
            if mapping is None:
                raise ChannelRosterMissing(
                    f"player_ref {player_ref!r} is not in channel {channel_id!r} roster"
                )
            result = self.store.ingest_activity(
                str(mapping["player_id"]),
                event_id=event_id,
                seconds=seconds,
                occurred_at=at,
                source=SOURCE_CHANNEL,
                now=now,
                channel_id=channel_id,
                player_ref=player_ref,
            )
        return {
            **result,
            "channel_id": channel_id,
            "player_ref": player_ref,
        }

    def hook_snapshot(self, player_id: str, at: datetime) -> dict[str, Any]:
        """Small rank/streak snapshot used only by webhook derivation."""

        assert self.store is not None
        week = _week_start(at)
        streak = self.store.refresh_streak(player_id, today=at.date(), now=at)
        group = self.store.group_for_player(player_id, week)
        rank = None
        group_size = 0
        if group is not None:
            rows = self.store.standings(week, group_id=int(group["id"]), now=at)
            group_size = len(rows)
            rank = next(
                (
                    int(row["rank"])
                    for row in rows
                    if str(row["player_id"]) == player_id
                ),
                None,
            )
        score = self.store.get_week_score(player_id, week)
        return {
            "week_start": week.isoformat(),
            "rank": rank,
            "group_size": group_size,
            "current_streak": int(streak.get("current") or 0),
            "last_checkin_date": streak.get("last_checked_date"),
            "week_seconds": int(score["seconds"]) if score else 0,
            "week_xp": int(score["xp"]) if score else 0,
        }

    def repair(
        self,
        account: dict[str, Any],
        *,
        day: date,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._prepare_read(account)
        assert self.store is not None
        return self.store.repair_checkin(
            str(account["user_id"]),
            day,
            idempotency_key=idempotency_key,
            now=self.now(),
        )

    def embers_for(self, account: dict[str, Any]) -> dict[str, Any]:
        now, week = self._prepare_read(account)
        assert self.store is not None
        user_id = str(account["user_id"])
        score = self.store.get_week_score(user_id, week)
        week_seconds = int(score["seconds"]) if score else 0
        row = self.store.get_ember_balance(user_id)
        ledger = self.store.ember_ledger(user_id)
        return {
            "week_start": week.isoformat(),
            **self._ember_summary(user_id, week, week_seconds),
            "week_xp": int(score["xp"]) if score else 0,
            "ledger": [
                {
                    "id": int(item["id"]),
                    "week_start": str(item["week_start"]),
                    "delta": int(item["delta"]),
                    "balance_after": int(item["balance_after"]),
                    "reason": str(item["reason"]),
                    "ref": item.get("ref"),
                    "created_at": str(item["created_at"]),
                }
                for item in reversed(ledger[-20:])
            ],
            "updated_at": (
                str(row["updated_at"]) if row is not None else _iso(now)
            ),
        }

    def checkins_for(
        self, account: dict[str, Any], week_start: date | None = None
    ) -> dict[str, Any]:
        now, current_week = self._prepare_read(account)
        assert self.store is not None
        week = _week_start(week_start or current_week)
        user_id = str(account["user_id"])
        rows = {
            str(row["date"]): row
            for row in self.store.checkins_between(
                user_id, week, week + timedelta(days=7)
            )
        }
        days: list[dict[str, Any]] = []
        for offset in range(7):
            day = week + timedelta(days=offset)
            row = rows.get(day.isoformat())
            seconds = self.store.day_seconds(user_id, day)
            days.append(
                {
                    "date": day.isoformat(),
                    "checked_in": row is not None,
                    "source": str(row["source"]) if row is not None else None,
                    "seconds": int(row["seconds"]) if row is not None else seconds,
                    "xp": (
                        int(row["xp"])
                        if row is not None
                        else xp_for_seconds(seconds)
                    ),
                }
            )
        return {
            "week_start": week.isoformat(),
            "required_xp": CHECKIN_XP,
            "days": days,
            "generated_at": _iso(now),
        }

    def collection_for(self, account: dict[str, Any]) -> dict[str, Any]:
        self._prepare_read(account)
        assert self.store is not None
        return self.store.collection(str(account["user_id"]))

    def update_loadout_for(
        self,
        account: dict[str, Any],
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        self._prepare_read(account)
        assert self.store is not None
        return self.store.update_loadout(
            str(account["user_id"]),
            **fields,
            now=self.now(),
        )

    # -- profile / avatars --------------------------------------------
    def profile_for(self, account: dict[str, Any]) -> dict[str, Any]:
        now, week = self._prepare_read(account)
        assert self.store is not None
        user_id = str(account["user_id"])
        player = self.store.get_player(user_id)
        group = self.store.group_for_player(user_id, week)
        loadout = self.store.loadout_view(user_id)
        return {
            "user_id": user_id,
            "display_name": str(account["display_name"]),
            "avatar_url": self._avatar_public_url(account),
            "activity_label": account.get("activity_label") or "练习",
            "icon_theme": icon_theme_or_default(account.get("icon_theme")),
            "tier": str(group["tier"]) if group else "Bronze",
            "group_id": int(group["id"]) if group else None,
            "group_no": int(group["group_no"]) if group else None,
            "joined_week": str(player["joined_week"]),
            "week_start": week.isoformat(),
            "equipped_title": loadout["title"],
            "frame": loadout["frame"],
            "backdrop": loadout["backdrop"],
            "badge_accent": loadout["badge_accent"],
            "updated_at": _iso(now),
        }

    def update_profile(
        self,
        account: dict[str, Any],
        display_name: str | None = None,
        activity_label: str | None = None,
        icon_theme: str | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        updated = self.accounts.update_profile(
            str(account["user_id"]),
            display_name=display_name,
            activity_label=activity_label,
            icon_theme=icon_theme,
        )
        now = self.now()
        self._ensure_human(updated, _week_start(now), now)
        return self.profile_for(updated)

    def avatar_path(self, user_id: str) -> Path | None:
        if not isinstance(user_id, str) or not SAFE_USER_ID.fullmatch(user_id):
            return None
        path = (self.avatar_dir / f"{user_id}.webp").resolve()
        if path.parent != self.avatar_dir.resolve():
            return None
        return path

    def save_avatar(self, user_id: str, data: bytes) -> str:
        if not data:
            raise AvatarValidationError("empty image")
        if len(data) > MAX_AVATAR_BYTES:
            raise AvatarValidationError("image exceeds 2MB")
        try:
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in ALLOWED_IMAGE_FORMATS:
                    raise AvatarValidationError(
                        "only PNG, JPEG or WebP images are allowed"
                    )
                if source.width * source.height > 25_000_000:
                    raise AvatarValidationError("image dimensions are too large")
                image = ImageOps.exif_transpose(source)
                image.load()
                side = min(image.width, image.height)
                left = (image.width - side) // 2
                top = (image.height - side) // 2
                image = image.crop((left, top, left + side, top + side))
                image = image.resize(
                    (AVATAR_SIZE, AVATAR_SIZE), Image.Resampling.LANCZOS
                )
                canvas = Image.new("RGB", (AVATAR_SIZE, AVATAR_SIZE), "white")
                if "A" in image.getbands():
                    rgba = image.convert("RGBA")
                    canvas.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    canvas.paste(image.convert("RGB"))
        except AvatarValidationError:
            raise
        except (
            Image.DecompressionBombError,
            UnidentifiedImageError,
            OSError,
            ValueError,
        ) as exc:
            raise AvatarValidationError("invalid image file") from exc

        path = self.avatar_path(user_id)
        if path is None:
            raise AvatarValidationError("unsafe user id")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp.webp")
        try:
            canvas.save(temporary, format="WEBP", quality=88, method=6)
            try:
                temporary.chmod(0o600)
            except OSError:
                pass
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
        account = self.accounts.set_avatar_url(user_id, f"avatars/{user_id}.webp")
        return self._avatar_public_url(account) or f"/avatars/{user_id}"

    # -- social --------------------------------------------------------
    def _target_player(
        self, user_id: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        account = self.accounts.get(user_id)
        try:
            assert self.store is not None
            player = self.store.get_player(user_id)
        except GameError:
            player = None
        return account, player

    def _summary_for(
        self,
        user_id: str,
        viewer_id: str,
        now: datetime,
        week: date,
    ) -> dict[str, Any] | None:
        account, player = self._target_player(user_id)
        if account is None and player is None:
            return None
        assert self.store is not None
        if player is None and account is not None:
            player = self._ensure_human(account, week, now)
        if (
            player is not None
            and self.store.group_for_player(user_id, week) is None
            and self._has_channel_roster(week)
        ):
            ensure_all_groups(self.store, week, now=now)
        snapshot = (
            self.store.player_status(user_id, week=week, now=now)
            if player is not None
            else None
        )
        loadout = self.store.loadout_view(user_id)
        following, followers = self.follows.counts(user_id)
        is_ai = bool(player is not None and str(player["kind"]) == "ai")
        avatar_url: str | None = None
        if account is not None:
            avatar_url = self._avatar_public_url(account)
        elif is_ai:
            avatar_url = self._profile_avatar_url(
                self.store.channel_profile_for_player(user_id)
            )
        return {
            "user_id": user_id,
            "display_name": (
                str(account["display_name"])
                if account is not None
                else str(player["display_name"])
            ),
            "avatar_url": avatar_url,
            "activity_label": (
                (account.get("activity_label") or "练习")
                if account is not None
                else None
            ),
            "tier": str(snapshot.get("tier") or "Bronze") if snapshot else None,
            "group_id": (
                int(snapshot["group"]["id"])
                if snapshot and snapshot.get("group")
                else None
            ),
            "week_start": week.isoformat(),
            "xp": int(snapshot.get("xp") or 0) if snapshot else 0,
            "rank": snapshot.get("rank") if snapshot else None,
            "group_size": int(snapshot.get("group_size") or 0) if snapshot else 0,
            "checkin": snapshot.get("checkin") if snapshot else None,
            "streak": int((snapshot.get("streak") or {}).get("current") or 0)
            if snapshot
            else 0,
            "equipped_title": loadout["title"],
            "frame": loadout["frame"],
            "backdrop": loadout["backdrop"],
            "badge_accent": loadout["badge_accent"],
            "is_following": self.follows.is_following(viewer_id, user_id),
            "following_count": following,
            "followers_count": followers,
        }

    def user_detail(self, user_id: str, viewer_id: str) -> dict[str, Any]:
        self._prepare_read(self.accounts.get(viewer_id) or {"user_id": viewer_id})
        now = self.now()
        week = _week_start(now)
        summary = self._summary_for(user_id, viewer_id, now, week)
        if summary is None:
            raise LookupError(user_id)
        return summary

    def follow_user(self, account: dict[str, Any], target_id: str) -> dict[str, Any]:
        self.initialize()
        user_id = str(account["user_id"])
        if target_id == user_id:
            raise ValueError("cannot follow yourself")
        account_target, player_target = self._target_player(target_id)
        if account_target is None and player_target is None:
            raise LookupError(target_id)
        self.follows.follow(user_id, target_id)
        now = self.now()
        return self._summary_for(target_id, user_id, now, _week_start(now)) or {}

    def unfollow_user(self, account: dict[str, Any], target_id: str) -> None:
        self.initialize()
        account_target, player_target = self._target_player(target_id)
        if account_target is None and player_target is None:
            raise LookupError(target_id)
        self.follows.unfollow(str(account["user_id"]), target_id)

    def following_for(self, account: dict[str, Any]) -> list[dict[str, Any]]:
        self._prepare_read(account)
        now = self.now()
        week = _week_start(now)
        return [
            summary
            for user_id in self.follows.following_ids(str(account["user_id"]))
            if (summary := self._summary_for(user_id, str(account["user_id"]), now, week))
            is not None
        ]

    def followers_for(self, account: dict[str, Any]) -> list[dict[str, Any]]:
        self._prepare_read(account)
        now = self.now()
        week = _week_start(now)
        return [
            summary
            for user_id in self.follows.follower_ids(str(account["user_id"]))
            if (summary := self._summary_for(user_id, str(account["user_id"]), now, week))
            is not None
        ]

    def friends_standings(self, account: dict[str, Any]) -> dict[str, Any]:
        self._prepare_read(account)
        now = self.now()
        week = _week_start(now)
        user_id = str(account["user_id"])
        ids = [user_id]
        ids.extend(
            followed
            for followed in self.follows.following_ids(user_id)
            if followed != user_id
        )
        members = [
            summary
            for member_id in ids
            if (summary := self._summary_for(member_id, user_id, now, week))
            is not None
        ]
        members.sort(key=lambda item: (-int(item["xp"]), str(item["user_id"])))
        return {"week_start": week.isoformat(), "members": members}

    def discover_people(self, account: dict[str, Any]) -> list[dict[str, Any]]:
        self._prepare_read(account)
        now = self.now()
        week = _week_start(now)
        user_id = str(account["user_id"])
        people = []
        for other in self.accounts.list_accounts():
            other_id = str(other["user_id"])
            if other_id == user_id:
                continue
            summary = self._summary_for(other_id, user_id, now, week)
            if summary is not None:
                people.append(summary)
        return people


def _auth_dependency(service: GameService):
    def dependency(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        if not authorization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        scheme, _, provided = authorization.partition(" ")
        if scheme.lower() != "bearer" or not provided:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        account = service.accounts.authenticate(provided)
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return account

    return dependency


def _channel_auth_dependency(service: GameService):
    """Separate bearer auth for Channels; account tokens never authorize it."""

    def dependency(authorization: str | None = Header(default=None)) -> str:
        expected = service.channel_token
        if not authorization or not expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing channel token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        scheme, _, provided = authorization.partition(" ")
        if (
            scheme.lower() != "bearer"
            or not provided
            or not hmac.compare_digest(provided, expected)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing channel token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return provided

    return dependency


def create_app(
    *,
    state_path: str | Path | None = None,
    cache_path: str | Path | None = None,
    avatars_path: str | Path | None = None,
    api_dir: str | Path | None = None,
    accounts_db: str | Path | None = None,
    social_db: str | Path | None = None,
    wakatime_cache_path: str | Path | None = None,
    wakatime_fetch_fn: Callable[[str], dict[str, Any] | None] | None = None,
    webhooks_db: str | Path | None = None,
    start_webhook_worker: bool = True,
    token: str | None = None,
    bootstrap_token: str | None = None,
    channel_token: str | None = None,
    secret_path: str | Path = DEFAULT_SECRET_PATH,
    now_fn: Callable[[], datetime] | None = None,
    game_db_path: str | Path | None = None,
    game_now_fn: Callable[[], datetime] | None = None,
) -> FastAPI:
    """Application factory used by production and tests.

    ``state_path`` and the WakaTime arguments remain accepted only so local
    launchers can be upgraded independently; no legacy league file is read.
    """

    del state_path, wakatime_cache_path, wakatime_fetch_fn
    resolved_api_dir = Path(
        api_dir or os.environ.get("GHOST_LEAGUE_API_DIR", DEFAULT_API_DIR)
    )
    service = GameService(
        game_db_path=(
            game_db_path
            or os.environ.get("GHOST_LEAGUE_GAME_DB", str(DEFAULT_DB_PATH))
        ),
        cache_path=(
            cache_path
            or os.environ.get("GHOST_LEAGUE_CACHE_PATH", str(DEFAULT_CACHE_PATH))
        ),
        avatars_path=(
            avatars_path
            or os.environ.get("GHOST_LEAGUE_AVATARS_PATH", str(DEFAULT_AVATARS_PATH))
        ),
        api_dir=resolved_api_dir,
        accounts_db=(
            accounts_db
            or os.environ.get("GHOST_LEAGUE_ACCOUNTS_DB", str(DEFAULT_ACCOUNTS_DB))
        ),
        social_db=social_db,
        token=token,
        bootstrap_token=bootstrap_token,
        channel_token=channel_token,
        secret_path=secret_path,
        now_fn=now_fn,
        game_now_fn=game_now_fn,
    )
    webhook_service = WebhookService(
        webhooks_db
        or os.environ.get("GHOST_LEAGUE_WEBHOOKS_DB", resolved_api_dir / "webhooks.db"),
        now_fn=service.now,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        service.initialize()
        webhook_service.initialize()
        if start_webhook_worker:
            webhook_service.start_worker()
        try:
            yield
        finally:
            webhook_service.stop_worker()

    docs_enabled = os.environ.get("GHOST_LEAGUE_ENABLE_DOCS", "").lower() in {
        "1",
        "true",
        "yes",
    }
    app = FastAPI(
        title="Ghost League API",
        version="3.0.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.game_service = service
    app.state.webhook_service = webhook_service
    auth = _auth_dependency(service)
    channel_auth = _channel_auth_dependency(service)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.url.path.startswith("/embed/"):
            if "x-frame-options" in response.headers:
                del response.headers["x-frame-options"]
            response.headers["Content-Security-Policy"] = (
                "frame-ancestors *; base-uri 'self'; object-src 'none'"
            )
        else:
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Content-Security-Policy"] = (
                "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
            )
        return response

    def game_error(exc: Exception) -> HTTPException:
        if isinstance(exc, ChannelRosterMissing):
            return HTTPException(status_code=404, detail=str(exc))
        if isinstance(exc, FutureTimestampError):
            return HTTPException(
                status_code=422, detail="occurred_at must not be in the future"
            )
        if isinstance(exc, RepairRejected):
            return HTTPException(
                status_code=422, detail={"code": exc.code, "message": exc.detail}
            )
        if isinstance(exc, DuplicateIdempotencyKey):
            return HTTPException(status_code=409, detail=str(exc))
        if isinstance(exc, WeekLocked):
            return HTTPException(status_code=409, detail=str(exc))
        return HTTPException(status_code=422, detail=str(exc))

    @app.get("/health", response_model=HealthResponse)
    def health() -> dict[str, Any]:
        service.initialize()
        return {
            "status": "ok",
            "current_week": _week_start(service.now()).isoformat(),
            "timezone": "Asia/Shanghai",
        }

    @app.get("/badge/{user_id}.svg", include_in_schema=False)
    def badge(user_id: str) -> Response:
        service.initialize()
        status = service.status_for_user(user_id)
        if status is None:
            raise HTTPException(status_code=404, detail="user not found")
        return Response(
            content=render_badge(status),
            media_type="image/svg+xml; charset=utf-8",
            headers={
                "Cache-Control": "no-store, max-age=0",
                "CDN-Cache-Control": "no-store",
                "Cloudflare-CDN-Cache-Control": "no-store",
                "Access-Control-Allow-Origin": "*",
            },
        )

    @app.get("/embed/{user_id}", include_in_schema=False)
    def embed(user_id: str) -> Response:
        service.initialize()
        if service.accounts.get(user_id) is None:
            raise HTTPException(status_code=404, detail="user not found")
        return Response(
            content=render_embed(user_id),
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "public, max-age=60"},
        )

    @app.get("/v1/me/profile")
    def get_profile(account: dict[str, Any] = Depends(auth)) -> dict[str, Any]:
        return service.profile_for(account)

    @app.post("/v1/me/token/rotate", response_model=TokenRotateResponse)
    def rotate_token(account: dict[str, Any] = Depends(auth)) -> dict[str, str]:
        user_id = str(account["user_id"])
        _, token = service.accounts.rotate(user_id)
        logging.getLogger(__name__).info("rotated API token for account %s", user_id)
        return {"user_id": user_id, "token": token}

    @app.patch("/v1/me/profile")
    def patch_profile(
        request: ProfileUpdateRequest,
        account: dict[str, Any] = Depends(auth),
    ) -> dict[str, Any]:
        try:
            return service.update_profile(
                account,
                display_name=request.display_name,
                activity_label=(
                    request.activity_label
                    if request.activity_label is not None
                    else request.activity
                ),
                icon_theme=request.icon_theme,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/me/avatar", response_model=AvatarResponse)
    async def upload_avatar(
        file: UploadFile = File(...),
        account: dict[str, Any] = Depends(auth),
    ) -> dict[str, Any]:
        data = await file.read(MAX_AVATAR_BYTES + 1)
        await file.close()
        if len(data) > MAX_AVATAR_BYTES:
            raise HTTPException(status_code=413, detail="avatar must be at most 2MB")
        try:
            avatar_url = service.save_avatar(str(account["user_id"]), data)
        except AvatarValidationError as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc
        return {"avatar_url": avatar_url}

    @app.get("/avatars/{user_id}")
    def get_avatar(user_id: str) -> FileResponse:
        service.initialize()
        path = service.avatar_path(user_id)
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="avatar not found")
        return FileResponse(
            path,
            media_type="image/webp",
            headers={
                "Cache-Control": "public, max-age=86400",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/v1/me/status")
    def status_snapshot(account: dict[str, Any] = Depends(auth)) -> dict[str, Any]:
        return service.status_for(account)

    @app.post("/v1/me/increments")
    def increments(
        request: DrawingIncrementRequest,
        account: dict[str, Any] = Depends(auth),
    ) -> dict[str, Any]:
        try:
            result, before, after = service.increment(
                account,
                event_id=request.event_id,
                seconds=request.seconds,
                occurred_at=request.occurred_at,
            )
        except (FutureTimestampError, GameError, ValueError) as exc:
            raise game_error(exc) from exc

        if not result["duplicate"]:
            at = _local(request.occurred_at) if request.occurred_at else service.now()
            day = at.date()
            checkin = result.get("checkin") or {}
            crossed_checkin = bool(checkin.get("created"))
            try:
                webhook_service.initialize()
                if crossed_checkin:
                    webhook_service.enqueue_checkin(
                        user_id=str(account["user_id"]),
                        date=day.isoformat(),
                        today_seconds=int(result.get("day_seconds") or 0),
                        current_streak=int(after.get("current_streak") or 0),
                        week_start=str(result.get("week_start") or ""),
                        occurred_at=_iso(at),
                        activity_label=str(account.get("activity_label") or "练习"),
                        week_total_seconds=int(after.get("week_seconds") or 0),
                        rank=after.get("rank"),
                        group_size=after.get("group_size"),
                    )
                specs = _streak_change_specs(
                    user_id=str(account["user_id"]),
                    day=day,
                    before=before,
                    after=after,
                    crossed_checkin=crossed_checkin,
                )
                specs.extend(
                    _rank_change_specs(
                        user_id=str(account["user_id"]),
                        occurrence_id=request.event_id,
                        before=before,
                        after=after,
                    )
                )
                for event_type, event_id, payload in specs:
                    webhook_service.enqueue_event(
                        str(account["user_id"]),
                        event_type,
                        event_id,
                        payload,
                        _iso(at),
                    )
            except Exception:
                logging.getLogger(__name__).warning(
                    "could not enqueue webhook events", exc_info=True
                )

        return {
            "accepted": bool(result.get("accepted")),
            "duplicate": bool(result.get("duplicate")),
            "event_id": str(result["event_id"]),
            "week_start": str(result["week_start"]),
            "seconds": int(result.get("seconds") or 0),
            "week_seconds": int(result.get("week_seconds") or 0),
            "week_xp": int(result.get("week_xp") or 0),
            "today_seconds": int(result.get("day_seconds") or 0),
            "today_xp": int(result.get("day_xp") or 0),
            "checkin": (result.get("checkin") or {}).get("source"),
        }

    @app.post("/v1/channels/{channel_id}/roster")
    def channel_roster(
        channel_id: str,
        request: ChannelRosterRequest | list[ChannelRosterPlayer],
        _channel_token: str = Depends(channel_auth),
    ) -> dict[str, Any]:
        players = (
            [player.model_dump(exclude_none=True) for player in request.players]
            if isinstance(request, ChannelRosterRequest)
            else [player.model_dump(exclude_none=True) for player in request]
        )
        try:
            return service.channel_roster(channel_id, players)
        except (GameError, ValueError) as exc:
            raise game_error(exc) from exc

    @app.post("/v1/channels/{channel_id}/increments")
    def channel_increments(
        channel_id: str,
        request: ChannelIncrementRequest,
        _channel_token: str = Depends(channel_auth),
    ) -> dict[str, Any]:
        try:
            result = service.channel_increment(
                channel_id,
                player_ref=request.player_ref,
                event_id=request.event_id,
                seconds=request.seconds,
                occurred_at=request.occurred_at,
            )
        except (FutureTimestampError, GameError, ValueError, TypeError) as exc:
            raise game_error(exc) from exc
        return {
            "accepted": bool(result.get("accepted")),
            "duplicate": bool(result.get("duplicate")),
            "channel_id": channel_id,
            "player_ref": request.player_ref,
            "player_id": str(result["player_id"]),
            "event_id": str(result["event_id"]),
            "week_start": str(result["week_start"]),
            "seconds": int(result.get("seconds") or 0),
            "week_seconds": int(result.get("week_seconds") or 0),
            "week_xp": int(result.get("week_xp") or 0),
            "today_seconds": int(result.get("day_seconds") or 0),
            "today_xp": int(result.get("day_xp") or 0),
            "checkin": (result.get("checkin") or {}).get("source"),
        }

    @app.get("/v1/me/league")
    def me_league(account: dict[str, Any] = Depends(auth)) -> dict[str, Any]:
        return service.league_for(account)

    @app.get("/v1/league/standings")
    def standings(account: dict[str, Any] = Depends(auth)) -> dict[str, Any]:
        return service.standings_for(account)

    @app.get("/v1/league/history")
    def history(account: dict[str, Any] = Depends(auth)) -> dict[str, Any]:
        return service.history_for(account)

    @app.get("/v1/league/feed")
    def feed(
        limit: int = Query(default=20, ge=1, le=50),
        account: dict[str, Any] = Depends(auth),
    ) -> dict[str, Any]:
        return service.feed_for(account, limit=limit)

    @app.post("/v1/league/feed/{event_id}/reactions")
    def react_to_feed(
        event_id: int,
        request: FeedReactionRequest,
        account: dict[str, Any] = Depends(auth),
    ) -> dict[str, Any]:
        try:
            return service.add_feed_reaction(
                account, event_id=event_id, emoji=request.emoji
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="feed event not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/me/embers")
    def embers(account: dict[str, Any] = Depends(auth)) -> dict[str, Any]:
        return service.embers_for(account)

    @app.get("/v1/me/collection")
    def collection(account: dict[str, Any] = Depends(auth)) -> dict[str, Any]:
        return service.collection_for(account)

    @app.patch("/v1/me/loadout")
    def patch_loadout(
        request: LoadoutPatchRequest,
        account: dict[str, Any] = Depends(auth),
    ) -> dict[str, Any]:
        fields = {
            field: getattr(request, field)
            for field in request.model_fields_set
        }
        try:
            return service.update_loadout_for(account, fields=fields)
        except (GameError, ValueError) as exc:
            raise game_error(exc) from exc

    @app.post("/v1/me/repair")
    def repair(
        request: RepairRequest,
        account: dict[str, Any] = Depends(auth),
    ) -> dict[str, Any]:
        try:
            return service.repair(
                account,
                day=request.date,
                idempotency_key=request.idempotency_key,
            )
        except (DuplicateIdempotencyKey, RepairRejected, GameError, ValueError) as exc:
            raise game_error(exc) from exc

    @app.get("/v1/me/checkins")
    def checkins(
        week_start: date | None = Query(default=None),
        account: dict[str, Any] = Depends(auth),
    ) -> dict[str, Any]:
        return service.checkins_for(account, week_start=week_start)

    @app.get("/v1/users/{user_id}")
    def get_user(
        user_id: str,
        account: dict[str, Any] = Depends(auth),
    ) -> dict[str, Any]:
        try:
            return service.user_detail(user_id, str(account["user_id"]))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="user not found") from exc

    @app.post("/v1/me/follows/{user_id}")
    def follow_user(
        user_id: str,
        account: dict[str, Any] = Depends(auth),
    ) -> dict[str, Any]:
        try:
            return service.follow_user(account, user_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="user not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete("/v1/me/follows/{user_id}", status_code=204)
    def unfollow_user(
        user_id: str,
        account: dict[str, Any] = Depends(auth),
    ) -> Response:
        try:
            service.unfollow_user(account, user_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="user not found") from exc
        return Response(status_code=204)

    @app.get("/v1/me/follows")
    def list_follows(account: dict[str, Any] = Depends(auth)) -> list[dict[str, Any]]:
        return service.following_for(account)

    @app.get("/v1/me/followers")
    def list_followers(account: dict[str, Any] = Depends(auth)) -> list[dict[str, Any]]:
        return service.followers_for(account)

    @app.get("/v1/me/friends/standings")
    def friends_standings(account: dict[str, Any] = Depends(auth)) -> dict[str, Any]:
        return service.friends_standings(account)

    @app.get("/v1/discover/people")
    def discover_people(account: dict[str, Any] = Depends(auth)) -> list[dict[str, Any]]:
        return service.discover_people(account)

    @app.post("/v1/me/webhooks", response_model=WebhookCreateResponse)
    def create_webhook(
        request: WebhookCreateRequest,
        account: dict[str, Any] = Depends(auth),
    ) -> dict[str, Any]:
        webhook_service.initialize()
        try:
            return webhook_service.create_webhook(
                str(account["user_id"]),
                request.url,
                request.events,
                transport=request.transport,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/me/webhooks", response_model=list[WebhookResponse])
    def list_webhooks(account: dict[str, Any] = Depends(auth)) -> list[dict[str, Any]]:
        webhook_service.initialize()
        return webhook_service.list_webhooks(str(account["user_id"]))

    @app.patch("/v1/me/webhooks/{webhook_id}", response_model=WebhookResponse)
    def update_webhook(
        webhook_id: int,
        request: WebhookPatchRequest,
        account: dict[str, Any] = Depends(auth),
    ) -> dict[str, Any]:
        webhook_service.initialize()
        try:
            updated = webhook_service.update_webhook(
                str(account["user_id"]),
                webhook_id,
                url=request.url,
                events=request.events,
                transport=request.transport,
                active=request.active,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="webhook not found")
        return updated

    @app.delete("/v1/me/webhooks/{webhook_id}", status_code=204)
    def delete_webhook(
        webhook_id: int,
        account: dict[str, Any] = Depends(auth),
    ) -> Response:
        webhook_service.initialize()
        if not webhook_service.delete_webhook(str(account["user_id"]), webhook_id):
            raise HTTPException(status_code=404, detail="webhook not found")
        return Response(status_code=204)

    @app.post(
        "/v1/me/webhooks/{webhook_id}/test",
        response_model=WebhookTestResponse,
    )
    def test_webhook(
        webhook_id: int,
        account: dict[str, Any] = Depends(auth),
    ) -> dict[str, Any]:
        service.initialize()
        webhook_service.initialize()
        user_id = str(account["user_id"])
        if webhook_service.get_webhook(user_id, webhook_id) is None:
            raise HTTPException(status_code=404, detail="webhook not found")
        now = service.now()
        snapshot = service.hook_snapshot(user_id, now)
        delivery_id = webhook_service.enqueue_test(
            user_id=user_id,
            webhook_id=webhook_id,
            date=now.date().isoformat(),
            today_seconds=service.store.day_seconds(user_id, now.date())
            if service.store is not None
            else 0,
            current_streak=int(snapshot.get("current_streak") or 0),
            week_start=_week_start(now).isoformat(),
            occurred_at=_iso(now),
            activity_label=str(account.get("activity_label") or "练习"),
            week_total_seconds=int(snapshot.get("week_seconds") or 0),
            rank=snapshot.get("rank"),
            group_size=snapshot.get("group_size"),
        )
        if delivery_id is None:
            raise HTTPException(status_code=404, detail="webhook not found")
        delivery = webhook_service.deliver_now(delivery_id)
        if delivery is None:
            raise HTTPException(status_code=500, detail="delivery failed")
        return {
            "delivery_id": delivery_id,
            "status": delivery["status"],
            "attempts": delivery["attempts"],
            "last_error": delivery["last_error"],
        }

    return app


app = create_app()


__all__ = [
    "app",
    "create_app",
    "AvatarValidationError",
    "GameService",
    "OWNER_USER_ID",
]
