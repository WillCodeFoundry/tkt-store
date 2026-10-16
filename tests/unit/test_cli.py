"""The CLI parser against docs/cli.md. REAL tests (the parser is implemented).

The command tables in docs/cli.md are the contract: every documented command exists,
with exactly the documented flags, and Required/Optional match argparse. The store
options are documented once in their own section and required on every store command.
Handlers are checked against a recording fake TicketStore (injected, not patched).
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import pytest

from tkt_store.application.service import TicketView
from tkt_store.cli import STORE_OPTIONS, build_parser, view_json
from tkt_store.domain.operations import UNSET
from tkt_store.domain.status import Status
from tkt_store.domain.ticket import Ticket, TicketId

CLI_MD = Path(__file__).resolve().parents[2] / "docs" / "cli.md"
STORE = ["--repo", "/work/tasks", "--remote", "origin"]
CLAIM_ID = "3f9c0d2e8b1a47c6a5e4f30b2d9c8e71"

ROW = re.compile(
    r"^\| `tkt (?P<cmd>[a-z-]+)(?P<pos>[^`]*)` \|[^|]*\|(?P<req>[^|]*)\|(?P<opt>[^|]*)\|$"
)
FLAG = re.compile(r"--[a-z][a-z-]*")


def _documented() -> dict[str, tuple[str, set[str], set[str]]]:
    """command -> (positional text, required flags, optional flags) from docs/cli.md."""
    rows = {}
    for line in CLI_MD.read_text().splitlines():
        if m := ROW.match(line.replace("\\|", "|")):
            rows[m["cmd"]] = (
                m["pos"].strip(),
                set(FLAG.findall(m["req"])),
                set(FLAG.findall(m["opt"])),
            )
    return rows


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    raise AssertionError("no subcommands")


DOCUMENTED = _documented()
PARSERS = _subparsers(build_parser())


def test_docs_list_every_command_and_nothing_else() -> None:
    assert set(DOCUMENTED) == set(PARSERS)


@pytest.mark.parametrize("name", sorted(PARSERS))
def test_flags_and_required_match_the_docs(name: str) -> None:
    positional, required, optional = DOCUMENTED[name]
    actions = [a for a in PARSERS[name]._actions if not isinstance(a, argparse._HelpAction)]
    flags = {a.option_strings[0]: a for a in actions if a.option_strings}
    if name != "mint":
        assert set(STORE_OPTIONS) <= set(flags)
        flags = {f: a for f, a in flags.items() if f not in STORE_OPTIONS}
    assert set(flags) == required | optional
    assert {f for f, a in flags.items() if a.required} == required
    positionals = [a for a in actions if not a.option_strings]
    if positional == "ID":
        assert len(positionals) == 1 and positionals[0].nargs is None
    elif positional == "[ID]":
        assert len(positionals) == 1 and positionals[0].nargs == "?"
    elif "|" in positional:
        choices = set(positionals[0].choices or ())
        assert len(positionals) == 1 and choices == set(positional.split("|"))
    else:
        assert positional == "" and not positionals


@pytest.mark.parametrize(
    "argv",
    [
        ["claim", "tkt-0001", "--as", "a", "--ttl", "60", "--claim-id", CLAIM_ID],  # no store opts
        ["claim", "tkt-0001", "--as", "a", "--ttl", "60", "--claim-id", CLAIM_ID, "--repo", "r"],
        ["reap", "--repo", "r"],  # --remote is required
        ["reap", "--remote", "origin"],  # --repo is required
        ["claim", "tkt-0001", "--as", "a", "--ttl", "60", *STORE],  # missing --claim-id
        ["renew", "tkt-0001", "--claim-id", CLAIM_ID, "--ttl", "30m", *STORE],  # seconds only
        ["edit", "tkt-0001", "--if-version", "1", "--priority", "2", "--clear-priority", *STORE],
        ["move", "tkt-0001", "--claim-id", CLAIM_ID, "--to-phase", "done", *STORE],  # not a phase
        ["move", "tkt-0001", "--claim-id", CLAIM_ID, *STORE],  # --to-phase is required
        ["mint", "token"],  # not a mintable kind
        ["log", "--limit", "-1", *STORE],  # a count, >= 0
    ],
)
def test_usage_errors_exit_2(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(argv)
    assert exc.value.code == 2


def test_mint_needs_no_store_options() -> None:
    args = build_parser().parse_args(["mint", "claim-id"])
    assert args.what == "claim-id" and hasattr(args, "local") and not hasattr(args, "run")


def test_store_options_may_come_anywhere_after_the_command() -> None:
    args = build_parser().parse_args(["reap", "--remote", "origin", "--repo", "r"])
    assert args.repo == "r" and args.remote == "origin"


class RecordingStore:
    """A fake TicketStore that records the call a handler makes."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, method: str) -> Any:
        def record(*args: Any, **kwargs: Any) -> None:
            self.calls.append((method, args, kwargs))

        return record


def _run(argv: list[str]) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
    args = build_parser().parse_args([*argv, *STORE])
    store = RecordingStore()
    args.run(store, args)
    (call,) = store.calls
    return call


def test_claim_maps_to_ticket_store_claim() -> None:
    method, args, kwargs = _run(
        ["claim", "tkt-0001", "--as", "coder-7", "--ttl", "1800", "--claim-id", CLAIM_ID]
    )
    assert (method, args, kwargs) == (
        "claim",
        ("tkt-0001", "coder-7", 1800),
        {"claim_id": CLAIM_ID},
    )


def test_edit_absent_flags_are_unset_and_clear_flags_clear() -> None:
    method, args, kwargs = _run(
        [
            "edit",
            "tkt-0001",
            "--if-version",
            "3",
            "--title",
            "New",
            "--clear-priority",
            "--clear-tags",
        ]
    )
    assert method == "edit" and args == ("tkt-0001", 3)
    assert kwargs["title"] == "New"
    assert kwargs["body"] is UNSET and kwargs["blocked_by"] is UNSET
    assert kwargs["priority"] is None and kwargs["tags"] == ()


def test_move_maps_to_ticket_store_move() -> None:
    method, args, kwargs = _run(
        ["move", "tkt-0001", "--claim-id", CLAIM_ID, "--to-phase", "review"]
    )
    assert (method, args, kwargs) == ("move", ("tkt-0001", CLAIM_ID, "review"), {})


def test_release_takes_no_phase() -> None:
    method, args, kwargs = _run(["release", "tkt-0001", "--claim-id", CLAIM_ID])
    assert (method, args, kwargs) == ("release", ("tkt-0001", CLAIM_ID, ""), {})


def test_show_uses_one_snapshot() -> None:
    method, args, _ = _run(["show", "tkt-0001"])
    assert (method, args) == ("show", ("tkt-0001",))


def test_a_view_says_when_its_ticket_is_held_by_a_set_aside_claim() -> None:
    ticket = Ticket(id=TicketId("tkt-0001"), title="T", created=0, updated=0)
    held = view_json(TicketView(ticket, None, Status.CLAIMED, "more than one open claim"))
    assert (held["status"], held["claim"], held["held_aside"]) == (
        "claimed", None, "more than one open claim"
    )  # fmt: skip
    assert view_json(TicketView(ticket, None, Status.OPEN))["held_aside"] is None
