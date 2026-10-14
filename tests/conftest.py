"""Shared fixtures. Fakes are injected, never patched in (AGENTS.md)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tkt_store.infrastructure.clock import FakeClock
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
    """An empty bare repository acting as the shared remote (skeleton: not created yet)."""
    return tmp_path / "remote.git"


@pytest.fixture
def clones(tmp_path: Path, bare_remote: Path) -> Iterator[list[Path]]:
    """Two independent clones of `bare_remote`, each usable by its own GitStore (skeleton)."""
    yield [tmp_path / "clone-a", tmp_path / "clone-b"]
