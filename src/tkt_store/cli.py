"""`tkt` command line (docs/cli.md).

A thin, explicit adapter for agents: every command maps to exactly one TicketStore
method, every input is an explicit flag (no environment defaults, no inferred ids, no
local state), and every result is printed as one JSON value. It holds no rules.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from enum import IntEnum
from pathlib import Path
from typing import Any

from tkt_store import open_store
from tkt_store.application.service import TicketStore
from tkt_store.domain.errors import TktError
from tkt_store.domain.operations import UNSET
from tkt_store.domain.status import Status
from tkt_store.domain.ticket import AgentId, ClaimId, Kind, Phase, ProjectId, TicketId


class ExitCode(IntEnum):
    OK = 0
    REFUSED = 1
    USAGE = 2
    RETRIES_EXHAUSTED = 3
    STORE_ERROR = 4


Run = Callable[[TicketStore, argparse.Namespace], object]


def _unset_if_none(value: Any) -> Any:
    """Absent optional flag -> UNSET ('leave unchanged'), for edit."""
    return UNSET if value is None else value


def _list_change(values: Sequence[str] | None, clear: bool) -> Any:
    """For edit's repeated flags: --clear-X -> (), absent -> UNSET, given -> the values."""
    if clear:
        return ()
    return UNSET if values is None else tuple(values)


def _ids(values: Sequence[str] | None) -> tuple[TicketId, ...]:
    return tuple(TicketId(v) for v in values or ())


def build_parser() -> argparse.ArgumentParser:
    """Required global options (--repo, and exactly one of --remote/--no-remote) and one
    subcommand per TicketStore method. Each subcommand stores its handler as `run`."""
    parser = argparse.ArgumentParser(
        prog="tkt",
        description="Ticket store for coordinating agents. All output is JSON (docs/cli.md).",
    )
    parser.add_argument("--repo", required=True, help="store repository (a clone)")
    remote = parser.add_mutually_exclusive_group(required=True)
    remote.add_argument("--remote", help="the shared remote, e.g. origin")
    remote.add_argument("--no-remote", action="store_true", help="local-only store")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def command(name: str, help: str, run: Run) -> argparse.ArgumentParser:
        cmd = sub.add_parser(name, help=help)
        cmd.set_defaults(run=run)
        return cmd

    def ticket_id(cmd: argparse.ArgumentParser) -> None:
        cmd.add_argument("ticket_id", metavar="ID")

    # --- setup
    command("init", "create the store", lambda s, a: s.init())

    # --- content
    c = command(
        "add",
        "create a ticket",
        lambda s, a: s.add(
            a.title,
            ticket_id=TicketId(a.id),
            kind=a.kind,
            phase=a.phase,
            body=a.body,
            project=None if a.project is None else ProjectId(a.project),
            priority=a.priority,
            blocked_by=_ids(a.blocked_by),
            tags=tuple(a.tag or ()),
            agent=None if a.agent is None else AgentId(a.agent),
        ),
    )
    c.add_argument("--id", required=True)
    c.add_argument("--title", required=True)
    c.add_argument("--kind", required=True, type=Kind, choices=list(Kind))
    c.add_argument("--phase", required=True, type=Phase, choices=list(Phase))
    c.add_argument("--body", default="")
    c.add_argument("--project")
    c.add_argument("--priority", type=int)
    c.add_argument("--blocked-by", action="append")
    c.add_argument("--tag", action="append")
    c.add_argument("--as", dest="agent")

    c = command(
        "edit",
        "edit content fields",
        lambda s, a: s.edit(
            TicketId(a.ticket_id),
            a.if_version,
            title=_unset_if_none(a.title),
            body=_unset_if_none(a.body),
            priority=None if a.clear_priority else _unset_if_none(a.priority),
            blocked_by=_list_change(a.blocked_by, a.clear_blocked_by),
            tags=_list_change(a.tag, a.clear_tags),
            agent=None if a.agent is None else AgentId(a.agent),
        ),
    )
    ticket_id(c)
    c.add_argument("--if-version", type=int, required=True)
    c.add_argument("--title")
    c.add_argument("--body")
    group = c.add_mutually_exclusive_group()
    group.add_argument("--priority", type=int)
    group.add_argument("--clear-priority", action="store_true")
    group = c.add_mutually_exclusive_group()
    group.add_argument("--blocked-by", action="append")
    group.add_argument("--clear-blocked-by", action="store_true")
    group = c.add_mutually_exclusive_group()
    group.add_argument("--tag", action="append")
    group.add_argument("--clear-tags", action="store_true")
    c.add_argument("--as", dest="agent")

    # --- work (occupancy)
    c = command(
        "claim",
        "claim a ticket",
        lambda s, a: s.claim(
            TicketId(a.ticket_id), AgentId(a.agent), a.ttl, claim_id=ClaimId(a.claim_id)
        ),
    )
    ticket_id(c)
    c.add_argument("--as", dest="agent", required=True)
    c.add_argument("--ttl", type=int, required=True)
    c.add_argument("--claim-id", required=True)

    c = command(
        "claim-next",
        "claim the most urgent claimable ticket",
        lambda s, a: s.claim_next(
            AgentId(a.agent),
            a.ttl,
            claim_id=ClaimId(a.claim_id),
            phase=a.phase,
            project=None if a.project is None else ProjectId(a.project),
            kind=a.kind,
        ),
    )
    c.add_argument("--as", dest="agent", required=True)
    c.add_argument("--ttl", type=int, required=True)
    c.add_argument("--claim-id", required=True)
    c.add_argument("--phase", type=Phase, choices=list(Phase))
    c.add_argument("--project")
    c.add_argument("--kind", type=Kind, choices=list(Kind))

    c = command(
        "renew",
        "extend a lease",
        lambda s, a: s.renew(TicketId(a.ticket_id), ClaimId(a.claim_id), a.ttl),
    )
    ticket_id(c)
    c.add_argument("--claim-id", required=True)
    c.add_argument("--ttl", type=int, required=True)

    c = command(
        "release",
        "give a claim back (the phase is untouched)",
        lambda s, a: s.release(TicketId(a.ticket_id), ClaimId(a.claim_id), a.reason),
    )
    ticket_id(c)
    c.add_argument("--claim-id", required=True)
    c.add_argument("--reason", default="")

    command("reap", "release every claim lapsed past the grace", lambda s, a: s.reap())

    # --- workflow
    c = command(
        "move",
        "move the ticket to another phase, keeping the claim (holder only)",
        lambda s, a: s.move(TicketId(a.ticket_id), ClaimId(a.claim_id), a.to_phase),
    )
    ticket_id(c)
    c.add_argument("--claim-id", required=True)
    c.add_argument("--to-phase", required=True, type=Phase, choices=list(Phase))

    c = command(
        "done",
        "complete a ticket (holder only)",
        lambda s, a: s.done(TicketId(a.ticket_id), ClaimId(a.claim_id)),
    )
    ticket_id(c)
    c.add_argument("--claim-id", required=True)

    c = command(
        "cancel",
        "abandon a ticket (no claim needed)",
        lambda s, a: s.cancel(
            TicketId(a.ticket_id),
            a.reason,
            agent=None if a.agent is None else AgentId(a.agent),
        ),
    )
    ticket_id(c)
    c.add_argument("--reason", default="")
    c.add_argument("--as", dest="agent")

    # --- read
    c = command(
        "list",
        "list tickets",
        lambda s, a: s.list(
            status=a.status,
            phase=a.phase,
            project=None if a.project is None else ProjectId(a.project),
            agent=None if a.agent is None else AgentId(a.agent),
            kind=a.kind,
        ),
    )
    c.add_argument("--status", type=Status, choices=list(Status))
    c.add_argument("--phase", type=Phase, choices=list(Phase))
    c.add_argument("--project")
    c.add_argument("--agent")
    c.add_argument("--kind", type=Kind, choices=list(Kind))

    c = command(
        "show",
        "one ticket with its derived status",
        lambda s, a: {
            "ticket": s.get(TicketId(a.ticket_id)),
            "status": s.status(TicketId(a.ticket_id)),
        },
    )
    ticket_id(c)

    c = command(
        "log",
        "history from commit trailers",
        lambda s, a: s.log(None if a.ticket_id is None else TicketId(a.ticket_id), limit=a.limit),
    )
    c.add_argument("ticket_id", metavar="ID", nargs="?")
    c.add_argument("--limit", type=int)

    return parser


def emit(result: object) -> int:
    """Print `result` as one JSON value on stdout and return its exit code.

    Outcomes: Committed -> {"outcome": "committed", "revision", "tickets"} (0);
    Unchanged -> {"outcome": "unchanged", "reason", "tickets"} (0);
    Refused -> {"outcome": "refused", "code", "message"} (1).
    Reads: list/log -> a JSON array; show -> {"ticket", "status"}, or a refused
    NOT_FOUND object (1) when the ticket does not exist.
    Tickets are rendered as their on-branch JSON (docs/format.md).
    """
    raise NotImplementedError


def emit_error(error: TktError) -> int:
    """Print {"outcome": "error", "exit", "message", "op"} and return the exit code:
    RetriesExhausted -> 3, any other failure (StoreError, ...) -> 4. `op` is the op with
    the ids it was last tried with, when the error carries one."""
    raise NotImplementedError


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)  # usage errors exit 2
    try:
        store = open_store(Path(args.repo), remote=None if args.no_remote else args.remote)
        try:
            return emit(args.run(store, args))
        except TktError as error:
            return emit_error(error)
    except NotImplementedError:
        parser.exit(ExitCode.STORE_ERROR, "tkt: not implemented yet (skeleton)\n")
