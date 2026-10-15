"""Real git: interrupt an op at each step and re-run it (design.md §6)."""

import pytest

pytestmark = [pytest.mark.git, pytest.mark.skip(reason="skeleton")]


def test_crash_before_commit_leaves_only_unreachable_objects() -> None: ...


def test_crash_after_push_before_local_update_converges_on_next_op() -> None: ...


def test_rerunning_claim_with_same_claim_id_converges_to_one_claim() -> None: ...


def test_push_landed_then_local_update_failed_is_committed() -> None:
    """Never Conflict after a successful push; commit returns the new revision."""


def test_ambiguous_push_failure_rerun_converges() -> None:
    """StoreError(op=…) during push, commit actually landed: re-running op → Unchanged
    naming the same ticket and claim id."""
