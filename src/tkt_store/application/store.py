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
from tkt_store.domain.ticket import Revision, Snapshot, TicketId


@dataclass(frozen=True)
class HistoryEntry:
    """One applied op, recovered from the store's history. Its time is `record.at`."""

    revision: Revision
    record: OpRecord


class Store(Protocol):
    """Contract:

    snapshot()
        Returns the current revision and all tickets. Reflects every commit that
        returned successfully before the call. May fetch first.
        Raises StoreError if the store's format version is missing or newer than
        supported, or if a ticket file is corrupt (the whole snapshot fails: a partial
        view could mislead dependency checks and claim-next).

    commit(base, changes, record)
        Atomically applies `changes` as ONE commit whose parent is `base`, and
        moves the head from `base` to it — compare-and-swap.
        - Raises Conflict if the head is not `base`. Conflict always means nothing
          became visible: once a commit is published it is never reported as a
          Conflict, even if a local cache could not be updated.
        - Raises StoreError on infrastructure failure. A StoreError raised while
          publishing may hide a commit that landed; re-running the op converges.
        - Either the whole commit is visible afterwards, or none of it.
        `base` is the revision the changes were computed from (design.md §4),
        never a value re-read at commit time.

    history(ticket_id, limit)
        Newest first. Filtered to records naming `ticket_id` when given.
        Commits without tkt trailers (foreign commits) yield no entry.
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
