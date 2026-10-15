"""The rules: pure decisions about an op against a snapshot at a given time.

PURE module. `decide(snapshot, op, now)` is the single entry point. It never
writes, never reads the clock, never touches git — everything it needs is in
its arguments. This is where invariants 1, 4, 5, 9 and 10 (docs/design.md §5)
live. The result is a `Decision` from `domain.outcomes`.

Every `Apply.record` carries `at=now`, the injected time (`OpRecord.at`).
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

TICKET_ID_RE = re.compile(r"^tkt-[0-9a-f]+$")
"""A ticket id, also its file name `tickets/<id>.json`: no '/', '.', or traversal."""

CLAIM_ID_RE = re.compile(r"^[0-9a-f]+$")
"""A claim id, written verbatim into the `tkt-claim` trailer."""

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
    """Refusal(INVALID) if any externally supplied string in `op` is malformed, else None.

    - ticket ids (`ticket_id`, each `blocked_by` entry) must match TICKET_ID_RE;
    - `claim_id` must match CLAIM_ID_RE;
    - `agent`, `reason` and `title` must not contain CONTROL_CHARS_RE.
    Shape checks only; whether ids exist is each rule's concern.
    """
    raise NotImplementedError


def decide_init(snapshot: Snapshot, op: InitOp, now: Timestamp) -> Decision:
    """Apply an empty tree if snapshot.revision is None; NoOp otherwise."""
    raise NotImplementedError


def decide_add(snapshot: Snapshot, op: AddOp, now: Timestamp) -> Decision:
    """Refuse: NOT_INITIALISED, INVALID (empty title, unknown or self blocker,
    op.stage in TERMINAL — a ticket reaches DONE only through its holder),
    DUPLICATE_ID (same id, different content). NoOp: same id, identical content.
    Apply: a new ticket at op.stage with created = updated = now."""
    raise NotImplementedError


def decide_update(snapshot: Snapshot, op: UpdateOp, now: Timestamp) -> Decision:
    """Refuse: NOT_FOUND, TERMINAL, INVALID (empty title, unknown or self blocker,
    dependency cycle). NoOp: nothing differs.
    Apply: changed descriptive fields, updated = now. Never touches claim/stage."""
    raise NotImplementedError


def decide_claim(snapshot: Snapshot, op: ClaimOp, now: Timestamp) -> Decision:
    """Refuse: NOT_FOUND, TERMINAL, BLOCKED, ALREADY_CLAIMED (a claim by another
    claim_id that is not yet takeable — live, or lapsed but within SKEW_GRACE),
    INVALID (ttl <= 0). NoOp: a live claim with the same claim_id.
    Apply: claim = (agent, claim_id, now + ttl); takes over a takeable claim
    (`Claim.is_takeable`), fencing out its claim_id. Stage is untouched.
    Accepts exactly when `status.claimable` is true."""
    raise NotImplementedError


def decide_claim_next(snapshot: Snapshot, op: ClaimNextOp, now: Timestamp) -> Decision:
    """Choose min(sort_key_for_next) among tickets for which `status.claimable` is
    true and that match the filters (project, kind, stage), then as decide_claim.
    NoOp: the same claim_id already holds a live claim on some ticket (retry after success).
    Refuse: NOTHING_CLAIMABLE."""
    raise NotImplementedError


def decide_renew(snapshot: Snapshot, op: RenewOp, now: Timestamp) -> Decision:
    """Refuse: NOT_FOUND, TERMINAL, NOT_CLAIMED, NOT_HOLDER (claim_id mismatch — fencing).
    An expired claim with a matching claim_id MAY be renewed if nobody took it over.
    Apply: lease_until = now + ttl."""
    raise NotImplementedError


def decide_release(snapshot: Snapshot, op: ReleaseOp, now: Timestamp) -> Decision:
    """Refuse, checked in this order:
    NOT_FOUND; TERMINAL (already done/cancelled — checked before the unclaimed
    case, since terminal tickets are unclaimed); INVALID (to_stage is terminal —
    use done/cancel); NOT_HOLDER (claimed under another claim_id).

    Unclaimed, non-terminal ticket (a re-run, or a retry after the push landed):
    - to_stage absent or equal to the current stage -> NoOp (effect already present);
    - to_stage differs from the current stage -> NOT_HOLDER (a fenced-out agent
      must not move the stage).

    A matching claim_id is accepted even when the claim has expired, as long as
    nobody took it over (mirrors decide_renew).
    Apply: claim = None; stage = op.to_stage when given (a handoff to another
    phase), with record.stage = op.to_stage."""
    raise NotImplementedError


def decide_done(snapshot: Snapshot, op: DoneOp, now: Timestamp) -> Decision:
    """Refuse: NOT_FOUND; TERMINAL if CANCELLED; NOT_HOLDER if claimed under another
    claim_id, or if already DONE with done_by != op.claim_id (fencing survives
    completion).
    NoOp: already DONE and op.claim_id == done_by (idempotent repeat after success).
    A matching claim_id is accepted even when the claim has expired, as long as
    nobody took it over (mirrors decide_renew).
    Apply: stage = DONE, done_by = op.claim_id, claim = None."""
    raise NotImplementedError


def decide_cancel(snapshot: Snapshot, op: CancelOp, now: Timestamp) -> Decision:
    """Refuse: NOT_FOUND, TERMINAL as done. NoOp: already CANCELLED.
    Apply: stage = CANCELLED, claim = None."""
    raise NotImplementedError


def decide_reap(snapshot: Snapshot, op: ReapOp, now: Timestamp) -> Decision:
    """Apply: claim = None on every ticket whose claim is takeable
    (`Claim.is_takeable`: past lease_until + SKEW_GRACE), blocked or not; one record
    listing them all. NoOp: none is past the grace period.
    Safe to run from any writer on a schedule (idempotent)."""
    raise NotImplementedError
