"""CLI for the account-backed AI channel.

Commands only use Ghost's public HTTP API.  Tokens live in the local state DB
and are never printed by ``list``, ``provision``, ``tick`` or ``serve``.

Two tick sources exist:

- ``accounts`` (default): the existing generic per-account simulator, unchanged;
- ``waka``: read the Waka cache/projection library and send each projected
  increment through the matching ordinary account token.
"""

from __future__ import annotations

import argparse
import re
import signal
import sys
import threading
from datetime import datetime
from typing import Any, Callable, Sequence

from . import __version__
from .client import AIClient, AIChannelHTTPError, AIChannelTransportError
from .config import ChannelConfig, load_config
from .policy import choose_star, parse_at, star_request_id, xp_event_id
from .store import StateStore

Output = Callable[[str], None]

DEFAULT_SERVE_INTERVAL_SECONDS = 3600
DEFAULT_SERVE_PREFIX = "sim-"
DEFAULT_WAKA_CACHE = "data/cache/cn-978.json"
DEFAULT_WAKA_STATE = "data/cache/waka-channel-state.json"
SOURCE_ACCOUNTS = "accounts"
SOURCE_WAKA = "waka"
TICK_SOURCES = (SOURCE_ACCOUNTS, SOURCE_WAKA)
DEFAULT_TICK_SOURCE = SOURCE_ACCOUNTS


def _validate_source(source: str) -> str:
    if source not in TICK_SOURCES:
        raise ValueError(f"source must be one of {', '.join(TICK_SOURCES)}")
    return source


def _valid_prefix(prefix: str) -> str:
    if not isinstance(prefix, str) or not prefix:
        raise ValueError("prefix must be a non-empty string")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", prefix) is None:
        raise ValueError(
            "prefix may contain letters, digits, dot, underscore and dash"
        )
    return prefix


def _validate_optional_prefix(prefix: str | None) -> str | None:
    if prefix is None:
        return None
    return _valid_prefix(prefix)


def _positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


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


def list_accounts(
    store: StateStore,
    *,
    prefix: str | None = None,
    out: Output = print,
) -> list[dict[str, Any]]:
    """Print account ids and names only; tokens never leave the store silently."""

    prefix = _validate_optional_prefix(prefix)
    accounts = store.list_accounts(prefix)
    out("user_id\tdisplay_name")
    for account in accounts:
        out(f"{account['user_id']}\t{account['display_name']}")
    return accounts


def tick(
    client: AIClient,
    store: StateStore,
    *,
    seconds: int | None = None,
    buy_stars: bool = False,
    at: datetime | str | None = None,
    prefix: str | None = None,
    source: str = DEFAULT_TICK_SOURCE,
    cache: str | None = None,
    state_path: str | None = None,
    week_start: str | None = None,
    out: Output = print,
) -> dict[str, Any]:
    """Send one hourly increment per matching account, then buy stars.

    ``prefix=None`` keeps the one-shot default of every local account.  The
    resident ``serve`` command defaults to ``sim-`` instead so unrelated
    Channel tokens stored in the same local DB are never touched.

    ``source="waka"`` delegates to the Waka projection transport, which uses
    ``--cache`` / ``--state`` and ignores ``seconds`` / ``prefix`` /
    ``buy_stars``.  The generic account mode is unchanged.
    """

    source = _validate_source(source)
    if source == SOURCE_WAKA:
        from .waka import DEFAULT_CACHE, DEFAULT_STATE, waka_tick

        return waka_tick(
            client,
            store,
            at=at,
            cache=cache if cache is not None else DEFAULT_CACHE,
            state_path=state_path if state_path is not None else DEFAULT_STATE,
            week_start=week_start,
            out=out,
        )

    seconds = _positive_int("seconds", seconds)
    prefix = _validate_optional_prefix(prefix)
    moment = parse_at(at)
    accounts = store.list_accounts(prefix, include_tokens=True)
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


def _install_stop_handlers(stop_event: threading.Event) -> dict[int, Any]:
    """Turn SIGINT/SIGTERM into a flag so the wait loop can unwind cleanly."""

    previous: dict[int, Any] = {}
    if threading.current_thread() is not threading.main_thread():
        return previous

    def _stop(_signum: int, _frame: Any) -> None:
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, _stop)
        except (ValueError, OSError):  # pragma: no cover - platform dependent
            continue
    return previous


def _restore_stop_handlers(previous: dict[int, Any]) -> None:
    for signum, handler in previous.items():
        try:
            signal.signal(signum, handler)
        except (ValueError, OSError):  # pragma: no cover - platform dependent
            continue


def serve(
    client: AIClient,
    store: StateStore,
    *,
    interval: int = DEFAULT_SERVE_INTERVAL_SECONDS,
    seconds: int | None = None,
    buy_stars: bool = False,
    prefix: str | None = DEFAULT_SERVE_PREFIX,
    source: str = DEFAULT_TICK_SOURCE,
    cache: str | None = None,
    state_path: str | None = None,
    week_start: str | None = None,
    cycles: int = 0,
    at: datetime | str | None = None,
    out: Output = print,
    stop_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Run ``tick`` every ``interval`` seconds until stopped or cycles end.

    ``cycles=0`` is the resident service mode (run forever).  Bounded runs are
    for tests and manual dry runs; the last cycle never sleeps, so
    ``--cycles 1`` returns immediately.  An empty account set costs no HTTP
    request at all: ``tick`` still logs its zero summary, then the loop waits.

    ``source="waka"`` repeats the Waka projection tick; ``cache`` / ``state_path``
    select the snapshot and cursor, and ``prefix`` / ``buy_stars`` are ignored.
    """

    source = _validate_source(source)
    interval = _positive_int("interval", interval)
    waka = source == SOURCE_WAKA
    seconds = 0 if waka else _positive_int("seconds", seconds)
    if isinstance(cycles, bool) or not isinstance(cycles, int) or cycles < 0:
        raise ValueError("cycles must be a non-negative integer")
    prefix = None if waka else _validate_optional_prefix(prefix)
    moment = parse_at(at)

    event = stop_event if stop_event is not None else threading.Event()
    handlers = _install_stop_handlers(event)
    totals: dict[str, Any] = {
        "cycles": 0,
        "source": source,
        "prefix": prefix,
        "interval": interval,
        "accounts": 0,
        "events": 0,
        "increments": 0,
        "duplicates": 0,
        "purchases": 0,
        "missing_tokens": 0,
        "errors": 0,
    }
    try:
        while not event.is_set():
            if cycles and totals["cycles"] >= cycles:
                break
            summary = tick(
                client,
                store,
                seconds=seconds,
                buy_stars=buy_stars,
                at=moment,
                prefix=prefix,
                source=source,
                cache=cache,
                state_path=state_path,
                week_start=week_start,
                out=out,
            )
            totals["cycles"] += 1
            for key in (
                "accounts",
                "events",
                "increments",
                "duplicates",
                "purchases",
                "missing_tokens",
                "errors",
            ):
                totals[key] += int(summary.get(key, 0))
            if waka:
                out(
                    f"serve: cycle={totals['cycles']} source=waka "
                    f"accounts={summary['accounts']} events={summary['events']} "
                    f"sent={summary['sent']} "
                    f"missing_tokens={summary['missing_tokens']} "
                    f"errors={summary['errors']}"
                )
            else:
                out(
                    f"serve: cycle={totals['cycles']} prefix={prefix or '*'} "
                    f"accounts={summary['accounts']} increments={summary['increments']} "
                    f"purchases={summary['purchases']} errors={summary['errors']}"
                )
            if cycles and totals["cycles"] >= cycles:
                break
            if event.wait(interval):
                break
    finally:
        _restore_stop_handlers(handlers)
    if waka:
        out(
            f"serve: stopped cycles={totals['cycles']} source=waka "
            f"accounts={totals['accounts']} events={totals['events']} "
            f"sent={totals['increments']} missing_tokens={totals['missing_tokens']} "
            f"duplicates={totals['duplicates']} errors={totals['errors']}"
        )
    else:
        out(
            f"serve: stopped cycles={totals['cycles']} prefix={prefix or '*'} "
            f"accounts={totals['accounts']} increments={totals['increments']} "
            f"duplicates={totals['duplicates']} purchases={totals['purchases']} "
            f"errors={totals['errors']}"
        )
    return totals


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
    listing.add_argument(
        "--prefix",
        default=None,
        help="only show user ids with this prefix",
    )

    tick_parser = subparsers.add_parser(
        "tick", help="send one increment per account and optionally buy a star"
    )
    tick_parser.add_argument("--config", default="config.json")
    tick_parser.add_argument(
        "--source",
        choices=TICK_SOURCES,
        default=DEFAULT_TICK_SOURCE,
        help="account simulator or Waka projection transport (default: accounts)",
    )
    tick_parser.add_argument(
        "--seconds",
        type=int,
        default=None,
        help="increment seconds (default: config default_seconds)",
    )
    tick_parser.add_argument("--buy-stars", action="store_true")
    tick_parser.add_argument(
        "--prefix",
        default=None,
        help="only tick user ids with this prefix (default: all accounts)",
    )
    tick_parser.add_argument(
        "--cache",
        default=DEFAULT_WAKA_CACHE,
        help="Waka cache path for --source waka",
    )
    tick_parser.add_argument(
        "--state",
        default=DEFAULT_WAKA_STATE,
        help="Waka cursor state path for --source waka",
    )
    tick_parser.add_argument(
        "--week-start",
        default=None,
        help="optional ISO Monday for a Waka catch-up",
    )
    tick_parser.add_argument(
        "--at",
        default=None,
        help="ISO-8601 simulation time (default: now)",
    )

    serve_parser = subparsers.add_parser(
        "serve", help="run tick every interval until SIGINT/SIGTERM"
    )
    serve_parser.add_argument("--config", default="config.json")
    serve_parser.add_argument(
        "--source",
        choices=TICK_SOURCES,
        default=DEFAULT_TICK_SOURCE,
        help="account simulator or Waka projection transport (default: accounts)",
    )
    serve_parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_SERVE_INTERVAL_SECONDS,
        help="seconds between ticks (default: 3600)",
    )
    serve_parser.add_argument(
        "--seconds",
        type=int,
        default=None,
        help="increment seconds (default: config default_seconds)",
    )
    serve_parser.add_argument("--buy-stars", action="store_true")
    serve_parser.add_argument(
        "--prefix",
        default=DEFAULT_SERVE_PREFIX,
        help="only tick user ids with this prefix (default: sim-)",
    )
    serve_parser.add_argument(
        "--cache",
        default=DEFAULT_WAKA_CACHE,
        help="Waka cache path for --source waka",
    )
    serve_parser.add_argument(
        "--state",
        default=DEFAULT_WAKA_STATE,
        help="Waka cursor state path for --source waka",
    )
    serve_parser.add_argument(
        "--week-start",
        default=None,
        help="optional ISO Monday for a Waka catch-up",
    )
    serve_parser.add_argument(
        "--cycles",
        type=int,
        default=0,
        help="bounded number of ticks; 0 means forever (default: 0)",
    )
    serve_parser.add_argument(
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
            list_accounts(store, prefix=args.prefix)
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
                prefix=args.prefix,
                source=args.source,
                cache=args.cache,
                state_path=args.state,
                week_start=args.week_start,
            )
            if summary["errors"]:
                return 1
        elif args.command == "serve":
            seconds = (
                config.default_seconds if args.seconds is None else args.seconds
            )
            summary = serve(
                client,
                store,
                interval=args.interval,
                seconds=seconds,
                buy_stars=bool(args.buy_stars),
                prefix=args.prefix,
                source=args.source,
                cache=args.cache,
                state_path=args.state,
                week_start=args.week_start,
                cycles=args.cycles,
                at=args.at,
            )
            if summary["errors"]:
                return 1
        else:  # pragma: no cover - argparse enforces the choices
            raise ValueError(f"unknown command {args.command}")
    except (
        AIChannelHTTPError,
        AIChannelTransportError,
        ImportError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"ai-channel: error: {exc}", file=sys.stderr)
        return 1
    return 0


__all__ = [
    "DEFAULT_TICK_SOURCE",
    "DEFAULT_WAKA_CACHE",
    "DEFAULT_WAKA_STATE",
    "SOURCE_ACCOUNTS",
    "SOURCE_WAKA",
    "TICK_SOURCES",
    "build_parser",
    "list_accounts",
    "main",
    "next_user_ids",
    "provision_accounts",
    "serve",
    "tick",
]
