"""Real-git helpers for tests: repositories with local config, out-of-band commits, and
GitRunner wrappers that interleave or fail commands on purpose (injected, not patched)."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal, overload

from tkt_store.infrastructure.git.runner import GitRunner, git_runner
from tkt_store.infrastructure.git.wire import DEFAULT_REF

LOCAL_CONFIG = {
    "user.name": "tkt-store tests",
    "user.email": "tests@tkt-store.invalid",
    "commit.gpgsign": "false",
}
"""Per-repository config, so tests never depend on (or sign with) the developer's."""


@overload
def git(
    repo: Path,
    *args: str,
    env: Mapping[str, str] | None = None,
    stdin: str | bytes | None = None,
    check: bool = True,
    raw: Literal[False] = False,
) -> str: ...
@overload
def git(
    repo: Path,
    *args: str,
    env: Mapping[str, str] | None = None,
    stdin: str | bytes | None = None,
    check: bool = True,
    raw: Literal[True],
) -> bytes: ...
def git(
    repo: Path,
    *args: str,
    env: Mapping[str, str] | None = None,
    stdin: str | bytes | None = None,
    check: bool = True,
    raw: bool = False,
) -> str | bytes:
    """Run git in `repo` for test setup and inspection; returns its output as text, or as
    bytes when `raw` (file contents, `-z` listings with non-UTF-8 names)."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=stdin.encode() if isinstance(stdin, str) else stdin,
        capture_output=True,
        check=check,
        env=None if env is None else {**os.environ, **env},
    )
    return result.stdout if raw else result.stdout.decode()


def configure(repo: Path) -> Path:
    for key, value in LOCAL_CONFIG.items():
        git(repo, "config", key, value)
    return repo


def new_repo(path: Path, *, bare: bool = False) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "--quiet", *(["--bare"] if bare else []))
    return configure(path)


def clone(remote: Path, path: Path) -> Path:
    git(path.parent, "clone", "--quiet", str(remote), str(path))
    return configure(path)


def head(repo: Path, ref: str = DEFAULT_REF) -> str:
    return git(repo, "rev-parse", ref).strip()


def show(repo: Path, path: str, ref: str = DEFAULT_REF) -> bytes:
    return git(repo, "show", f"{ref}:{path}", raw=True)


def paths(repo: Path, ref: str = DEFAULT_REF) -> set[str]:
    return set(git(repo, "ls-tree", "-r", "--name-only", ref).split())


FileContent = bytes | Mapping[str, Any] | None
"""What `write_files` commits at a path: raw bytes, a dict written as JSON, or None to
delete the path."""


def write_files(
    repo: Path,
    files: Mapping[str, FileContent] | Mapping[bytes, FileContent],
    *,
    ref: str = DEFAULT_REF,
    message: str = "edited by hand\n",
    modes: Mapping[str, str] | None = None,
) -> str:
    """Commit `files` on top of `ref` without touching any worktree, as a person repairing
    the branch (or an agent bypassing tkt) would. Paths may be bytes (any file name git
    allows); `modes` gives a path another git mode than 100644, e.g. 120000 for a symlink
    whose target is the data. Moves `ref`; returns the new commit."""
    env = {"GIT_INDEX_FILE": str(repo / "tkt-test-index")}
    parent = git(repo, "rev-parse", "--verify", "--quiet", ref, check=False).strip()
    git(repo, "read-tree", *([parent] if parent else ["--empty"]), env=env)
    for path, content in files.items():
        name = path.decode(errors="surrogateescape") if isinstance(path, bytes) else path
        if content is None:  # an index entry with mode 0 removes the path (works in a bare repo)
            git(repo, "update-index", "--index-info", env=env, stdin=f"0 {'0' * 40}\t{name}\n")
            continue
        data = content if isinstance(content, bytes) else json.dumps(content).encode()
        blob = git(repo, "hash-object", "-w", "--stdin", stdin=data).strip()
        mode = (modes or {}).get(name, "100644")
        git(repo, "update-index", "--add", "--cacheinfo", f"{mode},{blob},{name}", env=env)
    tree = git(repo, "write-tree", env=env).strip()
    (repo / "tkt-test-index").unlink()
    parents = ["-p", parent] if parent else []
    commit = git(repo, "commit-tree", tree, *parents, stdin=message).strip()
    git(repo, "update-ref", ref, commit)
    return commit


class HookedRunner:
    """A real git_runner that records every call, calls `hook(args)` before every command,
    and `after(args)` after every successful one. A hook may raise to simulate a failure or
    a crash, or run another writer to interleave deterministically.

    `calls` holds each call's arguments, and `inputs` what it got on standard input (b""
    for none); `count` and `inputs_to` query them by command."""

    def __init__(
        self,
        repo: Path,
        hook: Callable[[tuple[str, ...]], None] = lambda args: None,
        after: Callable[[tuple[str, ...]], None] = lambda args: None,
    ) -> None:
        self._run: GitRunner = git_runner(repo)
        self.hook, self.after = hook, after
        self.calls: list[tuple[str, ...]] = []
        self.inputs: list[bytes] = []

    def count(self, *command: str) -> int:
        """How many calls started with `command` (e.g. "gc")."""
        return sum(args[: len(command)] == command for args in self.calls)

    def inputs_to(self, *command: str) -> list[bytes]:
        """What each call starting with `command` (e.g. "mktree") got on standard input."""
        calls = zip(self.calls, self.inputs, strict=True)
        return [data for args, data in calls if args[: len(command)] == command]

    def __call__(self, *args: str, stdin: bytes | None = None) -> bytes:
        self.calls.append(args)
        self.inputs.append(stdin or b"")
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
