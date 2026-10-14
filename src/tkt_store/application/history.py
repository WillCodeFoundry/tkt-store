"""Derived views over the store's history (invariant 6). Read-only.

Times are each record's injected `at`: consistent within one writer and
deterministic in tests, but clocks may skew across writers, so these views are
informational. Nothing that grants exclusivity depends on them.
"""

from __future__ import annotations

from collections.abc import Sequence

from tkt_store.application.store import HistoryEntry, Store
from tkt_store.domain.ticket import TicketId, Timestamp


def timeline(store: Store, ticket_id: TicketId) -> Sequence[HistoryEntry]:
    """Every op that named this ticket, oldest first."""
    raise NotImplementedError


def claimed_at(store: Store, ticket_id: TicketId) -> Timestamp | None:
    """`record.at` of the op that started the CURRENT claim: the newest 'claim' or
    'claim-next' record for the ticket, provided no later release/done/cancel/reap.
    None if not claimed."""
    raise NotImplementedError


def claim_age(store: Store, ticket_id: TicketId, now: Timestamp) -> int | None:
    """Seconds since claimed_at, or None. Informational (see module docstring)."""
    raise NotImplementedError
