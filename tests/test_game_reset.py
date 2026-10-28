from __future__ import annotations

import pytest

from ghost_league.game import reset as reset_module
from ghost_league.game.reset import dry_run, reset_database
from ghost_league.game.store import GameStore


def test_dry_run_does_not_create_or_write(tmp_path) -> None:
    target = tmp_path / "not-yet.db"
    snapshot = dry_run(target)
    assert snapshot["dry_run"] is True
    assert snapshot["writes_performed"] == 0
    assert snapshot["would_archive"]["exists"] is False
    assert not target.exists()

    store = GameStore(target, epoch_reason="seed")
    store.create_player(
        "human-1",
        kind="human",
        joined_week="2026-10-26",
        now="2026-10-26T00:00:00+08:00",
    )
    before = store.table_counts()
    snapshot = dry_run(target)
    assert snapshot["would_archive"]["counts"]["players"] == 1
    assert snapshot["writes_performed"] == 0
    assert store.table_counts() == before
    assert target.exists()


def test_temp_reset_is_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(reset_module, "DEFAULT_DB_PATH", tmp_path / "other-live.db")
    target = tmp_path / "league.db"
    first = reset_database(
        target, confirm=True, now="2026-10-26T00:00:00+08:00"
    )
    assert first["reset"] is True
    assert first["already_initialized"] is False
    assert first["integrity_check"] == "ok"
    assert first["created_epoch"]["reason"] == "reset:to-bronze"
    assert first["counts"]["players"] == 0

    second = reset_database(
        target, confirm=True, now="2026-10-26T01:00:00+08:00"
    )
    assert second["reset"] is False
    assert second["already_initialized"] is True
    assert second["writes_performed"] == 0
    assert second["active_epoch"]["id"] == first["created_epoch"]["id"]


def test_reset_does_not_touch_protected_account_files(tmp_path, monkeypatch) -> None:
    sentinels = {
        "accounts": tmp_path / "accounts.db",
        "events": tmp_path / "events.db",
        "membership": tmp_path / "membership.json",
        "state": tmp_path / "state.json",
        "weeks": tmp_path / "weeks.json",
    }
    for path in sentinels.values():
        path.write_bytes(b"sentinel-content")
    monkeypatch.setattr(
        reset_module, "_PROTECTED_PATHS", tuple(sentinels.values())
    )
    monkeypatch.setattr(reset_module, "DEFAULT_DB_PATH", tmp_path / "live.db")

    result = reset_database(
        tmp_path / "temp-league.db",
        confirm=True,
        now="2026-10-26T00:00:00+08:00",
    )
    assert result["reset"] is True
    assert set(result["protected_paths_untouched"]) == {
        str(path) for path in sentinels.values()
    }
    for path in sentinels.values():
        assert path.read_bytes() == b"sentinel-content"


def test_confirm_on_live_path_is_refused(tmp_path, monkeypatch) -> None:
    live = tmp_path / "live.db"
    monkeypatch.setattr(reset_module, "DEFAULT_DB_PATH", live)
    with pytest.raises(ValueError):
        reset_database(live, confirm=True, now="2026-10-26T00:00:00+08:00")
    assert not live.exists()


def test_live_reset_requires_both_explicit_switches(tmp_path, monkeypatch) -> None:
    live = tmp_path / "live.db"
    monkeypatch.setattr(reset_module, "DEFAULT_DB_PATH", live)

    with pytest.raises(ValueError):
        reset_database(
            live,
            confirm=True,
            force_new_epoch=True,
            now="2026-10-26T00:00:00+08:00",
        )
    with pytest.raises(ValueError):
        reset_database(
            live,
            confirm=True,
            allow_live=True,
            now="2026-10-26T00:00:00+08:00",
        )
    assert not live.exists()

    result = reset_database(
        live,
        confirm=True,
        force_new_epoch=True,
        allow_live=True,
        now="2026-10-26T00:00:00+08:00",
    )
    assert result["reset"] is True
    assert result["created_epoch"]["reason"] == "reset:to-bronze"
    assert result["integrity_check"] == "ok"
    assert result["counts"]["players"] == 0
    assert result["counts"]["weekly_results"] == 0
