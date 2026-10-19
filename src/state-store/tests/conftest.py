"""Fixtures for the state-store tests: a protected bare remote with the store's branch,
and writers of one store."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from state_store import GitStateStore, MemoryStateStore, StateStore
from state_store_testkit import BRANCH, Writers, create_branch, run_git


@pytest.fixture(autouse=True)
def isolated_git_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test sees the machine's git configuration or git variables, only an identity
    to commit with."""
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
    requires, with the store's branch."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True)
    run_git(remote, "config", "receive.denyNonFastForwards", "true")
    run_git(remote, "config", "receive.denyDeletes", "true")
    create_branch(remote, BRANCH)
    return remote


@pytest.fixture(params=["memory", pytest.param("git", marks=pytest.mark.git)])
def writers(request: pytest.FixtureRequest) -> Writers:
    """Writers of one store, for the contract every implementation keeps. The memory
    writers run no git at all."""
    if request.param == "memory":
        shared: list[MemoryStateStore] = []

        def memory_writer() -> StateStore:
            if not shared:
                shared.append(MemoryStateStore())
            return shared[0]

        return Writers(new=memory_writer, other_store=MemoryStateStore)

    bare_remote: Path = request.getfixturevalue("bare_remote")
    tmp_path: Path = request.getfixturevalue("tmp_path")
    count = 0

    def git_writer() -> StateStore:
        nonlocal count
        count += 1
        return GitStateStore.clone(tmp_path / f"clone-{count}", url=str(bare_remote), branch=BRANCH)

    return Writers(new=git_writer, other_store=git_writer)
