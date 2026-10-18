"""The operator log (state-store design §8): no git."""

from __future__ import annotations

from pathlib import Path

import pytest

from state_store.runner import LOG_MAX, append_log

pytestmark = pytest.mark.xfail(raises=NotImplementedError, strict=True, reason="skeleton")


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
