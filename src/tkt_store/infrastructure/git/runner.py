"""Running git commands: the one seam between this package and the git binary.

`GitRunner` is the narrow interface the rest of the git adapter calls; injecting
it lets tests record commands or simulate failures without patching. The
production runner shells out with `git -C <repo> ...`.

No git error's text reaches agents: a command that talks to the remote can quote the
server (hook output, an SSH server's own errors, a redirect's target), which can write
anything there, lines that look like git's own included; and a local command can quote
a file name read from the store, which a forger chose. So a failure reaches agents only
as a category; git's text goes to an operator's log (ADR 0005).
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Protocol

from tkt_store.application.errors import StoreError

REMOTE_COMMANDS = frozenset({"fetch", "push", "ls-remote"})
"""The git commands tkt runs that talk to the remote. No other command does: lazy
fetches are off, and partial clones are refused (`git_runner`, `GitStore.at`)."""

LOG_MAX = 1024 * 1024
"""Bytes in the error log before it is moved to `<name>.1`, replacing an older one."""

NOT_A_REPOSITORY = (
    "the clone is not a git repository",
    ("not a git repository (or any of the parent", "cannot change to"),
)
"""git's wording about the clone itself, never what a server could print about its own
repository."""
REMOTE_CATEGORIES = (
    NOT_A_REPOSITORY,
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
"""What a failed remote command is, by git's own wording (LC_ALL=C), first match wins.
A server can mimic a wording, so it chooses the category at most, never text."""
LOCAL_CATEGORIES = (NOT_A_REPOSITORY,)
UNRECOGNISED = "an unrecognised failure"
LOCAL_FAILURE = "a local git command failed"

LOGGED = "; git's own text is in the clone's error log, for an operator"


def category(args: tuple[str, ...], stderr: str) -> str:
    """What kind of failure a git command's `stderr` shows: never its text."""
    remote = bool(args) and args[0] in REMOTE_COMMANDS
    for name, wordings in REMOTE_CATEGORIES if remote else LOCAL_CATEGORIES:
        if any(wording in stderr for wording in wordings):
            return name
    return UNRECOGNISED if remote else LOCAL_FAILURE


class GitError(StoreError):
    """A git command exited non-zero. Carries what callers need to recognise a known
    failure (e.g. `ls-remote --exit-code` 2 = no such ref, a rejected push).

    The message names the command and only the `category` of the failure, and says when
    git's text was logged (`logged`). `stderr` is git's text in full: it may quote the
    server or a file name a forger chose, so it is never printed."""

    def __init__(
        self,
        args: tuple[str, ...],
        returncode: int,
        stdout: bytes,
        stderr: str,
        *,
        logged: bool = False,
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.logged = LOGGED if logged else ""
        super().__init__(
            f"git {' '.join(args)} failed ({returncode}): {category(args, stderr)}{self.logged}"
        )


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
    raising GitError on a non-zero exit and StoreError if git is not installed. Local
    commands never fetch missing objects (`GIT_NO_LAZY_FETCH`, git 2.44 and later; a
    partial clone is refused anyway, `GitStore.at`), so only REMOTE_COMMANDS talk to the
    remote. Output is untranslated (LC_ALL=C) so callers can recognise known failures. With
    `log`, a failed remote command's text is appended there for an operator, stamped
    with `now()` (Unix seconds) when given."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1", "LC_ALL": "C"}

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
            logged = False
            if log is not None and stderr.strip():  # an expected failure prints nothing
                stamp = None if now is None else now()
                text = stderr
                if args[0] == "push":  # the porcelain status, with the server's reason
                    text += "\n" + result.stdout.decode("utf-8", errors="replace")
                logged = _append(log, stamp, args, result.returncode, text)
            raise GitError(args, result.returncode, result.stdout, stderr, logged=logged)
        return result.stdout

    return run


_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
"""Controls but tab and newline, escaped in the log: an operator reading it with `cat`
must not let the server drive the terminal (set its title, write the clipboard)."""


def _append(
    log: Path, stamp: int | None, args: tuple[str, ...], returncode: int, stderr: str
) -> bool:
    """Append one failure to `log`, moving a full log to `<name>.1` first. Returns
    whether it was written: logging never fails an op."""
    when = "" if stamp is None else f"at {stamp} "
    text = f"--- {when}git {' '.join(args)} ({returncode})\n{stderr.rstrip()}"
    entry = (_CONTROL.sub(lambda m: f"\\x{ord(m[0]):02x}", text) + "\n").encode()
    with suppress(OSError):
        log.parent.mkdir(parents=True, exist_ok=True)
        with suppress(FileNotFoundError):
            if log.stat().st_size + len(entry) > LOG_MAX:
                os.replace(log, log.with_name(log.name + ".1"))
        with log.open("ab") as out:
            out.write(entry)
        return True
    return False
