"""What the state-store tests share besides fixtures: running git, and the writer types."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from state_store import StateStore

BRANCH = "state"


def run_git(cwd: Path, *args: str, stdin: bytes | None = None) -> str:
    """Run plain git in `cwd`; raises on failure."""
    result = subprocess.run(
        ["git", "-C", str(cwd), *args], input=stdin, capture_output=True, check=True
    )
    return result.stdout.decode()


def create_branch(remote: Path, branch: str) -> str:
    """Create `branch` on `remote` with one commit of the empty tree, as state-store
    README requires before the first clone; its id."""
    empty = run_git(remote, "hash-object", "-t", "tree", "/dev/null").strip()
    commit = run_git(remote, "commit-tree", empty, "-m", "Create the store").strip()
    run_git(remote, "update-ref", f"refs/heads/{branch}", commit, "")
    return commit


@dataclass(frozen=True)
class Writers:
    """Writers of one shared store, as the processes sharing it would have them."""

    new: Callable[[], StateStore]
    """Another writer of the shared store (for git, a store on a new clone)."""

    other_store: Callable[[], StateStore]
    """A store object that is not the shared one's (for memory, a separate instance)."""
