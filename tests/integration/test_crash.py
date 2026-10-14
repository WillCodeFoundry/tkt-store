"""Real git: interrupt an op at each step and re-run it (design.md §6)."""

import pytest

pytestmark = [pytest.mark.git, pytest.mark.skip(reason="skeleton")]


def test_crash_before_commit_leaves_only_unreachable_objects() -> None: ...


def test_crash_after_push_before_local_update_converges_on_next_op() -> None: ...


def test_crash_after_local_update_before_push_converges_on_next_op() -> None: ...


def test_rerunning_claim_with_same_claim_id_converges_to_one_claim() -> None: ...
