"""Derived views over the store's history (invariant 6). Read-only.

Times are each record's injected `at`: consistent within one writer and
deterministic in tests, but clocks may skew across writers, so these views are
informational. Nothing that grants exclusivity depends on them. Claim age is not
derived here: it comes from the stored `Claim.claimed_at`.
"""

from __future__ import annotations

from collections.abc import Sequence

from tkt_store.application.store import HistoryEntry, Store
from tkt_store.domain.ticket import TicketId


def timeline(store: Store, ticket_id: TicketId) -> Sequence[HistoryEntry]:
    """Every op that named this ticket, oldest first."""
    raise NotImplementedError
