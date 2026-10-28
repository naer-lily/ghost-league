from __future__ import annotations

import ast
import json
import math
from pathlib import Path

import pytest

from ghost_league.source.normalize import (
    NORMALIZATION_VERSION,
    normalize_seconds,
)

REAL_CACHE = Path("data/cache/cn-978.json")


def test_empty_snapshot_is_valid_and_deterministic() -> None:
    assert normalize_seconds([]) == {
        "raw_seconds": [],
        "effective_seconds": [],
        "p75_seconds": 0,
        "version": "p75-soft-0.2-v1",
    }
    assert normalize_seconds(()) == normalize_seconds([])


def test_single_row_is_unchanged() -> None:
    result = normalize_seconds([12_345])
    assert result["p75_seconds"] == 12_345
    assert result["raw_seconds"] == [12_345]
    assert result["effective_seconds"] == [12_345]


def test_all_equal_and_all_zero_rows_are_unchanged() -> None:
    equal = normalize_seconds([42_000] * 20)
    assert equal["raw_seconds"] == equal["effective_seconds"]
    assert equal["p75_seconds"] == 42_000

    zeros = normalize_seconds([0] * 20)
    assert zeros["raw_seconds"] == zeros["effective_seconds"]
    assert zeros["p75_seconds"] == 0


def test_zero_p75_with_a_positive_tail_does_not_erase_activity() -> None:
    result = normalize_seconds([0, 0, 0, 100])
    assert result["p75_seconds"] == 0
    assert result["effective_seconds"] == [0, 0, 0, 100]


def test_rule_is_monotonic_and_only_compresses_above_p75() -> None:
    raw = [0, 10, 100, 1_000, 10_000, 100_000, 1_000_000]
    result = normalize_seconds(raw)
    effective = result["effective_seconds"]
    p75 = result["p75_seconds"]

    assert p75 == sorted(raw)[math.floor(0.75 * (len(raw) - 1))]
    assert effective == sorted(effective)
    assert max(effective) < max(raw)
    assert all(
        actual == value
        for actual, value in zip(effective, raw, strict=True)
        if value <= p75
    )
    assert all(
        actual < value
        for actual, value in zip(effective, raw, strict=True)
        if value > p75
    )
    assert len(set(effective)) == len(set(raw))


def test_row_mappings_keep_input_order_and_ignore_extra_fields() -> None:
    rows = [
        {"id": "c", "seconds": 300, "rank": 3},
        {"id": "a", "seconds": 100, "rank": 1},
        {"id": "b", "seconds": 200, "rank": 2},
        {"id": "d", "seconds": 1_000, "rank": 4},
    ]
    result = normalize_seconds(rows)
    assert result["raw_seconds"] == [300, 100, 200, 1_000]
    assert result["effective_seconds"] == normalize_seconds(
        [300, 100, 200, 1_000]
    )["effective_seconds"]
    assert result["p75_seconds"] == 300
    assert result["effective_seconds"][0] == 300
    assert result["effective_seconds"][1] == 100
    assert result["effective_seconds"][2] == 200
    assert result["effective_seconds"][3] < 1_000

    assert normalize_seconds(
        [{"anchor_seconds": 10}, {"anchor_seconds": 20}]
    )["raw_seconds"] == [10, 20]


def test_invalid_input_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_seconds([1, -1])
    for bad in ([1, 1.5], [1, True], ["100"], [object()]):
        with pytest.raises(TypeError):
            normalize_seconds(bad)
    for bad in (None, 123, "not-a-row-list"):
        with pytest.raises(TypeError):
            normalize_seconds(bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        normalize_seconds([{"rank": 1}])


def test_real_978_row_snapshot_matches_the_agreed_shape() -> None:
    if not REAL_CACHE.exists():
        pytest.skip("real snapshot cache is not present")
    users = json.loads(REAL_CACHE.read_text(encoding="utf-8"))["users"]
    assert len(users) == 978

    result = normalize_seconds(users)
    raw = result["raw_seconds"]
    effective = result["effective_seconds"]
    p75 = result["p75_seconds"]

    assert p75 == sorted(raw)[math.floor(0.75 * (len(raw) - 1))]
    assert max(effective) < max(raw)
    # Top1 raw is ~121.9h; the agreed soft cap lands near 30.8h.
    assert max(effective) == 110_943
    assert max(effective) / 3600 == pytest.approx(30.82, abs=0.01)
    # Rank 10 effective is near 29.0h.
    assert effective[9] / 3600 == pytest.approx(29.03, abs=0.01)
    assert all(
        actual == value
        for actual, value in zip(effective, raw, strict=True)
        if value <= p75
    )
    assert normalize_seconds(users) == result


def test_source_module_has_no_game_or_tier_imports() -> None:
    source_dir = Path("ghost_league/source")
    for path in source_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        assert not any(
            name == "ghost_league.game"
            or name.startswith("ghost_league.game.")
            or name.startswith(".")
            and "game" in name
            for name in imported
        ), (path, imported)
        text = path.read_text(encoding="utf-8").lower()
        assert "tier" not in text
        assert "ghost" not in text


def test_version_constant_is_exposed() -> None:
    assert NORMALIZATION_VERSION == "p75-soft-0.2-v1"
