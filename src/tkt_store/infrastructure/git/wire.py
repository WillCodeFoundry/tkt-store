"""The on-branch wire format: tickets as JSON files, claims as empty files whose names
hold their state, op records as commit trailers (docs/format.md, ADR 0007).

No git here — bytes and strings in, domain objects out (and back). Used by the git
store and by history. Any change to this format bumps PROTOCOL_VERSION and updates
docs/format.md in the same change (pre-1.0 exception: see AGENTS.md).

Everything decoded here is treated as hostile (ADR 0005): decoding is strict, and an
error never carries a value it read, only which check failed.
"""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from tkt_store.application.errors import StoreError
from tkt_store.domain import fields
from tkt_store.domain.operations import OpName
from tkt_store.domain.outcomes import OpRecord
from tkt_store.domain.ticket import (
    CLAIM_HASH_RE,
    TICKET_ID_RE,
    AgentId,
    Claim,
    ClaimFile,
    ClaimHash,
    EndedBy,
    EndedClaim,
    Kind,
    Phase,
    ProjectId,
    Resolution,
    Ticket,
    TicketId,
    canonical_json,
)

PROTOCOL_VERSION = 2
TICKETS_DIR = "tickets"
CLAIMS_DIR = "claims"
DEFAULT_REF = "refs/heads/tkt-store"
STORE_META_PATH = "tkt-store.json"
"""Root file recording the store's format version: {"protocol": <int>}. Written into the
root commit by `init`; checked on every snapshot."""

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
        "updated",
    }
)
"""Exactly the keys of a ticket file: a missing or unknown key makes it invalid."""

_TIME = r"0|[1-9][0-9]{0,11}"
_SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
CLAIM_NAME_RE = re.compile(
    rf"(?P<hash>[0-9a-f]{{64}})\.(?P<state>open|{'|'.join(e.value for e in EndedBy)})"
    rf"\.(?P<agent>(?=[a-z0-9-]{{1,39}}\.){_SLUG})\.(?P<claimed_at>{_TIME})\.(?P<time>{_TIME})"
)
"""A claim file's name in `claims/<ticket id>/` (ADR 0007): `<hash>.<open|ended_by>.
<agent>.<claimed_at>.<t>`, where `t` is `lease_until` for an open claim and `ended_at`
for an ended one; the agent follows the agent rule."""
_ENDED_BY = {by.value: by for by in EndedBy}


_E = TypeVar("_E", Kind, Phase, Resolution)


class Invalid(Exception):
    """A file or commit that breaks the format. Its message names the check that failed,
    never a value read."""


_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def ticket_path(ticket_id: TicketId) -> str:
    """'tickets/<id>.json'."""
    return f"{TICKETS_DIR}/{ticket_id}.json"


def ticket_id_of(path: str) -> TicketId | None:
    """The id of 'tickets/<id>.json' when <id> follows the id rule, else None: every other
    path on the branch is preserved and never interpreted."""
    directory, _, name = path.partition("/")
    stem = name.removesuffix(".json")
    if directory != TICKETS_DIR or stem == name or not TICKET_ID_RE.fullmatch(stem):
        return None
    return TicketId(stem)


def claim_name(claim: ClaimFile) -> str:
    """The file name that holds `claim`'s whole state (ADR 0007)."""
    if isinstance(claim, Claim):
        state, last = "open", claim.lease_until
    else:
        state, last = claim.ended_by.value, claim.ended_at
    return f"{claim.hash}.{state}.{claim.agent}.{claim.claimed_at}.{last}"


def claim_path(claim: ClaimFile) -> str:
    """'claims/<ticket_id>/<name>'."""
    return f"{CLAIMS_DIR}/{claim.ticket_id}/{claim_name(claim)}"


def claim_of(path: str) -> ClaimFile | None:
    """The claim a 'claims/<id>/<name>' path holds, or None when the path is not a claim
    file's (an unknown file: no part of it is used, ADR 0007). Whether the file itself is
    an empty regular file is the caller's check."""
    parts = path.split("/")
    if len(parts) != 3 or parts[0] != CLAIMS_DIR or not TICKET_ID_RE.fullmatch(parts[1]):
        return None
    return claim_named(TicketId(parts[1]), parts[2])


def claim_named(folder: TicketId, name: str) -> ClaimFile | None:
    """The claim a file named `name` in `claims/<folder>/` holds, or None when the name is
    not a claim file's. `folder` must already follow the ticket id rule."""
    found = CLAIM_NAME_RE.fullmatch(name)
    if found is None:
        return None
    hashed, state, agent, claimed_at, last = found.groups()
    claim, holder = ClaimHash(hashed), AgentId(agent)
    if state == "open":
        return Claim(folder, claim, holder, int(claimed_at), int(last))
    return EndedClaim(folder, claim, holder, int(claimed_at), _ENDED_BY[state], int(last))


def claims_folder_of(path: str) -> TicketId | None:
    """The ticket id when `path` is 'claims/<id>' itself, a ticket's claims folder: listed
    as an entry of its own only when it is not a folder (ADR 0007)."""
    directory, slash, name = path.partition("/")
    if directory != CLAIMS_DIR or not slash or "/" in name or not TICKET_ID_RE.fullmatch(name):
        return None
    return TicketId(name)


def encode_store_meta() -> bytes:
    """The tkt-store.json written by init: canonical JSON {"protocol": PROTOCOL_VERSION}."""
    return canonical_json({"protocol": PROTOCOL_VERSION})


def decode_store_meta(data: bytes) -> None:
    """Accepts only `{"protocol": PROTOCOL_VERSION}`; anything else is a StoreError that
    names no value: 0.2.0 reads protocol 2 stores only and migrates none (ADR 0005)."""
    try:
        meta = json.loads(data)
    except (ValueError, RecursionError) as error:
        raise StoreError(f"malformed {STORE_META_PATH}: not JSON") from error
    if not isinstance(meta, dict) or set(meta) != {"protocol"} or type(meta["protocol"]) is not int:
        raise StoreError(f'malformed {STORE_META_PATH}: expected {{"protocol": <integer>}}')
    if meta["protocol"] != PROTOCOL_VERSION:
        raise StoreError(
            f"the store uses another tkt-protocol; this client reads only protocol "
            f"{PROTOCOL_VERSION} (stores are not migrated)"
        )


def encode_ticket(ticket: Ticket) -> bytes:
    """Canonical JSON: UTF-8, sorted keys, 2-space indent, trailing newline. Round-trips
    byte-identically."""
    return ticket.encoded()


def decode_ticket(data: bytes) -> Ticket:
    """Parse a ticket file strictly: JSON, exactly the TICKET_FIELDS, each of its type.
    Raises Invalid naming the check that failed. The caller checks the field rules, and
    that the file name is the ticket's `id`."""
    try:
        raw = json.loads(data)
    except (ValueError, RecursionError) as error:
        raise Invalid("not JSON") from error
    return ticket_from_raw(raw)


def ticket_from_raw(raw: object) -> Ticket:
    """A ticket from parsed JSON, strictly (as `decode_ticket`): the clone cache loads its
    tickets through this, without the field rules they already passed."""
    if not isinstance(raw, dict):
        raise Invalid("not a JSON object")
    if missing := sorted(TICKET_FIELDS - set(raw)):
        raise Invalid(f"missing field {missing[0]}")
    if set(raw) - TICKET_FIELDS:
        raise Invalid("unknown field")
    return Ticket(
        id=TicketId(_str(raw, "id")),
        kind=_enum(Kind, raw, "kind"),
        project=None if raw["project"] is None else ProjectId(_str(raw, "project")),
        created=_int(raw, "created"),
        title=_str(raw, "title"),
        body=_str(raw, "body"),
        priority=None if raw["priority"] is None else _int(raw, "priority"),
        blocked_by=tuple(TicketId(b) for b in _strings(raw, "blocked_by")),
        tags=_strings(raw, "tags"),
        content_version=_int(raw, "content_version"),
        phase=_enum(Phase, raw, "phase"),
        resolution=None if raw["resolution"] is None else _enum(Resolution, raw, "resolution"),
        updated=_int(raw, "updated"),
    )


def _str(raw: dict[str, object], key: str) -> str:
    value = raw[key]
    if not isinstance(value, str):
        raise Invalid(f"{key} is not a string")
    return value


def _int(raw: dict[str, object], key: str) -> int:
    value = raw[key]
    if type(value) is not int:
        raise Invalid(f"{key} is not an integer")
    return value


def _strings(raw: dict[str, object], key: str) -> tuple[str, ...]:
    value = raw[key]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise Invalid(f"{key} is not a list of strings")
    return tuple(value)


_MEMBERS: dict[type, dict[str, Any]] = {
    kind: {member.value: member for member in kind} for kind in (Kind, Phase, Resolution)
}


def _enum(kind: type[_E], raw: dict[str, object], key: str) -> _E:
    value = raw[key]
    member = _MEMBERS[kind].get(value) if isinstance(value, str) else None
    if member is None:
        raise Invalid(f"{key} is not one of its values")
    return member  # type: ignore[no-any-return]


def _one_line(text: str) -> str:
    return _CONTROL.sub(" ", text).strip()


def encode_message(record: OpRecord) -> str:
    """Subject line, blank line, trailers in a fixed order, including tkt-protocol.

    The subject is always emitted on one line (defensively, although the rules
    already refuse line breaks in titles). tkt-time (`record.at`) is always
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
    if record.claim_hash is not None:
        trailers.append((TRAILER_CLAIM, record.claim_hash))
    if record.phase is not None:
        trailers.append((TRAILER_PHASE, record.phase.value))
    if record.reason:
        trailers.append((TRAILER_REASON, record.reason))
    subject = _one_line(record.summary) or record.op.value
    body = "\n".join(f"{key}: {_one_line(value)}" for key, value in trailers)
    return f"{subject}\n\n{body}\n"


def decode_message(message: str) -> OpRecord | None:
    """Parse trailers into an OpRecord, including `at` (tkt-time) and `phase` (tkt-phase).
    Returns None for a commit without tkt trailers (a foreign commit). Raises Invalid for
    a tkt commit that breaks the format: another protocol, a missing required trailer
    (tkt-protocol, tkt-op, tkt-time, and tkt-id except for init), or a value that breaks
    its rule (the field rules, a claim hash, a phase). History skips such a commit."""
    paragraphs = [p for p in message.strip().split("\n\n") if p.strip()]
    if len(paragraphs) < 2:
        return None
    trailers: dict[str, list[str]] = {}
    for line in paragraphs[-1].split("\n"):
        key, sep, value = line.partition(":")
        if sep:
            trailers.setdefault(key.strip(), []).append(value.strip())
    if TRAILER_PROTOCOL not in trailers:
        return None
    if trailers[TRAILER_PROTOCOL] != [str(PROTOCOL_VERSION)]:
        raise Invalid("another tkt-protocol")
    op = _one(trailers, TRAILER_OP, {name.value for name in OpName})
    at = _one(trailers, TRAILER_TIME)
    if not re.fullmatch(_TIME, at):
        raise Invalid(f"{TRAILER_TIME} is not a time")
    ticket_ids = tuple(trailers.get(TRAILER_ID, []))
    if (not ticket_ids and op != OpName.INIT) or any(map(fields.ticket_id_problem, ticket_ids)):
        raise Invalid(f"{TRAILER_ID} is missing or not a ticket id")
    agent = _optional(trailers, TRAILER_AGENT)
    if agent is not None and fields.agent_problem(agent):
        raise Invalid(f"{TRAILER_AGENT} is not an agent")
    claim = _optional(trailers, TRAILER_CLAIM)
    if claim is not None and not CLAIM_HASH_RE.fullmatch(claim):
        raise Invalid(f"{TRAILER_CLAIM} is not a claim hash")
    phase = _optional(trailers, TRAILER_PHASE, {p.value for p in Phase})
    reason = _optional(trailers, TRAILER_REASON) or ""
    if fields.reason_problem(reason):
        raise Invalid(f"{TRAILER_REASON} breaks the field rules")
    return OpRecord(
        OpName(op),
        at=int(at),
        ticket_ids=tuple(TicketId(i) for i in ticket_ids),
        agent=None if agent is None else AgentId(agent),
        claim_hash=None if claim is None else ClaimHash(claim),
        reason=reason,
        summary=paragraphs[0].split("\n")[0].strip(),
        phase=None if phase is None else Phase(phase),
    )


def _one(trailers: dict[str, list[str]], key: str, allowed: set[str] | None = None) -> str:
    if len(values := trailers.get(key, [])) != 1 or (allowed and values[0] not in allowed):
        raise Invalid(f"{key} is missing, repeated or not one of its values")
    return values[0]


def _optional(
    trailers: dict[str, list[str]], key: str, allowed: set[str] | None = None
) -> str | None:
    return None if key not in trailers else _one(trailers, key, allowed)
