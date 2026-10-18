"""Running git: the one place this package starts a process (state-store design §6, §8).

Every command is an argument list, never a shell, run in the clone with hooks off,
git's automatic maintenance in the foreground, prompts off, lazy fetches off, replace
objects off, untranslated messages, and the inherited variables that would point git at
other repository data removed. A failure becomes a `GitFailure` that carries git's exit
code, output and the category of its message; git's text itself goes only to the
operator log, never into an exception's message, arguments or repr, and the store raises
its own errors `from None`.
"""

from __future__ import annotations

from pathlib import Path

from state_store.errors import Category

REMOTE_COMMANDS = frozenset({"fetch", "push", "ls-remote"})
"""The only commands that talk to the remote; only their failures can be remote ones."""

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
`git rev-parse --local-env-vars` lists, plus `GIT_NAMESPACE`. `GIT_NO_REPLACE_OBJECTS`
is set again in `FIXED_VARIABLES`. The caller's configuration variables
(`GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_COUNT`, …: how CI injects credentials) are kept;
the store's own `-c` settings come after them and win."""

FIXED_VARIABLES = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_NO_LAZY_FETCH": "1",  # git 2.44+; ignoring it is harmless: partial clones are refused
    "GIT_NO_REPLACE_OBJECTS": "1",
    "LC_ALL": "C",
}

NOT_A_CLONE_WORDING = ("not a git repository (or any of the parent", "cannot change to")

REMOTE_WORDING: tuple[tuple[Category, tuple[str, ...]], ...] = (
    (Category.NOT_A_CLONE, NOT_A_CLONE_WORDING),
    (
        Category.AUTH,
        (
            "Authentication failed",
            "Permission denied",
            "could not read Username",
            "could not read Password",
            "terminal prompts disabled",
            "returned error: 401",
            "returned error: 403",
            "Host key verification failed",
        ),
    ),
    (
        Category.NOT_FOUND,
        (
            # never a bare "not found" or "No such file or directory": those also say
            # that a program (ssh, a remote helper) is missing, which is not this
            "Repository not found",
            "does not appear to be a git repository",
            "returned error: 404",
        ),
    ),
    (
        Category.UNREACHABLE,
        (
            "Could not resolve host",
            "Couldn't resolve host",
            "Connection refused",
            "timed out",
            "Network is unreachable",
            "No route to host",
            "Connection reset",
            "the remote end hung up",
            "early EOF",
            "unable to access",
        ),
    ),
)
"""How a failed remote command's category is read from git's wording; first match wins,
otherwise `UNRECOGNISED`. A server can imitate a wording: it picks a category at most."""

LOCAL_WORDING: tuple[tuple[Category, tuple[str, ...]], ...] = (
    (Category.NOT_A_CLONE, NOT_A_CLONE_WORDING),
    (Category.NO_IDENTITY, ("Please tell me who you are", "empty ident name")),
)
"""The same for local commands; otherwise `LOCAL`."""

LOG_NAME = "state-store/git-errors.log"
"""The operator log, relative to the clone's git directory."""

LOG_MAX = 1024 * 1024
"""Bytes in the log before it is moved to `<name>.1`, replacing an older one."""


class GitFailure(Exception):
    """A git command exited non-zero. Never reaches a caller: the store turns it into
    one of its own outcomes (state-store design §5, §8); any error it raises is raised
    `from None`.

    Its message and `args` are only the command and the category; `stdout` (which can
    quote the server, e.g. a push's `[remote rejected] (<reason>)`) is an attribute,
    never part of `args` or the repr, so a traceback cannot show it."""

    def __init__(self, command: str, returncode: int, stdout: bytes, category: Category) -> None:
        super().__init__(f"git {command} failed: {category.value}")
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.category = category


def category(command: str, stderr: str) -> Category:
    """The category of a failure of `command` (a git subcommand) from its message."""
    raise NotImplementedError


def append_log(log: Path, header: str, text: str) -> bool:
    """Append one failure to the operator log: `header` on a line of its own, then each
    line of `text` after `| `, so no text can pass for a header; every character an
    operator's terminal must not get raw (non-printable, but tab) escaped in both. Moves
    a log that would pass `LOG_MAX` to `<name>.1` first. Returns whether it was written:
    logging never fails an operation."""
    raise NotImplementedError


class Runner:
    """Runs git in one clone."""

    def __init__(self, repo: Path) -> None:
        raise NotImplementedError

    def __call__(self, *args: str, stdin: bytes | None = None) -> bytes:
        """The stdout of `git -C <repo> <settings> <args>`, where the settings turn hooks
        off and keep automatic maintenance in the foreground (`core.hooksPath=/dev/null`,
        `maintenance.autoDetach=false`, `gc.autoDetach=false`); `GitFailure` on a non-zero
        exit, after logging git's text for an operator."""
        raise NotImplementedError
