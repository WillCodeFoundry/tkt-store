"""Engine behaviour with deterministic conflicts (MemStore.before_next_commit)."""

import pytest

pytestmark = pytest.mark.skip(reason="skeleton: engine not implemented")


def test_conflict_triggers_retry_with_fresh_snapshot() -> None: ...


def test_retry_rechecks_rules() -> None:
    """Another writer claims during our attempt → retry returns Refused(ALREADY_CLAIMED)."""


def test_retries_exhausted_raises_with_the_op() -> None:
    """After DEFAULT_MAX_ATTEMPTS conflicts → RetriesExhausted whose .op has the ids tried."""


def test_store_error_carries_the_op() -> None:
    """A StoreError from commit is re-raised as StoreError(..., op=op) from the original."""


def test_refusal_and_noop_write_nothing() -> None: ...


def test_committed_carries_the_written_tickets() -> None: ...


def test_unchanged_carries_the_tickets_it_concerns() -> None:
    """E.g. a re-run claim: Unchanged.tickets shows the ticket and its claim id."""


def test_commit_uses_the_snapshot_revision_not_a_fresh_read() -> None:
    """Regression guard for the 'wrong old value' bug class (balls bl-cdec G1)."""
