"""The rules (domain/rules.py decide) facing forged state that decodes fine, with a guard
that the lease cap must keep: honest renewals are never taken over."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from tkt_store.domain.occupancy import assemble
from tkt_store.domain.operations import ClaimOp, Op, ReapOp
from tkt_store.domain.outcomes import Apply, NoOp, Refusal, RefusalCode
from tkt_store.domain.rules import decide
from tkt_store.domain.ticket import (
    LEASE_CAP_MARGIN,
    MAX_TTL,
    AgentId,
    Claim,
    ClaimId,
    Phase,
    Revision,
    Snapshot,
    Ticket,
    TicketId,
    claim_hash,
)

NOW = 1_000_000
TTL = 1800
A = AgentId("coder-7")
B = AgentId("reviewer-2")
C1 = ClaimId("1" * 32)
C2 = ClaimId("2" * 32)
T1 = TicketId("tkt-0001")


def tkt(ticket_id: TicketId, **fields: Any) -> Ticket:
    """A plain open ticket; `fields` override."""
    base = Ticket(
        id=ticket_id, title="Expire tokens", created=0, updated=0, phase=Phase.IMPLEMENTATION
    )
    return replace(base, **fields)


def held_by(claim: Claim) -> Snapshot:
    """A snapshot holding T1 under `claim`."""
    return assemble(Revision("r1"), {T1: tkt(T1)}, {}, [claim])


FORGED_LEASE = Claim(T1, claim_hash(C1), A, NOW, NOW + 100 * MAX_TTL)
"""A lease no honest writer can produce: renew and claim cap it at now + MAX_TTL."""


@pytest.mark.parametrize(
    "op", [ClaimOp(T1, B, C2, TTL), ReapOp()], ids=["claim by another agent", "reap"]
)
def test_a_forged_far_future_lease_does_not_lock_a_ticket(op: Op) -> None:
    """Past the longest lease an honest writer could have set (MAX_TTL plus the cap's
    clock margin), the claim can be taken over or reaped, however far its lease_until
    claims to run."""
    later = NOW + MAX_TTL + LEASE_CAP_MARGIN + 1
    assert isinstance(decide(held_by(FORGED_LEASE), op, later), Apply)


RENEWED_AT = NOW + MAX_TTL + LEASE_CAP_MARGIN + 1
HONESTLY_RENEWED = Claim(T1, claim_hash(C1), A, NOW, RENEWED_AT + TTL)
"""Claimed at NOW and renewed for longer than MAX_TTL: renew keeps claimed_at."""


def test_guard_an_honestly_renewed_claim_is_never_taken_over() -> None:
    """A guard for the lease cap above. A cap based on claimed_at would let anyone
    take over a claim that has been renewed for more than MAX_TTL while its lease is live,
    breaking invariant 1; only a cap relative to now passes both tests."""
    now = RENEWED_AT + 1
    snapshot = held_by(HONESTLY_RENEWED)
    claim = decide(snapshot, ClaimOp(T1, B, C2, TTL), now)
    assert isinstance(claim, Refusal) and claim.code is RefusalCode.ALREADY_CLAIMED
    assert isinstance(decide(snapshot, ReapOp(), now), NoOp)
