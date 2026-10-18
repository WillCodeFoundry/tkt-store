"""A key/value store on a git branch: snapshot reads, all-or-nothing commits that land
only if nothing changed since the snapshot (state-store README)."""

from state_store.errors import (
    CommitRefused,
    CompareAndSwapFailed,
    CorruptState,
    GitFailed,
    KeyCollision,
    NoIdentity,
    NoSuchBranch,
    PushElsewhere,
    RemoteFailed,
    StoreError,
    UnknownOutcome,
    UnusableRepository,
)
from state_store.git import GitStateStore
from state_store.keys import MAX_VALUE_SIZE
from state_store.memory import MemoryStateStore
from state_store.snapshot import StateSnapshot, StateStore

__all__ = [
    "MAX_VALUE_SIZE",
    "CommitRefused",
    "CompareAndSwapFailed",
    "CorruptState",
    "GitFailed",
    "GitStateStore",
    "KeyCollision",
    "MemoryStateStore",
    "NoIdentity",
    "NoSuchBranch",
    "PushElsewhere",
    "RemoteFailed",
    "StateSnapshot",
    "StateStore",
    "StoreError",
    "UnknownOutcome",
    "UnusableRepository",
]
