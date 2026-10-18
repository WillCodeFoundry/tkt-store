"""Fixtures for the state-store tests: a protected bare remote with the store's branch,
clones of it made by the store, and writers.

Stores are built inside tests (fixtures return factories), so a failure to clone or
open one is part of the test, not an error in its setup.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from state_store import GitStateStore, MemoryStateStore, StateStore
from state_store_testkit import BRANCH, CloneStore, NewPath, Writers, create_branch, run_git


@pytest.fixture(autouse=True)
def isolated_git_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test sees the machine's git configuration or git variables (hooks,
    `push.followTags`, the `GIT_DIR` a git hook running the tests sets, …): only what the
    test itself sets up, and an identity to commit with. Every `GIT_*` variable goes,
    not only those the store drops, so a gap in the store's own list shows up in its
    tests."""
    for name in [name for name in os.environ if name.startswith("GIT_")] + ["EMAIL"]:
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("[user]\n\tname = writer\n\temail = writer@example.invalid\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    """A bare repository acting as the shared remote, protected as state-store README
    requires, with the store's branch created as the README says: one commit of the
    empty tree."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True)
    run_git(remote, "config", "receive.denyNonFastForwards", "true")
    run_git(remote, "config", "receive.denyDeletes", "true")
    create_branch(remote, BRANCH)
    return remote


@pytest.fixture
def new_path(tmp_path: Path) -> NewPath:
    """Makes a new path that does not exist yet, for the store to clone to."""
    count = 0

    def make() -> Path:
        nonlocal count
        count += 1
        return tmp_path / "stores" / f"store-{count}"

    (tmp_path / "stores").mkdir()
    return make


@pytest.fixture
def clone_store(bare_remote: Path, new_path: NewPath) -> CloneStore:
    """Clones `bare_remote`'s `BRANCH` with the store, to a new path unless one is given."""

    def clone(
        path: Path | None = None, *, url: str | None = None, branch: str = BRANCH
    ) -> GitStateStore:
        return GitStateStore.clone(
            path or new_path(), url=str(bare_remote) if url is None else url, branch=branch
        )

    return clone


@pytest.fixture(params=["memory", pytest.param("git", marks=pytest.mark.git)])
def writers(request: pytest.FixtureRequest) -> Writers:
    """Writers of one store, for the contract every implementation keeps. The memory
    writers run no git at all (pre-commit runs them as tests that need no git)."""
    if request.param == "memory":
        shared: list[MemoryStateStore] = []

        def memory_writer() -> StateStore:
            if not shared:
                shared.append(MemoryStateStore())
            return shared[0]

        return Writers(new=memory_writer, other_store=MemoryStateStore)

    clone_store: CloneStore = request.getfixturevalue("clone_store")
    return Writers(new=clone_store, other_store=clone_store)
