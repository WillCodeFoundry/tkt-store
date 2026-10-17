"""The clone cache (ADR 0006): what a clone already read and checked, kept between processes.

JSON files in the clone's git directory, never pushed. Every entry is keyed by a git
object id, which names exact content, so an entry is never stale:

- `tickets`: blob id -> a valid resolved ticket (it never changes again);
- `invalid`: blob id -> the check its file failed (never the value read, ADR 0005);
- `folders`: tree id -> the claim file names in a resolved ticket's `claims/<id>/`
  folder (it never changes again either; ADR 0007).

Entries are spread over 256 shard files by the first two digits of their object id, so
an op that resolves a ticket rewrites one or two small files, not the whole cache.

Only what depends on the object's bytes alone is cached: checks that relate a file to its
path, to other tickets or to claims run on every snapshot. The cache is a convenience,
never the source of truth: a shard written by another cache version or tkt-store version,
one that does not parse, or one with an entry of the wrong shape is ignored, and the next
snapshot rebuilds it. Each shard is written to a uniquely named temporary file renamed
over the old one, so a crash never leaves a torn file. It is JSON, never pickle: loading
a pickle can run code. Whoever can write the clone's git directory can forge an entry,
which adds no exposure: they can already run code there through hooks or config. A
cached reason must still look like one of tkt's own (`_plain`), since it is printed.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from tkt_store.domain import fields
from tkt_store.domain import ticket as ticket_module
from tkt_store.domain.ticket import Ticket
from tkt_store.infrastructure.git import wire

CACHE_VERSION = 1
"""Bumped whenever the cache's own layout changes. The decoder and the checks it caches
are stamped by the hash of their source too (`_writer`), so changing a rule, even in an
editable install, never keeps a verdict an older rule gave."""

REASON_MAX = 200
"""The longest cached reason accepted: tkt's own are far shorter."""


def _writer() -> str | None:
    """The stamp every shard carries: the cache version, the installed tkt-store version,
    and a hash of the modules whose rules decide a cached entry. None if those modules'
    source can't be read (a frozen install): then the cache is off."""
    try:
        tkt_store = version("tkt-store")
    except PackageNotFoundError:  # pragma: no cover - always installed in practice
        tkt_store = "unknown"
    rules = hashlib.sha256()
    try:
        for module in (fields, ticket_module, wire):
            rules.update(Path(module.__file__ or "").read_bytes())
    except OSError:
        return None
    return f"{CACHE_VERSION}/{tkt_store}/{rules.hexdigest()[:16]}"


@dataclass
class Cached:
    """What the cache holds (see the module docstring)."""

    tickets: dict[str, Ticket] = field(default_factory=dict)
    invalid: dict[str, str] = field(default_factory=dict)
    folders: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def ids(self) -> set[str]:
        """Every object id it holds an entry for."""
        return {*self.tickets, *self.invalid, *self.folders}


class CloneCache:
    """The cache's shard files in `directory` (`tkt-store/cache/` in the clone's git
    directory)."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._writer = _writer()
        self._saved: dict[str, set[str]] = {}
        """Each shard's keys as last loaded or saved: a shard is rewritten only when its
        keys change, or when it could not be loaded (so it is not rejected again)."""
        self._spoilt: set[str] = set()

    @property
    def spoilt(self) -> bool:
        """True if a shard could not be loaded: the next save rewrites it."""
        return bool(self._spoilt)

    def load(self) -> Cached:
        """Everything the trusted shards hold; a missing or untrusted shard holds nothing
        (another writer version, not JSON, an entry of the wrong shape)."""
        cached = Cached()
        self._saved, self._spoilt = {}, set()
        if self._writer is None:
            return cached
        with suppress(OSError):
            for path in sorted(self.directory.glob("??.json")):
                if (shard := self._load(path)) is None:
                    self._spoilt.add(path.stem)
                    continue
                cached.tickets.update(shard.tickets)
                cached.invalid.update(shard.invalid)
                cached.folders.update(shard.folders)
                self._saved[path.stem] = shard.ids()
        return cached

    def _load(self, path: Path) -> Cached | None:
        try:
            raw = json.loads(path.read_bytes())
            if not isinstance(raw, dict) or raw.get("writer") != self._writer:
                return None
            shard = Cached(
                tickets={_key(k): wire.ticket_from_raw(v) for k, v in _object(raw["tickets"])},
                invalid={_key(k): _plain(v) for k, v in _object(raw["invalid"])},
                folders={_key(k): _names(v) for k, v in _object(raw["folders"])},
            )
        except (OSError, ValueError, KeyError, TypeError, RecursionError, wire.Invalid):
            return None
        return shard if all(key[:2] == path.stem for key in shard.ids()) else None

    def save(self, cached: Cached) -> None:
        """Make the shards hold exactly `cached`, rewriting only those whose keys changed
        or that could not be loaded. A failure only costs a re-read next time, so it is
        ignored."""
        if self._writer is None:
            return
        shards: dict[str, Cached] = defaultdict(Cached)
        for key, ticket in cached.tickets.items():
            shards[key[:2]].tickets[key] = ticket
        for key, reason in cached.invalid.items():
            shards[key[:2]].invalid[key] = reason
        for key, names in cached.folders.items():
            shards[key[:2]].folders[key] = names
        for name in {*shards, *self._saved, *self._spoilt}:
            shard = shards.get(name, Cached())
            if name in self._spoilt or shard.ids() != self._saved.get(name, set()):
                self._write(name, shard)
                self._spoilt.discard(name)

    def _write(self, name: str, shard: Cached) -> None:
        document = {
            "writer": self._writer,
            "tickets": {k: t.to_dict() for k, t in shard.tickets.items()},
            "invalid": shard.invalid,
            "folders": {k: list(names) for k, names in shard.folders.items()},
        }
        with suppress(OSError):
            self.directory.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(dir=self.directory, prefix=".shard-")
            try:
                with os.fdopen(handle, "wb") as out:
                    out.write(json.dumps(document, separators=(",", ":")).encode())
                os.replace(temporary, self.directory / f"{name}.json")
            except OSError:
                with suppress(OSError):
                    os.unlink(temporary)
                raise
            self._saved[name] = shard.ids()


def _object(value: object) -> list[tuple[object, object]]:
    if not isinstance(value, dict):
        raise TypeError("not an object")
    return list(value.items())


def _key(value: object) -> str:
    if not isinstance(value, str) or len(value) not in (40, 64) or value.strip("0123456789abcdef"):
        raise TypeError("not an object id")
    return value


def _plain(value: object) -> str:
    """A cached reason, accepted only if it looks like one of tkt's own: short printable
    ASCII. It is printed in SET_ASIDE refusals."""
    if not isinstance(value, str) or len(value) > REASON_MAX:
        raise TypeError("not a reason")
    if not (value.isascii() and value.isprintable()):
        raise TypeError("not a reason")
    return value


def _names(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise TypeError("not a list of names")
    return tuple(value)
