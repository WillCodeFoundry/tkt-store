"""Running git: the one place this package starts a process (state-store design §6, §8).

Every command is an argument list, never a shell, run in the store's clone with hooks
off, git's automatic maintenance in the foreground, prompts off, lazy fetches off,
replace objects off, untranslated messages, and the inherited variables that would point
git at other repository data removed. A failure becomes a `GitFailure` that carries the
command, git's exit code and its output; git's text itself goes only to the operator
log, never into an exception's message, arguments or repr, and the store raises its own
errors `from None`. git's text never decides anything.
"""

from __future__ import annotations

from pathlib import Path

REMOTE_COMMANDS = frozenset({"clone", "fetch", "ls-remote"})
"""What cloning and taking a snapshot run against the remote: their failures there are
`RemoteFailed` (state-store design §3, §7, §8)."""

DROPPED_VARIABLES = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_IMPLICIT_WORK_TREE",
        "GIT_PREFIX",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_GRAFT_FILE",
        "GIT_SHALLOW_FILE",
        "GIT_REPLACE_REF_BASE",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_CONFIG",
        "GIT_NAMESPACE",
    }
)
"""Inherited variables that would make git read another repository, object store, index,
graft, shallow or replace data, or ref namespace (state-store design §6): those
`git rev-parse --local-env-vars` lists, except the caller's configuration variables,
plus `GIT_NAMESPACE`. `GIT_NO_REPLACE_OBJECTS` is set again in `FIXED_VARIABLES`. The
caller's configuration variables (`GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_COUNT` and its
keys: how CI injects credentials) are kept; the store's own `-c` settings come after
them and win."""

FIXED_VARIABLES = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_NO_LAZY_FETCH": "1",  # git 2.44+; ignoring it is harmless: the clone is never partial
    "GIT_NO_REPLACE_OBJECTS": "1",
    "LC_ALL": "C",  # the operator log in one language
}

LOG_NAME = "state-store/git-errors.log"
"""The operator log, relative to the clone's git directory."""

LOG_MAX = 1024 * 1024
"""Bytes in the log before it is moved to `<name>.1`, replacing an older one."""


class GitFailure(Exception):
    """A git command exited non-zero. Never reaches a caller: the store turns it into
    one of its own outcomes (state-store design §5, §8); any error it raises is raised
    `from None`.

    Its message and `args` are only the command and the exit code; `stdout` (which can
    quote the server, e.g. a push's `[remote rejected] (<reason>)`) is an attribute,
    never part of `args` or the repr, so a traceback cannot show it."""

    def __init__(self, command: str, returncode: int, stdout: bytes) -> None:
        super().__init__(f"git {command} failed ({returncode})")
        self.command = command
        self.returncode = returncode
        self.stdout = stdout


def append_log(log: Path, header: str, text: str) -> bool:
    """Append one failure to the operator log: `header` on a line of its own, then each
    line of `text` after `| `, so no text can pass for a header; every character an
    operator's terminal must not get raw (non-printable, but tab) escaped in both. Moves
    a log that would pass `LOG_MAX` to `<name>.1` first. Returns whether it was written:
    logging never fails an operation."""
    raise NotImplementedError


class Runner:
    """Runs git in one directory: a clone, or the temporary directory a clone is made in."""

    def __init__(self, path: Path, *, log: bool = True) -> None:
        """Run in `path`, with `GIT_CEILING_DIRECTORIES` set to its parent, so git never
        searches above it; `log=False` while cloning, which logs nothing."""
        raise NotImplementedError

    def __call__(self, *args: str, stdin: bytes | None = None) -> bytes:
        """The stdout of `git -C <path> <settings> <args>`, where the settings turn hooks
        off and keep automatic maintenance in the foreground (`core.hooksPath=/dev/null`,
        `maintenance.autoDetach=false`, `gc.autoDetach=false`); `GitFailure` on a non-zero
        exit, after logging git's text for an operator."""
        raise NotImplementedError
