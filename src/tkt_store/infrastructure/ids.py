"""Concrete id sources, and backoff jitter. The ONLY module allowed to create random
values.

Both satisfy the `application.ids.IdSource` port structurally. Ids are minted by
the caller BEFORE a transaction (invariant 7), so retries reuse them.
"""

from __future__ import annotations

import secrets

from tkt_store.domain.ticket import TICKET_PREFIX, ClaimId, TicketId


class RandomIds:
    """Production ids from `secrets`. Ticket ids: TICKET_PREFIX + 8 hex chars (short
    enough to type); on the rare collision the rules refuse DUPLICATE_ID and the service
    re-mints a fresh id."""

    def ticket_id(self) -> TicketId:
        return TicketId(TICKET_PREFIX + secrets.token_hex(4))

    def claim_id(self) -> ClaimId:
        """128 bits, hex."""
        return ClaimId(secrets.token_hex(16))


def jitter() -> float:
    """A uniform random fraction in [0, 1), for backoff (not an id, but random)."""
    return secrets.randbits(53) / (1 << 53)


class SequentialIds:
    """Deterministic ids for tests, counting in hex so they pass the rules' id
    patterns: tickets f"tkt-{n:04x}" (tkt-0001, ...), claims f"{n:032x}" (32 hex digits)."""

    def __init__(self) -> None:
        self._n = 0

    def ticket_id(self) -> TicketId:
        self._n += 1
        return TicketId(f"{TICKET_PREFIX}{self._n:04x}")

    def claim_id(self) -> ClaimId:
        self._n += 1
        return ClaimId(f"{self._n:032x}")
