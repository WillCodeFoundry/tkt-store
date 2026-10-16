"""Real git: two clones of one bare remote compete for one ticket."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from tests.gitkit import HookedRunner, head, once
from tkt_store.application.service import TicketStore
from tkt_store.application.transaction import Committed, Refused
from tkt_store.domain.outcomes import RefusalCode
from tkt_store.domain.ticket import AgentId, ClaimId, TicketId, claim_hash
from tkt_store.infrastructure.clock import FakeClock
from tkt_store.infrastructure.git.repo import GitStore
from tkt_store.infrastructure.ids import SequentialIds

NOW = 1_000_000
TTL = 1800
A = AgentId("coder-7")
B = AgentId("reviewer-2")
C1 = ClaimId("1" * 32)
C2 = ClaimId("2" * 32)
T1 = TicketId("tkt-0001")
T2 = TicketId("tkt-0002")

pytestmark = [pytest.mark.git, pytest.mark.slow]


def service(repo: Path, hook: Callable[[tuple[str, ...]], None] = lambda args: None) -> TicketStore:
    store = GitStore(HookedRunner(repo, hook), remote="origin")
    return TicketStore(store, FakeClock(NOW), SequentialIds())


@pytest.fixture
def seeded(clones: list[Path]) -> list[Path]:
    """Both clones of a remote store holding two open tickets."""
    tickets = service(clones[0])
    tickets.init()
    tickets.add("First", ticket_id=T1)
    tickets.add("Second", ticket_id=T2)
    return clones


def test_exactly_one_clone_wins_a_claim(seeded: list[Path]) -> None:
    """Both claim the same ticket; one Committed, the other Refused(ALREADY_CLAIMED) after retry."""
    # deterministic: b claims in the window between a's snapshot and a's push
    b = service(seeded[1])
    a = service(seeded[0], once("push", lambda: b.claim(T1, B, TTL, claim_id=C2)))
    outcome = a.claim(T1, A, TTL, claim_id=C1)
    assert isinstance(outcome, Refused) and outcome.refusal.code is RefusalCode.ALREADY_CLAIMED
    view = b.view(T1)
    assert view is not None and view.claim is not None and view.claim.agent == B


def test_exactly_one_wins_when_truly_concurrent(seeded: list[Path]) -> None:
    """Two threads, each with its own clone, released together at their first fetch."""
    barrier = Barrier(2)
    a = service(seeded[0], once("fetch", lambda: barrier.wait(timeout=10)))
    b = service(seeded[1], once("fetch", lambda: barrier.wait(timeout=10)))
    with ThreadPoolExecutor(2) as pool:
        racing = [
            pool.submit(a.claim, T1, A, TTL, claim_id=C1),
            pool.submit(b.claim, T1, B, TTL, claim_id=C2),
        ]
        outcomes = [f.result() for f in racing]
    committed = [o for o in outcomes if isinstance(o, Committed)]
    refused = [o for o in outcomes if isinstance(o, Refused)]
    assert len(committed) == 1 and len(refused) == 1
    assert refused[0].refusal.code is RefusalCode.ALREADY_CLAIMED


def test_unrelated_tickets_both_succeed(seeded: list[Path]) -> None:
    b = service(seeded[1])
    a = service(seeded[0], once("push", lambda: b.claim(T2, B, TTL, claim_id=C2)))
    assert isinstance(a.claim(T1, A, TTL, claim_id=C1), Committed)  # after one retry
    view = a.view(T2)
    assert view is not None and view.claim is not None and view.claim.agent == B


def test_loser_never_sees_partial_state(seeded: list[Path], bare_remote: Path) -> None:
    b = service(seeded[1])
    a = service(seeded[0], once("push", lambda: b.claim(T1, B, TTL, claim_id=C2)))
    a.claim(T1, A, TTL, claim_id=C1)
    views = [service(c).list() for c in seeded]
    assert views[0] == views[1]
    assert head(seeded[0]) == head(seeded[1]) == head(bare_remote)
    claims = [v.claim for v in views[0] if v.claim is not None]
    assert [c.hash for c in claims] == [claim_hash(C2)]
