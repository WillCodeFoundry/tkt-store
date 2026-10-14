"""Engine behaviour with deterministic conflicts (MemStore.before_next_commit)."""

import pytest

pytestmark = pytest.mark.skip(reason="skeleton: engine not implemented")


def test_conflict_triggers_retry_with_fresh_snapshot() -> None: ...


def test_retry_rechecks_rules() -> None:
    """Another writer claims during our attempt → retry returns Refused(ALREADY_CLAIMED)."""


def test_retries_exhausted_raises() -> None: ...


def test_refusal_and_noop_write_nothing() -> None: ...


def test_commit_uses_the_snapshot_base_not_a_fresh_read() -> None:
    """Regression guard for the 'wrong old value' bug class (balls bl-cdec G1)."""
