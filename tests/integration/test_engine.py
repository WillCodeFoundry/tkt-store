"""Engine behaviour with deterministic conflicts (MemStore.before_next_commit) and small
injected stores that fail on purpose."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from tests.unit.builders import C1, C2, NOW, T1, T2, TTL, A, B, held, tkt
from tkt_store.application.errors import Conflict, RetriesExhausted, StoreError
from tkt_store.application.store import HistoryEntry
from tkt_store.application.transaction import (
    DEFAULT_MAX_ATTEMPTS,
    Committed,
    Refused,
    Unchanged,
    transact,
)
from tkt_store.domain.operations import AddOp, ClaimOp, InitOp, OpName
from tkt_store.domain.outcomes import Change, OpRecord, RefusalCode, WriteTicket
from tkt_store.domain.ticket import Revision, Snapshot, Ticket, TicketId
from tkt_store.infrastructure.clock import FakeClock
from tkt_store.infrastructure.memory import MemStore


@pytest.fixture
def store() -> MemStore:
    store = MemStore()
    clock = FakeClock(NOW)
    transact(store, InitOp(), clock)
    transact(store, AddOp(T1, "Expire tokens"), clock)
    return store


def other_writer(store: MemStore, *tickets: Ticket) -> None:
    store.force_advance(tuple(WriteTicket(t) for t in tickets), OpRecord(OpName.EDIT, at=NOW))


class FailingStore:
    """Wraps a MemStore; every commit raises the given error after the snapshot."""

    def __init__(self, inner: MemStore, error: Exception) -> None:
        self.inner, self.error, self.commits = inner, error, 0

    def snapshot(self) -> Snapshot:
        return self.inner.snapshot()

    def commit(
        self, base: Revision | None, changes: Sequence[Change], record: OpRecord
    ) -> Revision:
        self.commits += 1
        raise self.error

    def history(
        self, ticket_id: TicketId | None = None, limit: int | None = None
    ) -> Iterator[HistoryEntry]:
        return self.inner.history(ticket_id, limit)


class RecordingStore(FailingStore):
    """Wraps a MemStore and records the base of every commit, then delegates."""

    def __init__(self, inner: MemStore) -> None:
        super().__init__(inner, Exception())
        self.bases: list[Revision | None] = []

    def commit(
        self, base: Revision | None, changes: Sequence[Change], record: OpRecord
    ) -> Revision:
        self.bases.append(base)
        return self.inner.commit(base, changes, record)


def test_conflict_triggers_retry_with_fresh_snapshot(store: MemStore) -> None:
    store.before_next_commit(lambda: other_writer(store, tkt(T2)))
    outcome = transact(store, ClaimOp(T1, A, C1, TTL), FakeClock(NOW))
    assert isinstance(outcome, Committed)
    assert store.snapshot().get(T2) is not None  # the other writer's commit survived


def test_retry_rechecks_rules(store: MemStore) -> None:
    taken = tkt(T1, title="Expire tokens", claim=held(C2, B))
    store.before_next_commit(lambda: other_writer(store, taken))
    outcome = transact(store, ClaimOp(T1, A, C1, TTL), FakeClock(NOW))
    assert isinstance(outcome, Refused) and outcome.refusal.code is RefusalCode.ALREADY_CLAIMED


def test_retries_exhausted_raises_with_the_op(store: MemStore) -> None:
    failing = FailingStore(store, Conflict(None, None))
    op = ClaimOp(T1, A, C1, TTL)
    with pytest.raises(RetriesExhausted) as exc:
        transact(failing, op, FakeClock(NOW))
    assert exc.value.op == op and failing.commits == DEFAULT_MAX_ATTEMPTS


def test_store_error_carries_the_op(store: MemStore) -> None:
    original = StoreError("push failed")
    op = ClaimOp(T1, A, C1, TTL)
    with pytest.raises(StoreError) as exc:
        transact(FailingStore(store, original), op, FakeClock(NOW))
    assert exc.value.op == op and exc.value.__cause__ is original


def test_refusal_and_noop_write_nothing(store: MemStore) -> None:
    before = list(store.history())
    clock = FakeClock(NOW)
    assert isinstance(transact(store, ClaimOp(T2, A, C1, TTL), clock), Refused)  # no T2
    assert isinstance(transact(store, InitOp(), clock), Unchanged)
    assert list(store.history()) == before


def test_committed_carries_the_written_tickets(store: MemStore) -> None:
    outcome = transact(store, ClaimOp(T1, A, C1, TTL), FakeClock(NOW))
    assert isinstance(outcome, Committed)
    assert [t.id for t in outcome.tickets] == [T1] and outcome.tickets[0].claim is not None
    assert outcome.revision == store.snapshot().revision


def test_unchanged_carries_the_tickets_it_concerns(store: MemStore) -> None:
    clock = FakeClock(NOW)
    transact(store, ClaimOp(T1, A, C1, TTL), clock)
    outcome = transact(store, ClaimOp(T1, A, C1, TTL), clock)
    assert isinstance(outcome, Unchanged)
    assert outcome.tickets[0].claim is not None and outcome.tickets[0].claim.claim_id == C1


def test_commit_uses_the_snapshot_revision_not_a_fresh_read(store: MemStore) -> None:
    """Regression guard for the 'wrong old value' bug class (balls bl-cdec G1)."""
    recording = RecordingStore(store)
    first_snapshot = store.snapshot().revision
    store.before_next_commit(lambda: other_writer(store, tkt(T2)))
    transact(recording, ClaimOp(T1, A, C1, TTL), FakeClock(NOW))
    assert recording.bases[0] == first_snapshot  # the decision's base, not the new head
    assert len(recording.bases) == 2  # it lost that race, re-decided, committed on the new head


class RecordingBackoff:
    def __init__(self) -> None:
        self.waits: list[int] = []

    def wait(self, attempt: int) -> None:
        self.waits.append(attempt)


def test_backoff_waits_between_attempts_never_after_the_last(store: MemStore) -> None:
    backoff = RecordingBackoff()
    with pytest.raises(RetriesExhausted):
        transact(FailingStore(store, Conflict(None, None)), ClaimOp(T1, A, C1, TTL),
                 FakeClock(NOW), max_attempts=4, backoff=backoff)  # fmt: skip
    assert backoff.waits == [1, 2, 3]


def test_backoff_waits_only_after_a_lost_race(store: MemStore) -> None:
    backoff = RecordingBackoff()
    store.before_next_commit(lambda: other_writer(store, tkt(T2)))
    outcome = transact(store, ClaimOp(T1, A, C1, TTL), FakeClock(NOW), backoff=backoff)
    assert isinstance(outcome, Committed) and backoff.waits == [1]  # one lost race
    assert isinstance(
        transact(store, ClaimOp(T2, A, C2, TTL), FakeClock(NOW), backoff=backoff), Committed
    )
    assert backoff.waits == [1]
