"""The identifier source the application depends on.

A port: ids are minted by the caller BEFORE a transaction (invariant 7) so that
retries reuse them and converge. The concrete sources (random for production, a
deterministic sequence for tests) live in `infrastructure.ids`.
"""

from __future__ import annotations

from typing import Protocol

from tkt_store.domain.ticket import ClaimId, TicketId


class IdSource(Protocol):
    def ticket_id(self) -> TicketId: ...

    def claim_id(self) -> ClaimId: ...
