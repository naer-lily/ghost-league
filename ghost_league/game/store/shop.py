"""Diamond wallet, generic inventory, and the backend shop.

Every purchase runs inside one ``BEGIN IMMEDIATE`` transaction so a failed
grant, cooldown write, or request record can never leave diamonds deducted
without the item.  Request ids are unique per player and the diamond ledger is
the final guard against paying twice.
"""

from __future__ import annotations

import json
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
    ShopQuantityRejected,
    UnknownShopItem,
)
from .core import _row_to_dict

STAR_ITEM_ID = "star"
EMBER_ITEM_ID = "ember"
STAR_MAX_QUANTITY = 99
EMBER_PURCHASE_QUANTITY = 1


class ShopMixin:
    """Diamond wallets, inventory quantities, and shop purchases."""

    # ------------------------------------------------------------------
    # Diamond wallet and ledger
    # ------------------------------------------------------------------
    def get_diamond_balance(self, player_id: str) -> int:
        """Return the wallet balance; a missing wallet simply means zero."""

        with self._reader() as conn:
            row = conn.execute(
                "SELECT balance FROM diamond_balance WHERE player_id = ?",
                (player_id,),
            ).fetchone()
            return 0 if row is None else int(row["balance"])

    def diamond_ledger(self, player_id: str) -> list[dict[str, Any]]:
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT * FROM diamond_ledger WHERE player_id = ? ORDER BY id",
                (player_id,),
            ).fetchall()
            return [dict(row) for row in rows]

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
        """Internal/local-test entry point for future reward grants.

        The same idempotency key never credits twice.  A caller that omits the
        key gets a random one, so a repeated call is a new grant by design.
        """

        self._validate_diamond_amount(amount)
        self._validate_reason(reason)
        if idempotency_key is not None and not str(idempotency_key).strip():
            raise ValueError("idempotency_key must be non-empty")
        key = idempotency_key or f"diamond-credit:{uuid.uuid4().hex}"
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        created_at = cal.iso_ts(local_now)

        with self.transaction() as conn:
            self._ensure_diamond_owner_with(conn, player_id)
            prior = self._ledger_by_key_with(conn, key)
            if prior is not None:
                self._require_same_ledger(
                    prior,
                    player_id=player_id,
                    delta=int(amount),
                    reason=reason,
                    ref_type=ref_type,
                    ref_id=ref_id,
                )
                return self._ledger_result(prior, duplicate=True)

            balance = self._diamond_balance_with(conn, player_id)
            new_balance = balance + int(amount)
            self._set_diamond_balance_with(
                conn, player_id, new_balance, created_at
            )
            ledger_id = self._insert_diamond_ledger_with(
                conn,
                player_id=player_id,
                delta=int(amount),
                balance_after=new_balance,
                reason=reason,
                ref_type=ref_type,
                ref_id=ref_id,
                idempotency_key=key,
                created_at=created_at,
            )
            return {
                "player_id": player_id,
                "delta": int(amount),
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
        delta: int,
        reason: str,
        ref_type: str | None,
        ref_id: str | None,
    ) -> None:
        same = (
            str(prior["player_id"]) == player_id
            and int(prior["delta"]) == delta
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

        balance = self._diamond_balance_with(conn, player_id)
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
        """Project active products with ownership, cooldown, and availability."""

        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        with self._reader() as conn:
            inventory = self._inventory_with(conn, player_id)
            ember = conn.execute(
                "SELECT balance FROM ember_balance WHERE player_id = ?",
                (player_id,),
            ).fetchone()
            ember_balance = 0 if ember is None else int(ember["balance"])
            rows = conn.execute(
                "SELECT * FROM shop_items WHERE active = 1 "
                "ORDER BY sort, id"
            ).fetchall()
            catalog: list[dict[str, Any]] = []
            for row in rows:
                item_id = str(row["id"])
                if str(row["grant_kind"]) == "ember":
                    owned = ember_balance
                else:
                    grant_item_id = str(row["grant_item_id"] or item_id)
                    owned = int(inventory.get(grant_item_id, 0))
                cooldown_until = self._cooldown_until_with(
                    conn, player_id, item_id, row, local_now
                )
                catalog.append(
                    {
                        "id": item_id,
                        "name": str(row["name"]),
                        "description": str(row["description"]),
                        "price_diamonds": int(row["price_diamonds"]),
                        "currency": "diamonds",
                        "owned_quantity": owned,
                        "cooldown_seconds": int(row["cooldown_seconds"]),
                        "cooldown_until": cooldown_until,
                        "available": cooldown_until is None,
                    }
                )
            return catalog

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
    # Purchase
    # ------------------------------------------------------------------
    def purchase_shop_item(
        self,
        player_id: str,
        item_id: str,
        quantity: int = 1,
        request_id: str | None = None,
        *,
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
        key = str(request_id) if request_id is not None else uuid.uuid4().hex
        local_now = cal.parse_datetime(now) if now is not None else cal.now_local()
        created_at = cal.iso_ts(local_now)

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

            item = conn.execute(
                "SELECT * FROM shop_items WHERE id = ? AND active = 1",
                (item_id,),
            ).fetchone()
            if item is None:
                raise UnknownShopItem("unknown shop item")

            self._validate_purchase_quantity(item, quantity)
            price = int(item["price_diamonds"])
            grant_quantity = int(item["grant_quantity"])
            total_price = price * quantity

            cooldown_until = self._cooldown_until_with(
                conn, player_id, item_id, item, local_now
            )
            if cooldown_until is not None:
                raise ShopCooldown(cooldown_until)

            self._debit_diamonds_with(
                conn,
                player_id=player_id,
                amount=total_price,
                reason="shop_purchase",
                ref_type="shop_item",
                ref_id=item_id,
                idempotency_key=key,
                now=local_now,
            )

            grant_kind = str(item["grant_kind"])
            if grant_kind == "inventory":
                self._grant_inventory_with(
                    conn,
                    player_id=player_id,
                    item=item,
                    quantity=quantity * grant_quantity,
                    now=created_at,
                )
            elif grant_kind == "ember":
                self._grant_embers_with(
                    conn,
                    player_id=player_id,
                    item=item,
                    quantity=quantity * grant_quantity,
                    request_id=key,
                    now=local_now,
                )
            else:  # pragma: no cover - schema CHECK already rejects this
                raise ShopNotAllowed(f"unsupported grant kind: {grant_kind}")

            if int(item["cooldown_seconds"]) > 0:
                conn.execute(
                    "INSERT INTO shop_purchase_cooldowns "
                    "(player_id, item_id, last_purchased_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(player_id, item_id) DO UPDATE SET "
                    "last_purchased_at = excluded.last_purchased_at",
                    (player_id, item_id, created_at),
                )

            inventory = self._inventory_with(conn, player_id)
            inventory["ember"] = self._ember_balance_with(conn, player_id)
            payload = {
                "ok": True,
                "item_id": item_id,
                "quantity": quantity,
                "diamonds": self._diamond_balance_with(conn, player_id),
                "inventory": inventory,
                "cooldown_until": self._response_cooldown_until(item, local_now),
                "replayed": False,
            }
            conn.execute(
                "INSERT INTO shop_purchase_requests "
                "(player_id, request_id, item_id, quantity, result_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    player_id,
                    key,
                    item_id,
                    quantity,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    created_at,
                ),
            )
            return payload

    @staticmethod
    def _validate_purchase_quantity(
        item: sqlite3.Row, quantity: int
    ) -> None:
        item_id = str(item["id"])
        if item_id == STAR_ITEM_ID:
            if quantity > STAR_MAX_QUANTITY:
                raise ShopQuantityRejected(
                    "quantity_too_large",
                    f"star can be bought at most {STAR_MAX_QUANTITY} at a time",
                )
            return
        if item_id == EMBER_ITEM_ID and quantity != EMBER_PURCHASE_QUANTITY:
            raise ShopQuantityRejected(
                "ember_quantity",
                "ember can only be bought one at a time",
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
