"""The audit log (`tkt log`, history from commit trailers) against a compromised agent."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.gitkit import write_files
from tests.security import bug
from tests.security.conftest import service
from tests.unit.builders import T1, T2
from tkt_store.domain.operations import OpName
from tkt_store.domain.ticket import AgentId

pytestmark = pytest.mark.git

MALFORMED = "release tkt-1: x\n\ntkt-protocol: 1\ntkt-op: release\ntkt-time: 1\n" \
    "tkt-id: tkt-1\ntkt-phase: bogus\n"  # fmt: skip
"""A tkt commit whose tkt-phase is not a phase: decode_message raises for it."""


@bug("a U+2028 in --as forges a tkt-id trailer: log(victim) shows an op that never happened")
def test_an_agent_name_cannot_forge_history_for_another_ticket(clone: Path) -> None:
    tickets = service(clone)
    tickets.add("Attacker's own ticket", ticket_id=T2)
    tickets.cancel(T2, agent=AgentId("mallory\u2028tkt-id: tkt-1"))
    assert [e.record.op for e in tickets.log(T1)] == [OpName.ADD]


@bug("a U+2028 in --reason writes a malformed trailer that breaks every later tkt log")
def test_a_reason_cannot_break_history(clone: Path) -> None:
    tickets = service(clone)
    tickets.add("Attacker's own ticket", ticket_id=T2)
    tickets.cancel(T2, "bye\u2028tkt-phase: bogus")
    assert [e.record.op for e in tickets.log(T1)] == [OpName.ADD]


@bug("one malformed tkt commit (pushed by hand) makes every tkt log fail for good")
@pytest.mark.parametrize("limit", [None, 1])
def test_a_malformed_commit_is_skipped_not_fatal(
    clone: Path, bare_remote: Path, limit: int | None
) -> None:
    write_files(bare_remote, {"NOTES.txt": b"x"}, message=MALFORMED)
    entries = service(clone).log(limit=limit)
    assert [e.record.op for e in entries][:1] == [OpName.ADD]
