"""ONE contract suite, run against every Store implementation (store.py docstring).

If MemStore and GitStore ever differ, a test here must fail. GitStore runs both
local-only and remote-backed (a clone of a bare remote).
"""

from __future__ import annotations

import pytest

from tests.unit.builders import NOW, T1, T2, tkt
from tkt_store.application.errors import Conflict
from tkt_store.application.store import Store
from tkt_store.domain.operations import OpName
from tkt_store.domain.outcomes import OpRecord, WriteTicket
from tkt_store.domain.ticket import Revision, TicketId

STORES = [
    "memstore",
    pytest.param("gitstore", marks=pytest.mark.git),
    pytest.param("remote_gitstore", marks=pytest.mark.git),
]


@pytest.fixture(params=STORES)
def store(request: pytest.FixtureRequest) -> Store:
    result: Store = request.getfixturevalue(request.param)
    return result


def record(op: OpName, *ticket_ids: TicketId) -> OpRecord:
    return OpRecord(op, at=NOW, ticket_ids=ticket_ids)


def init(store: Store) -> Revision:
    return store.commit(None, (), record(OpName.INIT))


def test_unborn_snapshot_has_no_revision(store: Store) -> None:
    snapshot = store.snapshot()
    assert snapshot.revision is None and dict(snapshot.tickets) == {}


def test_commit_on_current_base_becomes_visible(store: Store) -> None:
    base = init(store)
    revision = store.commit(base, (WriteTicket(tkt(T1)),), record(OpName.ADD, T1))
    snapshot = store.snapshot()
    assert snapshot.revision == revision != base
    assert snapshot.get(T1) == tkt(T1)


def test_commit_on_stale_base_raises_conflict_and_changes_nothing(store: Store) -> None:
    stale = init(store)
    head = store.commit(stale, (WriteTicket(tkt(T1)),), record(OpName.ADD, T1))
    with pytest.raises(Conflict):
        store.commit(stale, (WriteTicket(tkt(T2)),), record(OpName.ADD, T2))
    snapshot = store.snapshot()
    assert snapshot.revision == head and snapshot.get(T2) is None


def test_commit_is_all_or_nothing_for_multiple_changes(store: Store) -> None:
    base = init(store)
    both = (WriteTicket(tkt(T1)), WriteTicket(tkt(T2)))
    store.commit(base, both, record(OpName.REAP, T1, T2))
    snapshot = store.snapshot()
    assert snapshot.get(T1) is not None and snapshot.get(T2) is not None
    with pytest.raises(Conflict):
        store.commit(base, (WriteTicket(tkt(T1, title="x")),), record(OpName.EDIT, T1))
    assert store.snapshot().get(T1) == tkt(T1)


def test_history_newest_first_and_filterable_by_ticket(store: Store) -> None:
    base = init(store)
    first = store.commit(base, (WriteTicket(tkt(T1)),), record(OpName.ADD, T1))
    second = store.commit(first, (WriteTicket(tkt(T2)),), record(OpName.ADD, T2))
    assert [e.revision for e in store.history()] == [second, first, base]
    assert [e.revision for e in store.history(T1)] == [first]
    assert [e.revision for e in store.history(limit=1)] == [second]
    assert all(e.record.at == NOW for e in store.history())
