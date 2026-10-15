"""Status is derived from facts, never stored (ADR 0004).

PURE module. `Status` answers the availability question — can this ticket be
worked, and who holds it — which is orthogonal to the `Phase` a ticket is in.
They combine in `derive_status`: a resolution dominates (a finished ticket reads
DONE/CANCELLED); otherwise the status comes from the claim and the
blockers. Everything here is a function of a snapshot, a ticket, and the current
time, so there is nothing to persist and nothing to keep in sync.

Display vs action: a claim reads EXPIRED from `lease_until`, but it may only be
taken over or reaped from `lease_until + SKEW_GRACE` (`Claim.is_takeable`). So an
EXPIRED ticket is not necessarily claimable yet.
"""

from __future__ import annotations

from enum import StrEnum

from tkt_store.domain.outcomes import Refusal, RefusalCode
from tkt_store.domain.ticket import Resolution, Snapshot, Ticket, TicketId, Timestamp


class Status(StrEnum):
    OPEN = "open"  # live, unclaimed, not blocked — available to claim
    BLOCKED = "blocked"  # no live claim, some blocker not yet done
    CLAIMED = "claimed"  # a live claim (lease_until > now)
    EXPIRED = "expired"  # a claim is present, its lease has lapsed, not blocked
    DONE = "done"  # terminal: resolution is DONE
    CANCELLED = "cancelled"  # terminal: resolution is CANCELLED


def open_blockers(snapshot: Snapshot, ticket: Ticket) -> tuple[TicketId, ...]:
    """The blockers that are not resolved DONE. An unknown id counts as not done, and a
    cancelled blocker does not satisfy the dependency (invariant 10)."""
    return tuple(
        blocker
        for blocker in ticket.blocked_by
        if (found := snapshot.get(blocker)) is None or not found.is_done
    )


def derive_status(snapshot: Snapshot, ticket: Ticket, now: Timestamp) -> Status:
    """Compute a ticket's status.

    Precedence: resolution > CLAIMED (live claim) > BLOCKED (any blocker not
    DONE) > EXPIRED (lapsed claim) > OPEN. Blocked outranks expired so a blocked
    ticket never reads as available; side effect: a blocked ticket with a lapsed
    claim reads BLOCKED (`list --status expired` omits it) although `reap` still
    releases that claim once it is past the grace. Blockers are resolved against
    `snapshot`; an unknown blocker id counts as not done.
    """
    if ticket.resolution is Resolution.DONE:
        return Status.DONE
    if ticket.resolution is Resolution.CANCELLED:
        return Status.CANCELLED
    if ticket.claim is not None and ticket.claim.is_live(now):
        return Status.CLAIMED
    if open_blockers(snapshot, ticket):
        return Status.BLOCKED
    if ticket.claim is not None:
        return Status.EXPIRED
    return Status.OPEN


def why_not_claimable(snapshot: Snapshot, ticket: Ticket, now: Timestamp) -> Refusal | None:
    """The single claimability check, shared by `claimable` and the claim rules.

    None if a NEW claim may be taken now; otherwise the refusal, in this order:
    TERMINAL (resolved); BLOCKED (any blocker not resolved DONE; unknown counts as not done);
    ALREADY_CLAIMED (a claim that is not takeable: live, or lapsed within SKEW_GRACE).
    Not the same as status in {OPEN, EXPIRED}: a claim within the grace reads EXPIRED
    but cannot be taken yet. Claim-id checks (re-runs, ended ids) are the rules' concern.
    """
    if ticket.resolution is not None:
        return Refusal(RefusalCode.TERMINAL, f"{ticket.id} is {ticket.resolution.value}")
    if blockers := open_blockers(snapshot, ticket):
        return Refusal(RefusalCode.BLOCKED, f"{ticket.id} is blocked by {', '.join(blockers)}")
    claim = ticket.claim
    if claim is not None and not claim.is_takeable(now):
        state = "until" if claim.is_live(now) else "lapsed at"
        return Refusal(
            RefusalCode.ALREADY_CLAIMED,
            f"{ticket.id} is held by {claim.agent} ({state} {claim.lease_until})",
        )
    return None


def claimable(snapshot: Snapshot, ticket: Ticket, now: Timestamp) -> bool:
    """True iff a new claim on `ticket` would be accepted now."""
    return why_not_claimable(snapshot, ticket, now) is None


def sort_key_for_next(ticket: Ticket) -> tuple[bool, int, int, str]:
    """Ordering for claim-next: priority (lower first, None last), then created, then id."""
    return (ticket.priority is None, ticket.priority or 0, ticket.created, ticket.id)
