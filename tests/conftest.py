"""Shared fixtures. Fakes are injected, never patched in (AGENTS.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.gitkit import clone, new_repo
from tkt_store.infrastructure.clock import FakeClock
from tkt_store.infrastructure.git.repo import GitStore
from tkt_store.infrastructure.ids import SequentialIds
from tkt_store.infrastructure.memory import MemStore


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
