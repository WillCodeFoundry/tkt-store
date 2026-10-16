"""The clone cache (ADR 0006): what a clone already read and checked, kept between
processes, against real git. Each new GitStore stands for a new process."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.gitkit import HookedRunner, write_files
from tkt_store.application.service import TicketStore
from tkt_store.domain.ticket import AgentId, ClaimId, TicketId
from tkt_store.infrastructure.clock import FakeClock
from tkt_store.infrastructure.git import wire
from tkt_store.infrastructure.git.cache import CloneCache
from tkt_store.infrastructure.git.repo import GitStore
from tkt_store.infrastructure.ids import SequentialIds

NOW = 1_000_000
TTL = 1800
A = AgentId("coder-7")
T1, T2, T3 = (TicketId(f"tkt-000{n}") for n in (1, 2, 3))
C1, C2 = ClaimId("1" * 32), ClaimId("2" * 32)

pytestmark = pytest.mark.git


def cache_of(clone: Path) -> CloneCache:
    return CloneCache(clone / ".git" / "tkt-store" / "cache.json")


def process(clone: Path) -> tuple[GitStore, HookedRunner]:
    """A new process's store on `clone`, with its clone cache and a recording runner."""
    runner = HookedRunner(clone)
    return GitStore(runner, remote="origin", cache=cache_of(clone)), runner


@pytest.fixture
def clone(clones: list[Path], bare_remote: Path) -> Path:
    """A store holding T1 done (with an ended claim), T2 open and held, and T3 invalid."""
    tickets = TicketStore(GitStore.at(clones[0], remote="origin"), FakeClock(NOW), SequentialIds())
    tickets.init()
    for ticket_id in (T1, T2):
        tickets.add("Expire tokens", ticket_id=ticket_id)
    tickets.claim(T1, A, TTL, claim_id=C1)
    tickets.done(T1, C1)
    tickets.claim(T2, A, TTL, claim_id=C2)
    write_files(bare_remote, {wire.ticket_path(T3): b"not json"})
    return clones[0]


def test_the_production_store_keeps_its_cache_in_the_git_directory(clone: Path) -> None:
    GitStore.at(clone, remote="origin").snapshot()
    saved = json.loads((clone / ".git" / "tkt-store" / "cache.json").read_bytes())
    assert set(saved) == {"writer", "tickets", "invalid", "folders"}


def test_it_holds_what_never_changes_again(clone: Path) -> None:
    """The resolved ticket, the invalid file and the resolved ticket's claims folder; never
    the open ticket or its folder."""
    process(clone)[0].snapshot()
    cached = cache_of(clone).load()
    assert [t.id for t in cached.tickets.values()] == [T1]
    assert list(cached.invalid.values()) == ["not JSON"]
    (names,) = cached.folders.values()
    assert len(names) == 1 and ".done." in names[0]


def test_a_new_process_reads_only_what_may_have_changed(clone: Path) -> None:
    first, _ = process(clone)
    before = first.snapshot()
    store, runner = process(clone)
    assert store.snapshot() == before
    (blobs,) = runner.inputs_to("cat-file", "--batch")[:1]  # only the open ticket's file
    assert len(blobs.split()) == 1
    trees = runner.inputs_to("cat-file", "--batch")[1:]  # only the open ticket's folder
    assert [len(t.split()) for t in trees] == [1]


def test_it_never_holds_more_than_the_store(clone: Path, bare_remote: Path) -> None:
    process(clone)[0].snapshot()
    write_files(bare_remote, {wire.ticket_path(T3): None})  # the invalid file is removed
    process(clone)[0].snapshot()
    assert cache_of(clone).load().invalid == {}


@pytest.mark.parametrize(
    "content",
    [b"not json", b'{"writer": "0/old", "tickets": {}, "invalid": {}, "folders": {}}', None],
    ids=["corrupt", "another_writer", "wrong_shape"],
)
def test_a_cache_it_cannot_trust_is_ignored(clone: Path, content: bytes | None) -> None:
    first, _ = process(clone)
    expected = first.snapshot()
    path = cache_of(clone).path
    if content is None:  # a ticket entry that is not a ticket
        saved = json.loads(path.read_bytes())
        saved["tickets"] = {oid: {"id": 1} for oid in saved["tickets"]}
        content = json.dumps(saved).encode()
    path.write_bytes(content)
    assert process(clone)[0].snapshot() == expected


def test_deleting_the_cache_is_always_safe(clone: Path) -> None:
    first, _ = process(clone)
    expected = first.snapshot()
    cache_of(clone).path.unlink()
    assert process(clone)[0].snapshot() == expected


def test_writes_leave_no_temporary_file(clone: Path) -> None:
    process(clone)[0].snapshot()
    assert [p.name for p in cache_of(clone).path.parent.iterdir()] == ["cache.json"]
