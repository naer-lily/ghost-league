from __future__ import annotations

import json
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

import scripts.source_fetch as source_fetch
from ghost_league.fetch import fetch_leaderboard, write_cache

FETCHED_AT = datetime(2026, 10, 27, 12, 34, 56, tzinfo=timezone.utc)
WEEK_START = "2026-10-19T00:00:00Z"


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class FakeOpener:
    def __init__(
        self,
        pages: dict[int, dict[str, Any]],
        *,
        fail_pages: set[int] | None = None,
    ) -> None:
        self.pages = pages
        self.fail_pages = fail_pages or set()
        self.urls: list[str] = []

    def __call__(self, request: Any, timeout: float | None = None) -> FakeResponse:
        url = getattr(request, "full_url", str(request))
        self.urls.append(url)
        page = int(parse_qs(urlparse(url).query)["page"][0])
        if page in self.fail_pages:
            raise urllib.error.URLError(f"fake page {page} failure")
        return FakeResponse(self.pages[page])


def entry(user_id: str, seconds: int, rank: int = 1) -> dict[str, Any]:
    return {
        "rank": rank,
        "user": {
            "id": user_id,
            "display_name": f"Display {user_id}",
            "photo": f"https://example.invalid/{user_id}.png",
            "photo_public": True,
            "city": "Not Retained",
        },
        "running_total": {"total_seconds": seconds},
    }


def page(
    entries: list[dict[str, Any]],
    *,
    page_number: int = 1,
    total_pages: int = 3,
    start: str = WEEK_START,
) -> dict[str, Any]:
    return {
        "data": entries,
        "page": page_number,
        "total_pages": total_pages,
        "range": {"start": start},
    }


def page_entries(prefix: str, count: int, *, offset: int = 0) -> list[dict[str, Any]]:
    return [
        entry(f"{prefix}-{index}", 10_000 - (offset + index) * 10, offset + index + 1)
        for index in range(count)
    ]


def test_fetches_all_pages_renumbers_ranks_and_rate_limits() -> None:
    pages = {
        1: page(page_entries("p1", 4), page_number=1, total_pages=3),
        2: page(page_entries("p2", 4, offset=4), page_number=2, total_pages=3),
        3: page(page_entries("p3", 4, offset=8), page_number=3, total_pages=3),
    }
    opener = FakeOpener(pages)
    sleeps: list[float] = []

    data = fetch_leaderboard(
        country="CN",
        page_size=4,
        min_interval=0.5,
        sleep=sleeps.append,
        opener=opener,
        now=FETCHED_AT,
    )

    assert data["source"] == "wakatime_public_leaderboard"
    assert data["source_week_start"] == "2026-10-19"
    assert data["fetched_at"] == "2026-10-27T12:34:56Z"
    assert data["pages"] == 3
    assert data["row_count"] == 12
    assert data["page_size"] == 4
    assert len(data["users"]) == 12
    assert [row["rank"] for row in data["users"]] == list(range(1, 13))
    assert [row["id"] for row in data["users"]] == [
        *(f"p1-{index}" for index in range(4)),
        *(f"p2-{index}" for index in range(4)),
        *(f"p3-{index}" for index in range(4)),
    ]
    assert all(
        set(row) == {"id", "rank", "seconds", "name", "avatar_url"}
        for row in data["users"]
    )
    assert all(row["name"] == f"Display {row['id']}" for row in data["users"])
    assert all(
        row["avatar_url"] == f"https://example.invalid/{row['id']}.png"
        for row in data["users"]
    )
    assert sleeps == [0.5, 0.5]

    assert len(opener.urls) == 3
    for expected_page, url in enumerate(opener.urls, start=1):
        query = parse_qs(urlparse(url).query)
        assert query["page"] == [str(expected_page)]
        assert query["limit"] == ["4"]
        assert query["country_code"] == ["CN"]


def test_page_two_failure_leaves_old_cache_and_returns_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "cn-978.json"
    old_text = '{"old": true}\n'
    out.write_text(old_text, encoding="utf-8")
    opener = FakeOpener(
        {1: page(page_entries("p1", 4), total_pages=3)},
        fail_pages={2},
    )

    def fake_fetch(**kwargs: Any) -> dict[str, Any]:
        return fetch_leaderboard(opener=opener, sleep=lambda _: None, **kwargs)

    ticks = iter([10.0, 10.125])
    exit_code = source_fetch.main(
        ["--out", str(out), "--country", "CN", "--page-size", "4"],
        fetch_fn=fake_fetch,
        clock=lambda: next(ticks),
        now=FETCHED_AT,
    )

    assert exit_code != 0
    assert out.read_text(encoding="utf-8") == old_text
    assert list(tmp_path.glob(".cn-978.json.*.tmp")) == []
    assert "page 2" in capsys.readouterr().err


def test_empty_page_stops_and_keeps_rows_already_fetched() -> None:
    pages = {
        1: page([entry("a", 300), entry("b", 200)], page_number=1, total_pages=5),
        2: page([], page_number=2, total_pages=5),
    }
    sleeps: list[float] = []

    data = fetch_leaderboard(
        page_size=2,
        sleep=sleeps.append,
        opener=FakeOpener(pages),
        now=FETCHED_AT,
    )

    assert data["pages"] == 2
    assert data["row_count"] == 2
    assert [row["id"] for row in data["users"]] == ["a", "b"]
    assert [row["rank"] for row in data["users"]] == [1, 2]
    assert sleeps == [0.75]


def test_duplicate_ids_are_deduplicated_and_duplicate_only_page_stops() -> None:
    pages = {
        1: page([entry("a", 300), entry("b", 200)], page_number=1, total_pages=4),
        2: page([entry("b", 200), entry("c", 100)], page_number=2, total_pages=4),
        3: page([entry("c", 100), entry("b", 200)], page_number=3, total_pages=4),
        4: page([entry("d", 50)], page_number=4, total_pages=4),
    }
    sleeps: list[float] = []

    data = fetch_leaderboard(
        page_size=2,
        sleep=sleeps.append,
        opener=FakeOpener(pages),
        now=FETCHED_AT,
    )

    assert data["pages"] == 3
    assert data["row_count"] == 3
    assert [row["id"] for row in data["users"]] == ["a", "b", "c"]
    assert [row["rank"] for row in data["users"]] == [1, 2, 3]
    assert [row["seconds"] for row in data["users"]] == [300, 200, 100]
    assert sleeps == [0.75, 0.75]


def test_dry_run_does_not_write_and_prints_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "missing" / "cn-978.json"
    pages = {1: page(page_entries("only", 2), total_pages=1)}
    opener = FakeOpener(pages)

    def fake_fetch(**kwargs: Any) -> dict[str, Any]:
        return fetch_leaderboard(opener=opener, sleep=lambda _: None, **kwargs)

    ticks = iter([1.0, 1.250])
    exit_code = source_fetch.main(
        ["--out", str(out), "--page-size", "2", "--dry-run"],
        fetch_fn=fake_fetch,
        clock=lambda: next(ticks),
        now=FETCHED_AT,
    )

    assert exit_code == 0
    assert not out.exists()
    summary = json.loads(capsys.readouterr().out)
    assert set(summary) == {
        "row_count",
        "pages",
        "source_week_start",
        "fetched_at",
        "elapsed_ms",
    }
    assert summary["row_count"] == 2
    assert summary["pages"] == 1
    assert summary["source_week_start"] == "2026-10-19"
    assert summary["fetched_at"] == "2026-10-27T12:34:56Z"
    assert summary["elapsed_ms"] == 250


def test_cache_rows_keep_only_public_identity_and_display_fields() -> None:
    pages = {
        1: page(
            [
                entry("alpha", 123, rank=1),
                entry("beta", 456, rank=2),
            ],
            total_pages=1,
        )
    }

    data = fetch_leaderboard(
        page_size=2,
        sleep=lambda _: None,
        opener=FakeOpener(pages),
        now=FETCHED_AT,
    )

    assert data["users"] == [
        {
            "id": "alpha",
            "rank": 1,
            "seconds": 123,
            "name": "Display alpha",
            "avatar_url": "https://example.invalid/alpha.png",
        },
        {
            "id": "beta",
            "rank": 2,
            "seconds": 456,
            "name": "Display beta",
            "avatar_url": "https://example.invalid/beta.png",
        },
    ]
    serialized = json.dumps(data)
    assert "display_name" not in serialized
    assert "photo_public" not in serialized
    assert "city" not in serialized
    assert "Not Retained" not in serialized


def test_avatar_uses_photo_then_public_photo_endpoint_and_opt_out() -> None:
    payload = page(
        [
            {
                "user": {
                    "id": "with-photo",
                    "display_name": "With Photo",
                    "photo": "https://images.invalid/with-photo.png",
                },
                "running_total": {"total_seconds": 300},
            },
            {
                "user": {
                    "id": "no-photo",
                    "name": "No Photo",
                },
                "running_total": {"total_seconds": 200},
            },
            {
                "user": {
                    "id": "private-photo",
                    "display_name": "Private Photo",
                    "photo": "https://images.invalid/private.png",
                    "photo_public": False,
                },
                "running_total": {"total_seconds": 100},
            },
        ],
        total_pages=1,
    )

    data = fetch_leaderboard(
        page_size=3,
        sleep=lambda _: None,
        fetch_json=lambda url, timeout=None: payload,
        now=FETCHED_AT,
    )

    assert data["users"] == [
        {
            "id": "with-photo",
            "rank": 1,
            "seconds": 300,
            "name": "With Photo",
            "avatar_url": "https://images.invalid/with-photo.png",
        },
        {
            "id": "no-photo",
            "rank": 2,
            "seconds": 200,
            "name": "No Photo",
            "avatar_url": "https://wakatime.com/photo/no-photo",
        },
        {
            "id": "private-photo",
            "rank": 3,
            "seconds": 100,
            "name": "Private Photo",
            "avatar_url": None,
        },
    ]


def test_parses_range_start_and_top_level_source_week_start() -> None:
    range_payload = page(
        [entry("a", 100)],
        total_pages=1,
        start="2026-10-19T08:30:00+08:00",
    )
    from_range = fetch_leaderboard(
        page_size=1,
        sleep=lambda _: None,
        fetch_json=lambda url, timeout=None: range_payload,
        now=FETCHED_AT,
    )
    assert from_range["source_week_start"] == "2026-10-19"

    top_level_payload = {
        "source_week_start": "2026-10-12",
        "data": [entry("b", 90)],
        "page": 1,
        "total_pages": 1,
    }
    from_top_level = fetch_leaderboard(
        page_size=1,
        sleep=lambda _: None,
        fetch_json=lambda url, timeout=None: top_level_payload,
        now=FETCHED_AT,
    )
    assert from_top_level["source_week_start"] == "2026-10-12"


def test_max_pages_fails_instead_of_writing_an_incomplete_snapshot() -> None:
    pages = {
        1: page(page_entries("p1", 2), page_number=1, total_pages=3),
    }

    with pytest.raises(RuntimeError, match="maximum page count"):
        fetch_leaderboard(
            page_size=2,
            max_pages=1,
            sleep=lambda _: None,
            opener=FakeOpener(pages),
            now=FETCHED_AT,
        )


def test_write_cache_replaces_the_old_file(tmp_path: Path) -> None:
    out = tmp_path / "cache.json"
    out.write_text('{"old": true}\n', encoding="utf-8")

    write_cache({"source": "test", "users": []}, out)

    assert json.loads(out.read_text(encoding="utf-8")) == {
        "source": "test",
        "users": [],
    }
    assert list(tmp_path.glob(".cache.json.*.tmp")) == []
