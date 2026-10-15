"""Status is derived from facts, never stored (ADR 0004).

PURE module. `Status` answers the availability question — can this ticket be
worked, and who holds it — which is orthogonal to the `Stage` a ticket sits at.
The two combine in `derive_status`: a terminal stage dominates (a finished
ticket reads DONE/CANCELLED); otherwise the status comes from the claim and the
blockers. Everything here is a function of a snapshot, a ticket, and the current
time, so there is nothing to persist and nothing to keep in sync.

Display vs action: a claim reads EXPIRED from `lease_until`, but it may only be
taken over or reaped from `lease_until + SKEW_GRACE` (`Claim.is_takeable`). So an
EXPIRED ticket is not necessarily claimable yet.
"""

from __future__ import annotations

from enum import StrEnum

from tkt_store.domain.ticket import Snapshot, Ticket, Timestamp


class Status(StrEnum):
    OPEN = "open"  # live, unclaimed, not blocked — available to claim
    BLOCKED = "blocked"  # no live claim, some blocker not yet done
    CLAIMED = "claimed"  # a live claim (lease_until > now)
    EXPIRED = "expired"  # a claim is present, its lease has lapsed, not blocked
    DONE = "done"  # terminal: stage is DONE
    CANCELLED = "cancelled"  # terminal: stage is CANCELLED


def derive_status(snapshot: Snapshot, ticket: Ticket, now: Timestamp) -> Status:
    """Compute a ticket's status.

    Precedence: terminal stage > CLAIMED (live claim) > BLOCKED (any blocker not
    DONE) > EXPIRED (lapsed claim) > OPEN. Blocked outranks expired so a blocked
    ticket never reads as available; side effect: a blocked ticket with a lapsed
    claim reads BLOCKED (`list --status expired` omits it) although `reap` still
    releases that claim once it is past the grace. Blockers are resolved against
    `snapshot`; an unknown blocker id counts as not done.
    """
    raise NotImplementedError


def claimable(snapshot: Snapshot, ticket: Ticket, now: Timestamp) -> bool:
    """True iff `decide_claim` would accept a claim now: not terminal, not blocked,
    and either unclaimed or the claim is takeable (`Claim.is_takeable`: past
    lease_until + SKEW_GRACE). Not the same as status in {OPEN, EXPIRED}: a claim
    within the grace reads EXPIRED but cannot be taken yet."""
    raise NotImplementedError


def sort_key_for_next(ticket: Ticket) -> tuple[int, int, str]:
    """Ordering for claim-next: priority (None last), then created, then id."""
    raise NotImplementedError
