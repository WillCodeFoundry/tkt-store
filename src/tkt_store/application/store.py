"""The Store port: the boundary between decisions and persistence.

A port, owned by the application and depended on by the transaction loop. Every
concrete store (the git store, the in-memory store) must satisfy this same
contract, which `tests/contract/test_store.py` verifies against each.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from tkt_store.domain.outcomes import Change, OpRecord
from tkt_store.domain.ticket import Revision, Snapshot, TicketId, Timestamp


@dataclass(frozen=True)
class HistoryEntry:
    """One applied op, recovered from the store's history."""

    revision: Revision
    at: Timestamp
    record: OpRecord


class Store(Protocol):
    """Contract:

    snapshot()
        Returns the current head and all tickets. Reflects every commit that
        returned successfully before the call. May fetch first (remote-backed).

    commit(base, changes, record)
        Atomically applies `changes` as ONE commit whose parent is `base`, and
        moves the head from `base` to it — compare-and-swap.
        - Raises Conflict if the head is not `base` (nothing becomes visible).
        - Raises StoreError on infrastructure failure.
        - Either the whole commit is visible afterwards, or none of it.
        `base` is the revision the changes were computed from (design.md §4),
        never a value re-read at commit time.

    history(ticket_id, limit)
        Newest first. Filtered to records naming `ticket_id` when given.
    """

    def snapshot(self) -> Snapshot: ...

    def commit(
        self,
        base: Revision | None,
        changes: Sequence[Change],
        record: OpRecord,
    ) -> Revision: ...

    def history(
        self,
        ticket_id: TicketId | None = None,
        limit: int | None = None,
    ) -> Iterator[HistoryEntry]: ...
