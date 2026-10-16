"""The rules: pure decisions about an op against a snapshot at a given time.

PURE module. `decide(snapshot, op, now)` is the single entry point. It never
writes, never reads the clock, never touches git — everything it needs is in
its arguments. This is where invariants 1, 4, 5, 8, 9, 10, 11 and 12 (docs/design.md §5)
live. The result is a `Decision` from `domain.outcomes`.

Every `Apply.record` carries `at=now`, the injected time (`OpRecord.at`), and the
acting `agent` when the op names one. Every ticket an Apply writes gets updated = now;
its `content_version` starts at 1 (add) and only `edit` increments it. Ending a claim
(release, reap, takeover, cancel, done) appends its id to `ended_claim_ids`. The full
op x state -> outcome table is in docs/design.md §5; the docstrings below summarise it.

Refusal messages for claim ids distinguish three cases, so an agent knows what
happened: "claim <id> already ended on this ticket", "claim <id> was never used on
this ticket", and "held by another claim".
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Literal

from tkt_store.domain.operations import (
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
    Unset,
)
from tkt_store.domain.outcomes import (
    Apply,
    Decision,
    NoOp,
    OpRecord,
    Refusal,
    RefusalCode,
    WriteTicket,
)
from tkt_store.domain.status import claimable, sort_key_for_next, why_not_claimable
from tkt_store.domain.ticket import (
    CLAIM_ID_RE,
    MAX_TTL,
    TICKET_ID_RE,
    AgentId,
    Claim,
    ClaimId,
    Duration,
    Phase,
    Resolution,
    Snapshot,
    Ticket,
    TicketId,
    Timestamp,
)

CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
"""Refused in `agent`, `reason` and `title`: they are written into the commit
message, so a newline could forge trailers or break the one-line subject."""


def decide(snapshot: Snapshot, op: Op, now: Timestamp) -> Decision:
    """Dispatch to the rule for this op type. Exhaustive over `Op`.

    `validate_op` runs first; its refusal (INVALID) wins over every other outcome.
    """
    if (invalid := validate_op(op)) is not None:
        return invalid
    match op:
        case InitOp():
            return decide_init(snapshot, op, now)
        case AddOp():
            return decide_add(snapshot, op, now)
        case EditOp():
            return decide_edit(snapshot, op, now)
        case ClaimOp():
            return decide_claim(snapshot, op, now)
        case ClaimNextOp():
            return decide_claim_next(snapshot, op, now)
        case RenewOp():
            return decide_renew(snapshot, op, now)
        case MoveOp():
            return decide_move(snapshot, op, now)
        case ReleaseOp():
            return decide_release(snapshot, op, now)
        case DoneOp():
            return decide_done(snapshot, op, now)
        case CancelOp():
            return decide_cancel(snapshot, op, now)
        case ReapOp():
            return decide_reap(snapshot, op, now)


def validate_op(op: Op) -> Refusal | None:
    """Refusal(INVALID) if any field of `op` is malformed on its own, else None.

    - ticket ids (`ticket_id`, each `blocked_by` entry) must `fullmatch`
      ticket.TICKET_ID_RE;
    - `claim_id` must `fullmatch` ticket.CLAIM_ID_RE;
    - `agent`, `reason` and `title` must not contain CONTROL_CHARS_RE;
    - `ttl` (claim, claim-next, renew) must satisfy 0 < ttl <= MAX_TTL;
    - `expected_version` (edit) must be >= 1.
    Shape checks only; anything that depends on the snapshot is each rule's concern.
    """
    for ticket_id in _ticket_ids_of(op):
        if not TICKET_ID_RE.fullmatch(ticket_id):
            return _invalid(f"malformed ticket id {ticket_id!r}")
    match op:
        case ClaimOp() | ClaimNextOp() | RenewOp() | MoveOp() | ReleaseOp() | DoneOp():
            if not CLAIM_ID_RE.fullmatch(op.claim_id):
                return _invalid(
                    f"malformed claim id {op.claim_id!r} (need 32 lowercase hex characters)"
                )
    for name, value in _texts_of(op).items():
        if isinstance(value, str) and CONTROL_CHARS_RE.search(value):
            return _invalid(f"{name} contains a newline or other control character")
    match op:
        case ClaimOp() | ClaimNextOp() | RenewOp():
            if not 0 < op.ttl <= MAX_TTL:
                return _invalid(f"ttl must be between 1 and {MAX_TTL} seconds, got {op.ttl}")
    if isinstance(op, EditOp) and op.expected_version < 1:
        return _invalid(f"expected_version must be >= 1, got {op.expected_version}")
    return None


def decide_init(snapshot: Snapshot, op: InitOp, now: Timestamp) -> Decision:
    """Apply an empty tree if snapshot.revision is None; NoOp otherwise. (The git store
    adds tkt-store.json to the root commit itself; it is not a ticket Change.)"""
    if snapshot.revision is not None:
        return NoOp("store already initialised")
    return Apply(changes=(), record=OpRecord(op.name, at=now, summary="init"))


def decide_add(snapshot: Snapshot, op: AddOp, now: Timestamp) -> Decision:
    """Refuse: NOT_INITIALISED, INVALID (empty title, unknown or self blocker).
    If the id already exists, decide whether this is a re-run of the same add (NoOp)
    or a different ticket reusing the id (DUPLICATE_ID). Workflow and occupancy are
    never compared — a handoff or claim since the add does not make a re-run fail:
    - identity differs (kind or project) -> DUPLICATE_ID;
    - never edited (content_version == 1): the content fields (title, body, priority,
      blocked_by, tags) must equal the op's -> NoOp, else DUPLICATE_ID;
    - edited since (content_version > 1): the original content can no longer be
      compared, so matching identity -> NoOp.
    Apply: a new, unresolved ticket in op.phase with created = updated = now,
    content_version = 1. (A ticket cannot be created finished: AddOp has no resolution.)"""
    if snapshot.revision is None:
        return Refusal(RefusalCode.NOT_INITIALISED, "the store is not initialised (run init)")
    if invalid := _invalid_content(snapshot, op.ticket_id, op.title, op.blocked_by):
        return invalid
    existing = snapshot.get(op.ticket_id)
    if existing is not None:
        if (existing.kind, existing.project) != (op.kind, op.project):
            return _duplicate(op.ticket_id, "with a different kind or project")
        content = (op.title, op.body, op.priority, op.blocked_by, op.tags)
        if existing.content_version == 1 and _content(existing) != content:
            return _duplicate(op.ticket_id, "with different content")
        return NoOp(f"{op.ticket_id} already exists", (op.ticket_id,))
    ticket = Ticket(
        id=op.ticket_id,
        kind=op.kind,
        project=op.project,
        created=now,
        title=op.title,
        body=op.body,
        priority=op.priority,
        blocked_by=op.blocked_by,
        tags=op.tags,
        phase=op.phase,
        updated=now,
    )
    return _apply(op.name, now, ticket, agent=op.agent)


def decide_edit(snapshot: Snapshot, op: EditOp, now: Timestamp) -> Decision:
    """Content op. In this order:
    NOT_FOUND; TERMINAL; INVALID (empty title, unknown or self blocker, dependency cycle);
    NoOp if every field the op sets already has that value (checked BEFORE the version, so
      a re-run of an edit that already landed converges);
    STALE if ticket.content_version != op.expected_version (edited since it was read).
    Apply: the content fields it sets, updated = now, content_version + 1. Never touches
    identity, workflow or occupancy; may add blockers to a claimed ticket without
    disturbing the claim. No silent overwrite: concurrent edits are refused STALE."""
    ticket = snapshot.get(op.ticket_id)
    if ticket is None:
        return _not_found(op.ticket_id)
    if ticket.is_terminal:
        return _terminal(ticket)
    changes: dict[str, Any] = {
        name: value
        for name in ("title", "body", "priority", "blocked_by", "tags")
        if not isinstance(value := getattr(op, name), Unset)
    }
    title = changes.get("title", ticket.title)
    blocked_by = changes.get("blocked_by", ticket.blocked_by)
    if invalid := _invalid_content(snapshot, ticket.id, title, blocked_by):
        return invalid
    if "blocked_by" in changes and (cycle := _cycle_through(snapshot, ticket.id, blocked_by)):
        return _invalid(f"blocked_by would create a dependency cycle via {cycle}")
    if all(getattr(ticket, name) == value for name, value in changes.items()):
        return NoOp("nothing to change", (ticket.id,))
    if ticket.content_version != op.expected_version:
        return Refusal(
            RefusalCode.STALE,
            f"{ticket.id} is at content_version {ticket.content_version}, "
            f"the edit was based on {op.expected_version}; re-read and retry",
        )
    edited = replace(ticket, **changes, content_version=ticket.content_version + 1, updated=now)
    return _apply(op.name, now, edited, agent=op.agent)


def decide_claim(snapshot: Snapshot, op: ClaimOp, now: Timestamp) -> Decision:
    """Occupancy op. In this order:
    NOT_FOUND; TERMINAL;
    this ticket's current claim has op.claim_id:
      another agent -> ALREADY_CLAIMED;
      same agent, live -> NoOp (a re-run after success);
      same agent, lapsed (not taken over) -> Apply: renew it, lease_until = now + ttl,
        claimed_at unchanged (a re-run after an outage gets a live claim, not a stale one);
    ALREADY_CLAIMED if op.claim_id is the current claim on another ticket (one claim id
      names one claim on one ticket);
    NOT_HOLDER if op.claim_id is in any ticket's ended_claim_ids (an ended claim's id is
      fenced for good);
    then `status.why_not_claimable` (BLOCKED, ALREADY_CLAIMED; TERMINAL already handled).
    Apply: claim = (agent, claim_id, lease_until = now + ttl, claimed_at = now). Taking
    over a takeable claim appends the old claim id to ended_claim_ids, fencing it. Phase
    is untouched. For a new claim id, accepts exactly when `status.claimable` is true."""
    ticket = snapshot.get(op.ticket_id)
    if ticket is None:
        return _not_found(op.ticket_id)
    if ticket.is_terminal:
        return _terminal(ticket)
    return _claim(snapshot, ticket, op.name, op.agent, op.claim_id, op.ttl, now)


def decide_claim_next(snapshot: Snapshot, op: ClaimNextOp, now: Timestamp) -> Decision:
    """Occupancy op. In this order:
    some ticket's current claim has op.claim_id:
      another agent -> ALREADY_CLAIMED;
      same agent, live -> NoOp naming that ticket (a retry never takes a second ticket);
      same agent, lapsed (not taken over) -> Apply: renew it on that ticket (as claim);
    NOT_HOLDER if op.claim_id is in any ticket's ended_claim_ids;
    choose min(sort_key_for_next) among tickets for which `status.claimable` is true and
      that match the filters (project, kind, phase; a project filter matches that exact
      value only, never a null project), then apply as decide_claim;
    NOTHING_CLAIMABLE if there is none."""
    for ticket in snapshot.tickets.values():
        if ticket.claim is not None and ticket.claim.claim_id == op.claim_id:
            return _claim(snapshot, ticket, op.name, op.agent, op.claim_id, op.ttl, now)
    if ended := _ended_on(snapshot, op.claim_id):
        return _already_ended(op.claim_id, ended)
    candidates = [
        ticket
        for ticket in snapshot.tickets.values()
        if (op.project is None or ticket.project == op.project)
        and (op.kind is None or ticket.kind is op.kind)
        and (op.phase is None or ticket.phase is op.phase)
        and claimable(snapshot, ticket, now)
    ]
    if not candidates:
        return Refusal(RefusalCode.NOTHING_CLAIMABLE, "no claimable ticket matches the filters")
    chosen = min(candidates, key=sort_key_for_next)
    return _claim(snapshot, chosen, op.name, op.agent, op.claim_id, op.ttl, now)


def decide_renew(snapshot: Snapshot, op: RenewOp, now: Timestamp) -> Decision:
    """Holder op (design.md §5 table), in this order after NOT_FOUND:
    TERMINAL; current claim has op.claim_id -> Apply (even if lapsed, as long as nobody
    took it over); op.claim_id in ended_claim_ids -> NOT_HOLDER ("already ended"); no
    claim -> NOT_CLAIMED; claimed by another -> NOT_HOLDER.
    Apply: lease_until = now + ttl (claimed_at unchanged)."""
    ticket = snapshot.get(op.ticket_id)
    if ticket is None:
        return _not_found(op.ticket_id)
    if ticket.is_terminal:
        return _terminal(ticket)
    match _holder(ticket, op.claim_id):
        case Refusal() as refusal:
            return refusal
        case "ended":
            return _already_ended(op.claim_id, ticket.id)
    assert ticket.claim is not None
    renewed = replace(ticket, claim=replace(ticket.claim, lease_until=now + op.ttl), updated=now)
    return _apply(op.name, now, renewed, agent=ticket.claim.agent, claim_id=op.claim_id)


def decide_move(snapshot: Snapshot, op: MoveOp, now: Timestamp) -> Decision:
    """Holder op, workflow only (design.md §5 table), in this order after NOT_FOUND:
    TERMINAL;
    current claim has op.claim_id -> NoOp if already in op.to_phase, else Apply (even if
      lapsed, as long as nobody took it over);
    op.claim_id in ended_claim_ids (the claim already ended) -> NoOp if the ticket is in
      op.to_phase (a re-run after the move landed and the claim was released), else
      NOT_HOLDER ("claim ended before the move");
    no claim -> NOT_CLAIMED; claimed by another -> NOT_HOLDER.
    Apply: phase = op.to_phase, with record.phase = op.to_phase. The claim is kept: a
    handoff is move, then release."""
    ticket = snapshot.get(op.ticket_id)
    if ticket is None:
        return _not_found(op.ticket_id)
    if ticket.is_terminal:
        return _terminal(ticket)
    match _holder(ticket, op.claim_id):
        case Refusal() as refusal:
            return refusal
        case "ended":
            if ticket.phase is op.to_phase:
                return NoOp(f"{ticket.id} is already in {op.to_phase.value}", (ticket.id,))
            return Refusal(
                RefusalCode.NOT_HOLDER,
                f"claim {op.claim_id} already ended on {ticket.id} before the move",
            )
    if ticket.phase is op.to_phase:
        return NoOp(f"{ticket.id} is already in {op.to_phase.value}", (ticket.id,))
    assert ticket.claim is not None
    moved = replace(ticket, phase=op.to_phase, updated=now)
    return _apply(
        op.name, now, moved, agent=ticket.claim.agent, claim_id=op.claim_id, phase=op.to_phase
    )


def decide_release(snapshot: Snapshot, op: ReleaseOp, now: Timestamp) -> Decision:
    """Holder op, occupancy only (design.md §5 table), in this order after NOT_FOUND:
    TERMINAL (resolved tickets are unclaimed, so this comes first);
    current claim has op.claim_id -> Apply (even if lapsed, as long as nobody took it over);
    op.claim_id in ended_claim_ids -> NoOp, reason "claim already ended" (a re-run of a
      landed release converges, however many claims came since);
    no claim -> NOT_CLAIMED; claimed by another -> NOT_HOLDER.
    Apply: claim = None, op.claim_id appended to ended_claim_ids. The phase is untouched."""
    ticket = snapshot.get(op.ticket_id)
    if ticket is None:
        return _not_found(op.ticket_id)
    if ticket.is_terminal:
        return _terminal(ticket)
    match _holder(ticket, op.claim_id):
        case Refusal() as refusal:
            return refusal
        case "ended":
            return NoOp(f"claim {op.claim_id} already ended on {ticket.id}", (ticket.id,))
    assert ticket.claim is not None
    released = _end_claim(ticket, now)
    return _apply(
        op.name,
        now,
        released,
        agent=ticket.claim.agent,
        claim_id=op.claim_id,
        reason=op.reason,
    )


def decide_done(snapshot: Snapshot, op: DoneOp, now: Timestamp) -> Decision:
    """Holder op (design.md §5 table), in this order after NOT_FOUND:
    resolved: CANCELLED -> TERMINAL; DONE and op.claim_id is the last of ended_claim_ids
      -> NoOp (idempotent repeat); DONE otherwise -> NOT_HOLDER (fencing survives
      completion);
    current claim has op.claim_id -> Apply (even if lapsed, as long as nobody took it over);
    op.claim_id in ended_claim_ids -> NOT_HOLDER ("already ended"); no claim ->
    NOT_CLAIMED; claimed by another -> NOT_HOLDER.
    Not gated by blockers: invariant 10 gates claims, not completion.
    Apply: resolution = DONE, claim = None, op.claim_id appended to ended_claim_ids.
    Phase is kept."""
    ticket = snapshot.get(op.ticket_id)
    if ticket is None:
        return _not_found(op.ticket_id)
    if ticket.resolution is Resolution.CANCELLED:
        return _terminal(ticket)
    if ticket.resolution is Resolution.DONE:
        if ticket.ended_claim_ids and ticket.ended_claim_ids[-1] == op.claim_id:
            return NoOp(f"{ticket.id} already done by this claim", (ticket.id,))
        return Refusal(RefusalCode.NOT_HOLDER, f"{ticket.id} was completed by another claim")
    match _holder(ticket, op.claim_id):
        case Refusal() as refusal:
            return refusal
        case "ended":
            return _already_ended(op.claim_id, ticket.id)
    assert ticket.claim is not None
    done = replace(_end_claim(ticket, now), resolution=Resolution.DONE)
    return _apply(op.name, now, done, agent=ticket.claim.agent, claim_id=op.claim_id)


def decide_cancel(snapshot: Snapshot, op: CancelOp, now: Timestamp) -> Decision:
    """Workflow op, deliberately unfenced (anyone may cancel; no claim needed).
    Refuse: NOT_FOUND, TERMINAL if resolved DONE. NoOp: already CANCELLED.
    Apply: resolution = CANCELLED, claim = None; a cleared claim's id is appended to
    ended_claim_ids. Phase is kept, so the ticket records where it was abandoned."""
    ticket = snapshot.get(op.ticket_id)
    if ticket is None:
        return _not_found(op.ticket_id)
    if ticket.resolution is Resolution.CANCELLED:
        return NoOp(f"{ticket.id} is already cancelled", (ticket.id,))
    if ticket.resolution is Resolution.DONE:
        return _terminal(ticket)
    cancelled = replace(_end_claim(ticket, now), resolution=Resolution.CANCELLED)
    return _apply(op.name, now, cancelled, agent=op.agent, reason=op.reason)


def decide_reap(snapshot: Snapshot, op: ReapOp, now: Timestamp) -> Decision:
    """Occupancy op. Apply: claim = None, with the reaped claim's id appended to
    ended_claim_ids, on every ticket whose claim is takeable (`Claim.is_takeable`: past
    lease_until + SKEW_GRACE), blocked or not; one record listing them all. NoOp: none
    is past the grace period. Safe to run from any writer on a schedule (idempotent)."""
    reaped = [
        _end_claim(ticket, now)
        for ticket in sorted(snapshot.tickets.values(), key=lambda t: t.id)
        if ticket.claim is not None and ticket.claim.is_takeable(now)
    ]
    if not reaped:
        return NoOp("no claim is past the grace period")
    record = OpRecord(
        op.name,
        at=now,
        ticket_ids=tuple(ticket.id for ticket in reaped),
        summary=f"reap {len(reaped)} lapsed claim(s)",
    )
    return Apply(changes=tuple(WriteTicket(ticket) for ticket in reaped), record=record)


# --- helpers ------------------------------------------------------------------


def _invalid(message: str) -> Refusal:
    return Refusal(RefusalCode.INVALID, message)


def _not_found(ticket_id: TicketId) -> Refusal:
    return Refusal(RefusalCode.NOT_FOUND, f"no ticket {ticket_id}")


def _terminal(ticket: Ticket) -> Refusal:
    assert ticket.resolution is not None
    return Refusal(RefusalCode.TERMINAL, f"{ticket.id} is {ticket.resolution.value} (final)")


def _duplicate(ticket_id: TicketId, how: str) -> Refusal:
    return Refusal(RefusalCode.DUPLICATE_ID, f"{ticket_id} already exists {how}")


def _already_ended(claim_id: ClaimId, where: TicketId) -> Refusal:
    return Refusal(RefusalCode.NOT_HOLDER, f"claim {claim_id} already ended on {where}")


def _ticket_ids_of(op: Op) -> tuple[TicketId, ...]:
    """Every ticket id an op names: its ticket, and any blockers it sets."""
    match op:
        case AddOp():
            return (op.ticket_id, *op.blocked_by)
        case EditOp():
            blocked_by = () if isinstance(op.blocked_by, Unset) else op.blocked_by
            return (op.ticket_id, *blocked_by)
        case ClaimOp() | RenewOp() | MoveOp() | ReleaseOp() | DoneOp() | CancelOp():
            return (op.ticket_id,)
        case InitOp() | ClaimNextOp() | ReapOp():
            return ()


def _texts_of(op: Op) -> dict[str, object]:
    """The free-text fields an op writes into a ticket or a commit trailer."""
    match op:
        case AddOp() | EditOp():
            return {"agent": op.agent, "title": op.title}
        case ClaimOp() | ClaimNextOp():
            return {"agent": op.agent}
        case CancelOp():
            return {"agent": op.agent, "reason": op.reason}
        case ReleaseOp():
            return {"reason": op.reason}
        case InitOp() | RenewOp() | MoveOp() | DoneOp() | ReapOp():
            return {}


def _content(ticket: Ticket) -> tuple[object, ...]:
    return (ticket.title, ticket.body, ticket.priority, ticket.blocked_by, ticket.tags)


def _invalid_content(
    snapshot: Snapshot, ticket_id: TicketId, title: str, blocked_by: tuple[TicketId, ...]
) -> Refusal | None:
    """Empty title, a ticket blocking itself, or an unknown blocker."""
    if not title.strip():
        return _invalid("title must not be empty")
    if ticket_id in blocked_by:
        return _invalid(f"{ticket_id} cannot block itself")
    if unknown := [b for b in blocked_by if snapshot.get(b) is None]:
        return _invalid(f"unknown blocker(s): {', '.join(unknown)}")
    return None


def _cycle_through(
    snapshot: Snapshot, ticket_id: TicketId, blocked_by: tuple[TicketId, ...]
) -> TicketId | None:
    """A blocker from which `ticket_id` is reachable through blocked_by links, if any."""
    for start in blocked_by:
        seen: set[TicketId] = set()
        stack = [start]
        while stack:
            current = stack.pop()
            if current == ticket_id:
                return start
            if current in seen or (found := snapshot.get(current)) is None:
                continue
            seen.add(current)
            stack.extend(found.blocked_by)
    return None


def _ended_on(snapshot: Snapshot, claim_id: ClaimId) -> TicketId | None:
    """The ticket on which `claim_id` already ended, if any (fenced for good)."""
    for ticket in snapshot.tickets.values():
        if claim_id in ticket.ended_claim_ids:
            return ticket.id
    return None


def _holder(ticket: Ticket, claim_id: ClaimId) -> Literal["current", "ended"] | Refusal:
    """Steps 2-5 of the holder-op order (design.md §5): the current claim, an ended claim
    on this ticket, no claim, or another holder."""
    if ticket.claim is not None and ticket.claim.claim_id == claim_id:
        return "current"
    if claim_id in ticket.ended_claim_ids:
        return "ended"
    if ticket.claim is None:
        return Refusal(
            RefusalCode.NOT_CLAIMED,
            f"{ticket.id} is not claimed; claim {claim_id} was never used on this ticket",
        )
    return Refusal(
        RefusalCode.NOT_HOLDER,
        f"{ticket.id} is held by another claim ({ticket.claim.agent}); "
        f"claim {claim_id} was never used on this ticket",
    )


def _end_claim(ticket: Ticket, now: Timestamp) -> Ticket:
    """Clear the claim (if any), recording its id in the ticket's claim history."""
    if ticket.claim is None:
        return replace(ticket, updated=now)
    return replace(
        ticket,
        claim=None,
        ended_claim_ids=(*ticket.ended_claim_ids, ticket.claim.claim_id),
        updated=now,
    )


def _claim(
    snapshot: Snapshot,
    ticket: Ticket,
    op_name: OpName,
    agent: AgentId,
    claim_id: ClaimId,
    ttl: Duration,
    now: Timestamp,
) -> Decision:
    """The shared body of claim and claim-next once a ticket is chosen."""
    current = ticket.claim
    if current is not None and current.claim_id == claim_id:
        if current.agent != agent:
            return Refusal(
                RefusalCode.ALREADY_CLAIMED,
                f"claim {claim_id} on {ticket.id} belongs to {current.agent}",
            )
        if current.is_live(now):
            return NoOp(f"{ticket.id} is already held by this claim", (ticket.id,))
        renewed = replace(ticket, claim=replace(current, lease_until=now + ttl), updated=now)
        return _apply(op_name, now, renewed, agent=agent, claim_id=claim_id)
    for other in snapshot.tickets.values():
        if other.claim is not None and other.claim.claim_id == claim_id:
            return Refusal(
                RefusalCode.ALREADY_CLAIMED,
                f"claim {claim_id} already holds {other.id}; one claim id names one claim",
            )
    if ended := _ended_on(snapshot, claim_id):
        return _already_ended(claim_id, ended)
    if refusal := why_not_claimable(snapshot, ticket, now):
        return refusal
    taken_over = _end_claim(ticket, now)
    claimed = replace(
        taken_over,
        claim=Claim(agent=agent, claim_id=claim_id, lease_until=now + ttl, claimed_at=now),
    )
    return _apply(op_name, now, claimed, agent=agent, claim_id=claim_id)


def _apply(
    op_name: OpName,
    now: Timestamp,
    ticket: Ticket,
    *,
    agent: AgentId | None = None,
    claim_id: ClaimId | None = None,
    reason: str = "",
    phase: Phase | None = None,
) -> Apply:
    """One written ticket under one audit record."""
    record = OpRecord(
        op_name,
        at=now,
        ticket_ids=(ticket.id,),
        agent=agent,
        claim_id=claim_id,
        reason=reason,
        summary=f"{op_name.value} {ticket.id}: {ticket.title}",
        phase=phase,
    )
    return Apply(changes=(WriteTicket(ticket),), record=record)
