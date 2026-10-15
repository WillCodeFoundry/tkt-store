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
    ReapOp,
    ReleaseOp,
    RenewOp,
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
    raise NotImplementedError


def decide_init(snapshot: Snapshot, op: InitOp, now: Timestamp) -> Decision:
    """Apply an empty tree if snapshot.revision is None; NoOp otherwise. (The git store
    adds tkt-store.json to the root commit itself; it is not a ticket Change.)"""
    raise NotImplementedError


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
    raise NotImplementedError


def decide_edit(snapshot: Snapshot, op: EditOp, now: Timestamp) -> Decision:
    """Content op. In this order:
    NOT_FOUND; TERMINAL; INVALID (empty title, unknown or self blocker, dependency cycle);
    NoOp if every field the op sets already has that value (checked BEFORE the version, so
      a re-run of an edit that already landed converges);
    STALE if ticket.content_version != op.expected_version (edited since it was read).
    Apply: the content fields it sets, updated = now, content_version + 1. Never touches
    identity, workflow or occupancy; may add blockers to a claimed ticket without
    disturbing the claim. No silent overwrite: concurrent edits are refused STALE."""
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError


def decide_renew(snapshot: Snapshot, op: RenewOp, now: Timestamp) -> Decision:
    """Holder op (design.md §5 table), in this order after NOT_FOUND:
    TERMINAL; current claim has op.claim_id -> Apply (even if lapsed, as long as nobody
    took it over); op.claim_id in ended_claim_ids -> NOT_HOLDER ("already ended"); no
    claim -> NOT_CLAIMED; claimed by another -> NOT_HOLDER.
    Apply: lease_until = now + ttl (claimed_at unchanged)."""
    raise NotImplementedError


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
    raise NotImplementedError


def decide_release(snapshot: Snapshot, op: ReleaseOp, now: Timestamp) -> Decision:
    """Holder op, occupancy only (design.md §5 table), in this order after NOT_FOUND:
    TERMINAL (resolved tickets are unclaimed, so this comes first);
    current claim has op.claim_id -> Apply (even if lapsed, as long as nobody took it over);
    op.claim_id in ended_claim_ids -> NoOp, reason "claim already ended" (a re-run of a
      landed release converges, however many claims came since);
    no claim -> NOT_CLAIMED; claimed by another -> NOT_HOLDER.
    Apply: claim = None, op.claim_id appended to ended_claim_ids. The phase is untouched."""
    raise NotImplementedError


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
    raise NotImplementedError


def decide_cancel(snapshot: Snapshot, op: CancelOp, now: Timestamp) -> Decision:
    """Workflow op, deliberately unfenced (anyone may cancel; no claim needed).
    Refuse: NOT_FOUND, TERMINAL if resolved DONE. NoOp: already CANCELLED.
    Apply: resolution = CANCELLED, claim = None; a cleared claim's id is appended to
    ended_claim_ids. Phase is kept, so the ticket records where it was abandoned."""
    raise NotImplementedError


def decide_reap(snapshot: Snapshot, op: ReapOp, now: Timestamp) -> Decision:
    """Occupancy op. Apply: claim = None, with the reaped claim's id appended to
    ended_claim_ids, on every ticket whose claim is takeable (`Claim.is_takeable`: past
    lease_until + SKEW_GRACE), blocked or not; one record listing them all. NoOp: none
    is past the grace period. Safe to run from any writer on a schedule (idempotent)."""
    raise NotImplementedError
