"""What can go wrong, as the caller needs to tell it apart (state-store README, *Errors*).

A caller either starts again from a new snapshot (`CompareAndSwapFailed`,
`UnknownOutcome`) or stops (`StoreError` and its kinds, `ValueError`, including
`KeyCollision`). What a message may hold: state-store README, *Errors*.
"""

from __future__ import annotations


class CompareAndSwapFailed(Exception):
    """The branch the commit was pushed to was not at the snapshot's revision (another
    writer committed first). Nothing was published.

    Take a new snapshot and decide again."""


class UnknownOutcome(Exception):
    """The commit's outcome could not be read (for example, the connection failed): it
    may or may not have landed.

    Take a new snapshot and decide again; it shows whether the commit landed. A caller
    whose changes are not safe to repeat checks for them first."""


class KeyCollision(ValueError):
    """A write would make a key both a value and a namespace.

    It can come from data another writer stored, not only from this caller's code."""


class StoreError(Exception):
    """A failure the store cannot recover from; an operator acts. Never retried."""


class CorruptState(StoreError):
    """The branch holds something the store would never write."""


class CommitRefused(StoreError):
    """The remote refused the commit, and the branch did not move."""


class UnusableRepository(StoreError):
    """The path is not a clone the store made, or it was changed since, or git's
    configuration changes its remote; or, when cloning, the path already exists or the
    clone could not be put there."""


class NoSuchBranch(StoreError):
    """The branch does not exist on the remote: when cloning, or when taking a snapshot."""


class PushElsewhere(StoreError):
    """The store object's last commit does not match the branch: a published commit is
    missing from its history, or a compare-and-swap failed while the branch had not
    moved. Pushes reach a different repository from fetches."""


class NoIdentity(StoreError):
    """git has no author identity to commit with."""


class GitFailed(StoreError):
    """A git command failed."""


class RemoteFailed(GitFailed):
    """Cloning, fetching, or checking whether the branch exists, failed."""
