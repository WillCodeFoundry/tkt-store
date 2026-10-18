"""What can go wrong, as the caller needs to tell it apart (state-store.md, *Errors*).

A caller either starts again from a new snapshot (`StaleSnapshot`, including
`UnknownOutcome`) or stops (`StoreError`, `ValueError`, including `KeyCollision`). No
message carries text git or a remote printed, nor a value read from the store.
"""

from __future__ import annotations

from enum import Enum


class StaleSnapshot(Exception):
    """The store changed since the snapshot was taken. Nothing was published.

    Take a new snapshot and decide again."""


class UnknownOutcome(StaleSnapshot):
    """The connection failed during the push: the commit may or may not have landed.

    Take a new snapshot and decide again; it shows whether the commit landed. A caller
    whose changes are not safe to repeat checks for them first."""


class KeyCollision(ValueError):
    """A write would make a key both a value and a namespace.

    It can come from data another writer stored, not only from this caller's code."""


class Category(Enum):
    """What kind of `StoreError` it is (state-store.md, *Errors*)."""

    CORRUPT = "the branch holds something the store would never write"
    REFUSED = "the remote refused the commit"
    AUTH = "the remote refused access"
    NOT_FOUND = "the remote repository was not found"
    UNREACHABLE = "the remote could not be reached"
    UNRECOGNISED = "a remote command failed in an unrecognised way"
    NO_IDENTITY = "git has no identity to author commits with"
    NOT_A_CLONE = "the path is not a usable clone"
    LOCAL = "a local git command failed"


class StoreError(Exception):
    """A failure the store cannot recover from; an operator acts. Never retried.

    `detail` names the operation, key or check, never text read from git or the store."""

    def __init__(self, category: Category, detail: str = "") -> None:
        self.category = category
        super().__init__(f"{category.value}: {detail}" if detail else category.value)
