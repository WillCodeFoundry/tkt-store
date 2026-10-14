"""The rules: pure decisions about an op against a snapshot at a given time.

PURE module. `decide(snapshot, op, now)` is the single entry point. It never
writes, never reads the clock, never touches git — everything it needs is in
its arguments. This is where invariants 1, 4, 5, 9 and 10 (docs/design.md §5)
live. The result is a `Decision` from `domain.outcomes`.
"""

from __future__ import annotations

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
from tkt_store.domain.outcomes import Decision
from tkt_store.domain.ticket import Snapshot, Timestamp


def decide(snapshot: Snapshot, op: Op, now: Timestamp) -> Decision:
    """Dispatch to the rule for this op type. Exhaustive over `Op`."""
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


def decide_init(snapshot: Snapshot, op: InitOp, now: Timestamp) -> Decision:
    """Apply an empty tree if base is None; NoOp otherwise."""
    raise NotImplementedError


def decide_add(snapshot: Snapshot, op: AddOp, now: Timestamp) -> Decision:
    """Refuse: NOT_INITIALISED, INVALID (empty title, unknown or self blocker),
    DUPLICATE_ID (same id, different content). NoOp: same id, identical content.
    Apply: a new ticket at op.stage with created = updated = now."""
    raise NotImplementedError


def decide_update(snapshot: Snapshot, op: UpdateOp, now: Timestamp) -> Decision:
    """Refuse: NOT_FOUND, TERMINAL, INVALID (dependency cycle). NoOp: nothing differs.
    Apply: changed descriptive fields, updated = now. Never touches claim/stage."""
    raise NotImplementedError


def decide_claim(snapshot: Snapshot, op: ClaimOp, now: Timestamp) -> Decision:
    """Refuse: NOT_FOUND, TERMINAL, BLOCKED, ALREADY_CLAIMED (live claim by another claim_id),
    INVALID (ttl <= 0). NoOp: a live claim with the same claim_id.
    Apply: claim = (agent, claim_id, now + ttl); takes over an EXPIRED claim. Stage is untouched."""
    raise NotImplementedError


def decide_claim_next(snapshot: Snapshot, op: ClaimNextOp, now: Timestamp) -> Decision:
    """Choose min(sort_key_for_next) among claimable tickets matching filters
    (project, kind, stage), then as decide_claim.
    NoOp: the same claim_id already holds a live claim on some ticket (retry after success).
    Refuse: NOTHING_CLAIMABLE."""
    raise NotImplementedError


def decide_renew(snapshot: Snapshot, op: RenewOp, now: Timestamp) -> Decision:
    """Refuse: NOT_FOUND, TERMINAL, NOT_CLAIMED, NOT_HOLDER (claim_id mismatch — fencing).
    An expired claim with a matching claim_id MAY be renewed if nobody took it over.
    Apply: lease_until = now + ttl."""
    raise NotImplementedError


def decide_release(snapshot: Snapshot, op: ReleaseOp, now: Timestamp) -> Decision:
    """Refuse: NOT_FOUND, NOT_HOLDER, INVALID (to_stage is terminal — use done/cancel).
    NoOp: not claimed and no stage change (already released).
    Apply: claim = None; stage = op.to_stage when given (a handoff to another phase)."""
    raise NotImplementedError


def decide_done(snapshot: Snapshot, op: DoneOp, now: Timestamp) -> Decision:
    """Refuse: NOT_FOUND, NOT_HOLDER, TERMINAL as cancelled.
    NoOp: already DONE (idempotent repeat after success).
    Apply: stage = DONE, claim = None."""
    raise NotImplementedError


def decide_cancel(snapshot: Snapshot, op: CancelOp, now: Timestamp) -> Decision:
    """Refuse: NOT_FOUND, TERMINAL as done. NoOp: already CANCELLED.
    Apply: stage = CANCELLED, claim = None."""
    raise NotImplementedError


def decide_reap(snapshot: Snapshot, op: ReapOp, now: Timestamp) -> Decision:
    """Apply: claim = None on every ticket whose claim has expired; one record listing them all.
    NoOp: none expired."""
    raise NotImplementedError
