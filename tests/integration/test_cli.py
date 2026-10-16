"""CLI end-to-end against a temporary store (docs/cli.md). Parser-level checks live in
tests/unit/test_cli.py."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tkt_store.application.errors import RetriesExhausted, StoreError
from tkt_store.application.service import TicketStore
from tkt_store.cli import emit_error, main, render_outcome
from tkt_store.domain.operations import ClaimOp
from tkt_store.domain.ticket import SKEW_GRACE, AgentId, ClaimId, TicketId
from tkt_store.infrastructure.clock import FakeClock
from tkt_store.infrastructure.git.repo import GitStore
from tkt_store.infrastructure.ids import SequentialIds

NOW = 1_000_000
TTL = 1800
A = AgentId("coder-7")
B = AgentId("reviewer-2")

pytestmark = pytest.mark.git

README = Path(__file__).resolve().parents[2] / "README.md"
TICKET = "tkt-7f3a91c2"
C1, C2 = "1" * 32, "2" * 32


class Tkt:
    """Runs `tkt` in-process against one clone; returns (exit code, parsed stdout)."""

    def __init__(self, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
        self.store = ["--repo", str(repo), "--remote", "origin"]
        self.capsys = capsys

    def __call__(self, *argv: str) -> tuple[int, Any]:
        code = main([*argv, *self.store])
        out = self.capsys.readouterr().out
        assert out.count("\n") == 1  # exactly one JSON value
        return code, json.loads(out)


@pytest.fixture
def tkt(clones: list[Path], capsys: pytest.CaptureFixture[str]) -> Tkt:
    run = Tkt(clones[0], capsys)
    run("init")
    run("add", "--id", TICKET, "--title", "Expire reset tokens", "--kind", "task",
        "--phase", "implementation")  # fmt: skip
    return run


def claim(tkt: Tkt, claim_id: str = C1, agent: str = A) -> tuple[int, Any]:
    return tkt("claim", TICKET, "--as", agent, "--ttl", "1800", "--claim-id", claim_id)


def test_add_claim_release_done_flow(tkt: Tkt) -> None:
    """Each command prints one JSON value with the documented shape."""
    code, out = claim(tkt)
    assert code == 0 and out["outcome"] == "committed" and len(out["revision"]) == 40
    (ticket,) = out["tickets"]
    assert ticket["id"] == TICKET and ticket["claim"]["claim_id"] == C1
    assert tkt("move", TICKET, "--claim-id", C1, "--to-phase", "review")[1]["outcome"] == (
        "committed"
    )
    assert tkt("release", TICKET, "--claim-id", C1, "--reason", "handoff")[0] == 0
    code, out = tkt("claim-next", "--as", B, "--ttl", "1800", "--claim-id", C2, "--phase", "review")
    assert code == 0 and out["tickets"][0]["id"] == TICKET
    code, out = tkt("done", TICKET, "--claim-id", C2)
    assert code == 0 and out["tickets"][0]["resolution"] == "done"
    code, out = tkt("show", TICKET)
    assert code == 0 and out["status"] == "done" and out["ticket"]["ended_claim_ids"] == [C1, C2]
    code, rows = tkt("list", "--status", "done")
    assert code == 0 and [r["ticket"]["id"] for r in rows] == [TICKET]
    code, log = tkt("log", TICKET, "--limit", "2")
    assert code == 0 and [e["op"] for e in log] == ["done", "claim-next"]
    assert set(log[0]) == {
        "revision", "at", "op", "ticket_ids", "agent", "claim_id", "phase", "reason",
    }  # fmt: skip


def test_edit_and_cancel(tkt: Tkt) -> None:
    code, out = tkt("edit", TICKET, "--if-version", "1", "--title", "New", "--tag", "auth")
    assert code == 0 and out["tickets"][0]["content_version"] == 2
    code, out = tkt("edit", TICKET, "--if-version", "1", "--title", "Other")
    assert code == 1 and out["code"] == "STALE"
    code, out = tkt("cancel", TICKET, "--reason", "duplicate", "--as", B)
    assert code == 0 and out["tickets"][0]["resolution"] == "cancelled"


@pytest.mark.parametrize(("command", "count"), [("init", 0), ("claim", 1), ("reap", 2)])
def test_tickets_list_has_the_documented_count(
    command: str, count: int, clones: list[Path]
) -> None:
    """Exactly one for single-ticket commands, none for init, zero or more for reap."""
    clock = FakeClock(NOW)
    service = TicketStore(GitStore.at(clones[0], remote="origin"), clock, SequentialIds())
    outcome = service.init()
    if command != "init":
        for n in (1, 2):
            service.add(f"Ticket {n}", ticket_id=TicketId(f"tkt-{n:04}"))
            outcome = service.claim(TicketId(f"tkt-{n:04}"), A, TTL, claim_id=ClaimId(f"{n}" * 32))
    if command == "reap":
        clock.advance(TTL + SKEW_GRACE)
        outcome = service.reap()
    value, code = render_outcome(outcome)
    assert code == 0 and value["outcome"] == "committed" and len(value["tickets"]) == count


def test_rerunning_the_same_command_is_unchanged(tkt: Tkt) -> None:
    claim(tkt)
    code, out = claim(tkt)
    assert code == 0 and out["outcome"] == "unchanged" and out["reason"]
    assert out["tickets"][0]["claim"]["claim_id"] == C1


def test_show_unknown_id_is_refused_not_found(tkt: Tkt) -> None:
    code, out = tkt("show", "tkt-0404")
    assert (code, out["outcome"], out["code"]) == (1, "refused", "NOT_FOUND")


def test_error_output_carries_the_op_and_its_ids(
    clones: list[Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """A store failure prints {"outcome": "error", "exit", "message", "op"}."""
    store = ["--repo", str(clones[0]), "--remote", "no-such-remote"]
    code = main(["claim", TICKET, "--as", A, "--ttl", "1800", "--claim-id", C1, *store])
    out = json.loads(capsys.readouterr().out)
    assert code == 4 and out["outcome"] == "error" and out["exit"] == 4 and out["message"]
    assert out["op"] == {
        "op": "claim", "ticket_id": TICKET, "agent": A, "claim_id": C1, "ttl": 1800,
    }  # fmt: skip


def test_exit_codes_match_docs(tkt: Tkt, capsys: pytest.CaptureFixture[str]) -> None:
    """0 committed/unchanged/read, 1 refused, 2 usage, 3 retries exhausted, 4 store error."""
    assert claim(tkt)[0] == 0 and claim(tkt)[0] == 0 and tkt("list")[0] == 0
    assert claim(tkt, C2, B)[0] == 1
    with pytest.raises(SystemExit) as usage:
        main(["claim", TICKET])
    assert usage.value.code == 2
    capsys.readouterr()
    op = ClaimOp(TicketId(TICKET), A, ClaimId(C1), TTL)
    assert emit_error(RetriesExhausted(op)) == 3
    assert json.loads(capsys.readouterr().out)["op"]["claim_id"] == C1
    assert emit_error(StoreError("boom")) == 4
    assert json.loads(capsys.readouterr().out)["op"] is None


def test_readme_quickstart_runs_as_written(clones: list[Path]) -> None:
    """The README quickstart, verbatim, against a clone of a bare remote."""
    block = re.search(r"## Quickstart.*?```sh\n(.*?)```", README.read_text(), re.S)
    assert block is not None
    script = block[1].replace("/work/tasks", str(clones[0]))
    bin_dir = Path(sys.executable).parent
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script], capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, result.stdout + result.stderr
    outputs = [json.loads(line) for line in result.stdout.splitlines()]
    assert all(not isinstance(o, dict) or o.get("outcome") != "refused" for o in outputs)
    done = outputs[-3]
    assert done["outcome"] == "committed" and done["tickets"][0]["resolution"] == "done"
