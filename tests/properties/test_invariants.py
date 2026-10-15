"""Property tests (hypothesis) over random op sequences against MemStore.

Each generated scenario: several agents, random ops (claim, renew, move, release, done, reap,
clock advances), random interleavings and injected conflicts. After every step:
"""

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.skip(reason="skeleton")]


def test_never_two_live_holders() -> None:
    """Invariant 1."""


def test_resolved_tickets_never_change() -> None:
    """Invariant 9."""


def test_only_current_claim_id_can_finish() -> None:
    """Invariant 4."""


def test_every_applied_op_is_exactly_one_history_entry() -> None:
    """Invariant 2."""
