"""Hijacking a claim through tkt itself: an agent confined to tkt reads another agent's
claim from the store and uses what it sees to act as the holder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tkt_store.application.service import TicketStore
from tkt_store.application.transaction import Refused
from tkt_store.cli import main
from tkt_store.domain.ticket import AgentId, ClaimId, Phase, TicketId

T1 = TicketId("tkt-0001")
HOLDER = AgentId("coder-7")
SECRET = ClaimId("5" * 32)
"""The holder's claim id: known only to the holder, which got it from `tkt mint`."""

pytestmark = pytest.mark.git


def visible_claim_values(clone: Path, capsys: pytest.CaptureFixture[str]) -> list[str]:
    """Every string an impostor sees in the claim when it runs `tkt show tkt-0001`."""
    assert main(["show", T1, "--repo", str(clone), "--remote", "origin"]) == 0
    claim: dict[str, Any] = json.loads(capsys.readouterr().out)["ticket"]["claim"]
    return [value for value in claim.values() if isinstance(value, str)]


HOLDER_OPS = {
    "renew": lambda store, claim_id: store.renew(T1, claim_id, 1800),
    "move": lambda store, claim_id: store.move(T1, claim_id, Phase.REVIEW),
    "release": lambda store, claim_id: store.release(T1, claim_id),
    "done": lambda store, claim_id: store.done(T1, claim_id),
}


@pytest.mark.security_design("claim ids are printed by show, so anyone can act as the holder")
@pytest.mark.parametrize("op", HOLDER_OPS.values(), ids=HOLDER_OPS)
def test_what_show_prints_cannot_be_used_to_act_as_the_holder(
    tickets: TicketStore, honest_clone: Path, capsys: pytest.CaptureFixture[str], op: Any
) -> None:
    tickets.claim(T1, HOLDER, 1800, claim_id=SECRET)
    before = tickets.view(T1)
    for value in visible_claim_values(honest_clone, capsys):
        assert isinstance(op(tickets, ClaimId(value)), Refused)
    assert tickets.view(T1) == before
