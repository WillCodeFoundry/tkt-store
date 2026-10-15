"""Concrete id sources. The ONLY module allowed to create random values.

Both satisfy the `application.ids.IdSource` port structurally. Ids are minted by
the caller BEFORE a transaction (invariant 7), so retries reuse them.
"""

from __future__ import annotations

from tkt_store.domain.ticket import ClaimId, TicketId

TICKET_PREFIX = "tkt-"


class RandomIds:
    """Production ids from `secrets`. Ticket ids: prefix + 4+ hex chars, lengthened on
    collision by the caller (rules refuse DUPLICATE_ID; the service retries with a new id)."""

    def ticket_id(self) -> TicketId:
        raise NotImplementedError

    def claim_id(self) -> ClaimId:
        """128 bits, hex."""
        raise NotImplementedError


class SequentialIds:
    """Deterministic ids for tests, counting in hex so they pass the rules' id
    patterns: tickets f"tkt-{n:04x}" (tkt-0001, ...), claims f"{n:032x}" (32 hex digits)."""

    def __init__(self) -> None:
        self._n = 0

    def ticket_id(self) -> TicketId:
        raise NotImplementedError

    def claim_id(self) -> ClaimId:
        raise NotImplementedError
