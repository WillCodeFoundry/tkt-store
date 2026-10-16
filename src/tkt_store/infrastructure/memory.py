"""An in-memory Store with the same compare-and-swap semantics as the git store.

Uses: fast unit/property tests, deterministic race injection, and callers' own
tests. Kept honest by tests/contract/test_store.py, which runs
the same contract against this and the git store.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from itertools import islice
from types import MappingProxyType

from tkt_store.application.errors import Conflict
from tkt_store.application.store import HistoryEntry
from tkt_store.domain.outcomes import Change, OpRecord
from tkt_store.domain.ticket import Revision, Snapshot, TicketId

UNBORN = Snapshot(None, MappingProxyType({}))


class MemStore:
    """Commits are kept as a list of (snapshot, record); each snapshot holds its own
    revision. Revisions are deterministic counters."""

    def __init__(self) -> None:
        self._commits: list[tuple[Snapshot, OpRecord]] = []
        self._before_next_commit: Callable[[], None] | None = None

    # --- Store protocol -------------------------------------------------

    def snapshot(self) -> Snapshot:
        return self._commits[-1][0] if self._commits else UNBORN

    def commit(
        self,
        base: Revision | None,
        changes: Sequence[Change],
        record: OpRecord,
    ) -> Revision:
        """Runs the before-next-commit hook (if any) first, then compare-and-swap."""
        if (hook := self._before_next_commit) is not None:
            self._before_next_commit = None
            hook()
        head = self.snapshot().revision
        if head != base:
            raise Conflict(base, head)
        return self._append(changes, record)

    def history(
        self,
        ticket_id: TicketId | None = None,
        limit: int | None = None,
    ) -> Iterator[HistoryEntry]:
        """Same contract as the git store; times come from each `record.at`."""

        def entries() -> Iterator[HistoryEntry]:
            for snapshot, record in reversed(self._commits):
                if ticket_id is None or ticket_id in record.ticket_ids:
                    assert snapshot.revision is not None  # every commit has one
                    yield HistoryEntry(snapshot.revision, record)

        return islice(entries(), limit)

    # --- Test controls --------------------------------------------------

    def before_next_commit(self, hook: Callable[[], None]) -> None:
        """Run `hook` once, just before the next commit's compare-and-swap.
        Use it to make another writer win the race at exactly that moment."""
        self._before_next_commit = hook

    def force_advance(self, changes: Sequence[Change], record: OpRecord) -> Revision:
        """Append a commit as if another writer landed first (moves the head)."""
        return self._append(changes, record)

    def _append(self, changes: Sequence[Change], record: OpRecord) -> Revision:
        revision = Revision(f"mem-{len(self._commits) + 1}")
        tickets = dict(self.snapshot().tickets)
        tickets.update((change.ticket.id, change.ticket) for change in changes)
        self._commits.append((Snapshot(revision, MappingProxyType(tickets)), record))
        return revision
