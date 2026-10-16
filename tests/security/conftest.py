"""The security suite's markers and fixtures.

`@pytest.mark.security_bug(reason)` marks a defect in tkt's code, fixable without a design
decision; `@pytest.mark.security_design(reason)` marks a property whose fix needs a
decision. Either makes the test a strict expected failure: it must fail today, and once
the fix lands, strict mode reports it until the marker is removed.

The markers exist only for tests in this directory. They are registered here (with
`--strict-markers`, using one elsewhere is an error when this suite is not collected) and
a marked test outside this directory is a usage error when it is, so a marker never
silently means something different depending on what a run collects."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tkt_store.application.service import TicketStore
from tkt_store.domain.ticket import TicketId
from tkt_store.infrastructure.clock import FakeClock
from tkt_store.infrastructure.git.repo import GitStore
from tkt_store.infrastructure.ids import SequentialIds

HERE = Path(__file__).parent
FINDINGS = {
    "security_bug": "security bug (batch A)",
    "security_design": "security, design pending (batch C)",
}


def pytest_configure(config: pytest.Config) -> None:
    for marker, label in FINDINGS.items():
        config.addinivalue_line("markers", f"{marker}(reason): {label}, a strict xfail")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Runs for every collected test, so it checks where each marked test lives."""
    for item in items:
        for marker, label in FINDINGS.items():
            if (found := item.get_closest_marker(marker)) is None:
                continue
            if not item.path.is_relative_to(HERE):
                suite = os.path.relpath(HERE, item.config.rootpath)
                raise pytest.UsageError(f"{item.nodeid}: @pytest.mark.{marker} is only for {suite}")
            if len(found.args) != 1 or not isinstance(found.args[0], str):
                raise pytest.UsageError(f"{item.nodeid}: @pytest.mark.{marker} needs a reason")
            item.add_marker(pytest.mark.xfail(strict=True, reason=f"{label}: {found.args[0]}"))


def _store_on(clone: Path) -> TicketStore:
    """A TicketStore on `clone` with a fake clock and sequential ids (not production wiring)."""
    return TicketStore(GitStore.at(clone, remote="origin"), FakeClock(), SequentialIds())


@pytest.fixture
def honest_clone(clones: list[Path]) -> Path:
    """An honest agent's clone of an initialised store holding tkt-0001 ("Expire tokens")."""
    store = _store_on(clones[0])
    store.init()
    store.add("Expire tokens", ticket_id=TicketId("tkt-0001"))
    return clones[0]


@pytest.fixture
def tickets(honest_clone: Path) -> TicketStore:
    """The honest agent's TicketStore, on `honest_clone`."""
    return _store_on(honest_clone)
