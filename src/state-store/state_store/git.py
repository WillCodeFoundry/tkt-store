"""`GitStateStore`: the store on a branch of a remote, through a clone it made
(state-store design).

Snapshots fetch the branch into its tracking ref and read its commit lazily (§3).
Commits build only the trees on the paths of changed keys, make one commit on the
snapshot's revision, and publish it by `push --force-with-lease` (§5).
"""

from __future__ import annotations

import os

from state_store.snapshot import StateSnapshot

TRACKING_REF = "refs/remotes/origin/{branch}"
"""Where the branch is fetched to: the ref `git clone` made for it. Only this package
moves it; the clone has no local branch."""

BRANCH_SETTING = "state-store.branch"
"""The clone's setting naming the store's branch (state-store design §7)."""


class GitStateStore:
    """The store on a branch of a remote, read and written through the clone at `path`,
    which `clone` made.

    Opening reads the URL and branch from the clone and checks it without contacting
    the remote (state-store design §7): `UnusableRepository` for a path that is not a
    clone the store made, a clone changed since, or one whose remote git's configuration
    changes.

    Every git failure becomes one of the store's outcomes, and errors are raised
    `from None`, so the README's rule on messages holds in tracebacks too (state-store
    design §8)."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        raise NotImplementedError

    @classmethod
    def clone(cls, path: str | os.PathLike[str], *, url: str, branch: str) -> GitStateStore:
        """Clone `branch` of the remote at `url` to `path`, then open it (state-store
        design §7).

        `ValueError` for an invalid branch name or an empty URL; `UnusableRepository`
        if anything exists at `path`, or the clone cannot be put there; `NoSuchBranch`
        if the remote has no such branch; `RemoteFailed` if cloning fails otherwise."""
        raise NotImplementedError

    def snapshot(self) -> StateSnapshot:
        """The branch's current state on the remote (state-store design §3); first
        checks it against this object's last commit, else `PushElsewhere`."""
        raise NotImplementedError

    def commit(self, snapshot: StateSnapshot, message: str) -> StateSnapshot:
        """See `StateStore.commit`; how, and every outcome: state-store design §5."""
        raise NotImplementedError
