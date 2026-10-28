#!/usr/bin/env python3
"""Fetch every page of the public weekly leaderboard into the anonymous cache."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Sequence

# Running ``python scripts/source_fetch.py`` puts ``scripts/`` on sys.path, not
# the repository root.  Keep the systemd ExecStart path simple and self-contained.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ghost_league.fetch import (  # noqa: E402
    DEFAULT_MAX_PAGES,
    DEFAULT_PAGE_SIZE,
    DEFAULT_RATE_LIMIT_SECONDS,
    DEFAULT_TIMEOUT,
    fetch_leaderboard,
    write_cache,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python scripts/source_fetch.py",
        description=(
            "Fetch all pages of the WakaTime public last_7_days leaderboard "
            "and atomically write anonymous id/rank/seconds rows"
        ),
    )
    parser.add_argument(
        "--out",
        default="data/cache/cn-978.json",
        help="cache output path (default: data/cache/cn-978.json)",
    )
    parser.add_argument("--country", default=None, help="two-letter country code")
    parser.add_argument("--language", default=None, help="language filter")
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=f"rows requested per page (default: {DEFAULT_PAGE_SIZE})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"per-page request timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=f"maximum pages before failing incomplete (default: {DEFAULT_MAX_PAGES})",
    )
    parser.add_argument(
        "--min-interval",
        type=float,
        default=DEFAULT_RATE_LIMIT_SECONDS,
        help=(
            "seconds to sleep between pages "
            f"(default: {DEFAULT_RATE_LIMIT_SECONDS})"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and print the summary without writing the cache",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    fetch_fn: Callable[..., dict[str, Any]] | None = None,
    write_fn: Callable[[dict[str, Any], str | Path], Path] | None = None,
    clock: Callable[[], float] | None = None,
    now: Any = None,
) -> int:
    args = build_parser().parse_args(argv)
    fetch = fetch_fn or fetch_leaderboard
    write = write_fn or write_cache
    timer = clock or time.perf_counter
    started = timer()

    fetch_kwargs: dict[str, Any] = {
        "country": args.country,
        "language": args.language,
        "page_size": args.page_size,
        "timeout": args.timeout,
        "max_pages": args.max_pages,
        "min_interval": args.min_interval,
    }
    if now is not None:
        fetch_kwargs["now"] = now

    try:
        data = fetch(**fetch_kwargs)
        if not args.dry_run:
            write(data, args.out)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"source-fetch: error: {exc}", file=sys.stderr)
        return 1

    elapsed_ms = int(round((timer() - started) * 1000))
    summary = {
        "row_count": int(data["row_count"]),
        "pages": int(data["pages"]),
        "source_week_start": data["source_week_start"],
        "fetched_at": data["fetched_at"],
        "elapsed_ms": elapsed_ms,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
