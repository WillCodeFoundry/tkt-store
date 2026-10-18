"""How a failed git command is categorised, and the operator log
(state-store-design.md §9): no git."""

from __future__ import annotations

from pathlib import Path

import pytest

from state_store import Category
from state_store.runner import LOG_MAX, append_log, category

pytestmark = pytest.mark.xfail(raises=NotImplementedError, strict=True, reason="skeleton")


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        ("fatal: Authentication failed for 'https://x/'", Category.AUTH),
        ("git@x: Permission denied (publickey).", Category.AUTH),
        (
            "fatal: could not read Username for 'https://x': terminal prompts disabled",
            Category.AUTH,
        ),
        ("The requested URL returned error: 403", Category.AUTH),
        ("Host key verification failed.", Category.AUTH),
        ("fatal: '/x.git' does not appear to be a git repository", Category.NOT_FOUND),
        ("The requested URL returned error: 404", Category.NOT_FOUND),
        ("fatal: unable to access 'https://x/': Could not resolve host: x", Category.UNREACHABLE),
        ("fatal: unable to connect to 127.0.0.1: Connection refused", Category.UNREACHABLE),
        ("fatal: the remote end hung up unexpectedly", Category.UNREACHABLE),
        ("remote: Repository not found.", Category.NOT_FOUND),
        ("something nobody has seen before", Category.UNRECOGNISED),
        ("error: cannot run ssh: No such file or directory", Category.UNRECOGNISED),
        ("git: 'remote-https' is not a git command. ... command not found", Category.UNRECOGNISED),
    ],
)
@pytest.mark.parametrize("command", ["fetch", "push", "ls-remote"])
def test_remote_failures(command: str, stderr: str, expected: Category) -> None:
    assert category(command, stderr) is expected


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (
            "fatal: not a git repository (or any of the parent directories): .git",
            Category.NOT_A_CLONE,
        ),
        ("Author identity unknown\n\n*** Please tell me who you are.", Category.NO_IDENTITY),
        ("fatal: empty ident name (for <>) not allowed", Category.NO_IDENTITY),
        ("error: unable to write file: Permission denied", Category.LOCAL),
        ("fatal: the remote end hung up unexpectedly", Category.LOCAL),
        ("anything else", Category.LOCAL),
    ],
)
@pytest.mark.parametrize("command", ["ls-tree", "cat-file", "hash-object", "mktree", "commit-tree"])
def test_local_failures_are_never_remote_ones(
    command: str, stderr: str, expected: Category
) -> None:
    assert category(command, stderr) is expected


def test_the_first_matching_category_wins() -> None:
    both = "Permission denied ... Connection refused"
    assert category("push", both) is Category.AUTH


# --- The operator log (state-store-design.md §9) ---------------------------------------


def test_a_failure_is_logged_under_a_header_with_each_line_prefixed(tmp_path: Path) -> None:
    log = tmp_path / "state-store" / "git-errors.log"
    assert append_log(log, "git push (1)", "first line\n--- fake header\nlast")
    assert log.read_text().splitlines() == [
        "git push (1)",
        "| first line",
        "| --- fake header",
        "| last",
    ]


def test_logged_text_cannot_drive_a_terminal(tmp_path: Path) -> None:
    log = tmp_path / "git-errors.log"
    append_log(log, "git push (1)", "colour \x1b[31mred\x1b[0m\rover\x07bell‮tab\tok")
    written = log.read_text()
    for raw in ("\x1b", "\r", "\x07", "‮"):
        assert raw not in written
    assert "\tok" in written


def test_the_header_is_escaped_too(tmp_path: Path) -> None:
    log = tmp_path / "git-errors.log"
    append_log(log, "git push\nforged line", "")
    lines = log.read_text().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("git push")


def test_a_full_log_is_moved_aside_first(tmp_path: Path) -> None:
    log = tmp_path / "git-errors.log"
    log.write_bytes(b"x" * (LOG_MAX - 10))
    assert append_log(log, "git fetch (128)", "this does not fit")
    assert (tmp_path / "git-errors.log.1").stat().st_size == LOG_MAX - 10
    assert log.read_text().startswith("git fetch (128)")


def test_an_unwritable_log_never_fails(tmp_path: Path) -> None:
    blocker = tmp_path / "state-store"
    blocker.write_text("a file where the log's directory should be")
    assert append_log(blocker / "git-errors.log", "git push (1)", "text") is False
