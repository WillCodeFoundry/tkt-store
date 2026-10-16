"""Shared builders for domain tests: fixed time, agents, claim and ticket ids, and small
constructors for tickets, claims and snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from tkt_store.domain.operations import Op
from tkt_store.domain.outcomes import Apply, Decision, NoOp, Refusal, RefusalCode
from tkt_store.domain.ticket import (
    SKEW_GRACE,
    AgentId,
    Claim,
    ClaimId,
    Phase,
    Revision,
    Snapshot,
    Ticket,
    TicketId,
)

NOW = 1_000_000
TTL = 1800
A = AgentId("coder-7")
B = AgentId("reviewer-2")
C1 = ClaimId("1" * 32)
C2 = ClaimId("2" * 32)
C3 = ClaimId("3" * 32)
T1 = TicketId("tkt-1")
T2 = TicketId("tkt-2")
T3 = TicketId("tkt-3")
LAPSED = NOW - 1  # a lease_until in the past, still within the grace
TAKEABLE = NOW - SKEW_GRACE  # lease_until + SKEW_GRACE == NOW


def tkt(ticket_id: TicketId = T1, **fields: object) -> Ticket:
    base = Ticket(
        id=ticket_id, created=0, title="Expire tokens", updated=0, phase=Phase.IMPLEMENTATION
    )
    return replace(base, **fields)  # type: ignore[arg-type]


def held(claim_id: ClaimId = C1, agent: AgentId = A, lease_until: int = NOW + 600) -> Claim:
    return Claim(agent=agent, claim_id=claim_id, lease_until=lease_until, claimed_at=NOW - 600)


def snap(*tickets: Ticket) -> Snapshot:
    return Snapshot(Revision("r1"), {t.id: t for t in tickets})


def written(decision: Decision, ticket_id: TicketId = T1) -> Ticket:
    assert isinstance(decision, Apply), decision
    return {change.ticket.id: change.ticket for change in decision.changes}[ticket_id]


def refused(decision: Decision, code: RefusalCode) -> Refusal:
    assert isinstance(decision, Refusal), decision
    assert decision.code is code, decision
    return decision


def noop(decision: Decision) -> NoOp:
    assert isinstance(decision, NoOp), decision
    return decision


def pick(options: Mapping[str, Op], key: str) -> Op:
    """Choose one op from a table of options (keeps mypy's inference on the Op union)."""
    return options[key]
