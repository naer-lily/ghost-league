from __future__ import annotations

import pytest

from ghost_league.game.rules import group_movement, group_quota


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (15, 4),
        (14, 4),
        (13, 3),
        (12, 3),
        (10, 3),
        (5, 1),
        (2, 1),
    ],
)
def test_group_quota_is_thirty_percent_rounded_down(
    size: int, expected: int
) -> None:
    assert group_quota(size) == expected


@pytest.mark.parametrize(
    ("size", "promoted_ranks", "demoted_ranks"),
    [
        (15, set(range(1, 5)), set(range(12, 16))),
        (14, set(range(1, 5)), set(range(11, 15))),
        (13, set(range(1, 4)), set(range(11, 14))),
        (2, {1}, {2}),
    ],
)
def test_group_movement_uses_the_thirty_percent_quota(
    size: int,
    promoted_ranks: set[int],
    demoted_ranks: set[int],
) -> None:
    for rank in range(1, size + 1):
        promoted, demoted = group_movement(rank, "Silver", size)
        assert promoted is (rank in promoted_ranks)
        assert demoted is (rank in demoted_ranks)
        assert not (promoted and demoted)


def test_bronze_never_demotes_and_diamond_never_promotes() -> None:
    for rank in range(1, 16):
        promoted, demoted = group_movement(rank, "Bronze", 15)
        assert demoted is False
        assert promoted is (rank <= 4)

        promoted, demoted = group_movement(rank, "Diamond", 15)
        assert promoted is False
        assert demoted is (rank >= 12)


def test_groups_smaller_than_two_do_not_move() -> None:
    assert group_movement(1, "Bronze", 1) == (False, False)
    assert group_movement(1, "Diamond", 1) == (False, False)


def test_group_quota_rejects_invalid_sizes() -> None:
    with pytest.raises(ValueError):
        group_quota(-1)
    with pytest.raises(TypeError):
        group_quota(True)  # type: ignore[arg-type]
