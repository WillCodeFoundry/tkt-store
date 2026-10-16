"""The rules: pure decisions about an op against a snapshot at a given time.

PURE module. `decide(snapshot, op, now)` is the single entry point. It never
writes, never reads the clock, never touches git — everything it needs is in
its arguments. This is where invariants 1, 4, 5, 8, 9, 10, 11 and 12 (docs/design.md §5)
live. The result is a `Decision` from `domain.outcomes`.

Every `Apply.record` carries `at=now`, the injected time (`OpRecord.at`), the acting
`agent` when the op names one, and the claim's hash when it concerns a claim. Every
ticket an Apply writes gets updated = now (never before created, `_touched`); its
`content_version` starts at 1 (add) and only `edit` increments it. Claims are files of
their own (ADR 0007): a claim op writes a `WriteClaim`, never the ticket, and ending a
claim (release, reap, takeover, cancel, done) turns it into an `EndedClaim`, kept for
good. The full op x state -> outcome table is in docs/design.md §5; the docstrings below
summarise it.

Ops carry the caller's claim id; the rules compare only its hash (`claim_hash`), and
neither is ever echoed. Refusal messages distinguish three cases, so an agent knows what
happened: "this claim already ended on <ticket>", "this claim was never used on
<ticket>", and "held by another claim".
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any, TypeVar

from tkt_store.domain import fields
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
    UnsetType,
)
from tkt_store.domain.outcomes import (
    Apply,
    Change,
    Decision,
    NoOp,
    OpRecord,
    Refusal,
    RefusalCode,
    WriteClaim,
    WriteTicket,
)
from tkt_store.domain.status import claimable, sort_key_for_next, why_not_claimable
from tkt_store.domain.ticket import (
    MAX_TTL,
    AgentId,
    Claim,
    ClaimHash,
    Duration,
    EndedBy,
    EndedClaim,
    Phase,
    Resolution,
    Snapshot,
    Ticket,
    TicketId,
    Timestamp,
    claim_hash,
)


def decide(snapshot: Snapshot, op: Op, now: Timestamp) -> Decision:
    """Dispatch to the rule for this op type. Exhaustive over `Op`.

    `validate_op` runs first; its refusal (INVALID) wins over every other outcome. Then
    `set_aside_refusal` (SET_ASIDE, ADR 0007), before every rule's own refusals. Last,
    every ticket an Apply would write must be writable (`_unwritable`), or the op is
    refused instead, so tkt never writes an invalid ticket or a file it would refuse to
    read.
    """
    if (invalid := validate_op(op)) is not None:
        return invalid
    if (aside := set_aside_refusal(snapshot, op)) is not None:
        return aside
    decision = _decide(snapshot, op, now)
    if isinstance(decision, Apply):
        for change in decision.changes:
            if isinstance(change, WriteTicket) and (refusal := _unwritable(change.ticket)):
                return refusal
    return decision


def set_aside_refusal(snapshot: Snapshot, op: Op) -> Refusal | None:
    """SET_ASIDE, in ADR 0007's order, if the op would act on something set aside:

    1. it names a set-aside ticket, as its ticket or as a blocker (`add` and `edit`; an
       edit checks the blockers of the ticket it would write, existing ones included);
       `add` of an id whose ticket, or claims folder without a ticket, is set aside;
    2. any op but `cancel` on a ticket held by a set-aside claim;
    3. a claim op or holder op whose claim hash has no valid file but a set-aside one, or
       lies on a set-aside ticket.
    Otherwise None, and the rules see only valid tickets and claims."""
    for ticket_id in _named_tickets(snapshot, op):
        if aside := ticket_set_aside(snapshot, ticket_id):
            return aside
    target = _ticket_of(op)
    held = None if target is None else snapshot.held_aside.get(target)
    if held and not isinstance(op, CancelOp):
        return _aside(f"{target} is held by a set-aside claim ({held})")
    match op:
        case ClaimOp() | ClaimNextOp() | RenewOp() | MoveOp() | ReleaseOp() | DoneOp():
            hashed = claim_hash(op.claim_id)
            if snapshot.find(hashed) is None and (why := snapshot.fenced.get(hashed)):
                return _aside(f"this claim is set aside ({why})")
    return None


def ticket_set_aside(snapshot: Snapshot, ticket_id: TicketId) -> Refusal | None:
    """SET_ASIDE if `ticket_id` was set aside on reading, naming the check that failed."""
    if why := snapshot.set_aside.get(ticket_id):
        return _aside(f"{ticket_id} is set aside ({why})")
    return None


def _unwritable(ticket: Ticket) -> Refusal | None:
    """INVALID if `ticket` breaks a field rule (`fields.ticket_problem`) or its file would
    exceed fields.TICKET_FILE_MAX. Claims never make a ticket file grow (ADR 0007)."""
    if problem := fields.ticket_problem(ticket):
        return _invalid(f"{ticket.id}: {problem}")
    if len(ticket.encoded()) > fields.TICKET_FILE_MAX:
        kib = fields.TICKET_FILE_MAX // 1024
        return _invalid(f"{ticket.id}: the ticket file would exceed {kib} KiB")
    return None


def _decide(snapshot: Snapshot, op: Op, now: Timestamp) -> Decision:
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

    - every value the op writes into a ticket or a commit trailer (ticket ids, claim id,
      title, body, reason, agent, tags, project, priority, blocked_by) must pass its
      `domain.fields` rule; an edit checks only the fields it sets;
    - `ttl` (claim, claim-next, renew) must satisfy 0 < ttl <= MAX_TTL;
    - `expected_version` (edit) must be >= 1.
    Shape checks only; anything that depends on the snapshot is each rule's concern.
    Filters (claim-next's project, kind, phase) are not written, so not checked: one
    that matches nothing finds nothing.
    """
    if problems := _field_problems(op):
        return _invalid(problems[0])
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
    """Refuse: NOT_INITIALISED, INVALID (unknown or self blocker).
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
    if invalid := _invalid_blockers(snapshot, op.ticket_id, op.blocked_by):
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
    return _apply(op.name, now, ticket, (WriteTicket(ticket),), agent=op.agent)


def decide_edit(snapshot: Snapshot, op: EditOp, now: Timestamp) -> Decision:
    """Content op. In this order:
    NOT_FOUND; TERMINAL; INVALID (unknown or self blocker, dependency cycle);
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
    blocked_by = changes.get("blocked_by", ticket.blocked_by)
    if invalid := _invalid_blockers(snapshot, ticket.id, blocked_by):
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
    edited = _touched(ticket, now, **changes, content_version=ticket.content_version + 1)
    return _apply(op.name, now, edited, (WriteTicket(edited),), agent=op.agent)


def decide_claim(snapshot: Snapshot, op: ClaimOp, now: Timestamp) -> Decision:
    """Occupancy op. In this order:
    NOT_FOUND; TERMINAL;
    this ticket's open claim has the op's hash:
      another agent -> ALREADY_CLAIMED;
      same agent, live -> NoOp (a re-run after success);
      same agent, lapsed (not taken over) -> Apply: renew it, lease_until = now + ttl,
        claimed_at unchanged (a re-run after an outage gets a live claim, not a stale one);
    ALREADY_CLAIMED if the hash is the open claim of another ticket (one claim id names
      one claim on one ticket);
    NOT_HOLDER if the hash has ended anywhere (an ended claim is fenced for good);
    then `status.why_not_claimable` (BLOCKED, ALREADY_CLAIMED; TERMINAL already handled).
    Apply: a new open claim (agent, hash, claimed_at = now, lease_until = now + ttl).
    Taking over a takeable claim first ends it as taken over, fencing it. The ticket is
    not written. For a new hash, accepts exactly when `status.claimable` is true."""
    ticket = snapshot.get(op.ticket_id)
    if ticket is None:
        return _not_found(op.ticket_id)
    if ticket.is_terminal:
        return _terminal(ticket)
    return _claim(snapshot, ticket, op.name, op.agent, claim_hash(op.claim_id), op.ttl, now)


def decide_claim_next(snapshot: Snapshot, op: ClaimNextOp, now: Timestamp) -> Decision:
    """Occupancy op. In this order:
    the op's hash is a ticket's open claim: as decide_claim on that ticket (another
      agent -> ALREADY_CLAIMED; same agent, live -> NoOp naming that ticket, so a retry
      never takes a second ticket; lapsed -> renew it);
    NOT_HOLDER if the hash has ended anywhere;
    choose min(sort_key_for_next) among tickets for which `status.claimable` is true and
      that match the filters (project, kind, phase; a project filter matches that exact
      value only, never a null project), then apply as decide_claim; set-aside tickets
      are never candidates, and a ticket held by a set-aside claim is not claimable;
    NOTHING_CLAIMABLE if there is none."""
    hashed = claim_hash(op.claim_id)
    found = snapshot.find(hashed)
    if isinstance(found, Claim) and (held := snapshot.get(found.ticket_id)) is not None:
        return _claim(snapshot, held, op.name, op.agent, hashed, op.ttl, now)
    if isinstance(found, EndedClaim):
        return _already_ended(found.ticket_id)
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
    return _claim(snapshot, chosen, op.name, op.agent, hashed, op.ttl, now)


def decide_renew(snapshot: Snapshot, op: RenewOp, now: Timestamp) -> Decision:
    """Holder op (design.md §5 table), in this order after NOT_FOUND:
    TERMINAL; open claim has the op's hash -> Apply (even if lapsed, as long as nobody
    took it over); the hash ended on this ticket -> NOT_HOLDER ("already ended"); no
    claim -> NOT_CLAIMED; claimed by another -> NOT_HOLDER.
    Apply: the claim with lease_until = now + ttl (claimed_at unchanged); NoOp if that is
    its lease already (the same file name: a re-run in the same second, or a renewer whose
    clock is clamped to claimed_at)."""
    ticket = snapshot.get(op.ticket_id)
    if ticket is None:
        return _not_found(op.ticket_id)
    if ticket.is_terminal:
        return _terminal(ticket)
    hashed = claim_hash(op.claim_id)
    match _holder(snapshot, ticket, hashed):
        case Refusal() as refusal:
            return refusal
        case EndedClaim():
            return _already_ended(ticket.id)
        case Claim() as current:
            renewed = current.renewed(now + op.ttl)
            if renewed == current:  # same name: nothing to write, no push to spend
                return NoOp(f"the lease on {ticket.id} already ends then", (ticket.id,))
            return _apply(
                op.name, now, ticket, (WriteClaim(renewed, current),),
                agent=current.agent, claim_hash=hashed,
            )  # fmt: skip


def decide_move(snapshot: Snapshot, op: MoveOp, now: Timestamp) -> Decision:
    """Holder op, workflow only (design.md §5 table), in this order after NOT_FOUND:
    TERMINAL;
    open claim has the op's hash -> NoOp if already in op.to_phase, else Apply (even if
      lapsed, as long as nobody took it over);
    the hash ended on this ticket -> NoOp if the ticket is in op.to_phase (a re-run after
      the move landed and the claim was released), else NOT_HOLDER ("claim ended before
      the move");
    no claim -> NOT_CLAIMED; claimed by another -> NOT_HOLDER.
    Apply: the ticket with phase = op.to_phase, and record.phase = op.to_phase. The claim
    is kept: a handoff is move, then release."""
    ticket = snapshot.get(op.ticket_id)
    if ticket is None:
        return _not_found(op.ticket_id)
    if ticket.is_terminal:
        return _terminal(ticket)
    hashed = claim_hash(op.claim_id)
    holder = _holder(snapshot, ticket, hashed)
    if isinstance(holder, Refusal):
        return holder
    if ticket.phase is op.to_phase:
        return NoOp(f"{ticket.id} is already in {op.to_phase.value}", (ticket.id,))
    if isinstance(holder, EndedClaim):
        return Refusal(
            RefusalCode.NOT_HOLDER, f"this claim already ended on {ticket.id} before the move"
        )
    moved = _touched(ticket, now, phase=op.to_phase)
    return _apply(
        op.name, now, moved, (WriteTicket(moved),),
        agent=holder.agent, claim_hash=hashed, phase=op.to_phase,
    )  # fmt: skip


def decide_release(snapshot: Snapshot, op: ReleaseOp, now: Timestamp) -> Decision:
    """Holder op, occupancy only (design.md §5 table), in this order after NOT_FOUND:
    TERMINAL (resolved tickets are unclaimed, so this comes first);
    open claim has the op's hash -> Apply (even if lapsed, as long as nobody took it over);
    the hash ended on this ticket -> NoOp, reason "claim already ended" (a re-run of a
      landed release converges, however many claims came since);
    no claim -> NOT_CLAIMED; claimed by another -> NOT_HOLDER.
    Apply: the claim ended as released. The ticket and its phase are untouched."""
    ticket = snapshot.get(op.ticket_id)
    if ticket is None:
        return _not_found(op.ticket_id)
    if ticket.is_terminal:
        return _terminal(ticket)
    hashed = claim_hash(op.claim_id)
    match _holder(snapshot, ticket, hashed):
        case Refusal() as refusal:
            return refusal
        case EndedClaim():
            return NoOp(f"this claim already ended on {ticket.id}", (ticket.id,))
        case Claim() as current:
            ended = current.ended(EndedBy.RELEASED, now)
            return _apply(
                op.name, now, ticket, (WriteClaim(ended, current),),
                agent=current.agent, claim_hash=hashed, reason=op.reason,
            )  # fmt: skip


def decide_done(snapshot: Snapshot, op: DoneOp, now: Timestamp) -> Decision:
    """Holder op (design.md §5 table), in this order after NOT_FOUND:
    resolved: CANCELLED -> TERMINAL; DONE and the op's hash ended on this ticket as done
      -> NoOp (idempotent repeat); DONE otherwise -> NOT_HOLDER (fencing survives
      completion);
    open claim has the hash -> Apply (even if lapsed, as long as nobody took it over);
    the hash ended on this ticket -> NOT_HOLDER ("already ended"); no claim ->
    NOT_CLAIMED; claimed by another -> NOT_HOLDER.
    Not gated by blockers: invariant 10 gates claims, not completion.
    Apply: the ticket with resolution = DONE (phase kept), and the claim ended as done."""
    ticket = snapshot.get(op.ticket_id)
    if ticket is None:
        return _not_found(op.ticket_id)
    hashed = claim_hash(op.claim_id)
    if ticket.resolution is Resolution.CANCELLED:
        return _terminal(ticket)
    if ticket.resolution is Resolution.DONE:
        ended = snapshot.ended.get(hashed)
        if ended is not None and ended.ticket_id == ticket.id and ended.ended_by is EndedBy.DONE:
            return NoOp(f"{ticket.id} already done by this claim", (ticket.id,))
        return Refusal(RefusalCode.NOT_HOLDER, f"{ticket.id} was completed by another claim")
    match _holder(snapshot, ticket, hashed):
        case Refusal() as refusal:
            return refusal
        case EndedClaim():
            return _already_ended(ticket.id)
        case Claim() as current:
            done = _touched(ticket, now, resolution=Resolution.DONE)
            changes = (WriteTicket(done), WriteClaim(current.ended(EndedBy.DONE, now), current))
            return _apply(op.name, now, done, changes, agent=current.agent, claim_hash=hashed)


def decide_cancel(snapshot: Snapshot, op: CancelOp, now: Timestamp) -> Decision:
    """Workflow op, deliberately unfenced (anyone may cancel; no claim needed), and the
    only op allowed on a ticket held by a set-aside claim, so no ticket is locked for good.
    Refuse: NOT_FOUND, TERMINAL if resolved DONE. NoOp: already CANCELLED.
    Apply: the ticket with resolution = CANCELLED (phase kept, so it records where it was
    abandoned), and its open claim, if any, ended as cancelled."""
    ticket = snapshot.get(op.ticket_id)
    if ticket is None:
        return _not_found(op.ticket_id)
    if ticket.resolution is Resolution.CANCELLED:
        return NoOp(f"{ticket.id} is already cancelled", (ticket.id,))
    if ticket.resolution is Resolution.DONE:
        return _terminal(ticket)
    cancelled = _touched(ticket, now, resolution=Resolution.CANCELLED)
    changes: list[Change] = [WriteTicket(cancelled)]
    if (current := snapshot.claim_of(ticket.id)) is not None:
        changes.append(WriteClaim(current.ended(EndedBy.CANCELLED, now), current))
    return _apply(op.name, now, cancelled, changes, agent=op.agent, reason=op.reason)


def decide_reap(snapshot: Snapshot, op: ReapOp, now: Timestamp) -> Decision:
    """Occupancy op. Apply: every valid open claim that is takeable (`Claim.is_takeable`:
    past lease_until + SKEW_GRACE, or beyond the cap), blocked or not, ended as reaped;
    one record listing their tickets. Set-aside claims, and claims on set-aside tickets,
    are left alone. NoOp: none is takeable. Safe to run from any writer on a schedule
    (idempotent)."""
    reaped = [
        claim
        for claim in sorted(snapshot.claims.values(), key=lambda c: c.ticket_id)
        if claim.is_takeable(now)
    ]
    if not reaped:
        return NoOp("no claim is past the grace period")
    record = OpRecord(
        op.name,
        at=now,
        ticket_ids=tuple(claim.ticket_id for claim in reaped),
        summary=f"reap {len(reaped)} lapsed claim(s)",
    )
    changes = tuple(WriteClaim(claim.ended(EndedBy.REAPED, now), claim) for claim in reaped)
    return Apply(changes=changes, record=record)


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


def _already_ended(where: TicketId) -> Refusal:
    return Refusal(RefusalCode.NOT_HOLDER, f"this claim already ended on {where}")


def _aside(message: str) -> Refusal:
    return Refusal(RefusalCode.SET_ASIDE, f"{message}; an operator must repair the store")


def _field_problems(op: Op) -> list[str]:
    """The `domain.fields` problems of every value an op writes, in field order."""
    match op:
        case AddOp():
            verdicts = [
                fields.ticket_id_problem(op.ticket_id),
                fields.title_problem(op.title),
                fields.body_problem(op.body),
                fields.project_problem(op.project),
                fields.priority_problem(op.priority),
                fields.blockers_problem(op.blocked_by),
                fields.tags_problem(op.tags),
                fields.agent_problem(op.agent),
            ]
        case EditOp():
            verdicts = [
                fields.ticket_id_problem(op.ticket_id),
                _if_set(fields.title_problem, op.title),
                _if_set(fields.body_problem, op.body),
                _if_set(fields.priority_problem, op.priority),
                _if_set(fields.blockers_problem, op.blocked_by),
                _if_set(fields.tags_problem, op.tags),
                fields.agent_problem(op.agent),
            ]
        case ClaimOp():
            verdicts = [
                fields.ticket_id_problem(op.ticket_id),
                fields.claim_id_problem(op.claim_id),
                fields.agent_problem(op.agent),
            ]
        case ClaimNextOp():
            verdicts = [fields.claim_id_problem(op.claim_id), fields.agent_problem(op.agent)]
        case RenewOp() | MoveOp() | DoneOp():
            verdicts = [
                fields.ticket_id_problem(op.ticket_id),
                fields.claim_id_problem(op.claim_id),
            ]
        case ReleaseOp():
            verdicts = [
                fields.ticket_id_problem(op.ticket_id),
                fields.claim_id_problem(op.claim_id),
                fields.reason_problem(op.reason),
            ]
        case CancelOp():
            verdicts = [
                fields.ticket_id_problem(op.ticket_id),
                fields.reason_problem(op.reason),
                fields.agent_problem(op.agent),
            ]
        case InitOp() | ReapOp():
            verdicts = []
    return [verdict for verdict in verdicts if verdict is not None]


_V = TypeVar("_V")


def _if_set(check: Callable[[_V], str | None], value: _V | UnsetType) -> str | None:
    """`check(value)`, or None for a field the edit leaves unchanged."""
    return None if isinstance(value, Unset) else check(value)


def _content(ticket: Ticket) -> tuple[object, ...]:
    return (ticket.title, ticket.body, ticket.priority, ticket.blocked_by, ticket.tags)


def _invalid_blockers(
    snapshot: Snapshot, ticket_id: TicketId, blocked_by: tuple[TicketId, ...]
) -> Refusal | None:
    """A ticket blocking itself, or an unknown blocker."""
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


def _touched(ticket: Ticket, now: Timestamp, **changes: Any) -> Ticket:
    """`ticket` with `changes`, written at `now`: `updated` is never before `created`, even
    when this writer's clock is behind the creator's (tkt never writes what it would set
    aside)."""
    return replace(ticket, **changes, updated=max(now, ticket.created))


def _holder(snapshot: Snapshot, ticket: Ticket, hashed: ClaimHash) -> Claim | EndedClaim | Refusal:
    """Steps 2-5 of the holder-op order (design.md §5): the ticket's open claim if it has
    the hash, the claim if it ended on this ticket, else NOT_CLAIMED (no claim) or
    NOT_HOLDER (another holder)."""
    current = snapshot.claim_of(ticket.id)
    if current is not None and current.hash == hashed:
        return current
    ended = snapshot.ended.get(hashed)
    if ended is not None and ended.ticket_id == ticket.id:
        return ended
    if current is None:
        return Refusal(
            RefusalCode.NOT_CLAIMED,
            f"{ticket.id} is not claimed; this claim was never used on {ticket.id}",
        )
    return Refusal(
        RefusalCode.NOT_HOLDER,
        f"{ticket.id} is held by another claim ({current.agent}); "
        f"this claim was never used on {ticket.id}",
    )


def _claim(
    snapshot: Snapshot,
    ticket: Ticket,
    op_name: OpName,
    agent: AgentId,
    hashed: ClaimHash,
    ttl: Duration,
    now: Timestamp,
) -> Decision:
    """The shared body of claim and claim-next once a ticket is chosen."""
    current = snapshot.claim_of(ticket.id)
    if current is not None and current.hash == hashed:
        if current.agent != agent:
            return Refusal(
                RefusalCode.ALREADY_CLAIMED, f"this claim on {ticket.id} belongs to {current.agent}"
            )
        if current.is_live(now):
            return NoOp(f"{ticket.id} is already held by this claim", (ticket.id,))
        renewed = current.renewed(now + ttl)
        if renewed == current:  # this clock is too far behind the claimer's to extend it
            return NoOp(f"the lapsed lease on {ticket.id} could not be extended", (ticket.id,))
        return _apply(
            op_name, now, ticket, (WriteClaim(renewed, current),), agent=agent, claim_hash=hashed
        )
    found = snapshot.find(hashed)
    if isinstance(found, Claim):
        return Refusal(
            RefusalCode.ALREADY_CLAIMED,
            f"this claim already holds {found.ticket_id}; one claim id names one claim",
        )
    if isinstance(found, EndedClaim):
        return _already_ended(found.ticket_id)
    if refusal := why_not_claimable(snapshot, ticket, now):
        return refusal
    changes: list[Change] = []
    if current is not None:
        changes.append(WriteClaim(current.ended(EndedBy.TAKEN_OVER, now), current))
    changes.append(WriteClaim(Claim(ticket.id, hashed, agent, now, now + ttl)))
    return _apply(op_name, now, ticket, changes, agent=agent, claim_hash=hashed)


def _apply(
    op_name: OpName,
    now: Timestamp,
    ticket: Ticket,
    changes: Sequence[Change],
    *,
    agent: AgentId | None = None,
    claim_hash: ClaimHash | None = None,
    reason: str = "",
    phase: Phase | None = None,
) -> Apply:
    """`changes` to one ticket and its claims, under one audit record."""
    record = OpRecord(
        op_name,
        at=now,
        ticket_ids=(ticket.id,),
        agent=agent,
        claim_hash=claim_hash,
        reason=reason,
        summary=f"{op_name.value} {ticket.id}: {ticket.title}",
        phase=phase,
    )
    return Apply(changes=tuple(changes), record=record)


def _named_tickets(snapshot: Snapshot, op: Op) -> tuple[TicketId, ...]:
    """The ticket ids an op names for SET_ASIDE step 1: its ticket, and for add and edit
    the blockers of the ticket it would write."""
    match op:
        case AddOp():
            return (op.ticket_id, *op.blocked_by)
        case EditOp():
            if not isinstance(op.blocked_by, Unset):
                return (op.ticket_id, *op.blocked_by)
            existing = snapshot.get(op.ticket_id)
            return (op.ticket_id, *(() if existing is None else existing.blocked_by))
        case ClaimOp() | RenewOp() | MoveOp() | ReleaseOp() | DoneOp() | CancelOp():
            return (op.ticket_id,)
        case InitOp() | ClaimNextOp() | ReapOp():
            return ()


def _ticket_of(op: Op) -> TicketId | None:
    match op:
        case InitOp() | ClaimNextOp() | ReapOp():
            return None
        case _:
            return op.ticket_id
