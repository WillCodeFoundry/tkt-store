"""The on-branch wire format: tickets as JSON files, op records as commit trailers.

No git here — bytes and strings in, domain objects out (and back). Used by the
git store and by history. Any change to this format bumps PROTOCOL_VERSION and
updates docs/format.md in the same change (pre-1.0 exception: see AGENTS.md).
"""

from __future__ import annotations

import json
import re
from typing import Literal, cast

from tkt_store.application.errors import StoreError
from tkt_store.domain.operations import OpName
from tkt_store.domain.outcomes import OpRecord
from tkt_store.domain.ticket import (
    TICKET_ID_RE,
    AgentId,
    Claim,
    ClaimId,
    Kind,
    Phase,
    ProjectId,
    Resolution,
    Ticket,
    TicketId,
)

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

TICKET_FIELDS = frozenset(
    {
        "id",
        "kind",
        "project",
        "created",
        "title",
        "body",
        "priority",
        "blocked_by",
        "tags",
        "content_version",
        "phase",
        "resolution",
        "claim",
        "ended_claim_ids",
        "updated",
    }
)
"""The keys Ticket models; any other top-level key is preserved in Ticket.extra."""

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def ticket_path(ticket_id: TicketId) -> str:
    """'tickets/<id>.json'."""
    return f"{TICKETS_DIR}/{ticket_id}.json"


def is_ticket_path(path: str) -> bool:
    """True only for 'tickets/<id>.json' where <id> matches ticket.TICKET_ID_RE. Every
    other path on the branch is preserved and never interpreted."""
    directory, _, name = path.partition("/")
    stem = name.removesuffix(".json")
    return directory == TICKETS_DIR and stem != name and TICKET_ID_RE.fullmatch(stem) is not None


StoreMode = Literal["remote", "local"]


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def encode_store_meta(mode: StoreMode) -> bytes:
    """The tkt-store.json written by init: canonical JSON
    {"mode": mode, "protocol": PROTOCOL_VERSION}. The mode is fixed for the store's life."""
    return _canonical({"mode": mode, "protocol": PROTOCOL_VERSION})


def decode_store_meta(data: bytes) -> tuple[int, StoreMode]:
    """The store's (protocol version, mode). Raises StoreError if malformed or the
    protocol is newer than PROTOCOL_VERSION. The caller refuses a mode that does not match
    how the store was opened, so a stray --no-remote can never diverge a clone."""
    try:
        meta = json.loads(data)
        protocol, mode = meta["protocol"], meta["mode"]
    except (ValueError, TypeError, KeyError) as error:
        raise StoreError(f"malformed {STORE_META_PATH}: {error!r}") from error
    if type(protocol) is not int or mode not in ("remote", "local"):
        raise StoreError(f"malformed {STORE_META_PATH}: {meta!r}")
    _check_protocol(protocol)
    return protocol, cast(StoreMode, mode)


def _check_protocol(protocol: int) -> None:
    if protocol > PROTOCOL_VERSION:
        raise StoreError(
            f"the store uses tkt-protocol {protocol}; this client supports up to "
            f"{PROTOCOL_VERSION}: upgrade tkt-store"
        )


def encode_ticket(ticket: Ticket) -> bytes:
    """Canonical JSON: UTF-8, sorted keys, 2-space indent, trailing newline.
    `extra` keys are merged back at top level. Round-trips byte-identically."""
    return _canonical(ticket.to_dict())


def decode_ticket(data: bytes) -> Ticket:
    """Parse a ticket file. Unknown keys go to `extra`. Raises StoreError on malformed data.
    The caller checks that the filename stem equals the decoded `id` (StoreError if not)."""
    try:
        raw = json.loads(data)
        if not isinstance(raw, dict):
            raise TypeError(f"expected a JSON object, got {raw!r}")
        claim = raw["claim"]
        return Ticket(
            id=TicketId(_str(raw["id"])),
            kind=Kind(raw["kind"]),
            project=None if raw["project"] is None else ProjectId(_str(raw["project"])),
            created=_int(raw["created"]),
            title=_str(raw["title"]),
            body=_str(raw["body"]),
            priority=None if raw["priority"] is None else _int(raw["priority"]),
            blocked_by=tuple(TicketId(_str(b)) for b in _list(raw["blocked_by"])),
            tags=tuple(_str(t) for t in _list(raw["tags"])),
            content_version=_int(raw["content_version"]),
            phase=Phase(raw["phase"]),
            resolution=None if raw["resolution"] is None else Resolution(raw["resolution"]),
            claim=None
            if claim is None
            else Claim(
                agent=AgentId(_str(claim["agent"])),
                claim_id=ClaimId(_str(claim["claim_id"])),
                lease_until=_int(claim["lease_until"]),
                claimed_at=_int(claim["claimed_at"]),
            ),
            ended_claim_ids=tuple(ClaimId(_str(c)) for c in _list(raw["ended_claim_ids"])),
            updated=_int(raw["updated"]),
            extra={k: v for k, v in raw.items() if k not in TICKET_FIELDS},
        )
    except (ValueError, TypeError, KeyError) as error:
        raise StoreError(f"malformed ticket file: {error!r}") from error


def _str(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"expected a string, got {value!r}")
    return value


def _int(value: object) -> int:
    if type(value) is not int:
        raise TypeError(f"expected an integer, got {value!r}")
    return value


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"expected a list, got {value!r}")
    return value


def _one_line(text: str) -> str:
    return _CONTROL.sub(" ", text).strip()


def encode_message(record: OpRecord) -> str:
    """Subject line, blank line, trailers in a fixed order, including tkt-protocol.

    The subject is always emitted on one line (defensively, although the rules
    already refuse control characters in titles). tkt-time (`record.at`) is always
    written; tkt-phase only when `record.phase` is set.
    """
    trailers = [
        (TRAILER_PROTOCOL, str(PROTOCOL_VERSION)),
        (TRAILER_OP, record.op.value),
        (TRAILER_TIME, str(record.at)),
        *((TRAILER_ID, ticket_id) for ticket_id in record.ticket_ids),
    ]
    if record.agent is not None:
        trailers.append((TRAILER_AGENT, record.agent))
    if record.claim_id is not None:
        trailers.append((TRAILER_CLAIM, record.claim_id))
    if record.phase is not None:
        trailers.append((TRAILER_PHASE, record.phase.value))
    if record.reason:
        trailers.append((TRAILER_REASON, record.reason))
    subject = _one_line(record.summary) or record.op.value
    body = "\n".join(f"{key}: {_one_line(value)}" for key, value in trailers)
    return f"{subject}\n\n{body}\n"


def decode_message(message: str) -> OpRecord | None:
    """Parse trailers into an OpRecord, including `at` (tkt-time) and `phase` (tkt-phase).
    Returns None for commits without tkt trailers (foreign commits).
    Raises StoreError for an unknown future protocol version, or for a tkt commit
    missing a required trailer: tkt-protocol, tkt-op, tkt-time, and tkt-id (except init)."""
    paragraphs = [p for p in message.strip().split("\n\n") if p.strip()]
    if len(paragraphs) < 2:
        return None
    trailers: dict[str, list[str]] = {}
    for line in paragraphs[-1].splitlines():
        key, sep, value = line.partition(":")
        if sep:
            trailers.setdefault(key.strip(), []).append(value.strip())
    if TRAILER_PROTOCOL not in trailers:
        return None
    try:
        _check_protocol(int(trailers[TRAILER_PROTOCOL][0]))
        op = OpName(trailers[TRAILER_OP][0])
        at = int(trailers[TRAILER_TIME][0])
        ticket_ids = tuple(TicketId(i) for i in trailers.get(TRAILER_ID, []))
        if not ticket_ids and op is not OpName.INIT:
            raise KeyError(TRAILER_ID)
        phase = trailers.get(TRAILER_PHASE)
        agent = trailers.get(TRAILER_AGENT)
        claim = trailers.get(TRAILER_CLAIM)
        return OpRecord(
            op,
            at=at,
            ticket_ids=ticket_ids,
            agent=None if agent is None else AgentId(agent[0]),
            claim_id=None if claim is None else ClaimId(claim[0]),
            reason=trailers.get(TRAILER_REASON, [""])[0],
            summary=paragraphs[0].splitlines()[0].strip(),
            phase=None if phase is None else Phase(phase[0]),
        )
    except (KeyError, ValueError) as error:
        raise StoreError(f"malformed tkt commit message: {error!r}") from error
