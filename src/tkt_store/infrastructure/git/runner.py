"""Running git commands: the one seam between this package and the git binary.

`GitRunner` is the narrow interface the rest of the git adapter calls; injecting
it lets tests record commands or simulate failures without patching. The
production runner shells out with `git -C <repo> ...`.

What git prints when a command that talks to the remote fails can quote the server
(hook output, an SSH server's own errors, a redirect's target), and a server can write
anything there, lines that look like git's own included. So such a failure reaches
agents only as a category; git's text goes to an operator's log (ADR 0005).
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Protocol

from tkt_store.application.errors import StoreError

REMOTE_COMMANDS = frozenset({"fetch", "push", "ls-remote"})
"""The git commands tkt runs that talk to the remote."""

LOG_MAX = 1024 * 1024
"""Bytes in the error log before it is moved to `<name>.1`, replacing an older one."""

CATEGORIES = (
    ("the remote refused access (authentication or permissions)",
     ("Authentication failed", "Permission denied", "could not read Username",
      "could not read Password", "terminal prompts disabled", "returned error: 401",
      "returned error: 403", "Host key verification failed")),
    ("the remote repository was not found, or the remote is not configured",
     ("not found", "does not appear to be a git repository", "No such file or directory",
      "returned error: 404")),
    ("the remote could not be reached",
     ("Could not resolve host", "Couldn't resolve host", "Connection refused",
      "timed out", "Network is unreachable", "No route to host", "Connection reset",
      "the remote end hung up", "early EOF", "unable to access")),
)  # fmt: skip
"""What a failure to reach the remote is, by git's own wording (LC_ALL=C), first match
wins. A server can mimic a wording, so it chooses the category at most, never text."""
UNRECOGNISED = "an unrecognised failure"


def category(stderr: str) -> str:
    """The category of a failed remote command from git's `stderr`: never its text."""
    for name, wordings in CATEGORIES:
        if any(wording in stderr for wording in wordings):
            return name
    return UNRECOGNISED


class GitError(StoreError):
    """A git command exited non-zero. Carries what callers need to recognise a known
    failure (e.g. `ls-remote --exit-code` 2 = no such ref, a rejected push).

    The message holds git's own text for a local command, but only its `category` for
    one that talks to the remote, and then says where git's text was logged (`log`).
    `stderr` is git's text in full: it may quote the server, so it is never printed."""

    def __init__(
        self,
        args: tuple[str, ...],
        returncode: int,
        stdout: bytes,
        stderr: str,
        *,
        log: Path | None = None,
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.logged = (
            f"; git's own message, which may quote the server, is logged in {log}" if log else ""
        )
        command = f"git {' '.join(args)} failed ({returncode})"
        if args[:1] and args[0] in REMOTE_COMMANDS:
            super().__init__(f"{command}: {category(stderr)}{self.logged}")
        else:
            super().__init__(f"{command}: {stderr.strip()}")


class GitRunner(Protocol):
    """Runs one git command in the store repository and returns stdout as raw bytes.

    Bytes, not text: `git cat-file --batch` reports object sizes in bytes, so decoding
    first would misparse any non-ASCII content. Callers decode what they know is text.
    Raises GitError (a StoreError) on a non-zero exit; callers handle known codes.
    """

    def __call__(self, *args: str, stdin: bytes | None = None) -> bytes: ...


def git_runner(
    repo: Path, *, log: Path | None = None, now: Callable[[], int] | None = None
) -> GitRunner:
    """The production GitRunner: `git -C <repo> ...`, never prompting for credentials,
    raising GitError on a non-zero exit and StoreError if git is not installed.
    Output is untranslated (LC_ALL=C) so callers can recognise known failures. With
    `log`, a failed remote command's text is appended there for an operator, stamped
    with `now()` (Unix seconds) when given."""
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
            logged = None
            if log is not None and args[:1] and args[0] in REMOTE_COMMANDS:
                stamp = None if now is None else now()
                logged = _append(log, stamp, args, result.returncode, result.stderr)
            raise GitError(args, result.returncode, result.stdout, stderr, log=logged)
        return result.stdout

    return run


def _append(
    log: Path, stamp: int | None, args: tuple[str, ...], returncode: int, stderr: bytes
) -> Path | None:
    """Append one failure to `log`, moving a full log to `<name>.1` first. Returns `log`,
    or None if it could not be written: logging never fails an op."""
    when = "" if stamp is None else f"at {stamp} "
    entry = f"--- {when}git {' '.join(args)} ({returncode})\n".encode() + stderr + b"\n"
    with suppress(OSError):
        log.parent.mkdir(parents=True, exist_ok=True)
        with suppress(FileNotFoundError):
            if log.stat().st_size + len(entry) > LOG_MAX:
                os.replace(log, log.with_name(log.name + ".1"))
        with log.open("ab") as out:
            out.write(entry)
        return log
    return None
