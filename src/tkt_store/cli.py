"""`tkt` command line (docs/cli.md).

A thin, explicit adapter for agents: every store command maps to one TicketStore
method, every input is an explicit flag (no environment defaults, no inferred ids, no
local state), and every store result is printed as one JSON value. `mint` is local and
prints a bare value; usage errors are argparse's plain text (exit 2). It holds no rules.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from collections.abc import Callable, Sequence
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any

from tkt_store import new_id_source, open_store, ticket_json
from tkt_store.application.errors import RetriesExhausted
from tkt_store.application.service import TicketStore, TicketView
from tkt_store.application.store import HistoryEntry
from tkt_store.application.transaction import Committed, Refused, Unchanged
from tkt_store.domain.errors import TktError
from tkt_store.domain.operations import (
    UNSET,
    AddOp,
    CancelOp,
    ClaimNextOp,
    ClaimOp,
    DoneOp,
    EditOp,
    InitOp,
    MoveOp,
    Op,
    OpName,
    ReapOp,
    ReleaseOp,
    RenewOp,
)
from tkt_store.domain.outcomes import Refusal, RefusalCode
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


STORE_OPTIONS = ("--repo", "--remote", "--no-remote")
"""Required on every store command (not on `mint`), anywhere after the command name."""

MINT_KINDS = ("claim-id", "ticket-id")


def build_parser() -> argparse.ArgumentParser:
    """One subcommand per TicketStore method, each with the store options (--repo, and
    exactly one of --remote/--no-remote) and its handler stored as `run`; plus the local
    `mint`, whose handler is stored as `local`."""
    parser = argparse.ArgumentParser(
        prog="tkt",
        description="Ticket store for coordinating agents (docs/cli.md).",
    )
    store_options = argparse.ArgumentParser(add_help=False)
    store_options.add_argument("--repo", required=True, help="store repository (a clone)")
    remote = store_options.add_mutually_exclusive_group(required=True)
    remote.add_argument("--remote", help="the shared remote, e.g. origin")
    remote.add_argument("--no-remote", action="store_true", help="local-only store")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def command(name: str, help: str, run: Run) -> argparse.ArgumentParser:
        cmd = sub.add_parser(name, help=help, parents=[store_options])
        cmd.set_defaults(run=run)
        return cmd

    # --- local
    c = sub.add_parser("mint", help="print a fresh random id (no store access)")
    c.add_argument("what", choices=MINT_KINDS, metavar="claim-id|ticket-id")
    c.set_defaults(
        local=lambda a: (
            new_id_source().claim_id() if a.what == "claim-id" else new_id_source().ticket_id()
        )
    )

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
        lambda s, a: _found(s.view(TicketId(a.ticket_id)), a.ticket_id),
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


def _found(view: TicketView | None, ticket_id: str) -> TicketView | Refused:
    """`show` of an unknown id is a refusal (NOT_FOUND), printed and exited like one."""
    if view is None:
        return Refused(Refusal(RefusalCode.NOT_FOUND, f"no ticket {ticket_id}"))
    return view


OP_NAMES: dict[type[Op], OpName] = {
    InitOp: OpName.INIT,
    AddOp: OpName.ADD,
    EditOp: OpName.EDIT,
    ClaimOp: OpName.CLAIM,
    ClaimNextOp: OpName.CLAIM_NEXT,
    RenewOp: OpName.RENEW,
    MoveOp: OpName.MOVE,
    ReleaseOp: OpName.RELEASE,
    DoneOp: OpName.DONE,
    CancelOp: OpName.CANCEL,
    ReapOp: OpName.REAP,
}


def _value(value: Any) -> Any:
    """Enums as their value, tuples as lists; everything else is already JSON."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_value(v) for v in value]
    return value


def op_json(op: Op) -> dict[str, Any]:
    """{"op": name, <field>: value, ...}; edit fields left UNSET are omitted."""
    fields = {f.name: getattr(op, f.name) for f in dataclasses.fields(op)}
    return {"op": OP_NAMES[type(op)].value} | {
        name: _value(value) for name, value in fields.items() if value is not UNSET
    }


def view_json(view: TicketView) -> dict[str, Any]:
    return {"ticket": ticket_json(view.ticket), "status": view.status.value}


def entry_json(entry: HistoryEntry) -> dict[str, Any]:
    record = entry.record
    return {
        "revision": entry.revision,
        "at": record.at,
        "op": record.op.value,
        "ticket_ids": list(record.ticket_ids),
        "agent": record.agent,
        "claim_id": record.claim_id,
        "phase": _value(record.phase),
        "reason": record.reason,
    }


def render(result: object) -> tuple[Any, ExitCode]:
    """The JSON value for a handler's result, and its exit code (see `emit`)."""
    match result:
        case Committed(revision=revision, tickets=tickets):
            committed = {"outcome": "committed", "revision": revision}
            return committed | {"tickets": [ticket_json(t) for t in tickets]}, ExitCode.OK
        case Unchanged(reason=reason, tickets=tickets):
            unchanged = {"outcome": "unchanged", "reason": reason}
            return unchanged | {"tickets": [ticket_json(t) for t in tickets]}, ExitCode.OK
        case Refused(refusal=refusal):
            refused = {"outcome": "refused", "code": refusal.code.value}
            return refused | {"message": refusal.message}, ExitCode.REFUSED
        case TicketView():
            return view_json(result), ExitCode.OK
        case list():  # list -> TicketViews, log -> HistoryEntries
            rows = [view_json(r) if isinstance(r, TicketView) else entry_json(r) for r in result]
            return rows, ExitCode.OK
    raise TypeError(f"cannot render {result!r}")


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False))


def emit(result: object) -> int:
    """Print `result` as one JSON value on stdout and return its exit code.

    Outcomes: Committed -> {"outcome": "committed", "revision", "tickets"} (0);
    Unchanged -> {"outcome": "unchanged", "reason", "tickets"} (0);
    Refused -> {"outcome": "refused", "code", "message"} (1).
    Reads: show -> {"ticket", "status"} (a TicketView), or a refused NOT_FOUND object (1)
    when the ticket does not exist; list -> a JSON array of {"ticket", "status"}; log ->
    a JSON array of history entries. Results are complete before anything is printed,
    so output is never partial: a failure prints only the error object.
    Tickets are rendered as their on-branch JSON (docs/format.md).
    """
    value, code = render(result)
    _print(value)
    return code


def emit_error(error: TktError) -> int:
    """Print {"outcome": "error", "exit", "message", "op"} and return the exit code:
    RetriesExhausted -> 3, any other failure (StoreError, ...) -> 4. `op` is the op with
    the ids it was last tried with, when the error carries one."""
    code = (
        ExitCode.RETRIES_EXHAUSTED if isinstance(error, RetriesExhausted) else ExitCode.STORE_ERROR
    )
    op = getattr(error, "op", None)
    _print(
        {
            "outcome": "error",
            "exit": int(code),
            "message": str(error),
            "op": None if op is None else op_json(op),
        }
    )
    return code


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)  # usage errors: plain text on stderr, exit 2
    if hasattr(args, "local"):
        print(args.local(args))
        return ExitCode.OK
    store = open_store(Path(args.repo), remote=None if args.no_remote else args.remote)
    try:
        result = args.run(store, args)  # complete before anything is printed
    except TktError as error:
        return emit_error(error)
    return emit(result)
