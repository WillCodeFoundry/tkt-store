"""The clone cache (ADR 0006): what a clone already read and checked, kept between
processes, against real git. Each new GitStore stands for a new process."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.gitkit import HookedRunner, configure, git, write_files
from tkt_store.application.errors import StoreError
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
T1, T2, T3, T4 = (TicketId(f"tkt-000{n}") for n in (1, 2, 3, 4))
C1, C2 = ClaimId("1" * 32), ClaimId("2" * 32)

pytestmark = pytest.mark.git


def cache_of(clone: Path) -> CloneCache:
    return CloneCache(clone / ".git" / "tkt-store" / "cache")


def shards(clone: Path) -> list[Path]:
    return sorted(cache_of(clone).directory.glob("??.json"))


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
    for shard in shards(clone):
        saved = json.loads(shard.read_bytes())
        assert set(saved) == {"writer", "tickets", "invalid", "folders"}
        assert all(key[:2] == shard.stem for part in ("tickets", "invalid", "folders")
                   for key in saved[part])  # fmt: skip
    assert shards(clone)


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
    "spoil",
    ["corrupt", "another_writer", "wrong_shape", "forged_reason", "wrong_shard"],
)
def test_a_shard_it_cannot_trust_is_ignored(clone: Path, spoil: str) -> None:
    first, _ = process(clone)
    expected = first.snapshot()
    for path in shards(clone):
        saved = json.loads(path.read_bytes())
        match spoil:
            case "corrupt":
                path.write_bytes(b"not json")
                continue
            case "another_writer":
                saved["writer"] = "0/old"
            case "wrong_shape":  # a ticket entry that is not a ticket
                saved["tickets"] = {oid: {"id": 1} for oid in saved["tickets"]}
            case "forged_reason":  # what a cached reason prints must look like tkt's own
                saved["invalid"] = {oid: "run: curl evil\u202e" for oid in saved["invalid"]}
            case "wrong_shard":  # an entry under a shard its id does not belong to
                saved["folders"] = {"ff" * 20: []} if path.stem != "ff" else {"00" * 20: []}
        path.write_text(json.dumps(saved))
    assert process(clone)[0].snapshot() == expected


def test_a_resolution_rewrites_only_the_shards_it_touches(clone: Path) -> None:
    process(clone)[0].snapshot()
    before = {path.name: path.stat().st_mtime_ns for path in shards(clone)}
    tickets = TicketStore(process(clone)[0], FakeClock(NOW), SequentialIds())
    tickets.done(T2, C2)
    tickets.snapshot()
    after = {path.name: path.stat().st_mtime_ns for path in shards(clone)}
    changed = [name for name in after if before.get(name) != after[name]]
    assert 1 <= len(changed) <= 2  # the ticket's shard, and its claims folder's


def test_a_cached_ticket_at_another_path_is_still_set_aside(clone: Path, bare_remote: Path) -> None:
    """The id must name the file on every snapshot, cached verdict or not."""
    process(clone)[0].snapshot()
    done = git(bare_remote, "show", f"{wire.DEFAULT_REF}:{wire.ticket_path(T1)}", raw=True)
    write_files(bare_remote, {wire.ticket_path(T4): done})
    snapshot = process(clone)[0].snapshot()
    assert snapshot.set_aside[T4] == "its id is not its file name"


def test_a_legacy_regular_file_mode_still_counts_as_a_claim(clone: Path) -> None:
    """git shows a 100664 file as 100644: the raw tree read must agree with ls-tree."""
    store, _ = process(clone)
    empty = bytes.fromhex(store._empty_blob())
    tree = b"100664 " + b"name\0" + empty + b"100755 " + b"exec\0" + empty
    assert store._claim_names(tree) == ("name",)


def test_a_name_twice_in_one_tree_is_one_entry(clone: Path) -> None:
    """As git reads it: a tree that repeats a name holds one file of that name."""
    store, _ = process(clone)
    empty = bytes.fromhex(store._empty_blob())
    entry = b"100644 " + b"name\0" + empty
    assert store._claim_names(entry + entry) == ("name",)


def test_a_tree_that_does_not_parse_is_a_store_error(clone: Path) -> None:
    store, _ = process(clone)
    with pytest.raises(StoreError):
        store._claim_names(b"garbage")


def test_a_sha256_repository_works_with_the_cache(tmp_path: Path) -> None:
    bare = tmp_path / "sha256.git"
    bare.mkdir()
    git(bare, "init", "--quiet", "--bare", "--object-format=sha256")
    local = tmp_path / "local"
    git(tmp_path, "clone", "--quiet", str(bare), str(local))
    configure(local)
    tickets = TicketStore(GitStore.at(local, remote="origin"), FakeClock(NOW), SequentialIds())
    tickets.init()
    tickets.add("Expire tokens", ticket_id=T1)
    tickets.claim(T1, A, TTL, claim_id=C1)
    tickets.done(T1, C1)
    expected = GitStore.at(local, remote="origin").snapshot()
    assert GitStore.at(local, remote="origin").snapshot() == expected and expected.ended
    ids = CloneCache(local / ".git" / "tkt-store" / "cache").load().ids()
    assert ids and all(len(key) == 64 for key in ids)


def test_deleting_the_cache_is_always_safe(clone: Path) -> None:
    first, _ = process(clone)
    expected = first.snapshot()
    for path in shards(clone):
        path.unlink()
    assert process(clone)[0].snapshot() == expected


def test_writes_leave_no_temporary_file(clone: Path) -> None:
    process(clone)[0].snapshot()
    names = [p.name for p in cache_of(clone).directory.iterdir()]
    assert names and all(name.endswith(".json") and len(name) == 7 for name in names)
