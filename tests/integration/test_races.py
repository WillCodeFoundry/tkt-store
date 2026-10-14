"""Real git: two clones of one bare remote compete for one ticket."""

import pytest

pytestmark = [pytest.mark.git, pytest.mark.slow, pytest.mark.skip(reason="skeleton")]


def test_exactly_one_clone_wins_a_claim() -> None:
    """Both claim the same ticket; one Committed, the other Refused(ALREADY_CLAIMED) after retry."""


def test_unrelated_tickets_both_succeed() -> None: ...


def test_loser_never_sees_partial_state() -> None: ...
