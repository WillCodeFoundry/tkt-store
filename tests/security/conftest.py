"""The fixture the security tests share: a store with one honest ticket."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.security.support import T1, service


@pytest.fixture
def clone(clones: list[Path]) -> Path:
    """An honest agent's clone of a store holding T1 ("Expire tokens")."""
    tickets = service(clones[0])
    tickets.init()
    tickets.add("Expire tokens", ticket_id=T1)
    return clones[0]
