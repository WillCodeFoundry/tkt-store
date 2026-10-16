"""Helpers for the security tests: the markers that record each finding, and how a
compromised agent with push access commits forged content directly to the remote."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.gitkit import write_files
from tkt_store.application.service import TicketStore
from tkt_store.domain.ticket import Phase, Ticket, TicketId
from tkt_store.infrastructure.clock import FakeClock
from tkt_store.infrastructure.git import wire
from tkt_store.infrastructure.git.repo import GitStore
from tkt_store.infrastructure.ids import SequentialIds

NOW = 1_000_000
T1 = TicketId("tkt-1")


def tkt(ticket_id: TicketId, **fields: Any) -> Ticket:
    """A plain open ticket; `fields` override."""
    base = Ticket(
        id=ticket_id, title="Expire tokens", created=0, updated=0, phase=Phase.IMPLEMENTATION
    )
    return replace(base, **fields)


def service(clone: Path) -> TicketStore:
    return TicketStore(GitStore.at(clone, remote="origin"), FakeClock(NOW), SequentialIds())


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


def bug(reason: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, reason=f"security bug (batch A): {reason}")


def design(reason: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, reason=f"security, design pending (batch C): {reason}")
