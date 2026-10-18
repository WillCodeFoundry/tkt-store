"""A key/value store on a git branch: snapshot reads, all-or-nothing commits that land
only if nothing changed since the snapshot (state-store README)."""

from state_store.errors import (
    CommitRefused,
    CorruptState,
    GitFailed,
    KeyCollision,
    NoIdentity,
    NotAClone,
    RemoteFailed,
    StaleSnapshot,
    StoreError,
    UnknownOutcome,
)
from state_store.git import GitStateStore
from state_store.keys import MAX_VALUE_SIZE
from state_store.memory import MemoryStateStore
from state_store.snapshot import StateSnapshot, StateStore

__all__ = [
    "MAX_VALUE_SIZE",
    "CommitRefused",
    "CorruptState",
    "GitFailed",
    "GitStateStore",
    "KeyCollision",
    "MemoryStateStore",
    "NoIdentity",
    "NotAClone",
    "RemoteFailed",
    "StaleSnapshot",
    "StateSnapshot",
    "StateStore",
    "StoreError",
    "UnknownOutcome",
]
