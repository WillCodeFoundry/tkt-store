"""Real git: behaviour specific to the git adapter (format marker, file layout, the local
cache, local-only mode). Shared Store semantics live in tests/contract/."""

import pytest

pytestmark = [pytest.mark.git, pytest.mark.skip(reason="skeleton")]


def test_init_writes_store_meta() -> None:
    """The root commit contains tkt-store.json = {"protocol": 1}."""


@pytest.mark.parametrize("meta", ["missing", "newer", "malformed"])
def test_snapshot_rejects_bad_store_meta(meta: str) -> None:
    """→ StoreError on every snapshot, never a silent misread."""


def test_stray_files_are_ignored_and_preserved() -> None:
    """tickets/README.md, tickets/foo.json, and root files are never decoded and survive
    later commits."""


def test_filename_must_match_id() -> None:
    """tickets/tkt-0001.json whose id is tkt-0002 → StoreError."""


def test_corrupt_ticket_fails_the_whole_snapshot() -> None: ...


def test_local_only_stale_base_is_conflict() -> None:
    """remote=None: update-ref is the compare-and-swap; a moved ref → Conflict."""


def test_fast_forward_local_tolerates_a_local_ref_ahead() -> None:
    """Another process on the clone pushed and moved the ref: no-op, not StoreError."""


def test_fast_forward_local_rejects_divergence() -> None:
    """→ StoreError."""


def test_remote_is_required_for_git_store() -> None:
    """GitStore/GitStore.at take `remote` with no default; open_store defaults to origin."""


def test_non_ascii_title_round_trips() -> None:
    """cat-file --batch sizes are bytes: a non-ASCII title is decoded correctly."""
