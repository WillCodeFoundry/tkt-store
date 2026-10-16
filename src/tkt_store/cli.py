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

from tkt_store import new_id_source, open_store
from tkt_store.application.errors import RetriesExhausted
from tkt_store.application.service import TicketStore, TicketView
from tkt_store.application.store import HistoryEntry
from tkt_store.application.transaction import Committed, Outcome, Refused, Unchanged
from tkt_store.domain.errors import TktError
from tkt_store.domain.operations import UNSET, Op
from tkt_store.domain.status import Status
from tkt_store.domain.ticket import AgentId, ClaimId, Kind, Phase, ProjectId, TicketId, TicketState


class ExitCode(IntEnum):
    OK = 0
    REFUSED = 1
    USAGE = 2
    RETRIES_EXHAUSTED = 3
    STORE_ERROR = 4


Run = Callable[[TicketStore, argparse.Namespace], Any]
Render = Callable[[Any], "tuple[Any, ExitCode]"]


def _unset_if_none(value: Any) -> Any:
    """Absent optional flag -> UNSET ('leave unchanged'), for edit."""
    return UNSET if value is None else value


def _list_change(values: Sequence[str] | None, clear: bool) -> Any:
    """For edit's repeated flags: --clear-X -> (), absent -> UNSET, given -> the values."""
    if clear:
        return ()
    return UNSET if values is None else tuple(values)


def _count(text: str) -> int:
    """argparse type for --limit: an integer >= 0 (a usage error otherwise)."""
    value = int(text)
    if value < 0:
        raise ValueError(text)
    return value


def _ids(values: Sequence[str] | None) -> tuple[TicketId, ...]:
    return tuple(TicketId(v) for v in values or ())


STORE_OPTIONS = ("--repo", "--remote")
"""Required on every store command (not on `mint`), anywhere after the command name."""

MINT_KINDS = ("claim-id", "ticket-id")


def build_parser() -> argparse.ArgumentParser:
    """One subcommand per TicketStore method, each with the store options (--repo and
    --remote) and its handler stored as `run`; plus the local `mint`, whose handler is
    stored as `local`."""
    parser = argparse.ArgumentParser(
        prog="tkt",
        description="Ticket store for coordinating agents (docs/cli.md).",
    )
    store_options = argparse.ArgumentParser(add_help=False)
    store_options.add_argument("--repo", required=True, help="store repository (a clone)")
    store_options.add_argument("--remote", required=True, help="the shared remote, e.g. origin")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def command(
        name: str, help: str, run: Run, render: Render | None = None
    ) -> argparse.ArgumentParser:
        """`render` turns what `run` returns into (JSON value, exit code); by default
        the run returns an Outcome."""
        cmd = sub.add_parser(name, help=help, parents=[store_options])
        cmd.set_defaults(run=run, render=render or render_outcome)
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
        render_views,
    )
    c.add_argument("--status", type=Status, choices=list(Status))
    c.add_argument("--phase", type=Phase, choices=list(Phase))
    c.add_argument("--project")
    c.add_argument("--agent")
    c.add_argument("--kind", type=Kind, choices=list(Kind))

    c = command(
        "show",
        "one ticket with its derived status",
        lambda s, a: s.show(TicketId(a.ticket_id)),
        render_show,
    )
    ticket_id(c)

    c = command(
        "log",
        "history from commit trailers",
        lambda s, a: s.log(None if a.ticket_id is None else TicketId(a.ticket_id), limit=a.limit),
        render_log,
    )
    c.add_argument("ticket_id", metavar="ID", nargs="?")
    c.add_argument("--limit", type=_count)

    return parser


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
    return {"op": op.name.value} | {
        name: _value(value) for name, value in fields.items() if value is not UNSET
    }


def state_json(state: TicketState) -> dict[str, Any]:
    """{"ticket": <on-branch JSON>, "claim": <open claim> or null}. A claim shows its
    hash, never a claim id (ADR 0005)."""
    claim = None if state.claim is None else state.claim.to_dict()
    return {"ticket": state.ticket.to_dict(), "claim": claim}


def view_json(view: TicketView) -> dict[str, Any]:
    """`state_json`, the status, and `held_aside`: the check that failed when the ticket is
    held by a set-aside claim, else null."""
    state = state_json(TicketState(view.ticket, view.claim))
    return state | {"status": view.status.value, "held_aside": view.held_aside}


def entry_json(entry: HistoryEntry) -> dict[str, Any]:
    record = entry.record
    return {
        "revision": entry.revision,
        "at": record.at,
        "op": record.op.value,
        "ticket_ids": list(record.ticket_ids),
        "agent": record.agent,
        "claim_hash": record.claim_hash,
        "phase": _value(record.phase),
        "reason": record.reason,
    }


def render_outcome(outcome: Outcome) -> tuple[Any, ExitCode]:
    """Committed -> {"outcome": "committed", "revision", "tickets"} (0);
    Unchanged -> {"outcome": "unchanged", "reason", "tickets"} (0);
    Refused -> {"outcome": "refused", "code", "message"} (1).
    Each ticket is {"ticket", "claim"} (`state_json`)."""
    match outcome:
        case Committed(revision=revision, tickets=tickets):
            committed = {"outcome": "committed", "revision": revision}
            return committed | {"tickets": [state_json(t) for t in tickets]}, ExitCode.OK
        case Unchanged(reason=reason, tickets=tickets):
            unchanged = {"outcome": "unchanged", "reason": reason}
            return unchanged | {"tickets": [state_json(t) for t in tickets]}, ExitCode.OK
        case Refused(refusal=refusal):
            refused = {"outcome": "refused", "code": refusal.code.value}
            return refused | {"message": refusal.message}, ExitCode.REFUSED


def render_show(found: TicketView | Refused) -> tuple[Any, ExitCode]:
    """{"ticket", "claim", "status"}, or a refused object (1): NOT_FOUND for an unknown id,
    SET_ASIDE for one set aside on reading."""
    if isinstance(found, Refused):
        return render_outcome(found)
    return view_json(found), ExitCode.OK


def render_views(views: Sequence[TicketView]) -> tuple[Any, ExitCode]:
    """`list`: a JSON array of {"ticket", "claim", "status"}."""
    return [view_json(v) for v in views], ExitCode.OK


def render_log(entries: Sequence[HistoryEntry]) -> tuple[Any, ExitCode]:
    """`log`: a JSON array of history entries."""
    return [entry_json(e) for e in entries], ExitCode.OK


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False))


def emit(result: Any, render: Render = render_outcome) -> int:
    """Print `result` as one JSON value on stdout (via the command's `render`) and
    return its exit code. Results are complete before anything is printed, so output
    is never partial: a failure prints only the error object."""
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
    store = open_store(Path(args.repo), remote=args.remote)
    try:
        result = args.run(store, args)  # complete before anything is printed
    except TktError as error:
        return emit_error(error)
    return emit(result, args.render)
