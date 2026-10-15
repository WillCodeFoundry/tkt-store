"""Running git commands: the one seam between this package and the git binary.

`GitRunner` is the narrow interface the rest of the git adapter calls; injecting
it lets tests record commands or simulate failures without patching. The
production runner shells out with `git -C <repo> ...`.
"""

from __future__ import annotations

import subprocess  # noqa: F401  (used by the production runner, below)
from pathlib import Path
from typing import Protocol


class GitRunner(Protocol):
    """Runs one git command in the store repository and returns stdout as raw bytes.

    Bytes, not text: `git cat-file --batch` reports object sizes in bytes, so decoding
    first would misparse any non-ASCII content. Callers decode what they know is text.
    Raises StoreError on a non-zero exit, except where a caller handles a known code.
    """

    def __call__(self, *args: str, stdin: bytes | None = None) -> bytes: ...


def git_runner(repo: Path) -> GitRunner:
    """The production GitRunner: `git -C <repo> ...`, raising StoreError on a non-zero exit."""
    raise NotImplementedError
