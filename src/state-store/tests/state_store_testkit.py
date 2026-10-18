"""What the state-store tests share besides fixtures: running git, and the writer types."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from state_store import StateStore

BRANCH = "state"


def run_git(cwd: Path, *args: str, stdin: bytes | None = None) -> str:
    """Run plain git in `cwd`, as a person (or a forger) would; raises on failure."""
    result = subprocess.run(
        ["git", "-C", str(cwd), *args], input=stdin, capture_output=True, check=True
    )
    return result.stdout.decode()


MakeClone = Callable[..., Path]
"""`make_clone(*clone_args, url=None, identity=True)`: a new clone of the test remote
(from `url` if given, e.g. a `file://` URL for shallow and partial clones)."""


# --- Forging: writing a branch with plain git, as someone bypassing the store would ----

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


def publish(repo: Path, root: str, message: str = "forged") -> str:
    """Commit tree `root` on top of the remote's branch (if any) and push it; its id."""
    run_git(repo, "fetch", "--quiet", "origin")
    parents = (
        ["-p", f"origin/{BRANCH}"]
        if run_git(repo, "ls-remote", "origin", f"refs/heads/{BRANCH}").strip()
        else []
    )
    commit = run_git(repo, "commit-tree", root, *parents, "-m", message).strip()
    run_git(repo, "push", "--quiet", "origin", f"{commit}:refs/heads/{BRANCH}")
    return commit


@dataclass(frozen=True)
class Writers:
    """Writers of one shared store, as the agents sharing it would have them."""

    new: Callable[[], StateStore]
    """Another writer of the shared store (for git, a store on a new clone)."""

    other_store: Callable[[], StateStore]
    """A store object that is not the shared one's (for memory, a separate instance)."""
