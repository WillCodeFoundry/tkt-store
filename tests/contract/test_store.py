"""ONE contract suite, run against every Store implementation (store.py docstring).

If MemStore and GitStore ever differ, a test here must fail.
"""

import pytest

pytestmark = pytest.mark.skip(reason="skeleton: stores not implemented")

STORES = ["memstore", "gitstore"]


@pytest.mark.parametrize("kind", STORES)
def test_unborn_snapshot_has_no_revision(kind: str) -> None: ...


@pytest.mark.parametrize("kind", STORES)
def test_commit_on_current_base_becomes_visible(kind: str) -> None: ...


@pytest.mark.parametrize("kind", STORES)
def test_commit_on_stale_base_raises_conflict_and_changes_nothing(kind: str) -> None: ...


@pytest.mark.parametrize("kind", STORES)
def test_commit_is_all_or_nothing_for_multiple_changes(kind: str) -> None: ...


@pytest.mark.parametrize("kind", STORES)
def test_history_newest_first_and_filterable_by_ticket(kind: str) -> None: ...


@pytest.mark.parametrize("kind", STORES)
def test_unknown_files_on_branch_are_preserved(kind: str) -> None: ...
