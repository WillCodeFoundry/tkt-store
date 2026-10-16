"""Real-git helpers for tests: repositories with local config, out-of-band commits, and
GitRunner wrappers that interleave or fail commands on purpose (injected, not patched)."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

from tkt_store.infrastructure.git.runner import GitRunner, git_runner
from tkt_store.infrastructure.git.wire import DEFAULT_REF

LOCAL_CONFIG = {
    "user.name": "tkt-store tests",
    "user.email": "tests@tkt-store.invalid",
    "commit.gpgsign": "false",
}
"""Per-repository config, so tests never depend on (or sign with) the developer's."""


def git(repo: Path, *args: str, env: Mapping[str, str] | None = None) -> str:
    """Run git in `repo` for test setup and inspection."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=None if env is None else {**os.environ, **env},
    )
    return result.stdout


def configure(repo: Path) -> Path:
    for key, value in LOCAL_CONFIG.items():
        git(repo, "config", key, value)
    return repo


def new_repo(path: Path, *, bare: bool = False) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "--quiet", *(["--bare"] if bare else []))
    return configure(path)


def clone(remote: Path, path: Path) -> Path:
    subprocess.run(
        ["git", "clone", "--quiet", str(remote), str(path)], capture_output=True, check=True
    )
    return configure(path)


def head(repo: Path, ref: str = DEFAULT_REF) -> str:
    return git(repo, "rev-parse", ref).strip()


def show(repo: Path, path: str, ref: str = DEFAULT_REF) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), "show", f"{ref}:{path}"], capture_output=True, check=True
    ).stdout


def paths(repo: Path, ref: str = DEFAULT_REF) -> set[str]:
    return set(git(repo, "ls-tree", "-r", "--name-only", ref).split())


def write_files(
    repo: Path,
    files: Mapping[str, bytes | None] | Mapping[bytes, bytes | None],
    *,
    ref: str = DEFAULT_REF,
    message: str = "edited by hand\n",
) -> str:
    """Commit `files` on top of `ref` (None deletes a path) without touching any worktree,
    as a person repairing the branch would. Paths may be bytes (any file name git allows).
    Moves `ref`; returns the new commit."""
    index = repo / "tkt-test-index"
    env = {"GIT_INDEX_FILE": str(index)}
    parent = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", ref],
        capture_output=True,
        text=True,
    ).stdout.strip()
    git(repo, "read-tree", *([parent] if parent else ["--empty"]), env=env)
    for path, data in files.items():
        name = path.decode(errors="surrogateescape") if isinstance(path, bytes) else path
        if data is None:  # an index entry with mode 0 removes the path (works in a bare repo)
            subprocess.run(
                ["git", "-C", str(repo), "update-index", "--index-info"],
                input=f"0 {'0' * 40}\t{name}\n",
                text=True,
                check=True,
                env={**os.environ, **env},
            )
            continue
        blob = (
            subprocess.run(
                ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
                input=data,
                capture_output=True,
                check=True,
            )
            .stdout.decode()
            .strip()
        )
        git(repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},{name}", env=env)
    tree = git(repo, "write-tree", env=env).strip()
    index.unlink()
    commit = subprocess.run(
        ["git", "-C", str(repo), "commit-tree", tree, *(["-p", parent] if parent else [])],
        input=message,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    git(repo, "update-ref", ref, commit)
    return commit


class HookedRunner:
    """A real git_runner that calls `hook(args)` before every command, and `after(args)`
    after every successful one. A hook may raise to simulate a failure or a crash, or run
    another writer to interleave deterministically."""

    def __init__(
        self,
        repo: Path,
        hook: Callable[[tuple[str, ...]], None] = lambda args: None,
        after: Callable[[tuple[str, ...]], None] = lambda args: None,
    ) -> None:
        self._run: GitRunner = git_runner(repo)
        self.hook, self.after = hook, after
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str, stdin: bytes | None = None) -> bytes:
        self.calls.append(args)
        self.hook(args)
        out = self._run(*args, stdin=stdin)
        self.after(args)
        return out


def once(command: str, action: Callable[[], object]) -> Callable[[tuple[str, ...]], None]:
    """A hook that runs `action` the first time `git <command>` is called."""
    fired = [False]

    def hook(args: tuple[str, ...]) -> None:
        if args[0] == command and not fired[0]:
            fired[0] = True
            action()

    return hook
