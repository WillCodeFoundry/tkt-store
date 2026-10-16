"""Real git: interrupt an op at each step and re-run it (design.md §6).

A crash is simulated by an injected runner that raises `Crash` (not a StoreError, so
nothing in the package handles it) at a chosen git command, as if the process died there.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.gitkit import HookedRunner, head, new_repo, once
from tests.unit.builders import C1, NOW, T1, TTL, A
from tkt_store.application.errors import StoreError
from tkt_store.application.service import TicketStore
from tkt_store.application.transaction import Committed, Unchanged
from tkt_store.domain.operations import ClaimOp, OpName
from tkt_store.infrastructure.clock import FakeClock
from tkt_store.infrastructure.git.repo import GitStore
from tkt_store.infrastructure.git.runner import GitError
from tkt_store.infrastructure.ids import SequentialIds

pytestmark = pytest.mark.git

Hook = Callable[[tuple[str, ...]], None]


class Crash(Exception):
    """The process died here."""


def crash() -> None:
    raise Crash


def fail() -> None:
    raise GitError(("simulated",), 1, b"", "simulated failure")


def service(
    repo: Path,
    *,
    remote: str | None = "origin",
    hook: Hook = lambda a: None,
    after: Hook = lambda a: None,
) -> TicketStore:
    store = GitStore(HookedRunner(repo, hook, after), remote=remote)
    return TicketStore(store, FakeClock(NOW), SequentialIds())


@pytest.fixture
def repo(clones: list[Path]) -> Path:
    """A clone of a remote store holding one open ticket."""
    tickets = service(clones[0])
    tickets.init()
    tickets.add("Expire tokens", ticket_id=T1)
    return clones[0]


def claims(repo: Path) -> list[OpName]:
    return [e.record.op for e in service(repo).log(T1) if e.record.op is OpName.CLAIM]


@pytest.mark.parametrize("step", ["hash-object", "mktree", "commit-tree", "push"])
def test_crash_before_publish_leaves_only_unreachable_objects(
    step: str, repo: Path, bare_remote: Path
) -> None:
    before = head(repo), head(bare_remote)
    with pytest.raises(Crash):
        service(repo, hook=once(step, crash)).claim(T1, A, TTL, claim_id=C1)
    assert (head(repo), head(bare_remote)) == before
    assert isinstance(service(repo).claim(T1, A, TTL, claim_id=C1), Committed)


def test_crash_before_local_cas_in_a_local_only_store(tmp_path: Path) -> None:
    repo = new_repo(tmp_path / "local")
    service(repo, remote=None).init()
    service(repo, remote=None).add("Expire tokens", ticket_id=T1)
    before = head(repo)
    with pytest.raises(Crash):
        service(repo, remote=None, hook=once("update-ref", crash)).claim(T1, A, TTL, claim_id=C1)
    assert head(repo) == before
    assert isinstance(service(repo, remote=None).claim(T1, A, TTL, claim_id=C1), Committed)


def test_crash_after_push_before_local_update_converges_on_next_op(
    repo: Path, bare_remote: Path
) -> None:
    with pytest.raises(Crash):
        service(repo, hook=once("update-ref", crash)).claim(T1, A, TTL, claim_id=C1)
    assert head(repo) != head(bare_remote)  # published; the local cache is behind
    view = service(repo).view(T1)
    assert view is not None and view.ticket.claim is not None
    assert head(repo) == head(bare_remote)  # the next snapshot repaired the cache


def test_rerunning_claim_with_same_claim_id_converges_to_one_claim(repo: Path) -> None:
    with pytest.raises(Crash):
        service(repo, hook=once("update-ref", crash)).claim(T1, A, TTL, claim_id=C1)
    again = service(repo).claim(T1, A, TTL, claim_id=C1)
    assert isinstance(again, Unchanged)
    assert again.tickets[0].claim is not None and again.tickets[0].claim.claim_id == C1
    assert claims(repo) == [OpName.CLAIM]


def test_push_landed_then_local_update_failed_is_committed(repo: Path, bare_remote: Path) -> None:
    """Never Conflict after a successful push; commit returns the new revision."""
    outcome = service(repo, hook=once("update-ref", fail)).claim(T1, A, TTL, claim_id=C1)
    assert isinstance(outcome, Committed) and outcome.revision == head(bare_remote)


def test_ambiguous_push_failure_rerun_converges(repo: Path) -> None:
    """StoreError(op=…) during push, commit actually landed: re-running op → Unchanged
    naming the same ticket and claim id."""
    with pytest.raises(StoreError) as exc:
        service(repo, after=once("push", fail)).claim(T1, A, TTL, claim_id=C1)
    op = exc.value.op
    assert isinstance(op, ClaimOp) and op.claim_id == C1
    again = service(repo).claim(op.ticket_id, op.agent, op.ttl, claim_id=op.claim_id)
    assert isinstance(again, Unchanged) and again.tickets[0].id == T1
    assert again.tickets[0].claim is not None and again.tickets[0].claim.claim_id == C1
    assert claims(repo) == [OpName.CLAIM]
