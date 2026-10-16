"""Fixtures for the security tests, and the markers that record each finding.

`@pytest.mark.security_bug(reason)` marks a defect in tkt's code (batch A), fixable
without a design decision; `@pytest.mark.security_design(reason)` marks a property whose
fix still needs a decision (batch C), pinned without fixing the fix's shape. Both make
the test a strict expected failure: it must fail today, and once its fix lands it
passes, which strict mode reports until the marker is removed."""

from __future__ import annotations

from pathlib import Path

import pytest

from tkt_store.application.service import TicketStore
from tkt_store.domain.ticket import TicketId
from tkt_store.infrastructure.clock import FakeClock
from tkt_store.infrastructure.git.repo import GitStore
from tkt_store.infrastructure.ids import SequentialIds

FINDINGS = {
    "security_bug": "security bug (batch A)",
    "security_design": "security, design pending (batch C)",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        for marker, label in FINDINGS.items():
            if (found := item.get_closest_marker(marker)) is not None:
                reason = f"{label}: {found.args[0]}"
                item.add_marker(pytest.mark.xfail(strict=True, reason=reason))


@pytest.fixture
def tickets(clones: list[Path]) -> TicketStore:
    """An honest agent's store, in its own clone, holding tkt-1 ("Expire tokens")."""
    store = TicketStore(GitStore.at(clones[0], remote="origin"), FakeClock(), SequentialIds())
    store.init()
    store.add("Expire tokens", ticket_id=TicketId("tkt-1"))
    return store


@pytest.fixture
def clone(tickets: TicketStore, clones: list[Path]) -> Path:
    """The honest agent's clone (the one `tickets` uses)."""
    return clones[0]
