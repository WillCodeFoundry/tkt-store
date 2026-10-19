"""Running git: the one place this package starts a process (state-store design,
*Running git*).

Every command is an argument list, never a shell, with hooks off, and without the
inherited variables that would point git at another repository.
"""

from __future__ import annotations

from pathlib import Path

DROPPED_VARIABLES = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    }
)
"""Inherited variables that would make git use another repository's data."""


class GitFailure(Exception):
    """A git command exited non-zero. The store turns it into one of its own errors."""

    def __init__(self, command: str, returncode: int, stderr: bytes) -> None:
        super().__init__(f"git {command} failed ({returncode})")
        self.command = command
        self.returncode = returncode
        self.stderr = stderr


class Runner:
    """Runs git in one directory."""

    def __init__(self, path: Path) -> None:
        raise NotImplementedError

    def __call__(self, *args: str, stdin: bytes | None = None) -> bytes:
        """The stdout of `git -C <path> -c core.hooksPath=/dev/null <args>`; `GitFailure`
        on a non-zero exit."""
        raise NotImplementedError
