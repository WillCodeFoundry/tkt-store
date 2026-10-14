"""Status is derived from facts, never stored (ADR 0004).

PURE module. `Status` answers the availability question — can this ticket be
worked, and who holds it — which is orthogonal to the `Stage` a ticket sits at.
The two combine in `derive_status`: a terminal stage dominates (a finished
ticket reads DONE/CANCELLED); otherwise the status comes from the claim and the
blockers. Everything here is a function of a snapshot, a ticket, and the current
time, so there is nothing to persist and nothing to keep in sync.
"""

from __future__ import annotations

from enum import StrEnum

from tkt_store.domain.ticket import Snapshot, Ticket, Timestamp


class Status(StrEnum):
    OPEN = "open"  # live, unclaimed, not blocked — available to claim
    BLOCKED = "blocked"  # live, unclaimed, some blocker not yet done
    CLAIMED = "claimed"  # a live claim (lease_until > now)
    EXPIRED = "expired"  # a claim is present but its lease has lapsed
    DONE = "done"  # terminal: stage is DONE
    CANCELLED = "cancelled"  # terminal: stage is CANCELLED


def derive_status(snapshot: Snapshot, ticket: Ticket, now: Timestamp) -> Status:
    """Compute a ticket's status.

    Precedence: terminal stage > claim (live -> CLAIMED, lapsed -> EXPIRED) >
    blocked (any blocker not DONE) > open. Blockers are resolved against
    `snapshot`; an unknown blocker id counts as not done.
    """
    raise NotImplementedError


def claimable(snapshot: Snapshot, ticket: Ticket, now: Timestamp) -> bool:
    """True if the status is OPEN or EXPIRED (a lapsed claim may be taken over).
    A terminal ticket is never claimable."""
    raise NotImplementedError


def sort_key_for_next(ticket: Ticket) -> tuple[int, int, str]:
    """Ordering for claim-next: priority (None last), then created, then id."""
    raise NotImplementedError
