"""Fixtures shared by every suite (clock, ids, stores, a bare remote and its clones), and
the hook that turns the security markers into strict expected failures. Fakes are
injected, never patched in (AGENTS.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.gitkit import clone, new_repo
from tkt_store.infrastructure.clock import FakeClock
from tkt_store.infrastructure.git.repo import GitStore
from tkt_store.infrastructure.ids import SequentialIds
from tkt_store.infrastructure.memory import MemStore

SECURITY_FINDINGS = {
    "security_bug": "security bug (batch A)",
    "security_design": "security, design pending (batch C)",
}
"""`@pytest.mark.security_bug(reason)` marks a security defect in tkt's code, fixable
without a design decision; `@pytest.mark.security_design(reason)` marks a security
property whose fix needs a decision (see tests/security). Either makes the test a strict
expected failure: it must fail today, and once the fix lands, strict mode reports it until
the marker is removed. Applied here, at the root, so a marked test behaves the same
whichever directories a run collects."""


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        for marker, label in SECURITY_FINDINGS.items():
            if (found := item.get_closest_marker(marker)) is None:
                continue
            if len(found.args) != 1 or not isinstance(found.args[0], str):
                raise pytest.UsageError(f"{item.nodeid}: @pytest.mark.{marker} needs a reason")
            item.add_marker(pytest.mark.xfail(strict=True, reason=f"{label}: {found.args[0]}"))


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def ids() -> SequentialIds:
    return SequentialIds()


@pytest.fixture
def memstore() -> MemStore:
    return MemStore()


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    """An empty bare repository acting as the shared remote."""
    return new_repo(tmp_path / "remote.git", bare=True)


@pytest.fixture
def clones(tmp_path: Path, bare_remote: Path) -> list[Path]:
    """Two independent clones of `bare_remote`, each usable by its own GitStore."""
    return [clone(bare_remote, tmp_path / name) for name in ("clone-a", "clone-b")]


@pytest.fixture
def gitstore(clones: list[Path]) -> GitStore:
    """A GitStore in a clone of `bare_remote`."""
    return GitStore.at(clones[0], remote="origin")
