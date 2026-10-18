"""What can go wrong, as the caller needs to tell it apart (state-store README, *Errors*).

A caller either starts again from a new snapshot (`StaleSnapshot`, including
`UnknownOutcome`) or stops (`StoreError` and its kinds, `ValueError`, including
`KeyCollision`). What a message may hold: state-store README, *Errors*.
"""

from __future__ import annotations


class StaleSnapshot(Exception):
    """The store changed since the snapshot was taken. Nothing was published, unless it
    is an `UnknownOutcome`.

    Take a new snapshot and decide again."""


class UnknownOutcome(StaleSnapshot):
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


class NotAClone(StoreError):
    """The path is not a usable clone, or its remote is not configured as required."""


class NoIdentity(StoreError):
    """git has no author identity to commit with."""


class GitFailed(StoreError):
    """A git command failed."""


class RemoteFailed(GitFailed):
    """Fetching, or checking whether the branch exists, failed while taking a snapshot."""
