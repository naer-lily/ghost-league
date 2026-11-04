"""Diamond wallet, generic inventory, named stars, and the backend shop.

Diamonds are a *soft* capped currency: the balance may exceed the cap, and the
excess loses 1% per complete hour.  Every purchase still runs inside one
``BEGIN IMMEDIATE`` transaction so a failed grant, cooldown write, or request
record can never leave diamonds deducted without the item.  Request ids are
unique per player and the diamond ledger is the final guard against paying
twice.
"""

from __future__ import annotations

import json
import math
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any

from .. import calendar as cal
from ..rules import (
    DuplicateIdempotencyKey,
    InsufficientDiamonds,
    ShopCooldown,
    ShopNotAllowed,
    ShopNotAvailable,
    ShopQuantityRejected,
    UnknownShopItem,
)
from ..stars import (
    RARITY_LABELS,
    RARITY_WEIGHTS,
    STAR_TYPES,
    TYPE_LABELS,
    generate_star_name,
    make_star_visual,
    parse_palette_json,
    roll_star_rarity,
    roll_star_type,
    validate_star_name,
)
from .core import _row_to_dict

STAR_ITEM_ID = "star"
SEASONAL_STAR_ITEM_ID = "seasonal_star"
EMBER_ITEM_ID = "ember"
CAP_ITEM_PREFIX = "diamond_cap_"

DIAMOND_INITIAL_BALANCE = 1000
DIAMOND_INITIAL_CAP = 1000
DIAMOND_CAP_STEP = 500
DIAMOND_CAP_MAX_LEVEL = 5
DIAMOND_DECAY_RATE_PER_HOUR = 0.01
DIAMOND_CAP_UPGRADES: tuple[tuple[int, int], ...] = (
    (1, 500),
    (2, 800),
    (3, 1200),
    (4, 1800),
    (5, 2600),
)

STAR_PRICE_DIAMONDS = 300
SEASONAL_STAR_PRICE_DIAMONDS = 500
STAR_NAME_MAX_LENGTH = 40
SINGLE_PURCHASE_QUANTITY = 1
EMBER_PURCHASE_QUANTITY = 1


def compute_diamond_decay(
    balance: int,
    cap: int,
    last_decay_at: datetime | str | None,
    now: datetime | str,
) -> tuple[int, int, datetime]:
    """Return ``(new_balance, lost, new_decay_anchor)``.

    Only complete hours count.  When the balance is at or below the cap nothing
    is lost and the anchor moves to ``now``; when it still has excess the
    anchor advances by the consumed whole hours so a partial hour is never
    charged twice.
    """

    current = cal.parse_datetime(now)
    if last_decay_at is None:
        return int(balance), 0, current
    anchor = cal.parse_datetime(last_decay_at)
    if int(balance) <= int(cap):
        return int(balance), 0, current
    if anchor > current:
        return int(balance), 0, anchor

    hours = int((current - anchor).total_seconds() // 3_600)
    if hours <= 0:
        return int(balance), 0, anchor

    excess = int(balance) - int(cap)
    remaining = math.floor(
        excess * (1.0 - DIAMOND_DECAY_RATE_PER_HOUR) ** hours + 1e-9
    )
    new_balance = max(int(cap), int(cap) + max(0, remaining))
    new_anchor = anchor + timedelta(hours=hours)
    if new_balance <= int(cap):
        new_anchor = current
    return new_balance, int(balance) - new_balance, new_anchor


class ShopMixin:
    """Diamond wallets, inventory quantities, stars, and shop purchases."""

    # ------------------------------------------------------------------
    # Diamond wallet and ledger
    # ------------------------------------------------------------------
    def get_diamond_balance(
        self,
        player_id: str,
        *,
        now: datetime | str | None = None,
    ) -> int:
        """Return the current balance after applying lazy time decay."""

        wallet = self.get_diamond_wallet(player_id, now=now)
        return int(wallet["balance"])

    def get_diamond_wallet(
        self,
        player_id: str,
        *,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Return wallet fields, creating/backfilling a human wallet on read."""

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        with self.transaction() as conn:
            row = self._sync_diamond_decay_with(
                conn, player_id, local_now, create_for_unknown=False
            )
            return self._wallet_summary(row)

    def diamond_ledger(self, player_id: str) -> list[dict[str, Any]]:
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT * FROM diamond_ledger WHERE player_id = ? ORDER BY id",
                (player_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def apply_diamond_decay(
        self,
        player_id: str,
        *,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Apply the same pure decay used by wallet reads and the hourly job."""

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        with self.transaction() as conn:
            before = self._wallet_row_with(conn, player_id)
            if before is None:
                return {
                    "player_id": player_id,
                    "balance": 0,
                    "lost": 0,
                    "applied": False,
                }
            row = self._sync_diamond_decay_with(
                conn, player_id, local_now, create_for_unknown=False
            )
            return {
                "player_id": player_id,
                "balance": 0 if row is None else int(row["balance"]),
                "lost": 0
                if row is None
                else int(before["balance"]) - int(row["balance"]),
                "applied": row is not None
                and int(before["balance"]) != int(row["balance"]),
            }

    def apply_all_diamond_decay(
        self,
        *,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Hourly/offline catch-up for every existing wallet."""

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        with self.transaction() as conn:
            rows = conn.execute(
                "SELECT player_id, balance FROM diamond_balance ORDER BY player_id"
            ).fetchall()
            decayed = 0
            total_lost = 0
            for prior in rows:
                player_id = str(prior["player_id"])
                row = self._sync_diamond_decay_with(
                    conn, player_id, local_now, create_for_unknown=False
                )
                if row is None:
                    continue
                lost = int(prior["balance"]) - int(row["balance"])
                if lost > 0:
                    decayed += 1
                    total_lost += lost
            return {
                "wallets": len(rows),
                "decayed": decayed,
                "lost": total_lost,
            }

    def credit_diamonds(
        self,
        player_id: str,
        amount: int,
        reason: str,
        ref_type: str | None = None,
        ref_id: str | None = None,
        idempotency_key: str | None = None,
        *,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Internal/local-test entry point for diamond grants.

        The same idempotency key never credits twice.  A caller that omits the
        key gets a random one, so a repeated call is a new grant by design.
        Credits are never hard-capped; any excess decays later by time.
        """

        self._validate_diamond_amount(amount)
        self._validate_reason(reason)
        if idempotency_key is not None and not str(idempotency_key).strip():
            raise ValueError("idempotency_key must be non-empty")
        key = idempotency_key or f"diamond-credit:{uuid.uuid4().hex}"
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()

        with self.transaction() as conn:
            self._ensure_diamond_owner_with(conn, player_id)
            return self._credit_diamonds_with(
                conn,
                player_id=player_id,
                amount=int(amount),
                reason=reason,
                ref_type=ref_type,
                ref_id=ref_id,
                idempotency_key=key,
                now=local_now,
            )

    def _credit_diamonds_with(
        self,
        conn: sqlite3.Connection,
        *,
        player_id: str,
        amount: int,
        reason: str,
        ref_type: str | None,
        ref_id: str | None,
        idempotency_key: str,
        now: datetime,
        boost: bool = False,
    ) -> dict[str, Any]:
        """Credit inside an existing transaction, keyed for idempotency.

        Settlement code (rival rewards, bet payouts) shares a transaction with
        its own status update, so it must not open a nested transaction.
        ``boost`` is opt-in: normal game income asks for the configured
        multiplier, while operator/test grants keep the base amount.
        """

        prior = self._ledger_by_key_with(conn, idempotency_key)
        if prior is not None:
            self._require_same_ledger(
                prior,
                player_id=player_id,
                delta=None if boost else int(amount),
                reason=reason,
                ref_type=ref_type,
                ref_id=ref_id,
            )
            return self._ledger_result(prior, duplicate=True)

        credited = int(amount)
        if boost:
            credited *= self._active_boost_multiplier_with(
                conn, player_id, now
            )
        created_at = cal.iso_ts(now)
        row = self._sync_diamond_decay_with(
            conn, player_id, now, create_for_unknown=True
        )
        balance = 0 if row is None else int(row["balance"])
        new_balance = balance + credited
        self._set_diamond_balance_with(conn, player_id, new_balance, created_at)
        ledger_id = self._insert_diamond_ledger_with(
            conn,
            player_id=player_id,
            delta=credited,
            balance_after=new_balance,
            reason=reason,
            ref_type=ref_type,
            ref_id=ref_id,
            idempotency_key=idempotency_key,
            created_at=created_at,
        )
        return {
            "player_id": player_id,
            "delta": credited,
            "balance": new_balance,
            "ledger_id": ledger_id,
            "duplicate": False,
        }

    def debit_diamonds(
        self,
        player_id: str,
        amount: int,
        reason: str,
        ref_type: str | None = None,
        ref_id: str | None = None,
        idempotency_key: str | None = None,
        *,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Spend diamonds; a missing wallet or a low balance is rejected."""

        self._validate_diamond_amount(amount)
        self._validate_reason(reason)
        if idempotency_key is not None and not str(idempotency_key).strip():
            raise ValueError("idempotency_key must be non-empty")
        key = idempotency_key or f"diamond-debit:{uuid.uuid4().hex}"
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()

        with self.transaction() as conn:
            self._ensure_diamond_owner_with(conn, player_id)
            return self._debit_diamonds_with(
                conn,
                player_id=player_id,
                amount=int(amount),
                reason=reason,
                ref_type=ref_type,
                ref_id=ref_id,
                idempotency_key=key,
                now=local_now,
                create_for_unknown=True,
            )

    @staticmethod
    def _validate_diamond_amount(amount: int) -> None:
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise TypeError("amount must be an integer")
        if amount <= 0:
            raise ValueError("amount must be positive")

    @staticmethod
    def _validate_reason(reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be non-empty")

    def _ensure_diamond_owner_with(
        self, conn: sqlite3.Connection, player_id: str
    ) -> None:
        """Diamonds belong to humans; unknown local-test ids are allowed."""

        row = conn.execute(
            "SELECT kind FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        if row is not None and str(row["kind"]) != "human":
            raise ShopNotAllowed("diamonds are only available to human players")

    @staticmethod
    def _wallet_row_with(
        conn: sqlite3.Connection, player_id: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM diamond_balance WHERE player_id = ?",
            (player_id,),
        ).fetchone()

    def _ensure_wallet_with(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        *,
        now: datetime,
        create_for_unknown: bool,
    ) -> sqlite3.Row | None:
        """Create the 1000/1000 wallet for a human if it does not exist yet."""

        row = self._wallet_row_with(conn, player_id)
        if row is not None:
            return row

        player = conn.execute(
            "SELECT kind FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        if player is not None:
            if str(player["kind"]) != "human":
                return None
        elif not create_for_unknown:
            return None

        created_at = cal.iso_ts(now)
        conn.execute(
            "INSERT INTO diamond_balance "
            "(player_id, balance, diamond_cap, diamond_cap_level, "
            "last_decay_at, updated_at) "
            "VALUES (?, ?, ?, 0, ?, ?) ON CONFLICT(player_id) DO NOTHING",
            (
                player_id,
                DIAMOND_INITIAL_BALANCE,
                DIAMOND_INITIAL_CAP,
                created_at,
                created_at,
            ),
        )
        return self._wallet_row_with(conn, player_id)

    def _sync_diamond_decay_with(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        now: datetime,
        *,
        create_for_unknown: bool,
    ) -> sqlite3.Row | None:
        row = self._ensure_wallet_with(
            conn,
            player_id,
            now=now,
            create_for_unknown=create_for_unknown,
        )
        if row is None:
            return None

        balance = int(row["balance"])
        cap = int(row["diamond_cap"])
        stored_anchor = row["last_decay_at"]
        new_balance, lost, new_anchor = compute_diamond_decay(
            balance, cap, stored_anchor, now
        )
        if stored_anchor is not None:
            stored_dt = cal.parse_datetime(stored_anchor)
            if new_anchor < stored_dt:
                new_anchor = stored_dt
        anchor_iso = cal.iso_ts(new_anchor)
        now_iso = cal.iso_ts(now)

        if lost > 0:
            self._insert_diamond_ledger_with(
                conn,
                player_id=player_id,
                delta=-lost,
                balance_after=new_balance,
                reason="decay",
                ref_type="time",
                ref_id=anchor_iso,
                idempotency_key=f"diamond-decay:{player_id}:{anchor_iso}",
                created_at=now_iso,
            )
            conn.execute(
                "UPDATE diamond_balance SET balance = ?, last_decay_at = ?, "
                "updated_at = ? WHERE player_id = ?",
                (new_balance, anchor_iso, now_iso, player_id),
            )
        elif stored_anchor != anchor_iso:
            conn.execute(
                "UPDATE diamond_balance SET last_decay_at = ?, updated_at = ? "
                "WHERE player_id = ?",
                (anchor_iso, now_iso, player_id),
            )
        return self._wallet_row_with(conn, player_id)

    @staticmethod
    def _wallet_summary(row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            return {
                "balance": 0,
                "diamond_cap": 0,
                "diamond_cap_level": 0,
                "diamond_excess": 0,
                "last_decay_at": None,
            }
        balance = int(row["balance"])
        cap = int(row["diamond_cap"])
        return {
            "balance": balance,
            "diamond_cap": cap,
            "diamond_cap_level": int(row["diamond_cap_level"]),
            "diamond_excess": max(0, balance - cap),
            "last_decay_at": row["last_decay_at"],
        }

    @staticmethod
    def _diamond_balance_with(conn: sqlite3.Connection, player_id: str) -> int:
        row = conn.execute(
            "SELECT balance FROM diamond_balance WHERE player_id = ?",
            (player_id,),
        ).fetchone()
        return 0 if row is None else int(row["balance"])

    @staticmethod
    def _set_diamond_balance_with(
        conn: sqlite3.Connection,
        player_id: str,
        balance: int,
        now: str,
    ) -> None:
        conn.execute(
            "INSERT INTO diamond_balance (player_id, balance, updated_at) "
            "VALUES (?, ?, ?) ON CONFLICT(player_id) DO UPDATE SET "
            "balance = excluded.balance, updated_at = excluded.updated_at",
            (player_id, balance, now),
        )

    @staticmethod
    def _ledger_by_key_with(
        conn: sqlite3.Connection, idempotency_key: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM diamond_ledger WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()

    @staticmethod
    def _require_same_ledger(
        prior: sqlite3.Row,
        *,
        player_id: str,
        delta: int | None,
        reason: str,
        ref_type: str | None,
        ref_id: str | None,
    ) -> None:
        same = (
            str(prior["player_id"]) == player_id
            and (delta is None or int(prior["delta"]) == delta)
            and str(prior["reason"]) == reason
            and (prior["ref_type"] or None) == (ref_type or None)
            and (prior["ref_id"] or None) == (ref_id or None)
        )
        if not same:
            raise DuplicateIdempotencyKey(
                "idempotency_key already used for a different request"
            )

    @staticmethod
    def _ledger_result(prior: sqlite3.Row, *, duplicate: bool) -> dict[str, Any]:
        return {
            "player_id": str(prior["player_id"]),
            "delta": int(prior["delta"]),
            "balance": int(prior["balance_after"]),
            "ledger_id": int(prior["id"]),
            "duplicate": duplicate,
        }

    @staticmethod
    def _insert_diamond_ledger_with(
        conn: sqlite3.Connection,
        *,
        player_id: str,
        delta: int,
        balance_after: int,
        reason: str,
        ref_type: str | None,
        ref_id: str | None,
        idempotency_key: str,
        created_at: str,
    ) -> int:
        cursor = conn.execute(
            "INSERT INTO diamond_ledger "
            "(player_id, delta, balance_after, reason, ref_type, ref_id, "
            "idempotency_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                player_id,
                delta,
                balance_after,
                reason,
                ref_type,
                ref_id,
                idempotency_key,
                created_at,
            ),
        )
        return int(cursor.lastrowid)

    def _debit_diamonds_with(
        self,
        conn: sqlite3.Connection,
        *,
        player_id: str,
        amount: int,
        reason: str,
        ref_type: str | None,
        ref_id: str | None,
        idempotency_key: str,
        now: datetime,
        create_for_unknown: bool = False,
    ) -> dict[str, Any]:
        prior = self._ledger_by_key_with(conn, idempotency_key)
        if prior is not None:
            self._require_same_ledger(
                prior,
                player_id=player_id,
                delta=-amount,
                reason=reason,
                ref_type=ref_type,
                ref_id=ref_id,
            )
            return self._ledger_result(prior, duplicate=True)

        row = self._sync_diamond_decay_with(
            conn, player_id, now, create_for_unknown=create_for_unknown
        )
        balance = 0 if row is None else int(row["balance"])
        if balance < amount:
            raise InsufficientDiamonds(balance)
        new_balance = balance - amount
        created_at = cal.iso_ts(now)
        self._set_diamond_balance_with(conn, player_id, new_balance, created_at)
        ledger_id = self._insert_diamond_ledger_with(
            conn,
            player_id=player_id,
            delta=-amount,
            balance_after=new_balance,
            reason=reason,
            ref_type=ref_type,
            ref_id=ref_id,
            idempotency_key=idempotency_key,
            created_at=created_at,
        )
        return {
            "player_id": player_id,
            "delta": -amount,
            "balance": new_balance,
            "ledger_id": ledger_id,
            "duplicate": False,
        }

    # ------------------------------------------------------------------
    # Inventory and shop catalog
    # ------------------------------------------------------------------
    def get_inventory(self, player_id: str) -> dict[str, int]:
        """Return every active inventory-grant item, including zeroes.

        Embers are intentionally absent: ``ember_balance`` remains their only
        source of truth.
        """

        with self._reader() as conn:
            return self._inventory_with(conn, player_id)

    def _inventory_with(
        self, conn: sqlite3.Connection, player_id: str
    ) -> dict[str, int]:
        rows = conn.execute(
            "SELECT s.grant_item_id AS item_id, "
            "COALESCE(i.quantity, 0) AS quantity "
            "FROM shop_items s "
            "LEFT JOIN inventory_items i "
            "ON i.player_id = ? AND i.item_id = COALESCE(s.grant_item_id, s.id) "
            "WHERE s.active = 1 AND s.grant_kind = 'inventory' "
            "ORDER BY s.sort, s.id",
            (player_id,),
        ).fetchall()
        return {str(row["item_id"]): int(row["quantity"]) for row in rows}

    def get_shop_item(self, item_id: str) -> dict[str, Any] | None:
        with self._reader() as conn:
            row = conn.execute(
                "SELECT * FROM shop_items WHERE id = ? AND active = 1",
                (item_id,),
            ).fetchone()
            return _row_to_dict(row)

    def list_shop_items(self) -> list[dict[str, Any]]:
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT * FROM shop_items WHERE active = 1 "
                "ORDER BY sort, id"
            ).fetchall()
            return [dict(row) for row in rows]

    def shop_catalog(
        self,
        player_id: str,
        *,
        now: datetime | str | None = None,
    ) -> list[dict[str, Any]]:
        """Project active products with ownership, window, and availability."""

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        season_key = self._season_key(local_now)
        with self._reader() as conn:
            inventory = self._inventory_with(conn, player_id)
            ember = conn.execute(
                "SELECT balance FROM ember_balance WHERE player_id = ?",
                (player_id,),
            ).fetchone()
            ember_balance = 0 if ember is None else int(ember["balance"])
            wallet = self._wallet_row_with(conn, player_id)
            cap_level = 0 if wallet is None else int(wallet["diamond_cap_level"])
            seasonal_owned = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM player_stars "
                    "WHERE player_id = ? AND season_key = ?",
                    (player_id, season_key),
                ).fetchone()["n"]
            )
            rows = conn.execute(
                "SELECT * FROM shop_items WHERE active = 1 "
                "ORDER BY sort, id"
            ).fetchall()
            catalog: list[dict[str, Any]] = []
            for row in rows:
                item_id = str(row["id"])
                kind = self._shop_item_kind(row)
                if kind == "ember":
                    owned = ember_balance
                else:
                    grant_item_id = str(row["grant_item_id"] or item_id)
                    owned = int(inventory.get(grant_item_id, 0))
                cooldown_until = self._cooldown_until_with(
                    conn, player_id, item_id, row, local_now
                )
                available = cooldown_until is None
                entry: dict[str, Any] = {
                    "id": item_id,
                    "name": str(row["name"]),
                    "description": str(row["description"]),
                    "price_diamonds": int(row["price_diamonds"]),
                    "currency": "diamonds",
                    "kind": kind,
                    "owned_quantity": owned,
                    "cooldown_seconds": int(row["cooldown_seconds"]),
                    "cooldown_until": cooldown_until,
                    "available": available,
                }
                if kind in {"star", "seasonal_star"}:
                    entry["gacha"] = True
                    entry["rates"] = dict(RARITY_WEIGHTS)
                    entry["types"] = list(STAR_TYPES)
                if kind == "seasonal_star":
                    entry["season_key"] = season_key
                    entry["available"] = available and seasonal_owned == 0
                catalog.append(entry)

            if cap_level < DIAMOND_CAP_MAX_LEVEL:
                upgrade = conn.execute(
                    "SELECT * FROM shop_cap_upgrades WHERE level = ?",
                    (cap_level + 1,),
                ).fetchone()
                if upgrade is not None:
                    level = int(upgrade["level"])
                    price = int(upgrade["price_diamonds"])
                    delta = int(upgrade["cap_delta"])
                    catalog.append(
                        {
                            "id": f"{CAP_ITEM_PREFIX}{level}",
                            "name": f"仓库上限 {level} 级",
                            "description": (
                                f"仓库上限 +{delta}；"
                                f"购买后进入 {level} 级。"
                            ),
                            "price_diamonds": price,
                            "currency": "diamonds",
                            "kind": "cap",
                            "required_cap_level": level - 1,
                            "owned_quantity": cap_level,
                            "cooldown_seconds": 0,
                            "cooldown_until": None,
                            "available": True,
                        }
                    )
            catalog.extend(
                self._boost_catalog_with(conn, player_id, local_now)
            )
            return catalog

    @staticmethod
    def _season_key(now: datetime) -> str:
        return now.strftime("%Y-%m")

    @staticmethod
    def _shop_item_kind(item: sqlite3.Row) -> str:
        try:
            kind = str(item["kind"] or "")
        except (IndexError, KeyError):
            kind = ""
        if kind:
            return kind
        item_id = str(item["id"])
        if item_id == STAR_ITEM_ID:
            return "star"
        if item_id == SEASONAL_STAR_ITEM_ID:
            return "seasonal_star"
        if item_id == EMBER_ITEM_ID:
            return "ember"
        return str(item["grant_kind"])

    @staticmethod
    def _cooldown_until_with(
        conn: sqlite3.Connection,
        player_id: str,
        item_id: str,
        item: sqlite3.Row,
        now: datetime,
    ) -> str | None:
        cooldown_seconds = int(item["cooldown_seconds"])
        if cooldown_seconds <= 0:
            return None
        row = conn.execute(
            "SELECT last_purchased_at FROM shop_purchase_cooldowns "
            "WHERE player_id = ? AND item_id = ?",
            (player_id, item_id),
        ).fetchone()
        if row is None:
            return None
        last = cal.parse_datetime(row["last_purchased_at"])
        until = last + timedelta(seconds=cooldown_seconds)
        if until <= now:
            return None
        return cal.iso_ts(until)

    # ------------------------------------------------------------------
    # Named stars
    # ------------------------------------------------------------------
    def list_player_stars(self, player_id: str) -> list[dict[str, Any]]:
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT * FROM player_stars WHERE player_id = ? "
                "ORDER BY acquired_at, rowid",
                (player_id,),
            ).fetchall()
            return [self._star_payload(row) for row in rows]

    def get_player_star(
        self, player_id: str, star_id: str
    ) -> dict[str, Any] | None:
        """Return one star only when it belongs to ``player_id``."""

        with self._reader() as conn:
            row = conn.execute(
                "SELECT * FROM player_stars "
                "WHERE id = ? AND player_id = ?",
                (star_id, player_id),
            ).fetchone()
            return None if row is None else self._star_payload(row)

    @staticmethod
    def _star_payload(row: Any) -> dict[str, Any]:
        records = dict(row)
        star_id = str(records["id"])
        star_type = str(records.get("star_type") or "")
        rarity = str(records.get("rarity") or "")
        palette = parse_palette_json(
            records.get("palette_json") or records.get("palette"), star_type
        )
        try:
            visual_seed = int(records.get("visual_seed") or 0)
        except (TypeError, ValueError):
            visual_seed = 0
        try:
            companion_count = int(records.get("companion_count") or 0)
        except (TypeError, ValueError):
            companion_count = 0
        return {
            "id": star_id,
            "name": str(records["name"]),
            "kind": str(records["kind"]),
            "season_key": records.get("season_key"),
            "star_type": star_type,
            "type_label": TYPE_LABELS.get(star_type, star_type),
            "rarity": rarity,
            "rarity_label": RARITY_LABELS.get(rarity, rarity),
            "palette": palette,
            "visual_seed": visual_seed,
            "companion_count": companion_count,
            "catalog_code": str(records.get("catalog_code") or ""),
            "acquired_at": str(records["acquired_at"]),
            "svg_url": f"/v1/me/stars/{star_id}/svg",
        }

    @staticmethod
    def _validate_star_name(name: str | None) -> str:
        return validate_star_name(name)

    @staticmethod
    def roll_star_rarity() -> str:
        return roll_star_rarity()

    @staticmethod
    def roll_star_type(rarity: str) -> str:
        return roll_star_type(rarity)

    @staticmethod
    def make_star_visual(
        self,
        star_type: str,
        rarity: str,
        season_key: str | None = None,
    ) -> dict[str, Any]:
        return make_star_visual(star_type, rarity, season_key)

    @staticmethod
    def generate_star_name() -> str:
        return generate_star_name()

    # ------------------------------------------------------------------
    # Purchase
    # ------------------------------------------------------------------
    def purchase_shop_item(
        self,
        player_id: str,
        item_id: str,
        quantity: int = 1,
        request_id: str | None = None,
        *,
        name: str | None = None,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Buy one shop item atomically, replaying the same request id.

        ``request_id`` is required by the HTTP API; the store keeps it optional
        only for direct local calls, which then generate one.
        """

        if not isinstance(item_id, str) or not item_id.strip():
            raise UnknownShopItem("unknown shop item")
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise ShopQuantityRejected(
                "invalid_quantity", "quantity must be a positive integer"
            )
        if quantity <= 0:
            raise ShopQuantityRejected(
                "invalid_quantity", "quantity must be a positive integer"
            )
        if request_id is not None and not str(request_id).strip():
            raise ValueError("request_id must be non-empty")
        if (
            item_id
            in {
                STAR_ITEM_ID,
                SEASONAL_STAR_ITEM_ID,
                EMBER_ITEM_ID,
            }
            or item_id.startswith(CAP_ITEM_PREFIX)
            or self._is_boost_item(item_id)
        ) and quantity != SINGLE_PURCHASE_QUANTITY:
            raise ShopQuantityRejected(
                "quantity_must_be_one",
                f"{item_id} can only be bought one at a time",
            )
        normalized_name = None
        if item_id in {STAR_ITEM_ID, SEASONAL_STAR_ITEM_ID}:
            normalized_name = (
                generate_star_name()
                if name is None
                else self._validate_star_name(name)
            )
        key = str(request_id) if request_id is not None else uuid.uuid4().hex
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        created_at = cal.iso_ts(local_now)
        season_key = self._season_key(local_now)

        with self.transaction() as conn:
            prior = conn.execute(
                "SELECT * FROM shop_purchase_requests "
                "WHERE player_id = ? AND request_id = ?",
                (player_id, key),
            ).fetchone()
            if prior is not None:
                if (
                    str(prior["item_id"]) != item_id
                    or int(prior["quantity"]) != quantity
                ):
                    raise DuplicateIdempotencyKey(
                        "request_id already used for a different purchase"
                    )
                payload = json.loads(str(prior["result_json"]))
                payload["replayed"] = True
                return payload

            self._ensure_diamond_owner_with(conn, player_id)

            if self._is_boost_item(item_id):
                return self._purchase_diamond_boost_with(
                    conn,
                    player_id=player_id,
                    item_id=item_id,
                    quantity=quantity,
                    request_id=key,
                    now=local_now,
                    created_at=created_at,
                )

            upgrade = self._cap_upgrade_with(conn, item_id)
            if upgrade is not None:
                return self._purchase_cap_upgrade_with(
                    conn,
                    player_id=player_id,
                    item_id=item_id,
                    quantity=quantity,
                    upgrade=upgrade,
                    request_id=key,
                    now=local_now,
                    created_at=created_at,
                )

            item = conn.execute(
                "SELECT * FROM shop_items WHERE id = ? AND active = 1",
                (item_id,),
            ).fetchone()
            if item is None:
                raise UnknownShopItem("unknown shop item")

            kind = self._shop_item_kind(item)
            self._validate_purchase_quantity(item, quantity)

            if kind == "seasonal_star":
                existing = conn.execute(
                    "SELECT 1 FROM player_stars "
                    "WHERE player_id = ? AND season_key = ?",
                    (player_id, season_key),
                ).fetchone()
                if existing is not None:
                    raise ShopNotAvailable(
                        "seasonal_star_owned",
                        "seasonal star already owned for this month",
                        season_key=season_key,
                    )

            cooldown_until = self._cooldown_until_with(
                conn, player_id, item_id, item, local_now
            )
            if cooldown_until is not None:
                raise ShopCooldown(cooldown_until)

            star_visual: dict[str, Any] | None = None
            star_type: str | None = None
            rarity: str | None = None
            if kind in {"star", "seasonal_star"}:
                rarity = roll_star_rarity()
                star_type = roll_star_type(rarity)
                star_visual = make_star_visual(
                    star_type,
                    rarity,
                    season_key if kind == "seasonal_star" else None,
                )

            price = int(item["price_diamonds"])
            total_price = price * quantity
            self._debit_diamonds_with(
                conn,
                player_id=player_id,
                amount=total_price,
                reason="shop_purchase",
                ref_type="shop_item",
                ref_id=item_id,
                idempotency_key=key,
                now=local_now,
                create_for_unknown=True,
            )

            star: dict[str, Any] | None = None
            if kind in {"star", "seasonal_star"}:
                assert normalized_name is not None
                assert star_type is not None
                assert rarity is not None
                assert star_visual is not None
                star = self._insert_player_star_with(
                    conn,
                    player_id=player_id,
                    name=normalized_name,
                    kind="normal" if kind == "star" else "seasonal",
                    season_key=None if kind == "star" else season_key,
                    price_diamonds=price,
                    acquired_at=created_at,
                    star_type=star_type,
                    rarity=rarity,
                    palette=star_visual["palette"],
                    visual_seed=int(star_visual["visual_seed"]),
                    companion_count=int(star_visual["companion_count"]),
                    catalog_code=self._new_catalog_code_with(
                        conn, created_at
                    ),
                )
                self._grant_inventory_with(
                    conn,
                    player_id=player_id,
                    item=item,
                    quantity=SINGLE_PURCHASE_QUANTITY,
                    now=created_at,
                )
            elif str(item["grant_kind"]) == "inventory":
                self._grant_inventory_with(
                    conn,
                    player_id=player_id,
                    item=item,
                    quantity=quantity * int(item["grant_quantity"]),
                    now=created_at,
                )
            elif str(item["grant_kind"]) == "ember":
                self._grant_embers_with(
                    conn,
                    player_id=player_id,
                    item=item,
                    quantity=quantity * int(item["grant_quantity"]),
                    request_id=key,
                    now=local_now,
                )
            else:  # pragma: no cover - schema CHECK already rejects this
                raise ShopNotAllowed(f"unsupported grant kind: {item['grant_kind']}")

            if int(item["cooldown_seconds"]) > 0:
                conn.execute(
                    "INSERT INTO shop_purchase_cooldowns "
                    "(player_id, item_id, last_purchased_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(player_id, item_id) DO UPDATE SET "
                    "last_purchased_at = excluded.last_purchased_at",
                    (player_id, item_id, created_at),
                )

            wallet = self._wallet_summary(
                self._wallet_row_with(conn, player_id)
            )
            payload: dict[str, Any] = {
                "ok": True,
                "item_id": item_id,
                "quantity": quantity,
                "diamonds": wallet["balance"],
                "diamond_cap": wallet["diamond_cap"],
                "diamond_cap_level": wallet["diamond_cap_level"],
                "diamond_excess": wallet["diamond_excess"],
                "inventory": self._inventory_payload_with(conn, player_id),
                "cooldown_until": self._response_cooldown_until(item, local_now),
                "replayed": False,
            }
            if star is not None:
                payload["star"] = star
                if star["kind"] == "seasonal":
                    payload["season_key"] = star["season_key"]
            self._record_purchase_request_with(
                conn,
                player_id=player_id,
                request_id=key,
                item_id=item_id,
                quantity=quantity,
                payload=payload,
                created_at=created_at,
            )
            return payload

    def _purchase_cap_upgrade_with(
        self,
        conn: sqlite3.Connection,
        *,
        player_id: str,
        item_id: str,
        quantity: int,
        upgrade: sqlite3.Row,
        request_id: str,
        now: datetime,
        created_at: str,
    ) -> dict[str, Any]:
        if quantity != SINGLE_PURCHASE_QUANTITY:
            raise ShopQuantityRejected(
                "quantity_must_be_one", "cap upgrades can only be bought one at a time"
            )
        level = int(upgrade["level"])
        row = self._sync_diamond_decay_with(
            conn, player_id, now, create_for_unknown=True
        )
        current_level = 0 if row is None else int(row["diamond_cap_level"])
        if current_level != level - 1:
            raise ShopNotAvailable(
                "cap_unavailable",
                "cap upgrade is not the next level",
                required_cap_level=level - 1,
                current_cap_level=current_level,
            )
        price = int(upgrade["price_diamonds"])
        self._debit_diamonds_with(
            conn,
            player_id=player_id,
            amount=price,
            reason="shop_purchase",
            ref_type="shop_item",
            ref_id=item_id,
            idempotency_key=request_id,
            now=now,
            create_for_unknown=True,
        )
        current_cap = 0 if row is None else int(row["diamond_cap"])
        new_cap = current_cap + int(upgrade["cap_delta"])
        conn.execute(
            "UPDATE diamond_balance SET diamond_cap = ?, diamond_cap_level = ?, "
            "last_decay_at = ?, updated_at = ? WHERE player_id = ?",
            (new_cap, level, created_at, created_at, player_id),
        )
        wallet = self._wallet_summary(
            self._wallet_row_with(conn, player_id)
        )
        payload: dict[str, Any] = {
            "ok": True,
            "item_id": item_id,
            "quantity": 1,
            "diamonds": wallet["balance"],
            "diamond_cap": wallet["diamond_cap"],
            "diamond_cap_level": wallet["diamond_cap_level"],
            "diamond_excess": wallet["diamond_excess"],
            "inventory": self._inventory_payload_with(conn, player_id),
            "cooldown_until": None,
            "replayed": False,
        }
        self._record_purchase_request_with(
            conn,
            player_id=player_id,
            request_id=request_id,
            item_id=item_id,
            quantity=1,
            payload=payload,
            created_at=created_at,
        )
        return payload

    @staticmethod
    def _cap_upgrade_with(
        conn: sqlite3.Connection, item_id: str
    ) -> sqlite3.Row | None:
        if not item_id.startswith(CAP_ITEM_PREFIX):
            return None
        suffix = item_id[len(CAP_ITEM_PREFIX) :]
        if not suffix.isdigit():
            return None
        return conn.execute(
            "SELECT * FROM shop_cap_upgrades WHERE level = ?",
            (int(suffix),),
        ).fetchone()

    @staticmethod
    def _validate_purchase_quantity(
        item: sqlite3.Row, quantity: int
    ) -> None:
        kind = ShopMixin._shop_item_kind(item)
        if kind in {"star", "seasonal_star", "ember", "cap"}:
            if quantity != SINGLE_PURCHASE_QUANTITY:
                raise ShopQuantityRejected(
                    "quantity_must_be_one",
                    f"{kind} can only be bought one at a time",
                )

    @staticmethod
    def _response_cooldown_until(
        item: sqlite3.Row, now: datetime
    ) -> str | None:
        cooldown_seconds = int(item["cooldown_seconds"])
        if cooldown_seconds <= 0:
            return None
        return cal.iso_ts(now + timedelta(seconds=cooldown_seconds))

    @staticmethod
    def _ember_balance_with(
        conn: sqlite3.Connection, player_id: str
    ) -> int:
        row = conn.execute(
            "SELECT balance FROM ember_balance WHERE player_id = ?",
            (player_id,),
        ).fetchone()
        return 0 if row is None else int(row["balance"])

    def _inventory_payload_with(
        self, conn: sqlite3.Connection, player_id: str
    ) -> dict[str, int]:
        inventory = self._inventory_with(conn, player_id)
        inventory["ember"] = self._ember_balance_with(conn, player_id)
        return inventory

    @staticmethod
    def _insert_player_star_with(
        conn: sqlite3.Connection,
        *,
        player_id: str,
        name: str,
        kind: str,
        season_key: str | None,
        price_diamonds: int,
        acquired_at: str,
        star_type: str,
        rarity: str,
        palette: list[str],
        visual_seed: int,
        companion_count: int,
        catalog_code: str,
    ) -> dict[str, Any]:
        star = {
            "id": uuid.uuid4().hex,
            "name": name,
            "kind": kind,
            "season_key": season_key,
            "star_type": star_type,
            "rarity": rarity,
            "palette": list(palette),
            "visual_seed": int(visual_seed),
            "companion_count": int(companion_count),
            "catalog_code": catalog_code,
            "acquired_at": acquired_at,
        }
        conn.execute(
            "INSERT INTO player_stars "
            "(id, player_id, name, kind, season_key, price_diamonds, "
            "acquired_at, source, star_type, rarity, palette_json, "
            "visual_seed, companion_count, catalog_code) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'shop', ?, ?, ?, ?, ?, ?)",
            (
                star["id"],
                player_id,
                name,
                kind,
                season_key,
                price_diamonds,
                acquired_at,
                star_type,
                rarity,
                json.dumps(list(palette), ensure_ascii=False),
                int(visual_seed),
                int(companion_count),
                catalog_code,
            ),
        )
        return ShopMixin._star_payload(star)

    @staticmethod
    def _new_catalog_code_with(
        conn: sqlite3.Connection, acquired_at: str
    ) -> str:
        year = str(acquired_at)[:4] if str(acquired_at)[:4].isdigit() else "2026"
        for _ in range(64):
            code = f"GL-{year}-{secrets.token_hex(4).upper()}"
            exists = conn.execute(
                "SELECT 1 FROM player_stars WHERE catalog_code = ?",
                (code,),
            ).fetchone()
            if exists is None:
                return code
        raise RuntimeError("could not allocate a unique star catalog code")

    @staticmethod
    def _record_purchase_request_with(
        conn: sqlite3.Connection,
        *,
        player_id: str,
        request_id: str,
        item_id: str,
        quantity: int,
        payload: dict[str, Any],
        created_at: str,
    ) -> None:
        conn.execute(
            "INSERT INTO shop_purchase_requests "
            "(player_id, request_id, item_id, quantity, result_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                player_id,
                request_id,
                item_id,
                quantity,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                created_at,
            ),
        )

    @staticmethod
    def _grant_inventory_with(
        conn: sqlite3.Connection,
        *,
        player_id: str,
        item: sqlite3.Row,
        quantity: int,
        now: str,
    ) -> None:
        grant_item_id = str(item["grant_item_id"] or item["id"])
        conn.execute(
            "INSERT INTO inventory_items "
            "(player_id, item_id, quantity, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(player_id, item_id) DO UPDATE SET "
            "quantity = inventory_items.quantity + excluded.quantity, "
            "updated_at = excluded.updated_at",
            (player_id, grant_item_id, quantity, now),
        )

    def _grant_embers_with(
        self,
        conn: sqlite3.Connection,
        *,
        player_id: str,
        item: sqlite3.Row,
        quantity: int,
        request_id: str,
        now: datetime,
    ) -> None:
        week_iso = cal.iso_date(cal.week_start(now))
        balance = self._ember_balance_with(conn, player_id) + quantity
        conn.execute(
            "INSERT INTO ember_balance "
            "(player_id, balance, week_earned, week_start, updated_at) "
            "VALUES (?, ?, 0, ?, ?) ON CONFLICT(player_id) DO UPDATE SET "
            "balance = excluded.balance, updated_at = excluded.updated_at",
            (player_id, balance, week_iso, cal.iso_ts(now)),
        )
        conn.execute(
            "INSERT INTO ember_ledger "
            "(player_id, week_start, delta, balance_after, reason, ref, "
            "idempotency_key, created_at) VALUES (?, ?, ?, ?, "
            "'shop_purchase', ?, ?, ?)",
            (
                player_id,
                week_iso,
                quantity,
                balance,
                str(item["id"]),
                f"shop-ember:{request_id}",
                cal.iso_ts(now),
            ),
        )
