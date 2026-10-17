"""Running git commands: the one seam between this package and the git binary.

`GitRunner` is the narrow interface the rest of the git adapter calls; injecting
it lets tests record commands or simulate failures without patching. The
production runner shells out with `git -C <repo> ...`.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Protocol

from tkt_store.application.errors import StoreError

SERVER_TEXT_OMITTED = "(the server's text is omitted)"


def own_text(stderr: str) -> str:
    """git's own lines from `stderr`, without any text a server chose: `remote:` lines
    (hook and server output) and `remote error:` messages. Error messages reach agents,
    and a server, or a hook planted in a path remote, can write anything (ADR 0005)."""
    lines = stderr.strip().splitlines()
    own = [line for line in lines if not line.startswith("remote:") and "remote error:" not in line]
    if len(own) < len(lines):
        own.append(SERVER_TEXT_OMITTED)
    return "\n".join(own)


class GitError(StoreError):
    """A git command exited non-zero. Carries what callers need to recognise a known
    failure (e.g. `ls-remote --exit-code` 2 = no such ref, a rejected push). `stderr`
    holds git's own text only (`own_text`)."""

    def __init__(self, args: tuple[str, ...], returncode: int, stdout: bytes, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = own_text(stderr)
        super().__init__(f"git {' '.join(args)} failed ({returncode}): {self.stderr}")


class GitRunner(Protocol):
    """Runs one git command in the store repository and returns stdout as raw bytes.

    Bytes, not text: `git cat-file --batch` reports object sizes in bytes, so decoding
    first would misparse any non-ASCII content. Callers decode what they know is text.
    Raises GitError (a StoreError) on a non-zero exit; callers handle known codes.
    """

    def __call__(self, *args: str, stdin: bytes | None = None) -> bytes: ...


def git_runner(repo: Path) -> GitRunner:
    """The production GitRunner: `git -C <repo> ...`, never prompting for credentials,
    raising GitError on a non-zero exit and StoreError if git is not installed.
    Output is untranslated (LC_ALL=C) so callers can recognise known failures."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}

    def run(*args: str, stdin: bytes | None = None) -> bytes:
        try:
            result = subprocess.run(
                ["git", "-C", str(repo), *args],
                input=stdin,
                capture_output=True,
                env=env,
                check=False,
            )
        except FileNotFoundError as error:
            raise StoreError("the git binary is not installed") from error
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            raise GitError(args, result.returncode, result.stdout, stderr)
        return result.stdout

    return run
