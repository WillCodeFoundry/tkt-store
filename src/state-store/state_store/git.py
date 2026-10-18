"""`GitStateStore`: the store on a branch of a remote, through a local clone
(state-store design).

Snapshots fetch the branch into a private ref and read its commit lazily (§3).
Commits build only the trees on the paths of changed keys, make one commit on the
snapshot's revision, and publish it by `push --force-with-lease` (§5).
"""

from __future__ import annotations

import os

from state_store.snapshot import StateSnapshot

PRIVATE_REF = "refs/state-store/{branch}"
"""Where the branch is fetched to. Only this package writes it; there is no local branch."""


class GitStateStore:
    """The store on `branch` of `remote`, read and written through the clone at `repo`.

    Opening checks the names and the clone without contacting the remote (state-store design §7):
    `ValueError` for an invalid branch name or an empty remote name,
    `StoreError(NOT_A_CLONE)` for a path that is not the top level of a full, non-bare
    clone, or a remote that is not configured with exactly one URL for both fetching and
    pushing.

    Every git failure becomes one of the store's errors raised `from None`, so no
    traceback carries git's or the server's text (state-store design §8)."""

    def __init__(
        self, repo: str | os.PathLike[str], *, remote: str = "origin", branch: str
    ) -> None:
        raise NotImplementedError

    def snapshot(self) -> StateSnapshot:
        """The branch's current state on the remote (state-store design §3)."""
        raise NotImplementedError

    def commit(self, snapshot: StateSnapshot, message: str) -> StateSnapshot:
        """See `StateStore.commit`; how, and every outcome: state-store design §5."""
        raise NotImplementedError
