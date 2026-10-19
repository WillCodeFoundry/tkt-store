"""`GitStateStore`: the store on a branch of a remote, through a clone it made
(state-store design)."""

from __future__ import annotations

import os

from state_store.snapshot import StateSnapshot

TRACKING_REF = "refs/remotes/origin/{branch}"
"""Where snapshots fetch the branch to: the ref `git clone` made for it."""

BRANCH_SETTING = "state-store.branch"
"""The clone's setting naming the store's branch."""


class GitStateStore:
    """The store through the clone at `path`, which `clone` made. Opening reads the
    branch from the clone and contacts nothing; `StoreError` if `path` is not such a
    clone."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        raise NotImplementedError

    @classmethod
    def clone(cls, path: str | os.PathLike[str], *, url: str, branch: str) -> GitStateStore:
        """Clone only `branch` of the remote at `url` to `path` and open it. `ValueError`
        for an invalid branch name; `StoreError` if the branch does not exist or cloning
        fails."""
        raise NotImplementedError

    def snapshot(self) -> StateSnapshot:
        """Fetch the branch and take a snapshot of its tip (state-store design,
        *Snapshot*)."""
        raise NotImplementedError

    def commit(self, snapshot: StateSnapshot, message: str) -> StateSnapshot:
        """See `StateStore.commit`; how: state-store design, *Commit*."""
        raise NotImplementedError
