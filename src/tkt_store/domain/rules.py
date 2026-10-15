"""The rules: pure decisions about an op against a snapshot at a given time.

PURE module. `decide(snapshot, op, now)` is the single entry point. It never
writes, never reads the clock, never touches git — everything it needs is in
its arguments. This is where invariants 1, 4, 5, 9 and 10 (docs/design.md §5)
live. The result is a `Decision` from `domain.outcomes`.

Every `Apply.record` carries `at=now`, the injected time (`OpRecord.at`), and the
acting `agent` when the op names one. The full op x state -> outcome table is in
docs/design.md §5; the docstrings below summarise it.
"""

from __future__ import annotations

import re

from tkt_store.domain.operations import (
    AddOp,
    CancelOp,
    ClaimNextOp,
    ClaimOp,
    DoneOp,
    InitOp,
    Op,
    ReapOp,
    ReleaseOp,
    RenewOp,
    UpdateOp,
)
from tkt_store.domain.outcomes import Decision, Refusal
from tkt_store.domain.ticket import Snapshot, Timestamp

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
        case UpdateOp():
            return decide_update(snapshot, op, now)
        case ClaimOp():
            return decide_claim(snapshot, op, now)
        case ClaimNextOp():
            return decide_claim_next(snapshot, op, now)
        case RenewOp():
            return decide_renew(snapshot, op, now)
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

    - ticket ids (`ticket_id`, each `blocked_by` entry) must match ticket.TICKET_ID_RE;
    - `claim_id` must match ticket.CLAIM_ID_RE;
    - `agent`, `reason` and `title` must not contain CONTROL_CHARS_RE;
    - `ttl` (claim, claim-next, renew) must satisfy 0 < ttl <= MAX_TTL.
    Shape checks only; anything that depends on the snapshot is each rule's concern.
    """
    raise NotImplementedError


def decide_init(snapshot: Snapshot, op: InitOp, now: Timestamp) -> Decision:
    """Apply an empty tree if snapshot.revision is None; NoOp otherwise."""
    raise NotImplementedError


def decide_add(snapshot: Snapshot, op: AddOp, now: Timestamp) -> Decision:
    """Refuse: NOT_INITIALISED, INVALID (empty title, unknown or self blocker,
    op.stage in TERMINAL — a ticket reaches DONE only through its holder),
    DUPLICATE_ID (the id exists with different content).
    NoOp: the id exists and the stored ticket's AddOp fields (title, body, kind,
    project, priority, blocked_by, tags, stage) equal the op's; created/updated are not
    compared. Once the ticket has been updated, a late re-run gets DUPLICATE_ID.
    Apply: a new ticket at op.stage with created = updated = now."""
    raise NotImplementedError


def decide_update(snapshot: Snapshot, op: UpdateOp, now: Timestamp) -> Decision:
    """Refuse: NOT_FOUND, TERMINAL, INVALID (empty title, unknown or self blocker,
    dependency cycle). NoOp: nothing differs.
    Apply: changed descriptive fields, updated = now. Never touches claim/stage; may
    add blockers to a claimed ticket without disturbing the claim.
    Last-writer-wins: a late re-run can revert someone else's newer edit."""
    raise NotImplementedError


def decide_claim(snapshot: Snapshot, op: ClaimOp, now: Timestamp) -> Decision:
    """In this order:
    NOT_FOUND; TERMINAL;
    the current claim has op.claim_id: same agent -> NoOp (live or lapsed — it was not
      taken over; the caller should renew), another agent -> ALREADY_CLAIMED;
    NOT_HOLDER if op.claim_id equals this ticket's last_claim_id or done_by (an ended
      claim's id is fenced and cannot claim again);
    then `status.why_not_claimable` (BLOCKED, ALREADY_CLAIMED; TERMINAL already handled).
    Apply: claim = (agent, claim_id, lease_until = now + ttl, claimed_at = now). Taking
    over a takeable claim sets last_claim_id to the old claim id, fencing it. Stage is
    untouched. For a new claim id, accepts exactly when `status.claimable` is true."""
    raise NotImplementedError


def decide_claim_next(snapshot: Snapshot, op: ClaimNextOp, now: Timestamp) -> Decision:
    """In this order:
    some ticket's current claim has op.claim_id: same agent -> NoOp naming that ticket
      (live or lapsed — a retry never takes a second ticket), another agent ->
      ALREADY_CLAIMED;
    NOT_HOLDER if op.claim_id equals any ticket's last_claim_id or done_by;
    choose min(sort_key_for_next) among tickets for which `status.claimable` is true and
      that match the filters (project, kind, stage), then apply as decide_claim;
    NOTHING_CLAIMABLE if there is none."""
    raise NotImplementedError


def decide_renew(snapshot: Snapshot, op: RenewOp, now: Timestamp) -> Decision:
    """Holder op (design.md §5 table), in this order after NOT_FOUND:
    TERMINAL; current claim has op.claim_id -> Apply (even if lapsed, as long as nobody
    took it over); op.claim_id == last_claim_id -> NOT_HOLDER; no claim -> NOT_CLAIMED;
    claimed by another -> NOT_HOLDER.
    Apply: lease_until = now + ttl (claimed_at unchanged)."""
    raise NotImplementedError


def decide_release(snapshot: Snapshot, op: ReleaseOp, now: Timestamp) -> Decision:
    """Holder op (design.md §5 table), in this order after NOT_FOUND:
    TERMINAL (terminal tickets are unclaimed, so this comes first);
    INVALID if to_stage is terminal (use done/cancel);
    current claim has op.claim_id -> Apply (even if lapsed, as long as nobody took it over);
    op.claim_id == last_claim_id (the claim already ended: released, reaped or taken
      over) -> NoOp if to_stage is absent or equals the current stage, else NOT_HOLDER
      ("claim ended before the handoff"); the NoOp reason says the claim ended;
    no claim -> NOT_CLAIMED; claimed by another -> NOT_HOLDER.
    A re-run of a landed release (including after a push-landed-then-conflict retry, or
    after someone else claimed the ticket) is therefore a NoOp.
    Apply: claim = None, last_claim_id = op.claim_id; stage = op.to_stage when given (a
    handoff to another phase), with record.stage = op.to_stage."""
    raise NotImplementedError


def decide_done(snapshot: Snapshot, op: DoneOp, now: Timestamp) -> Decision:
    """Holder op (design.md §5 table), in this order after NOT_FOUND:
    terminal: CANCELLED -> TERMINAL; DONE and done_by == op.claim_id -> NoOp
      (idempotent repeat); DONE otherwise -> NOT_HOLDER (fencing survives completion);
    current claim has op.claim_id -> Apply (even if lapsed, as long as nobody took it over);
    op.claim_id == last_claim_id -> NOT_HOLDER; no claim -> NOT_CLAIMED;
    claimed by another -> NOT_HOLDER.
    Not gated by blockers: invariant 10 gates claims, not completion.
    Apply: stage = DONE, done_by = op.claim_id, claim = None."""
    raise NotImplementedError


def decide_cancel(snapshot: Snapshot, op: CancelOp, now: Timestamp) -> Decision:
    """Refuse: NOT_FOUND, TERMINAL as done. NoOp: already CANCELLED.
    Apply: stage = CANCELLED, claim = None; a cleared claim's id goes to last_claim_id
    (for uniformity — the terminal check means it never changes a holder-op result)."""
    raise NotImplementedError


def decide_reap(snapshot: Snapshot, op: ReapOp, now: Timestamp) -> Decision:
    """Apply: claim = None and last_claim_id = the reaped claim's id on every ticket whose
    claim is takeable (`Claim.is_takeable`: past lease_until + SKEW_GRACE), blocked or
    not; one record listing them all. NoOp: none is past the grace period.
    Safe to run from any writer on a schedule (idempotent)."""
    raise NotImplementedError
