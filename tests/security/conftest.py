"""A store with one honest ticket, plus helpers for committing forged content directly to
the remote with git, as a compromised agent with push access could."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.gitkit import write_files
from tests.unit.builders import NOW, T1, tkt
from tkt_store.application.service import TicketStore
from tkt_store.domain.ticket import TicketId
from tkt_store.infrastructure.clock import FakeClock
from tkt_store.infrastructure.git import wire
from tkt_store.infrastructure.git.repo import GitStore
from tkt_store.infrastructure.ids import SequentialIds


def service(clone: Path) -> TicketStore:
    return TicketStore(GitStore.at(clone, remote="origin"), FakeClock(NOW), SequentialIds())


@pytest.fixture
def clone(clones: list[Path]) -> Path:
    """An honest agent's clone of a store holding T1 ("Expire tokens")."""
    tickets = service(clones[0])
    tickets.init()
    tickets.add("Expire tokens", ticket_id=T1)
    return clones[0]


def forged(ticket_id: str, **fields: Any) -> dict[str, Any]:
    """A ticket document as the attacker writes it: a valid ticket, then `fields`."""
    document = tkt(TicketId(ticket_id)).to_dict()
    document.update(fields)
    return document


def push_raw(bare_remote: Path, files: dict[str, Any], **kwargs: Any) -> str:
    """Commit `files` on the remote by hand; dict values are encoded as JSON."""
    encoded = {
        path: json.dumps(value).encode() if isinstance(value, dict) else value
        for path, value in files.items()
    }
    return write_files(bare_remote, encoded, **kwargs)


def ticket_file(ticket_id: str) -> str:
    return wire.ticket_path(TicketId(ticket_id))
