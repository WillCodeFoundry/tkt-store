"""CLI end-to-end against a temporary store (docs/cli.md). Parser-level checks live in
tests/unit/test_cli.py and already run; these need a working store."""

import pytest

pytestmark = [pytest.mark.git, pytest.mark.skip(reason="skeleton")]


def test_add_claim_release_done_flow() -> None:
    """Each command prints one JSON value with the documented shape."""


@pytest.mark.parametrize(("command", "count"), [("init", 0), ("claim", 1), ("reap", 2)])
def test_tickets_list_has_the_documented_count(command: str, count: int) -> None:
    """Exactly one for single-ticket commands, none for init, zero or more for reap."""


def test_rerunning_the_same_command_is_unchanged() -> None: ...


def test_show_unknown_id_is_refused_not_found() -> None: ...


def test_error_output_carries_the_op_and_its_ids() -> None:
    """A store failure prints {"outcome": "error", "exit": 4, "message", "op"}."""


def test_exit_codes_match_docs() -> None:
    """0 committed/unchanged/read, 1 refused, 2 usage, 3 retries exhausted, 4 store error."""
