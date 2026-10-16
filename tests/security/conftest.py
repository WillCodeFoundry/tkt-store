"""Fixtures for the security tests (their markers are applied in tests/conftest.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tkt_store.application.service import TicketStore
from tkt_store.domain.ticket import TicketId
from tkt_store.infrastructure.clock import FakeClock
from tkt_store.infrastructure.git.repo import GitStore
from tkt_store.infrastructure.ids import SequentialIds


def _store_on(clone: Path) -> TicketStore:
    """A TicketStore on `clone` with a fake clock and sequential ids (not production wiring)."""
    return TicketStore(GitStore.at(clone, remote="origin"), FakeClock(), SequentialIds())


@pytest.fixture
def honest_clone(clones: list[Path]) -> Path:
    """An honest agent's clone of an initialised store holding tkt-1 ("Expire tokens")."""
    store = _store_on(clones[0])
    store.init()
    store.add("Expire tokens", ticket_id=TicketId("tkt-1"))
    return clones[0]


@pytest.fixture
def tickets(honest_clone: Path) -> TicketStore:
    """The honest agent's TicketStore, on `honest_clone`."""
    return _store_on(honest_clone)
