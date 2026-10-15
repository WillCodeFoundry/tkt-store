"""The TicketStore facade: id minting, building ops, and single-snapshot reads
(docs/design.md §6). Runs against MemStore with injected fakes (AGENTS.md)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from tests.unit.builders import C1, NOW, T1, T2, TTL, A
from tkt_store.application.errors import Conflict, RetriesExhausted
from tkt_store.application.service import TicketStore
from tkt_store.application.store import HistoryEntry
from tkt_store.application.transaction import Committed, Refused, Unchanged
from tkt_store.domain.operations import AddOp, ClaimOp
from tkt_store.domain.outcomes import Change, OpRecord, RefusalCode
from tkt_store.domain.status import Status
from tkt_store.domain.ticket import ClaimId, Phase, Revision, Snapshot, TicketId
from tkt_store.infrastructure.clock import FakeClock
from tkt_store.infrastructure.ids import SequentialIds
from tkt_store.infrastructure.memory import MemStore


class ScriptedIds(SequentialIds):
    """Mints the given ticket ids first, then counts like SequentialIds."""

    def __init__(self, *ticket_ids: str) -> None:
        super().__init__()
        self._queued = [TicketId(i) for i in ticket_ids]

    def ticket_id(self) -> TicketId:
        return self._queued.pop(0) if self._queued else super().ticket_id()


class CountingStore:
    """Wraps a MemStore, counting snapshots; optionally every commit conflicts."""

    def __init__(self, inner: MemStore, *, conflict: bool = False) -> None:
        self.inner, self.conflict, self.snapshots = inner, conflict, 0

    def snapshot(self) -> Snapshot:
        self.snapshots += 1
        return self.inner.snapshot()

    def commit(
        self, base: Revision | None, changes: Sequence[Change], record: OpRecord
    ) -> Revision:
        if self.conflict:
            raise Conflict(base, base)
        return self.inner.commit(base, changes, record)

    def history(
        self, ticket_id: TicketId | None = None, limit: int | None = None
    ) -> Iterator[HistoryEntry]:
        return self.inner.history(ticket_id, limit)


@pytest.fixture
def memstore() -> MemStore:
    store = MemStore()
    service = TicketStore(store, FakeClock(NOW), SequentialIds())
    service.init()
    service.add("Existing", ticket_id=T1)
    return store


def service_on(store: object, ids: SequentialIds | None = None) -> TicketStore:
    return TicketStore(store, FakeClock(NOW), ids or SequentialIds())  # type: ignore[arg-type]


def test_add_remints_on_duplicate_id_when_minted(memstore: MemStore) -> None:
    outcome = service_on(memstore, ScriptedIds(T1, "tkt-beef")).add("Different title")
    assert isinstance(outcome, Committed) and outcome.tickets[0].id == "tkt-beef"


def test_add_with_supplied_id_never_retries(memstore: MemStore) -> None:
    service = service_on(memstore)
    duplicate = service.add("Different title", ticket_id=T1)
    assert isinstance(duplicate, Refused) and duplicate.refusal.code is RefusalCode.DUPLICATE_ID
    assert isinstance(service.add("Existing", ticket_id=T1), Unchanged)


def test_failures_carry_the_last_ids_tried(memstore: MemStore) -> None:
    service = service_on(CountingStore(memstore, conflict=True), ScriptedIds("tkt-aa"))
    with pytest.raises(RetriesExhausted) as exc:
        service.add("New")
    assert isinstance(exc.value.op, AddOp) and exc.value.op.ticket_id == "tkt-aa"
    with pytest.raises(RetriesExhausted) as exc:
        service.claim(T1, A, TTL)
    assert isinstance(exc.value.op, ClaimOp) and len(exc.value.op.claim_id) == 32


def test_claim_uses_a_supplied_claim_id_and_reruns_converge(memstore: MemStore) -> None:
    service = service_on(memstore)
    first = service.claim(T1, A, TTL, claim_id=C1)
    again = service.claim(T1, A, TTL, claim_id=C1)
    assert isinstance(first, Committed) and isinstance(again, Unchanged)
    assert again.tickets[0].claim is not None and again.tickets[0].claim.claim_id == C1


def test_handoff_through_the_service(memstore: MemStore) -> None:
    service = service_on(memstore)
    service.claim(T1, A, TTL, claim_id=C1)
    service.move(T1, C1, Phase.REVIEW)
    service.release(T1, C1)
    ticket = service.get(T1)
    assert ticket is not None and ticket.phase is Phase.REVIEW and ticket.claim is None
    nxt = service.claim_next(A, TTL, phase=Phase.REVIEW, claim_id=ClaimId("2" * 32))
    assert isinstance(nxt, Committed) and nxt.tickets[0].id == T1


def test_edit_with_stale_expected_version_is_stale(memstore: MemStore) -> None:
    service = service_on(memstore)
    assert isinstance(service.edit(T1, 1, title="One"), Committed)
    stale = service.edit(T1, 1, title="Two")
    assert isinstance(stale, Refused) and stale.refusal.code is RefusalCode.STALE


def test_view_and_list_read_one_snapshot(memstore: MemStore) -> None:
    counting = CountingStore(memstore)
    service = service_on(counting)
    view = service.view(T1)
    assert view is not None and view.status is Status.OPEN and counting.snapshots == 1
    assert [v.ticket.id for v in service.list(status=Status.OPEN)] == [T1]
    assert counting.snapshots == 2
    assert service.view(T2) is None


def test_list_filters_by_agent(memstore: MemStore) -> None:
    service = service_on(memstore)
    service.add("Second", ticket_id=T2)
    service.claim(T2, A, TTL, claim_id=C1)
    assert [v.ticket.id for v in service.list(agent=A)] == [T2]


def test_log_is_newest_first(memstore: MemStore) -> None:
    service = service_on(memstore)
    service.claim(T1, A, TTL, claim_id=C1)
    assert [e.record.op.value for e in service.log(T1)] == ["claim", "add"]
    assert len(service.log(limit=1)) == 1
