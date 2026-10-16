"""The rules (domain/rules.py decide) facing forged state that decodes fine."""

from __future__ import annotations

import pytest

from tests.security import design
from tests.unit.builders import C1, C2, NOW, T1, TTL, A, B, snap, tkt
from tkt_store.domain.operations import ClaimOp, Op, ReapOp
from tkt_store.domain.outcomes import Apply
from tkt_store.domain.rules import decide
from tkt_store.domain.ticket import MAX_TTL, SKEW_GRACE, Claim

FORGED_LEASE = Claim(agent=A, claim_id=C1, lease_until=NOW + 100 * MAX_TTL, claimed_at=NOW)
"""A lease no honest writer can produce: renew and claim cap it at now + MAX_TTL."""


@design("a forged lease far beyond MAX_TTL locks a ticket until someone cancels it")
@pytest.mark.parametrize(
    "op", [ClaimOp(T1, B, C2, TTL), ReapOp()], ids=["claim by another agent", "reap"]
)
def test_a_forged_far_future_lease_does_not_lock_a_ticket(op: Op) -> None:
    """Past the longest lease an honest writer could have set (MAX_TTL plus the grace),
    the claim can be taken over or reaped, however far its lease_until claims to run."""
    later = NOW + MAX_TTL + SKEW_GRACE + 1
    assert isinstance(decide(snap(tkt(T1, claim=FORGED_LEASE)), op, later), Apply)
