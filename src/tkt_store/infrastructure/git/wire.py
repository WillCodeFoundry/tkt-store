"""The on-branch wire format: tickets as JSON files, op records as commit trailers.

No git here — bytes and strings in, domain objects out (and back). Used by the
git store and by history. Any change to this format bumps PROTOCOL_VERSION and
updates docs/format.md in the same change.
"""

from __future__ import annotations

from tkt_store.domain.outcomes import OpRecord
from tkt_store.domain.ticket import Ticket, TicketId

PROTOCOL_VERSION = 1
TICKETS_DIR = "tickets"
DEFAULT_REF = "refs/heads/tkt"

TRAILER_PROTOCOL = "tkt-protocol"
TRAILER_OP = "tkt-op"
TRAILER_ID = "tkt-id"
TRAILER_AGENT = "tkt-agent"
TRAILER_CLAIM = "tkt-claim"
TRAILER_STAGE = "tkt-stage"
TRAILER_REASON = "tkt-reason"


def ticket_path(ticket_id: TicketId) -> str:
    """'tickets/<id>.json'."""
    return f"{TICKETS_DIR}/{ticket_id}.json"


def encode_ticket(ticket: Ticket) -> bytes:
    """Canonical JSON: UTF-8, sorted keys, 2-space indent, trailing newline.
    `extra` keys are merged back at top level. Round-trips byte-identically."""
    raise NotImplementedError


def decode_ticket(data: bytes) -> Ticket:
    """Parse a ticket file. Unknown keys go to `extra`. Raises StoreError on malformed data."""
    raise NotImplementedError


def encode_message(record: OpRecord) -> str:
    """Subject line, blank line, trailers in a fixed order, including tkt-protocol."""
    raise NotImplementedError


def decode_message(message: str) -> OpRecord | None:
    """Parse trailers. Returns None for commits without tkt trailers (foreign commits).
    Raises StoreError for an unknown future protocol version."""
    raise NotImplementedError
