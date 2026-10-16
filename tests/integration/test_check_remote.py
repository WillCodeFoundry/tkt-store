"""scripts/check_remote.py against real bare remotes, protected and not."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.gitkit import git, head
from tkt_store.application.service import TicketStore
from tkt_store.infrastructure.clock import FakeClock
from tkt_store.infrastructure.git.repo import GitStore
from tkt_store.infrastructure.ids import SequentialIds

pytestmark = pytest.mark.git

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_remote.py"


def check(clone: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(clone), "--remote", "origin"],
        capture_output=True,
        text=True,
    )


def protect(bare: Path) -> None:
    git(bare, "config", "receive.denyNonFastForwards", "true")
    git(bare, "config", "receive.denyDeletes", "true")


@pytest.fixture
def store(clones: list[Path], bare_remote: Path) -> Path:
    """A store with one ticket; returns the clone."""
    tickets = TicketStore(GitStore.at(clones[0], remote="origin"), FakeClock(), SequentialIds())
    tickets.init()
    tickets.add("Keep me")
    return clones[0]


def test_a_protected_remote_passes(store: Path, bare_remote: Path) -> None:
    protect(bare_remote)
    before = head(bare_remote)
    result = check(store)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("PASS") == 2 and "FAIL" not in result.stdout
    assert head(bare_remote) == before


def test_an_unprotected_remote_fails_and_the_branch_is_restored(
    store: Path, bare_remote: Path
) -> None:
    before = head(bare_remote)
    result = check(store)
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stdout.count("FAIL") == 2 and result.stdout.count("restored") == 2
    assert head(bare_remote) == before
    assert int(git(bare_remote, "rev-list", "--count", before)) == 2  # init + add, intact


def test_deletion_protection_alone_is_reported_per_check(store: Path, bare_remote: Path) -> None:
    git(bare_remote, "config", "receive.denyDeletes", "true")
    result = check(store)
    assert result.returncode == 1
    lines = result.stdout.splitlines()
    assert any(line.startswith("FAIL  refuses a non-fast-forward push") for line in lines)
    assert any(line.startswith("PASS  refuses deleting the branch") for line in lines)


def test_an_uninitialised_remote_is_not_probed(clones: list[Path]) -> None:
    result = check(clones[0])
    assert result.returncode == 2 and "tkt init" in result.stdout


def test_a_branch_that_is_not_a_store_is_not_probed(clones: list[Path], bare_remote: Path) -> None:
    clone = clones[0]
    git(clone, "commit", "--allow-empty", "-q", "-m", "not a store")
    git(clone, "push", "-q", "origin", "HEAD:refs/heads/tkt-store")
    before = head(bare_remote)
    result = check(clone)
    assert result.returncode == 2 and "not a tkt store" in result.stdout
    assert head(bare_remote) == before
