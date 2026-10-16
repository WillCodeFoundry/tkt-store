"""Derived status and claim timing (ADR 0004)."""

from __future__ import annotations

import pytest

from tests.unit.builders import C2, LAPSED, NOW, T2, B, held, snap, tkt
from tkt_store.domain.outcomes import RefusalCode
from tkt_store.domain.status import (
    Status,
    claimable,
    derive_status,
    sort_key_for_next,
    why_not_claimable,
)
from tkt_store.domain.ticket import SKEW_GRACE, Resolution, TicketId
from tkt_store.domain.ticket import Ticket as Ticket


@pytest.mark.parametrize(
    ("ticket", "expected"),
    [
        (tkt(resolution=Resolution.DONE, claim=held()), Status.DONE),
        (tkt(resolution=Resolution.CANCELLED), Status.CANCELLED),
        (tkt(claim=held(), blocked_by=(T2,)), Status.CLAIMED),
        (tkt(blocked_by=(T2,)), Status.BLOCKED),
        (tkt(claim=held(lease_until=LAPSED)), Status.EXPIRED),
        (tkt(), Status.OPEN),
    ],
    ids=["done", "cancelled", "claimed_beats_blocked", "blocked", "expired", "open"],
)
def test_status_precedence(ticket: Ticket, expected: Status) -> None:
    """resolution > claimed (live) > blocked > expired > open."""
    assert derive_status(snap(ticket, tkt(T2)), ticket, NOW) is expected


def test_blocked_with_lapsed_claim_reads_blocked() -> None:
    ticket = tkt(claim=held(lease_until=LAPSED), blocked_by=(T2,))
    assert derive_status(snap(ticket, tkt(T2)), ticket, NOW) is Status.BLOCKED


def test_claim_expires_at_lease_until() -> None:
    claim = held(lease_until=NOW)
    assert claim.is_live(NOW - 1) and not claim.is_live(NOW)


def test_claim_takeable_only_after_grace() -> None:
    claim = held(lease_until=NOW)
    assert not claim.is_takeable(NOW + SKEW_GRACE - 1)
    assert claim.is_takeable(NOW + SKEW_GRACE)


def test_claimable_is_false_within_grace() -> None:
    ticket = tkt(claim=held(C2, B, LAPSED))
    assert derive_status(snap(ticket), ticket, NOW) is Status.EXPIRED
    assert not claimable(snap(ticket), ticket, NOW)


def test_claimable_is_false_when_blocked() -> None:
    ticket = tkt(blocked_by=(T2,))
    assert not claimable(snap(ticket, tkt(T2)), ticket, NOW)


@pytest.mark.parametrize(
    ("ticket", "expected"),
    [
        (tkt(resolution=Resolution.DONE), RefusalCode.TERMINAL),
        (tkt(blocked_by=(T2,)), RefusalCode.BLOCKED),
        (tkt(claim=held()), RefusalCode.ALREADY_CLAIMED),
        (tkt(claim=held(lease_until=LAPSED)), RefusalCode.ALREADY_CLAIMED),
        (tkt(), None),
    ],
    ids=["resolved", "blocked", "live", "in_grace", "claimable"],
)
def test_why_not_claimable_gives_the_refusal(ticket: Ticket, expected: RefusalCode | None) -> None:
    refusal = why_not_claimable(snap(ticket, tkt(T2)), ticket, NOW)
    assert (refusal.code if refusal else None) is expected


def test_claim_age_is_since_claimed_at() -> None:
    claim = held()
    assert claim.age(NOW) == 600
    assert claim.age(claim.claimed_at - 5) == 0  # never negative under clock skew


def test_unknown_dependency_counts_as_not_done() -> None:
    ticket = tkt(blocked_by=(TicketId("tkt-99"),))
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
            tkt(TicketId("tkt-a"), priority=None),
            tkt(TicketId("tkt-b"), priority=5),
            tkt(TicketId("tkt-c"), priority=-1),
        ],
        key=sort_key_for_next,
    )
    assert [t.id for t in ordered] == ["tkt-c", "tkt-b", "tkt-a"]
