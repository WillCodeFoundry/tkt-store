"""Real git: behaviour specific to the git adapter (format marker, file layout, the local
cache, local-only mode). Shared Store semantics live in tests/contract/."""

import pytest

pytestmark = [pytest.mark.git, pytest.mark.skip(reason="skeleton")]


@pytest.mark.parametrize("mode", ["remote", "local"])
def test_init_writes_store_meta(mode: str) -> None:
    """The root commit contains tkt-store.json = {"mode": mode, "protocol": 1}."""


@pytest.mark.parametrize("opened_as", ["local_on_remote_store", "remote_on_local_store"])
def test_opening_in_the_other_mode_is_refused(opened_as: str) -> None:
    """A store opened in the mode it was not created with → StoreError, nothing written,
    so a stray --no-remote can never diverge a clone."""


def test_publish_uses_force_with_lease_on_base() -> None:
    """The push carries --force-with-lease=<ref>:<base>; a moved remote → Conflict."""


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
    """Local ref equal to, or a descendant of, the remote head → no-op, not StoreError.
    (A local ref that is behind is fast-forwarded: a separate repair.)"""


def test_fast_forward_local_rejects_divergence() -> None:
    """→ StoreError."""


def test_remote_is_required_for_git_store() -> None:
    """GitStore/GitStore.at take `remote` with no default; open_store defaults to origin."""


def test_non_ascii_title_round_trips() -> None:
    """cat-file --batch sizes are bytes: a non-ASCII title is decoded correctly."""
