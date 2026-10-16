"""The clone cache (ADR 0006): what a clone already read and checked, kept between processes.

A JSON file in the clone's git directory, never pushed. Every entry is keyed by a git
object id, which names exact content, so an entry is never stale:

- `tickets`: blob id -> a valid resolved ticket (it never changes again);
- `invalid`: blob id -> the check its file failed (never the value read, ADR 0005);
- `folders`: tree id -> the claim file names in a resolved ticket's `claims/<id>/`
  folder (it never changes again either; ADR 0007).

Only what depends on the object's bytes alone is cached: checks that relate a file to its
path, to other tickets or to claims run on every snapshot. The cache is a convenience,
never the source of truth: one written by another cache version or tkt-store version,
one that does not parse, or one with an entry of the wrong shape is ignored, and the next
snapshot rebuilds it. It is written to a uniquely named temporary file renamed over the
old one, so a crash never leaves a torn file. It is JSON, never pickle: loading a pickle
can run code. Whoever can write the clone's git directory can forge an entry, which adds
no exposure: they can already run code there through hooks or config.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from tkt_store.domain.ticket import Ticket
from tkt_store.infrastructure.git import wire

CACHE_VERSION = 1
"""Bumped whenever the decoder or a cached check changes, so an editable install that
changes them never trusts entries an older build wrote."""


def _writer() -> str:
    try:
        tkt_store = version("tkt-store")
    except PackageNotFoundError:  # pragma: no cover - always installed in practice
        tkt_store = "unknown"
    return f"{CACHE_VERSION}/{tkt_store}"


@dataclass
class Cached:
    """What a cache file holds (see the module docstring)."""

    tickets: dict[str, Ticket] = field(default_factory=dict)
    invalid: dict[str, str] = field(default_factory=dict)
    folders: dict[str, tuple[str, ...]] = field(default_factory=dict)


class CloneCache:
    """The cache file at `path` (`tkt-store/cache.json` in the clone's git directory)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._writer = _writer()

    def load(self) -> Cached:
        """The cache's contents, or an empty cache when there is none or it can't be
        trusted (another writer version, not JSON, an entry of the wrong shape)."""
        try:
            raw = json.loads(self.path.read_bytes())
            if not isinstance(raw, dict) or raw.get("writer") != self._writer:
                return Cached()
            return Cached(
                tickets={str(k): wire.ticket_from_raw(v) for k, v in _object(raw["tickets"])},
                invalid={str(k): _string(v) for k, v in _object(raw["invalid"])},
                folders={str(k): _names(v) for k, v in _object(raw["folders"])},
            )
        except (OSError, ValueError, KeyError, TypeError, RecursionError, wire.Invalid):
            return Cached()

    def save(self, cached: Cached) -> None:
        """Replace the file with `cached`, atomically. A failure only costs a re-read
        next time, so it is ignored."""
        document = {
            "writer": self._writer,
            "tickets": {k: t.to_dict() for k, t in cached.tickets.items()},
            "invalid": cached.invalid,
            "folders": {k: list(names) for k, names in cached.folders.items()},
        }
        with suppress(OSError):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".cache-")
            try:
                with os.fdopen(handle, "wb") as out:
                    out.write(json.dumps(document, separators=(",", ":")).encode())
                os.replace(temporary, self.path)
            except OSError:
                with suppress(OSError):
                    os.unlink(temporary)
                raise


def _object(value: object) -> list[tuple[object, object]]:
    if not isinstance(value, dict):
        raise TypeError("not an object")
    return list(value.items())


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("not a string")
    return value


def _names(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise TypeError("not a list of names")
    return tuple(value)
