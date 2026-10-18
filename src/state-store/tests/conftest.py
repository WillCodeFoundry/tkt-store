"""Fixtures for the state-store tests: a protected bare remote, clones of it, and writers.

Stores are built inside tests (fixtures return factories), so a failure to open one is
part of the test, not an error in its setup.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from state_store import GitStateStore, MemoryStateStore, StateStore
from state_store_testkit import BRANCH, MakeClone, Writers, run_git


@pytest.fixture(autouse=True)
def isolated_git_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test sees the machine's git configuration or git variables (an identity, hooks,
    `push.followTags`, the `GIT_DIR` a git hook running the tests sets, …): only what the
    test itself sets up. Every `GIT_*` variable goes, not only those the store drops, so
    a gap in the store's own list shows up in its tests."""
    for name in [name for name in os.environ if name.startswith("GIT_")] + ["EMAIL"]:
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    """A bare repository acting as the shared remote, protected as state-store.md requires."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True)
    run_git(remote, "config", "receive.denyNonFastForwards", "true")
    run_git(remote, "config", "receive.denyDeletes", "true")
    return remote


@pytest.fixture
def make_clone(tmp_path: Path, bare_remote: Path) -> MakeClone:
    """Makes a new clone of `bare_remote` without a checkout, with a git identity."""
    count = 0

    def make(*clone_args: str, url: str | None = None, identity: bool = True) -> Path:
        nonlocal count
        count += 1
        path = tmp_path / f"clone-{count}"
        source = url or str(bare_remote)
        subprocess.run(
            ["git", "clone", "--quiet", "--no-checkout", *clone_args, source, str(path)],
            check=True,
            capture_output=True,
        )
        if identity:
            run_git(path, "config", "user.name", f"writer-{count}")
            run_git(path, "config", "user.email", f"writer-{count}@example.invalid")
        return path

    return make


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

    make_clone: MakeClone = request.getfixturevalue("make_clone")

    def git_writer() -> StateStore:
        return GitStateStore(make_clone(), remote="origin", branch=BRANCH)

    return Writers(new=git_writer, other_store=git_writer)
