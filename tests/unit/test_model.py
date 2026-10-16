"""Derived status and claim timing (ADR 0004)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tkt_store.domain.occupancy import assemble
from tkt_store.domain.outcomes import RefusalCode
from tkt_store.domain.status import (
    Status,
    claimable,
    derive_status,
    sort_key_for_next,
    why_not_claimable,
)
from tkt_store.domain.ticket import (
    LEASE_CAP_MARGIN,
    MAX_TTL,
    SKEW_GRACE,
    AgentId,
    Claim,
    ClaimId,
    Phase,
    Resolution,
    Revision,
    Snapshot,
    Ticket,
    TicketId,
    claim_hash,
)

NOW = 1_000_000
A = AgentId("coder-7")
B = AgentId("reviewer-2")
C1 = ClaimId("1" * 32)
C2 = ClaimId("2" * 32)
T1 = TicketId("tkt-0001")
T2 = TicketId("tkt-0002")
LAPSED = NOW - 1  # a lease_until in the past, still within the grace


def tkt(ticket_id: TicketId = T1, **fields: object) -> Ticket:
    """An open, unclaimed ticket in the implementation phase; `fields` override."""
    base = Ticket(
        id=ticket_id, created=0, title="Expire tokens", updated=0, phase=Phase.IMPLEMENTATION
    )
    return replace(base, **fields)  # type: ignore[arg-type]


def held(claim_id: ClaimId = C1, agent: AgentId = A, lease_until: int = NOW + 600) -> Claim:
    """An open claim on T1, taken 10 minutes before NOW and, by default, live for 10 more."""
    return Claim(T1, claim_hash(claim_id), agent, NOW - 600, lease_until)


def snap(*items: Ticket | Claim) -> Snapshot:
    """A snapshot at an arbitrary revision holding these tickets and claims."""
    tickets = {item.id: item for item in items if isinstance(item, Ticket)}
    claims = [item for item in items if isinstance(item, Claim)]
    return assemble(Revision("r1"), tickets, {}, claims)


@pytest.mark.parametrize(
    ("ticket", "claims", "expected"),
    [
        (tkt(resolution=Resolution.DONE), (held(),), Status.DONE),
        (tkt(resolution=Resolution.CANCELLED), (), Status.CANCELLED),
        (tkt(blocked_by=(T2,)), (held(),), Status.CLAIMED),
        (tkt(blocked_by=(T2,)), (), Status.BLOCKED),
        (tkt(), (held(lease_until=LAPSED),), Status.EXPIRED),
        (tkt(), (), Status.OPEN),
    ],
    ids=["done", "cancelled", "claimed_beats_blocked", "blocked", "expired", "open"],
)
def test_status_precedence(ticket: Ticket, claims: tuple[Claim, ...], expected: Status) -> None:
    """resolution > claimed (live) > blocked > expired > open."""
    assert derive_status(snap(ticket, tkt(T2), *claims), ticket, NOW) is expected


def test_blocked_with_lapsed_claim_reads_blocked() -> None:
    ticket = tkt(blocked_by=(T2,))
    assert (
        derive_status(snap(ticket, held(lease_until=LAPSED), tkt(T2)), ticket, NOW)
        is Status.BLOCKED
    )


def test_held_by_a_set_aside_claim_reads_claimed_and_is_not_claimable() -> None:
    """Two open claims on one ticket: both set aside, the ticket held by an unknown claim."""
    ticket = tkt()
    snapshot = snap(ticket, held(C1), held(C2, B))
    assert derive_status(snapshot, ticket, NOW) is Status.CLAIMED
    assert not claimable(snapshot, ticket, NOW)


def test_claim_expires_at_lease_until() -> None:
    claim = held(lease_until=NOW)
    assert claim.is_live(NOW - 1) and not claim.is_live(NOW)


def test_claim_takeable_only_after_grace() -> None:
    claim = held(lease_until=NOW)
    assert not claim.is_takeable(NOW + SKEW_GRACE - 1)
    assert claim.is_takeable(NOW + SKEW_GRACE)


def test_a_lease_beyond_the_cap_reads_expired_and_is_takeable() -> None:
    """The cap is relative to now: MAX_TTL + LEASE_CAP_MARGIN ahead is the furthest an
    honest lease can reach from a clock up to the margin fast; one second more is forged."""
    furthest = held(lease_until=NOW + MAX_TTL + LEASE_CAP_MARGIN)
    assert furthest.is_live(NOW) and not furthest.is_takeable(NOW)
    forged = held(lease_until=NOW + MAX_TTL + LEASE_CAP_MARGIN + 1)
    assert not forged.is_live(NOW) and forged.is_takeable(NOW)
    ticket = tkt()
    assert derive_status(snap(ticket, forged), ticket, NOW) is Status.EXPIRED
    assert claimable(snap(ticket, forged), ticket, NOW)


def test_claimable_is_false_within_grace() -> None:
    ticket = tkt()
    snapshot = snap(ticket, held(C2, B, LAPSED))
    assert derive_status(snapshot, ticket, NOW) is Status.EXPIRED
    assert not claimable(snapshot, ticket, NOW)


def test_claimable_is_false_when_blocked() -> None:
    ticket = tkt(blocked_by=(T2,))
    assert not claimable(snap(ticket, tkt(T2)), ticket, NOW)


@pytest.mark.parametrize(
    ("ticket", "claims", "expected"),
    [
        (tkt(resolution=Resolution.DONE), (), RefusalCode.TERMINAL),
        (tkt(blocked_by=(T2,)), (), RefusalCode.BLOCKED),
        (tkt(), (held(),), RefusalCode.ALREADY_CLAIMED),
        (tkt(), (held(lease_until=LAPSED),), RefusalCode.ALREADY_CLAIMED),
        (tkt(), (held(C1), held(C2, B)), RefusalCode.SET_ASIDE),
        (tkt(), (), None),
    ],
    ids=["resolved", "blocked", "live", "in_grace", "held_aside", "claimable"],
)
def test_why_not_claimable_gives_the_refusal(
    ticket: Ticket, claims: tuple[Claim, ...], expected: RefusalCode | None
) -> None:
    refusal = why_not_claimable(snap(ticket, tkt(T2), *claims), ticket, NOW)
    assert (refusal.code if refusal else None) is expected


def test_claim_age_is_since_claimed_at() -> None:
    claim = held()
    assert claim.age(NOW) == 600
    assert claim.age(claim.claimed_at - 5) == 0  # never negative under clock skew


def test_unknown_dependency_counts_as_not_done() -> None:
    ticket = tkt(blocked_by=(TicketId("tkt-0099"),))
    assert derive_status(snap(ticket), ticket, NOW) is Status.BLOCKED


def test_cancelled_blocker_counts_as_not_done() -> None:
    ticket = tkt(blocked_by=(T2,))
    tickets = snap(ticket, tkt(T2, resolution=Resolution.CANCELLED))
    assert derive_status(tickets, ticket, NOW) is Status.BLOCKED


def test_done_blocker_unblocks() -> None:
    ticket = tkt(blocked_by=(T2,))
    tickets = snap(ticket, tkt(T2, resolution=Resolution.DONE))
    assert derive_status(tickets, ticket, NOW) is Status.OPEN


def test_sort_key_puts_none_priority_last() -> None:
    ordered = sorted(
        [
            tkt(TicketId("tkt-000a"), priority=None),
            tkt(TicketId("tkt-000b"), priority=5),
            tkt(TicketId("tkt-000c"), priority=-1),
        ],
        key=sort_key_for_next,
    )
    assert [t.id for t in ordered] == ["tkt-000c", "tkt-000b", "tkt-000a"]
