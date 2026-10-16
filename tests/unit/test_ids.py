"""Id sources (infrastructure/ids.py): ids match the formats the rules validate."""

from __future__ import annotations

from tkt_store.domain.ticket import CLAIM_ID_RE, TICKET_ID_RE
from tkt_store.infrastructure.ids import RandomIds, SequentialIds


def test_ticket_ids_have_prefix() -> None:
    for source in (RandomIds(), SequentialIds()):
        ticket_id = source.ticket_id()
        assert ticket_id.startswith("tkt-") and TICKET_ID_RE.fullmatch(ticket_id)


def test_claim_ids_are_unique() -> None:
    ids = RandomIds()
    claim_ids = {ids.claim_id() for _ in range(1000)}
    assert len(claim_ids) == 1000
    assert all(CLAIM_ID_RE.fullmatch(c) for c in claim_ids)


def test_sequential_ids_are_deterministic() -> None:
    a, b = SequentialIds(), SequentialIds()
    assert [a.ticket_id(), a.claim_id()] == [b.ticket_id(), b.claim_id()]
    assert CLAIM_ID_RE.fullmatch(SequentialIds().claim_id())
