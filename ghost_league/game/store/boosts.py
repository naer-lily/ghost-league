"""Config-driven diamond boosts.

Prices, durations, multipliers, and availability live in the ``game_config``
table so balance changes never require a code edit.  Purchases and the shop
catalog read the same rows; a missing or malformed row fails closed instead of
silently becoming a free or zero-multiplier product.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from .. import calendar as cal
from ..rules import ShopNotAvailable, ShopQuantityRejected

BOOST_ITEM_PREFIX = "diamond_boost_"
BOOST_SKU_SUFFIXES = ("25", "60")
DIAMOND_BOOST_MULTIPLIER_KEY = "diamond_boost_multiplier"
INACTIVE_BOOST_MULTIPLIER = 1


def _inactive_state() -> dict[str, Any]:
    return {
        "expires_at": None,
        "remaining_seconds": 0,
        "multiplier": INACTIVE_BOOST_MULTIPLIER,
    }


class BoostMixin:
    """Game config, diamond boost purchases, and boosted credits."""

    # ------------------------------------------------------------------
    # Game config
    # ------------------------------------------------------------------
    @staticmethod
    def _seed_game_config(conn: sqlite3.Connection, *, now: str) -> None:
        """Install balance seeds without overwriting operator edits."""

        seeds = (
            (DIAMOND_BOOST_MULTIPLIER_KEY, "2"),
            ("diamond_boost_25_price", "25"),
            ("diamond_boost_25_minutes", "25"),
            ("diamond_boost_60_price", "60"),
            ("diamond_boost_60_minutes", "60"),
            ("diamond_boost_25_active", "1"),
            ("diamond_boost_60_active", "1"),
        )
        for key, value in seeds:
            conn.execute(
                "INSERT INTO game_config (key, value, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(key) DO NOTHING",
                (key, value, now),
            )

    def get_game_config(self, key: str) -> str | None:
        with self._reader() as conn:
            row = conn.execute(
                "SELECT value FROM game_config WHERE key = ?", (key,)
            ).fetchone()
            return None if row is None else str(row["value"])

    def list_game_config(self) -> dict[str, str]:
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT key, value FROM game_config ORDER BY key"
            ).fetchall()
            return {str(row["key"]): str(row["value"]) for row in rows}

    def set_game_config(
        self,
        key: str,
        value: str,
        *,
        now: datetime | str | None = None,
    ) -> str:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("game config key must be non-empty")
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        updated_at = cal.iso_ts(local_now)
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO game_config (key, value, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
                "value = excluded.value, updated_at = excluded.updated_at",
                (key.strip(), str(value), updated_at),
            )
        return str(value)

    @staticmethod
    def _config_value_with(
        conn: sqlite3.Connection, key: str
    ) -> str | None:
        row = conn.execute(
            "SELECT value FROM game_config WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        value = str(row["value"]).strip()
        return value or None

    @classmethod
    def _config_int_with(
        cls,
        conn: sqlite3.Connection,
        key: str,
        *,
        minimum: int,
    ) -> int:
        value = cls._config_value_with(conn, key)
        if value is None:
            raise ValueError(f"missing game config: {key}")
        try:
            number = int(value)
        except ValueError as exc:
            raise ValueError(f"invalid integer game config: {key}") from exc
        if number < minimum:
            raise ValueError(f"game config below minimum: {key}")
        return number

    @classmethod
    def _config_bit_with(cls, conn: sqlite3.Connection, key: str) -> bool:
        value = cls._config_value_with(conn, key)
        if value not in {"0", "1"}:
            raise ValueError(f"invalid boolean game config: {key}")
        return value == "1"

    def _boost_sku_config_with(
        self, conn: sqlite3.Connection, item_id: str
    ) -> dict[str, Any] | None:
        """Return one boost SKU, or ``None`` when its config fails closed."""

        if not self._is_boost_item(item_id):
            return None
        try:
            multiplier = self._config_int_with(
                conn, DIAMOND_BOOST_MULTIPLIER_KEY, minimum=1
            )
            price = self._config_int_with(
                conn, f"{item_id}_price", minimum=0
            )
            minutes = self._config_int_with(
                conn, f"{item_id}_minutes", minimum=1
            )
            active = self._config_bit_with(conn, f"{item_id}_active")
        except ValueError:
            return None
        return {
            "id": item_id,
            "price_diamonds": price,
            "minutes": minutes,
            "multiplier": multiplier,
            "active": active,
        }

    @staticmethod
    def _is_boost_item(item_id: str) -> bool:
        return item_id in {
            f"{BOOST_ITEM_PREFIX}{suffix}" for suffix in BOOST_SKU_SUFFIXES
        }

    def _boost_catalog_with(
        self, conn: sqlite3.Connection
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for suffix in BOOST_SKU_SUFFIXES:
            item_id = f"{BOOST_ITEM_PREFIX}{suffix}"
            config = self._boost_sku_config_with(conn, item_id)
            if config is None:
                continue
            minutes = int(config["minutes"])
            entries.append(
                {
                    "id": item_id,
                    "name": f"经验宝 · {minutes} 分钟",
                    "description": "",
                    "price_diamonds": int(config["price_diamonds"]),
                    "currency": "diamonds",
                    "kind": "boost",
                    "active": bool(config["active"]),
                    "minutes": minutes,
                    "multiplier": int(config["multiplier"]),
                    "owned_quantity": 0,
                    "cooldown_seconds": 0,
                    "cooldown_until": None,
                    "available": bool(config["active"]),
                }
            )
        return entries

    # ------------------------------------------------------------------
    # Active boost state and boosted credits
    # ------------------------------------------------------------------
    def _boost_state_with(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        now: datetime,
    ) -> dict[str, Any]:
        row = conn.execute(
            "SELECT multiplier, expires_at FROM diamond_boosts "
            "WHERE player_id = ?",
            (player_id,),
        ).fetchone()
        if row is None:
            return _inactive_state()
        try:
            expires_at = cal.parse_datetime(str(row["expires_at"]))
            multiplier = int(row["multiplier"])
        except (TypeError, ValueError):
            return _inactive_state()
        if expires_at <= now or multiplier <= 0:
            return _inactive_state()
        return {
            "expires_at": cal.iso_ts(expires_at),
            "remaining_seconds": max(
                0, int((expires_at - now).total_seconds())
            ),
            "multiplier": multiplier,
        }

    def diamond_boost_state(
        self,
        player_id: str,
        *,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        with self._reader() as conn:
            return self._boost_state_with(conn, player_id, local_now)

    def _active_boost_multiplier_with(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        now: datetime,
    ) -> int:
        state = self._boost_state_with(conn, player_id, now)
        return int(state["multiplier"])

    def _purchase_diamond_boost_with(
        self,
        conn: sqlite3.Connection,
        *,
        player_id: str,
        item_id: str,
        quantity: int,
        request_id: str,
        now: datetime,
        created_at: str,
    ) -> dict[str, Any]:
        if quantity != 1:
            raise ShopQuantityRejected(
                "quantity_must_be_one",
                f"{item_id} can only be bought one at a time",
            )
        config = self._boost_sku_config_with(conn, item_id)
        if config is None:
            raise ShopNotAvailable(
                "boost_config_invalid",
                "diamond boost config is missing or invalid",
            )
        if not config["active"]:
            raise ShopNotAvailable(
                "boost_inactive",
                "diamond boost is not active",
            )

        base = now
        existing = conn.execute(
            "SELECT expires_at FROM diamond_boosts WHERE player_id = ?",
            (player_id,),
        ).fetchone()
        if existing is not None:
            try:
                stored = cal.parse_datetime(str(existing["expires_at"]))
            except (TypeError, ValueError):
                stored = None
            if stored is not None and stored > base:
                base = stored
        expires_at = base + timedelta(minutes=int(config["minutes"]))

        self._debit_diamonds_with(  # type: ignore[attr-defined]
            conn,
            player_id=player_id,
            amount=int(config["price_diamonds"]),
            reason="shop_purchase",
            ref_type="shop_item",
            ref_id=item_id,
            idempotency_key=request_id,
            now=now,
            create_for_unknown=True,
        )
        conn.execute(
            "INSERT INTO diamond_boosts "
            "(player_id, multiplier, expires_at, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(player_id) DO UPDATE SET "
            "multiplier = excluded.multiplier, "
            "expires_at = excluded.expires_at, "
            "updated_at = excluded.updated_at",
            (
                player_id,
                int(config["multiplier"]),
                cal.iso_ts(expires_at),
                created_at,
            ),
        )

        wallet = self._wallet_summary(  # type: ignore[attr-defined]
            self._wallet_row_with(conn, player_id)  # type: ignore[attr-defined]
        )
        payload: dict[str, Any] = {
            "ok": True,
            "item_id": item_id,
            "quantity": 1,
            "diamonds": wallet["balance"],
            "diamond_cap": wallet["diamond_cap"],
            "diamond_cap_level": wallet["diamond_cap_level"],
            "diamond_excess": wallet["diamond_excess"],
            "inventory": self._inventory_payload_with(  # type: ignore[attr-defined]
                conn, player_id
            ),
            "cooldown_until": None,
            "replayed": False,
            "diamond_boost": self._boost_state_with(conn, player_id, now),
        }
        self._record_purchase_request_with(  # type: ignore[attr-defined]
            conn,
            player_id=player_id,
            request_id=request_id,
            item_id=item_id,
            quantity=1,
            payload=payload,
            created_at=created_at,
        )
        return payload


__all__ = [
    "BOOST_ITEM_PREFIX",
    "BOOST_SKU_SUFFIXES",
    "BoostMixin",
    "DIAMOND_BOOST_MULTIPLIER_KEY",
    "INACTIVE_BOOST_MULTIPLIER",
]
