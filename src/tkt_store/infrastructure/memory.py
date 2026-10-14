"""An in-memory Store with the same compare-and-swap semantics as the git store.

Uses: fast unit/property tests, deterministic race injection, the coordinator's
own tests, and dry runs. Kept honest by tests/contract/test_store.py, which runs
the same contract against this and the git store.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence

from tkt_store.application.store import HistoryEntry
from tkt_store.domain.outcomes import Change, OpRecord
from tkt_store.domain.ticket import Revision, Snapshot, TicketId, Timestamp


class MemStore:
    """Commits are kept as a list of (revision, tickets, record). Revisions are
    deterministic counters."""

    def __init__(self) -> None:
        self._commits: list[tuple[Revision, Snapshot, OpRecord]] = []
        self._before_next_commit: Callable[[], None] | None = None

    # --- Store protocol -------------------------------------------------

    def snapshot(self) -> Snapshot:
        raise NotImplementedError

    def commit(
        self,
        base: Revision | None,
        changes: Sequence[Change],
        record: OpRecord,
    ) -> Revision:
        """Runs the before-next-commit hook (if any) first, then compare-and-swap."""
        raise NotImplementedError

    def history(
        self,
        ticket_id: TicketId | None = None,
        limit: int | None = None,
    ) -> Iterator[HistoryEntry]:
        """Same contract as the git store; times come from each `record.at`."""
        raise NotImplementedError

    # --- Test controls --------------------------------------------------

    def before_next_commit(self, hook: Callable[[], None]) -> None:
        """Run `hook` once, just before the next commit's compare-and-swap.
        Use it to make another writer win the race at exactly that moment."""
        self._before_next_commit = hook

    def force_advance(
        self,
        at: Timestamp,
        changes: Sequence[Change] = (),
        record: OpRecord | None = None,
    ) -> Revision:
        """Append a commit as if another writer landed first (moves the head).
        `at` stamps the default record; ignored when `record` is given."""
        raise NotImplementedError

    def copy(self) -> MemStore:
        """An independent copy (for dry runs against a snapshot of real state)."""
        raise NotImplementedError
