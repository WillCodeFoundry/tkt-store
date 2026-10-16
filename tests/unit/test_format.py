"""Serialisation (docs/format.md)."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from tkt_store.application.errors import StoreError
from tkt_store.domain.operations import OpName
from tkt_store.domain.outcomes import OpRecord
from tkt_store.domain.ticket import (
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
from tkt_store.infrastructure.git import wire

NOW = 1_000_000
A = AgentId("coder-7")
C1 = ClaimId("1" * 32)
C2 = ClaimId("2" * 32)
T1 = TicketId("tkt-0001")
T2 = TicketId("tkt-0002")
CLAIM = Claim(agent=A, claim_id=C2, lease_until=NOW + 600, claimed_at=NOW - 600)

FULL = Ticket(
    id=T1,
    phase=Phase.IMPLEMENTATION,
    title="Expire reset tokens — ünïcode",
    body="Line one\nline two",
    kind=Kind.BUG,
    project=ProjectId("91c6469b"),
    priority=2,
    blocked_by=(T2,),
    tags=("auth",),
    claim=CLAIM,
    ended_claim_ids=(C1,),
    content_version=3,
    created=NOW - 100,
    updated=NOW,
)


def round_trip(ticket: Ticket) -> Ticket:
    return wire.decode_ticket(wire.encode_ticket(ticket))


def test_ticket_round_trip_is_byte_identical() -> None:
    data = wire.encode_ticket(FULL)
    assert round_trip(FULL) == FULL
    assert wire.encode_ticket(wire.decode_ticket(data)) == data


def test_ticket_file_is_canonical_json() -> None:
    data = wire.encode_ticket(FULL)
    raw = json.loads(data)
    canonical = json.dumps(raw, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    assert data == canonical.encode()
    assert "ü".encode() in data and "extra" not in raw


def test_unknown_keys_preserved_at_top_level() -> None:
    """Unknown keys land in Ticket.extra and are written back at top level (no 'extra' key)."""
    raw = json.loads(wire.encode_ticket(FULL))
    raw["estimate"] = {"points": 3}
    ticket = wire.decode_ticket(json.dumps(raw).encode())
    assert ticket.extra == {"estimate": {"points": 3}}
    assert json.loads(wire.encode_ticket(ticket)) == raw


@pytest.mark.parametrize(
    ("field", "ticket"),
    [
        ("phase", replace(FULL, phase=Phase.REVIEW)),
        ("resolution", replace(FULL, claim=None, resolution=Resolution.DONE)),
        ("ended_claim_ids", replace(FULL, ended_claim_ids=(C1, C2))),
        ("claim.claimed_at", replace(FULL, claim=replace(CLAIM, claimed_at=NOW - 5))),
        ("content_version", replace(FULL, content_version=7)),
    ],
)
def test_new_fields_round_trip(field: str, ticket: Ticket) -> None:
    assert round_trip(ticket) == ticket


@pytest.mark.parametrize(
    "corrupt",
    [
        b"not json",
        b"[]",
        b'{"id": "tkt-0001"}',
        wire.encode_ticket(FULL).replace(b'"bug"', b'"epic"'),
        wire.encode_ticket(FULL).replace(b'"priority": 2', b'"priority": "2"'),
        wire.encode_ticket(FULL).replace(b'"priority": 2', b'"priority": true'),
    ],
)
def test_malformed_ticket_is_store_error(corrupt: bytes) -> None:
    with pytest.raises(StoreError):
        wire.decode_ticket(corrupt)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tickets/tkt-7f3a.json", True),
        ("tickets/tkt-7F3A.json", False),
        ("tickets/foo.json", False),
        ("tickets/README.md", False),
        ("tickets/tkt-7f3a.json.bak", False),
        ("tickets/sub/tkt-7f3a.json", False),
        ("tkt-7f3a.json", False),
        ("tkt-store.json", False),
    ],
)
def test_is_ticket_path(path: str, expected: bool) -> None:
    assert wire.is_ticket_path(path) is expected


def test_store_meta_round_trip() -> None:
    assert wire.encode_store_meta() == b'{\n  "protocol": 1\n}\n'
    assert wire.decode_store_meta(wire.encode_store_meta()) == 1


@pytest.mark.parametrize("meta", [b"{}", b"nope", b"[]", b'{"protocol": "1"}', b'{"protocol": 2}'])
def test_bad_store_meta_is_store_error(meta: bytes) -> None:
    with pytest.raises(StoreError):
        wire.decode_store_meta(meta)


RECORDS = [
    OpRecord(OpName.INIT, at=NOW, summary="init"),
    OpRecord(
        OpName.MOVE,
        at=NOW,
        ticket_ids=(T1,),
        agent=A,
        claim_id=C1,
        summary="move tkt-0001: Expire tokens",
        phase=Phase.REVIEW,
    ),
    OpRecord(
        OpName.CANCEL, at=NOW, ticket_ids=(T1,), reason="duplicate: see tkt-0002", summary="x"
    ),
    OpRecord(OpName.REAP, at=NOW, ticket_ids=(T1, T2), summary="reap 2 lapsed claim(s)"),
]


@pytest.mark.parametrize("record", RECORDS, ids=lambda r: r.op.value)
def test_message_round_trip(record: OpRecord) -> None:
    """encode_message → decode_message returns an equal OpRecord, including `at`
    (tkt-time) and `phase` (tkt-phase)."""
    assert wire.decode_message(wire.encode_message(record)) == record


def test_message_layout_matches_the_documented_example() -> None:
    record = OpRecord(
        OpName.CLAIM, at=NOW, ticket_ids=(T1,), agent=A, claim_id=C1, summary="claim tkt-0001: X"
    )
    assert wire.encode_message(record) == (
        "claim tkt-0001: X\n\n"
        "tkt-protocol: 1\ntkt-op: claim\ntkt-time: 1000000\ntkt-id: tkt-0001\n"
        f"tkt-agent: coder-7\ntkt-claim: {C1}\n"
    )


def test_subject_is_one_line() -> None:
    """encode_message never emits a multi-line subject."""
    record = OpRecord(OpName.ADD, at=NOW, ticket_ids=(T1,), summary="add tkt-0001: a\n\nb\x1b")
    subject, blank, *_ = wire.encode_message(record).split("\n")
    assert subject == "add tkt-0001: a b" and blank == ""


def test_tkt_commit_without_time_is_rejected() -> None:
    """A tkt commit missing tkt-time → StoreError."""
    with pytest.raises(StoreError):
        wire.decode_message("add tkt-0001: X\n\ntkt-protocol: 1\ntkt-op: add\ntkt-id: tkt-0001\n")


def test_tkt_commit_without_id_is_rejected_except_init() -> None:
    with pytest.raises(StoreError):
        wire.decode_message("add\n\ntkt-protocol: 1\ntkt-op: add\ntkt-time: 1\n")
    assert wire.decode_message("init\n\ntkt-protocol: 1\ntkt-op: init\ntkt-time: 1\n")


@pytest.mark.parametrize(
    "message", ["Fix typo by hand\n", "Merge branch 'x'\n\nSigned-off-by: Someone <a@b>\n", ""]
)
def test_foreign_commit_decodes_to_none(message: str) -> None:
    assert wire.decode_message(message) is None


def test_future_protocol_version_is_rejected() -> None:
    """→ StoreError, never silently misread."""
    with pytest.raises(StoreError, match="upgrade"):
        wire.decode_message("x\n\ntkt-protocol: 2\ntkt-op: add\ntkt-time: 1\ntkt-id: tkt-0001\n")
