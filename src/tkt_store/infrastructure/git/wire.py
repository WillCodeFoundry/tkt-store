"""The on-branch wire format: tickets as JSON files, op records as commit trailers.

No git here — bytes and strings in, domain objects out (and back). Used by the
git store and by history. Any change to this format bumps PROTOCOL_VERSION and
updates docs/format.md in the same change (pre-1.0 exception: see AGENTS.md).
"""

from __future__ import annotations

from typing import Literal

from tkt_store.domain.outcomes import OpRecord
from tkt_store.domain.ticket import Ticket, TicketId

PROTOCOL_VERSION = 1
TICKETS_DIR = "tickets"
DEFAULT_REF = "refs/heads/tkt-store"
STORE_META_PATH = "tkt-store.json"
"""Root file recording the store's format version and mode:
{"mode": "remote" | "local", "protocol": <int>}. Written into the root commit by `init`;
checked on every snapshot."""

TRAILER_PROTOCOL = "tkt-protocol"
TRAILER_OP = "tkt-op"
TRAILER_ID = "tkt-id"
TRAILER_AGENT = "tkt-agent"
TRAILER_CLAIM = "tkt-claim"
TRAILER_PHASE = "tkt-phase"
TRAILER_REASON = "tkt-reason"
TRAILER_TIME = "tkt-time"


def ticket_path(ticket_id: TicketId) -> str:
    """'tickets/<id>.json'."""
    return f"{TICKETS_DIR}/{ticket_id}.json"


def is_ticket_path(path: str) -> bool:
    """True only for 'tickets/<id>.json' where <id> matches ticket.TICKET_ID_RE. Every
    other path on the branch is preserved and never interpreted."""
    raise NotImplementedError


StoreMode = Literal["remote", "local"]


def encode_store_meta(mode: StoreMode) -> bytes:
    """The tkt-store.json written by init: canonical JSON
    {"mode": mode, "protocol": PROTOCOL_VERSION}. The mode is fixed for the store's life."""
    raise NotImplementedError


def decode_store_meta(data: bytes) -> tuple[int, StoreMode]:
    """The store's (protocol version, mode). Raises StoreError if malformed or the
    protocol is newer than PROTOCOL_VERSION. The caller refuses a mode that does not match
    how the store was opened, so a stray --no-remote can never diverge a clone."""
    raise NotImplementedError


def encode_ticket(ticket: Ticket) -> bytes:
    """Canonical JSON: UTF-8, sorted keys, 2-space indent, trailing newline.
    `extra` keys are merged back at top level. Round-trips byte-identically."""
    raise NotImplementedError


def decode_ticket(data: bytes) -> Ticket:
    """Parse a ticket file. Unknown keys go to `extra`. Raises StoreError on malformed data.
    The caller checks that the filename stem equals the decoded `id` (StoreError if not)."""
    raise NotImplementedError


def encode_message(record: OpRecord) -> str:
    """Subject line, blank line, trailers in a fixed order, including tkt-protocol.

    The subject is always emitted on one line (defensively, although the rules
    already refuse control characters in titles). tkt-time (`record.at`) is always
    written; tkt-phase only when `record.phase` is set.
    """
    raise NotImplementedError


def decode_message(message: str) -> OpRecord | None:
    """Parse trailers into an OpRecord, including `at` (tkt-time) and `phase` (tkt-phase).
    Returns None for commits without tkt trailers (foreign commits).
    Raises StoreError for an unknown future protocol version, or for a tkt commit
    missing a required trailer: tkt-protocol, tkt-op, tkt-time, and tkt-id (except init)."""
    raise NotImplementedError
