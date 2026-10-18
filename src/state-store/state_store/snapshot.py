"""Snapshots, and what a store gives them to read from (state-store.md, *Interface*;
state-store-design.md §3-5).

`StateSnapshot` is one class for every store. A store supplies a `Base`, a read-only
view of one committed state in its own terms; `CachedBase` remembers what was read from
it, once per taken snapshot; and the snapshot adds the overlay, the merging and every
check on what is read. So both stores have exactly the same semantics, and only the
git store knows git.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class Kind(Enum):
    VALUE = "value"
    NAMESPACE = "namespace"


@dataclass(frozen=True)
class Entry:
    """One entry of a listed namespace, as the base found it, before any check.

    `kind` is None for anything the store never writes (for git: a symlink, an
    executable, a submodule); the snapshot treats that as corrupt. `size` is a value's
    size, known before reading it; `ref` is how the base finds the entry's content
    again (an object id for git)."""

    name: str
    kind: Kind | None
    size: int | None
    ref: str


class Base(Protocol):
    """A read-only view of one committed state: what a snapshot reads through."""

    @property
    def store(self) -> object:
        """The store object the state belongs to; commits check snapshots against it."""
        ...

    @property
    def revision(self) -> str | None:
        """The committed state's id; None before the first commit."""
        ...

    def root(self) -> str | None:
        """The root namespace's ref, or None for a store never committed to."""
        ...

    def listing(self, ref: str) -> tuple[Entry, ...]:
        """Every entry of the namespace `ref`, as stored: names as found (possibly not
        valid segments), duplicates included."""
        ...

    def read(self, ref: str) -> bytes:
        """The value `ref`."""
        ...


class CachedBase:
    """A `Base` whose listings and values are each read at most once. Every snapshot
    derived from one taken snapshot shares one `CachedBase`."""

    def __init__(self, base: Base) -> None:
        raise NotImplementedError

    @property
    def store(self) -> object:
        raise NotImplementedError

    @property
    def revision(self) -> str | None:
        raise NotImplementedError

    def root(self) -> str | None:
        raise NotImplementedError

    def listing(self, ref: str) -> tuple[Entry, ...]:
        raise NotImplementedError

    def read(self, ref: str) -> bytes:
        raise NotImplementedError


class StateStore(Protocol):
    """A key/value store you change only by committing snapshots."""

    def snapshot(self) -> StateSnapshot:
        """The store's current state."""
        ...

    def commit(self, snapshot: StateSnapshot, message: str) -> StateSnapshot:
        """Publish `snapshot`'s changes as one commit, if the store has not changed since
        `snapshot` was taken; the committed state, as a snapshot without changes.

        Arguments are checked first: `ValueError` for a snapshot from another store
        object or a message holding NUL, even when nothing changes. Then a snapshot
        that changes nothing is returned as the snapshot it derives from, without
        contacting the remote. Otherwise `StaleSnapshot` (or `UnknownOutcome`) or
        `StoreError`."""
        ...


class StateSnapshot:
    """An immutable view of every key at one moment, plus changes derived from it.

    Only stores make snapshots; `with_value` and `without` return new ones."""

    __slots__ = ("_base", "_overlay")
    _base: CachedBase
    _overlay: Mapping[str, bytes | None]

    def __init__(self, base: CachedBase, overlay: Mapping[str, bytes | None] | None = None) -> None:
        raise NotImplementedError

    @property
    def revision(self) -> str | None:
        """The commit this snapshot was taken from; None before the store's first commit."""
        raise NotImplementedError

    @property
    def changes(self) -> Mapping[str, bytes | None]:
        """Each key this snapshot changes, as given, to its new value or None (removed).
        Read-only. Whether a change changes anything is only known at commit."""
        raise NotImplementedError

    def get(self, key: str) -> bytes | None:
        """The value of `key`, or None if it has none (a namespace, or nothing)."""
        raise NotImplementedError

    def keys(self, namespace: str = "") -> list[str]:
        """The full keys of the values directly in `namespace`, sorted."""
        raise NotImplementedError

    def with_value(self, key: str, value: bytes) -> StateSnapshot:
        """A new snapshot where `key` holds `value`; `KeyCollision` if `key`, or a
        prefix of it, is the other kind of thing."""
        raise NotImplementedError

    def without(self, key: str) -> StateSnapshot:
        """A new snapshot where `key` holds no value. Removing a key that has none (a
        namespace, or nothing) changes nothing."""
        raise NotImplementedError

    def __repr__(self) -> str:
        """The revision and how many changes; never a key or value."""
        raise NotImplementedError

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("a StateSnapshot is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("a StateSnapshot is immutable")
