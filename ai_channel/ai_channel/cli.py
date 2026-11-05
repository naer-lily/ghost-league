"""CLI for the account-backed AI channel.

Commands only use Ghost's public HTTP API.  Tokens live in the local state DB
and are never printed by ``list``, ``provision`` or ``tick``.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from typing import Any, Callable, Sequence

from . import __version__
from .client import AIClient, AIChannelHTTPError, AIChannelTransportError
from .config import ChannelConfig, load_config
from .policy import choose_star, parse_at, star_request_id, xp_event_id
from .store import StateStore

Output = Callable[[str], None]


def _valid_prefix(prefix: str) -> str:
    if not isinstance(prefix, str) or not prefix:
        raise ValueError("prefix must be a non-empty string")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", prefix) is None:
        raise ValueError(
            "prefix may contain letters, digits, dot, underscore and dash"
        )
    return prefix


def next_user_ids(
    existing_ids: Sequence[str], *, prefix: str, count: int
) -> list[str]:
    """Return the next ``prefix0001`` style ids without colliding locally."""

    _valid_prefix(prefix)
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise ValueError("count must be a positive integer")
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    highest = 0
    for user_id in existing_ids:
        match = pattern.fullmatch(str(user_id))
        if match is not None:
            highest = max(highest, int(match.group(1)))
    return [f"{prefix}{number:04d}" for number in range(highest + 1, highest + count + 1)]


def provision_accounts(
    client: AIClient,
    store: StateStore,
    *,
    count: int,
    prefix: str,
    out: Output = print,
) -> list[str]:
    """Provision ordinary accounts and persist their tokens locally."""

    existing = store.list_accounts()
    user_ids = next_user_ids(
        [str(account["user_id"]) for account in existing],
        prefix=prefix,
        count=count,
    )
    created: list[str] = []
    for user_id in user_ids:
        display_name = f"Sim {user_id[len(prefix):]}"
        response = client.provision_account(user_id, display_name)
        token = response.get("token") if isinstance(response, dict) else None
        if not isinstance(token, str) or not token:
            raise ValueError(f"provisioning {user_id} returned no token")
        account = response.get("account")
        if isinstance(account, dict) and isinstance(account.get("display_name"), str):
            display_name = account["display_name"]
        store.save_account(user_id, display_name, token)
        created.append(user_id)
    out(
        f"provisioned {len(created)} account(s): "
        + ", ".join(created)
    )
    return created


def list_accounts(store: StateStore, *, out: Output = print) -> list[dict[str, Any]]:
    """Print account ids and names only; tokens never leave the store silently."""

    accounts = store.list_accounts()
    out("user_id\tdisplay_name")
    for account in accounts:
        out(f"{account['user_id']}\t{account['display_name']}")
    return accounts


def tick(
    client: AIClient,
    store: StateStore,
    *,
    seconds: int,
    buy_stars: bool = False,
    at: datetime | str | None = None,
    out: Output = print,
) -> dict[str, Any]:
    """Send one hourly increment per account, then optionally buy a star."""

    if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0:
        raise ValueError("seconds must be a positive integer")
    moment = parse_at(at)
    accounts = store.list_accounts(include_tokens=True)
    summary: dict[str, Any] = {
        "at": moment.isoformat(),
        "accounts": len(accounts),
        "increments": 0,
        "duplicates": 0,
        "purchases": 0,
        "errors": 0,
        "results": [],
    }
    for account in accounts:
        user_id = str(account["user_id"])
        token = account.get("token")
        event_id = xp_event_id(user_id, moment)
        result: dict[str, Any] = {"user_id": user_id, "event_id": event_id}
        if not isinstance(token, str) or not token:
            summary["errors"] += 1
            result["error"] = "missing local token"
            out(f"{user_id}\tincrement\t{event_id}\terror\tmissing local token")
            summary["results"].append(result)
            continue
        try:
            increment = client.send_increment(
                token, event_id, seconds, moment.isoformat()
            )
        except (AIChannelHTTPError, AIChannelTransportError, ValueError, TypeError) as exc:
            summary["errors"] += 1
            result["error"] = str(exc)
            out(f"{user_id}\tincrement\t{event_id}\terror\t{exc}")
            summary["results"].append(result)
            continue

        summary["increments"] += 1
        duplicate = bool(increment.get("duplicate"))
        if duplicate:
            summary["duplicates"] += 1
        result["increment"] = increment
        store.record_run(user_id, event_id, seconds, moment.isoformat())
        out(
            f"{user_id}\tincrement\t{event_id}\t"
            f"{'duplicate' if duplicate else 'accepted'}\t"
            f"week_xp={increment.get('week_xp')}"
        )

        if buy_stars:
            try:
                status = client.get_status(token)
                shop = client.get_shop(token)
                item = choose_star(shop, status.get("diamonds"))
                if item is None:
                    result["star"] = None
                    out(f"{user_id}\tstar\tnone")
                else:
                    item_id = str(item["id"])
                    request_id = star_request_id(user_id, item_id, moment)
                    purchase = client.purchase(token, item_id, request_id)
                    summary["purchases"] += 1
                    result["star"] = {
                        "item_id": item_id,
                        "request_id": request_id,
                        "purchase": purchase,
                    }
                    out(
                        f"{user_id}\tstar\t{item_id}\tpurchased\t"
                        f"diamonds={purchase.get('diamonds')}"
                    )
            except (
                AIChannelHTTPError,
                AIChannelTransportError,
                ValueError,
                TypeError,
                KeyError,
            ) as exc:
                summary["errors"] += 1
                result["star_error"] = str(exc)
                out(f"{user_id}\tstar\terror\t{exc}")
        summary["results"].append(result)

    out(
        "summary: "
        f"accounts={summary['accounts']} increments={summary['increments']} "
        f"duplicates={summary['duplicates']} purchases={summary['purchases']} "
        f"errors={summary['errors']}"
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ai_channel")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    provision = subparsers.add_parser(
        "provision", help="create ordinary accounts and store their tokens"
    )
    provision.add_argument("--config", default="config.json")
    provision.add_argument("--count", type=int, default=3)
    provision.add_argument("--prefix", default="sim-")

    listing = subparsers.add_parser("list", help="list account ids and names")
    listing.add_argument("--config", default="config.json")

    tick_parser = subparsers.add_parser(
        "tick", help="send one increment per account and optionally buy a star"
    )
    tick_parser.add_argument("--config", default="config.json")
    tick_parser.add_argument(
        "--seconds",
        type=int,
        default=None,
        help="increment seconds (default: config default_seconds)",
    )
    tick_parser.add_argument("--buy-stars", action="store_true")
    tick_parser.add_argument(
        "--at",
        default=None,
        help="ISO-8601 simulation time (default: now)",
    )
    return parser


def _client(config: ChannelConfig) -> AIClient:
    return AIClient(
        config.base_url,
        provisioning_token=config.provisioning_token,
        timeout=config.request_timeout_seconds,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        store = StateStore(config.state_db)
        store.initialize()
        client = _client(config)
        if args.command == "provision":
            provision_accounts(
                client,
                store,
                count=args.count,
                prefix=args.prefix,
            )
        elif args.command == "list":
            list_accounts(store)
        elif args.command == "tick":
            seconds = (
                config.default_seconds if args.seconds is None else args.seconds
            )
            summary = tick(
                client,
                store,
                seconds=seconds,
                buy_stars=bool(args.buy_stars),
                at=args.at,
            )
            if summary["errors"]:
                return 1
        else:  # pragma: no cover - argparse enforces the choices
            raise ValueError(f"unknown command {args.command}")
    except (
        AIChannelHTTPError,
        AIChannelTransportError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"ai-channel: error: {exc}", file=sys.stderr)
        return 1
    return 0


__all__ = [
    "build_parser",
    "list_accounts",
    "main",
    "next_user_ids",
    "provision_accounts",
    "tick",
]
