"""Property tests (hypothesis) over random op sequences against MemStore.

Each generated scenario: two agents and three tickets (one blocked by another), random
ops (claim, claim-next, renew, move, release, done, cancel, reap, edit with a random
expected version), clock jumps, and conflicts injected at the moment of commit. Every
step goes through the real TicketStore and transaction loop; the invariants of
docs/design.md §5 are checked after every step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tkt_store.application.service import TicketStore
from tkt_store.application.transaction import Committed, Outcome, Refused, Unchanged
from tkt_store.domain.operations import OpName
from tkt_store.domain.outcomes import OpRecord, RefusalCode
from tkt_store.domain.ticket import AgentId, ClaimId, Phase, Snapshot, TicketId
from tkt_store.infrastructure.clock import FakeClock
from tkt_store.infrastructure.ids import SequentialIds
from tkt_store.infrastructure.memory import MemStore

NOW = 1_000_000
A = AgentId("coder-7")
B = AgentId("reviewer-2")

pytestmark = pytest.mark.slow

TICKETS = [TicketId(f"tkt-000{c}") for c in "abc"]
CLAIM_IDS = [ClaimId(f"{n:032x}") for n in range(1, 7)]
HOLDER_OPS = {OpName.RENEW, OpName.MOVE, OpName.RELEASE, OpName.DONE}
CLAIM_OPS = {OpName.CLAIM, OpName.CLAIM_NEXT}
BLOCKED, BLOCKERS = TICKETS[2], (TICKETS[0],)  # tkt-000c waits for tkt-000a

ticket = st.sampled_from(TICKETS)
agent = st.sampled_from([A, B])
claim_id = st.sampled_from(CLAIM_IDS)
step = st.one_of(
    st.tuples(st.just("claim"), ticket, agent, claim_id),
    st.tuples(st.just("claim_next"), agent, claim_id),
    st.tuples(st.just("renew"), ticket, claim_id),
    st.tuples(st.just("move"), ticket, claim_id, st.sampled_from(list(Phase))),
    st.tuples(st.just("release"), ticket, claim_id),
    st.tuples(st.just("done"), ticket, claim_id),
    st.tuples(st.just("cancel"), ticket),
    st.tuples(st.just("edit"), ticket, st.integers(1, 3)),
    st.tuples(st.just("reap")),
    st.tuples(st.just("advance"), st.integers(0, 3000)),
    st.tuples(st.just("conflict")),
)
scenarios = st.lists(step, max_size=40)


@dataclass(frozen=True)
class Step:
    action: str
    args: tuple[Any, ...]
    before: Snapshot
    outcome: Outcome | None
    after: Snapshot
    new_history: int
    forced: int


def run(steps: list[tuple[Any, ...]]) -> list[Step]:
    store, clock = MemStore(), FakeClock(NOW)
    service = TicketStore(store, clock, SequentialIds())
    service.init()
    for t in TICKETS[:2]:
        service.add(f"Ticket {t}", ticket_id=t, phase=Phase.IMPLEMENTATION)
    service.add("Blocked", ticket_id=BLOCKED, phase=Phase.IMPLEMENTATION, blocked_by=BLOCKERS)
    trace = []
    injected = [0]  # commits landed by the simulated other writer
    for action, *args in steps:
        before, history = store.snapshot(), len(list(store.history()))
        injected_before = injected[0]
        outcome: Outcome | None = None
        match action, args:
            case "claim", [t, a, c]:
                outcome = service.claim(t, a, 1800, claim_id=c)
            case "claim_next", [a, c]:
                outcome = service.claim_next(a, 1800, claim_id=c)
            case "renew", [t, c]:
                outcome = service.renew(t, c, 1800)
            case "move", [t, c, p]:
                outcome = service.move(t, c, p)
            case "release", [t, c]:
                outcome = service.release(t, c)
            case "done", [t, c]:
                outcome = service.done(t, c)
            case "cancel", [t]:
                outcome = service.cancel(t)
            case "edit", [t, version]:
                outcome = service.edit(t, version, title=f"Edited at {clock.now()}")
            case "reap", []:
                outcome = service.reap()
            case "advance", [seconds]:
                clock.advance(seconds)
            case "conflict", []:
                # another writer lands an (empty) commit just before our next commit
                def other_writer() -> None:
                    injected[0] += 1
                    store.force_advance((), OpRecord(OpName.REAP, at=clock.now()))

                store.before_next_commit(other_writer)
        after = store.snapshot()
        new_history = len(list(store.history())) - history
        forced = injected[0] - injected_before
        trace.append(Step(action, tuple(args), before, outcome, after, new_history, forced))
    return trace


@settings(max_examples=150, deadline=None)
@given(scenarios)
def test_never_two_live_holders(steps: list[tuple[Any, ...]]) -> None:
    """Invariant 1: a claim id is current on at most one ticket, and an ended claim id
    never becomes current again."""
    for s in run(steps):
        current = [t.claim.claim_id for t in s.after.tickets.values() if t.claim is not None]
        assert len(current) == len(set(current))
        ended = {c for t in s.after.tickets.values() for c in t.ended_claim_ids}
        assert not ended & set(current)


@settings(max_examples=150, deadline=None)
@given(scenarios)
def test_resolved_tickets_never_change(steps: list[tuple[Any, ...]]) -> None:
    """Invariant 9: once resolved, a ticket is never written again."""
    for s in run(steps):
        for ticket_id, before in s.before.tickets.items():
            if before.resolution is not None:
                assert s.after.tickets[ticket_id] == before


@settings(max_examples=150, deadline=None)
@given(scenarios)
def test_only_current_claim_id_can_finish(steps: list[tuple[Any, ...]]) -> None:
    """Invariant 4: a holder op that commits presented the ticket's current claim id."""
    for s in run(steps):
        if isinstance(s.outcome, Committed) and s.outcome.record.op in HOLDER_OPS:
            (ticket_id,) = s.outcome.record.ticket_ids
            # the snapshot the decision used may be after an injected commit, but injected
            # commits never change tickets, so `before` holds the same claims
            claim = s.before.tickets[ticket_id].claim
            assert claim is not None and claim.claim_id == s.outcome.record.claim_id


@settings(max_examples=150, deadline=None)
@given(scenarios)
def test_every_applied_op_is_exactly_one_history_entry(steps: list[tuple[Any, ...]]) -> None:
    """Invariant 2: a committed op adds exactly one history entry; refused and unchanged
    ops add none (injected commits from the other writer are accounted separately)."""
    for s in run(steps):
        expected = (1 if isinstance(s.outcome, Committed) else 0) + s.forced
        assert s.new_history == expected
        assert s.forced in (0, 1)


@settings(max_examples=150, deadline=None)
@given(scenarios)
def test_blocked_tickets_are_claimed_only_once_their_blockers_are_done(
    steps: list[tuple[Any, ...]],
) -> None:
    """Invariant 10: a new claim on a ticket (a fresh claim or a takeover, not a re-run of
    the holder's own claim) commits only if every blocker is done (a cancelled blocker
    does not count)."""
    for s in run(steps):
        if isinstance(s.outcome, Committed) and s.outcome.record.op in CLAIM_OPS:
            (ticket_id,) = s.outcome.record.ticket_ids
            prior = s.before.tickets[BLOCKED].claim
            if ticket_id == BLOCKED and (
                prior is None or prior.claim_id != s.outcome.record.claim_id
            ):
                assert all(s.before.tickets[b].is_done for b in BLOCKERS)


@settings(max_examples=150, deadline=None)
@given(scenarios)
def test_edits_never_overwrite_a_newer_version(steps: list[tuple[Any, ...]]) -> None:
    """An edit commits only when based on the ticket's current content_version, and bumps
    it by exactly one; based on any other version it is refused STALE (or is unchanged,
    when it would change nothing)."""
    for s in run(steps):
        if s.action != "edit":
            continue
        ticket_id, version = s.args
        before, after = s.before.tickets[ticket_id], s.after.tickets[ticket_id]
        if isinstance(s.outcome, Committed):
            assert version == before.content_version
            assert after.content_version == before.content_version + 1
        elif version != before.content_version and before.resolution is None:
            assert isinstance(s.outcome, Unchanged) or (
                isinstance(s.outcome, Refused) and s.outcome.refusal.code is RefusalCode.STALE
            )
