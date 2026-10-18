"""What the state-store tests share besides fixtures: running git, forging, and the
writer types."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from state_store import GitStateStore, StateStore

BRANCH = "state"


def run_git(cwd: Path, *args: str, stdin: bytes | None = None) -> str:
    """Run plain git in `cwd` (a store's clone, or the remote), as a person (or a
    forger) would; raises on failure."""
    result = subprocess.run(
        ["git", "-C", str(cwd), *args], input=stdin, capture_output=True, check=True
    )
    return result.stdout.decode()


NewPath = Callable[[], Path]
"""`new_path()`: a path that does not exist yet, in a directory that does."""

CloneStore = Callable[..., GitStateStore]
"""`clone_store(path=None, *, url=None, branch=BRANCH)`: `GitStateStore.clone` of the
test remote, given as a path (or of `url`), to `path`, or to a new path if none is
given."""

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
"""The empty tree's id in a SHA-1 repository, such as the test remote."""


def create_branch(remote: Path, branch: str) -> str:
    """Create `branch` on `remote` with one commit of the empty tree (in the remote's
    object format), as state-store README says to before the first clone; its id."""
    empty = run_git(remote, "hash-object", "-t", "tree", "/dev/null").strip()
    commit = run_git(remote, "commit-tree", empty, "-m", "Create the store").strip()
    run_git(remote, "update-ref", f"refs/heads/{branch}", commit, "")
    return commit


# --- Forging: writing the remote's branch with plain git, bypassing the store ---------

REGULAR, EXECUTABLE, SYMLINK, SUBMODULE, DIRECTORY = (
    "100644",
    "100755",
    "120000",
    "160000",
    "040000",
)


def blob(repo: Path, data: bytes) -> str:
    """Store `data` as a blob in `repo`; its id."""
    return run_git(repo, "hash-object", "-w", "--stdin", stdin=data).strip()


def tree(repo: Path, entries: list[tuple[str, str, str]]) -> str:
    """A tree of `(mode, object id, name)` entries, exactly as given (duplicates too)."""
    kinds = {REGULAR: "blob", EXECUTABLE: "blob", SYMLINK: "blob", SUBMODULE: "commit"}
    lines = b"".join(
        f"{mode} {kinds.get(mode, 'tree')} {oid}\t{name}".encode() + b"\0"
        for mode, oid, name in entries
    )
    return run_git(repo, "mktree", "-z", "--missing", stdin=lines).strip()


def publish(remote: Path, root: str, message: str = "forged") -> str:
    """Commit tree `root` (made in `remote`) on top of the remote's branch, and move the
    branch to it; its id."""
    tip = run_git(remote, "rev-parse", f"refs/heads/{BRANCH}").strip()
    commit = run_git(remote, "commit-tree", root, "-p", tip, "-m", message).strip()
    run_git(remote, "update-ref", f"refs/heads/{BRANCH}", commit, tip)
    return commit


@dataclass(frozen=True)
class Writers:
    """Writers of one shared store, as the processes sharing it would have them."""

    new: Callable[[], StateStore]
    """Another writer of the shared store (for git, a store with its own repository)."""

    other_store: Callable[[], StateStore]
    """A store object that is not the shared one's (for memory, a separate instance)."""
