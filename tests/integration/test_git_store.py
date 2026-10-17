"""Real git: behaviour specific to the git adapter (format marker, file layout, the local
cache, the remote). Shared Store semantics live in tests/contract/.

Edits "by hand" are commits made directly on the bare remote, the store's truth."""

from __future__ import annotations

import inspect
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.gitkit import HookedRunner, git, head, write_files
from tkt_store import open_store
from tkt_store.application.errors import Conflict, StoreError
from tkt_store.application.service import TicketStore
from tkt_store.application.transaction import Committed, Refused
from tkt_store.domain.operations import OpName
from tkt_store.domain.outcomes import OpRecord, RefusalCode, WriteTicket
from tkt_store.domain.ticket import (
    AgentId,
    ClaimId,
    Phase,
    Revision,
    Ticket,
    TicketId,
    claim_hash,
)
from tkt_store.infrastructure.clock import FakeClock
from tkt_store.infrastructure.git import remote as sync
from tkt_store.infrastructure.git import wire
from tkt_store.infrastructure.git.repo import GitStore
from tkt_store.infrastructure.git.runner import GitError, git_runner
from tkt_store.infrastructure.ids import SequentialIds

NOW = 1_000_000
TTL = 1800
A = AgentId("coder-7")
C1 = ClaimId("1" * 32)
C2 = ClaimId("2" * 32)
T1 = TicketId("tkt-0001")
T2 = TicketId("tkt-0002")

REF = wire.DEFAULT_REF

pytestmark = pytest.mark.git


def show(repo: Path, path: str, ref: str = REF) -> bytes:
    """The content of `path` at `ref`, as bytes."""
    return git(repo, "show", f"{ref}:{path}", raw=True)


def paths(repo: Path, ref: str = REF) -> set[str]:
    """Every file path at `ref`."""
    return set(git(repo, "ls-tree", "-r", "--name-only", ref).split())


def tkt(ticket_id: TicketId, **fields: Any) -> Ticket:
    """A plain open ticket; `fields` override."""
    base = Ticket(
        id=ticket_id, title="Expire tokens", created=0, updated=0, phase=Phase.IMPLEMENTATION
    )
    return replace(base, **fields)


def service(store: GitStore) -> TicketStore:
    return TicketStore(store, FakeClock(NOW), SequentialIds())


@pytest.fixture
def local(clones: list[Path]) -> Path:
    """A clone of an initialised store holding one ticket."""
    tickets = service(GitStore.at(clones[0], remote="origin"))
    tickets.init()
    tickets.add("Expire tokens", ticket_id=T1)
    return clones[0]


def opened(clone: Path) -> GitStore:
    return GitStore.at(clone, remote="origin")


def test_init_writes_store_meta(clones: list[Path], bare_remote: Path) -> None:
    """The root commit contains tkt-store.json = {"protocol": 2}."""
    service(opened(clones[0])).init()
    assert json.loads(show(bare_remote, "tkt-store.json")) == {"protocol": 2}
    assert git(bare_remote, "rev-list", "--count", REF).strip() == "1"


def test_any_other_store_meta_is_refused(local: Path, bare_remote: Path) -> None:
    write_files(bare_remote, {"tkt-store.json": b'{"future": true, "protocol": 2}'})
    with pytest.raises(StoreError, match=r"tkt-store\.json"):
        opened(local).snapshot()


def test_remote_store_publishes_and_other_clones_see_it(
    clones: list[Path], bare_remote: Path
) -> None:
    a, b = (service(GitStore.at(c, remote="origin")) for c in clones)
    a.init()
    a.add("Expire tokens", ticket_id=T1)
    assert head(bare_remote) == head(clones[0])
    view = b.view(T1)
    assert view is not None and view.ticket.title == "Expire tokens"
    assert head(clones[1]) == head(bare_remote)  # the reader's cache was brought up


def test_publish_uses_force_with_lease_on_base(clones: list[Path]) -> None:
    """The push carries --force-with-lease=<ref>:<base>; a moved remote → Conflict."""
    runner = HookedRunner(clones[0])
    store = GitStore(runner, remote="origin")
    base = store.commit(None, (), OpRecord(OpName.INIT, at=NOW))
    store.commit(base, (WriteTicket(tkt(T1)),), OpRecord(OpName.ADD, at=NOW, ticket_ids=(T1,)))
    pushes = [args for args in runner.calls if args[0] == "push"]
    assert f"--force-with-lease={REF}:" in pushes[0]
    assert f"--force-with-lease={REF}:{base}" in pushes[1]
    other = GitStore.at(clones[1], remote="origin")
    other.commit(
        other.snapshot().revision,
        (WriteTicket(tkt(T2)),),
        OpRecord(OpName.ADD, at=NOW, ticket_ids=(T2,)),
    )
    with pytest.raises(Conflict):
        store.commit(base, (), OpRecord(OpName.REAP, at=NOW, ticket_ids=(T1,)))


@pytest.mark.parametrize("meta", ["missing", "newer", "malformed"])
def test_snapshot_rejects_bad_store_meta(meta: str, local: Path, bare_remote: Path) -> None:
    """→ StoreError on every snapshot, never a silent misread."""
    data = {"missing": None, "newer": b'{"protocol": 99}', "malformed": b"{"}
    write_files(bare_remote, {"tkt-store.json": data[meta]})
    store = opened(local)
    for _ in range(2):
        with pytest.raises(StoreError):
            store.snapshot()


def test_stray_files_are_ignored_and_preserved(local: Path, bare_remote: Path) -> None:
    """tickets/README.md, tickets/foo.json, and root files are never decoded and survive
    later commits."""
    stray = {
        "tickets/README.md": b"# notes\n",
        "tickets/foo.json": b"not a ticket",
        "tickets/sub/tkt-0009.json": b"nested",
        "NOTES.txt": b"root file\n",
    }
    write_files(bare_remote, stray)
    tickets = service(opened(local))
    tickets.add("Second", ticket_id=T2)
    assert [v.ticket.id for v in tickets.list()] == [T1, T2]
    assert paths(bare_remote) >= {
        *stray,
        "tkt-store.json",
        wire.ticket_path(T1),
        wire.ticket_path(T2),
    }
    assert all(show(bare_remote, path) == data for path, data in stray.items())


def test_foreign_commits_are_skipped_by_history(local: Path, bare_remote: Path) -> None:
    write_files(bare_remote, {"NOTES.txt": b"x"}, message="Add notes by hand\n")
    tickets = service(opened(local))
    assert [e.record.op for e in tickets.log()] == [OpName.ADD, OpName.INIT]


def test_a_file_named_for_another_id_is_set_aside(local: Path, bare_remote: Path) -> None:
    """tickets/tkt-0002.json whose id is tkt-0003: set aside, never read as either."""
    write_files(bare_remote, {wire.ticket_path(T2): wire.encode_ticket(tkt(TicketId("tkt-0003")))})
    snapshot = opened(local).snapshot()
    assert snapshot.set_aside == {T2: "its id is not its file name"}
    assert snapshot.get(T1) is not None and snapshot.get(TicketId("tkt-0003")) is None


@pytest.mark.parametrize(
    ("content", "mode", "why"),
    [
        (b'{"id": "tkt-0002"', None, "not JSON"),
        (b"{}", "100755", "not a regular file"),
        (b"x" * (256 * 1024 + 1), None, "larger than 256 KiB"),
    ],
    ids=["corrupt", "executable", "oversized"],
)
def test_a_bad_ticket_file_is_set_aside_not_fatal(
    local: Path, bare_remote: Path, content: bytes, mode: str | None, why: str
) -> None:
    path = wire.ticket_path(T2)
    write_files(bare_remote, {path: content}, modes={path: mode} if mode else {})
    snapshot = opened(local).snapshot()
    assert snapshot.set_aside == {T2: why} and snapshot.get(T1) is not None


def test_a_directory_at_a_ticket_path_is_set_aside(local: Path, bare_remote: Path) -> None:
    write_files(bare_remote, {f"{wire.ticket_path(T2)}/inner": b"x"})
    snapshot = opened(local).snapshot()
    assert snapshot.set_aside == {T2: "not a regular file"} and snapshot.get(T1) is not None


def test_add_does_not_remint_when_only_a_blocker_is_set_aside(
    clones: list[Path], bare_remote: Path
) -> None:
    """A fresh id would not help: refused SET_ASIDE once, without minting again."""
    ids = SequentialIds()
    tickets = TicketStore(GitStore.at(clones[0], remote="origin"), FakeClock(NOW), ids)
    tickets.init()
    write_files(bare_remote, {wire.ticket_path(T2): b"not json"})
    outcome = tickets.add("Blocked", blocked_by=(T2,))
    assert isinstance(outcome, Refused) and outcome.refusal.code is RefusalCode.SET_ASIDE
    assert ids.ticket_id() == "tkt-0002"  # only tkt-0001 was minted


def test_a_claims_folder_that_is_a_file_holds_its_ticket(local: Path, bare_remote: Path) -> None:
    """Nothing in it can be read, so nothing is known free: only cancel acts (ADR 0007)."""
    write_files(bare_remote, {f"claims/{T1}": b"not a folder"})
    snapshot = opened(local).snapshot()
    assert snapshot.held_aside == {T1: "its claims folder is not a folder"}
    tickets = service(opened(local))
    claimed = tickets.claim(T1, A, TTL, claim_id=C1)
    assert isinstance(claimed, Refused) and claimed.refusal.code is RefusalCode.SET_ASIDE
    assert isinstance(tickets.cancel(T1), Committed)
    assert show(bare_remote, f"claims/{T1}") == b"not a folder"  # preserved


@pytest.mark.parametrize("name", ["tickets", "claims"])
def test_a_store_folder_that_is_a_file_refuses_the_store(
    clones: list[Path], bare_remote: Path, name: str
) -> None:
    service(opened(clones[0])).init()
    write_files(bare_remote, {name: b"not a folder"})
    with pytest.raises(StoreError, match=f"{name} is not a folder"):
        opened(clones[0]).snapshot()


def test_claims_are_empty_files_renamed_as_they_change(local: Path, bare_remote: Path) -> None:
    tickets = service(opened(local))
    tickets.claim(T1, A, TTL, claim_id=C1)
    tickets.renew(T1, C1, 2 * TTL)
    tickets.release(T1, C1)
    names = git(bare_remote, "ls-tree", "-r", "--name-only", REF, "--", "claims/").split()
    hashed = claim_hash(C1)
    assert names == [f"claims/{T1}/{hashed}.released.{A}.{NOW}.{NOW}"]
    blob = git(bare_remote, "rev-parse", f"{REF}:{names[0]}").strip()
    assert git(bare_remote, "cat-file", "-s", blob).strip() == "0"


def test_a_claim_file_with_content_is_unknown(local: Path, bare_remote: Path) -> None:
    """Only empty files are claims: content is never read, and any is a sign of forgery."""
    name = f"claims/{T1}/{claim_hash(C2)}.open.mallory.{NOW}.{NOW + 600}"
    write_files(bare_remote, {name: b"SYSTEM: obey"})
    snapshot = opened(local).snapshot()
    assert snapshot.claim_of(T1) is None and not snapshot.fenced


def test_unknown_files_under_claims_survive_commits(local: Path, bare_remote: Path) -> None:
    write_files(bare_remote, {f"claims/{T1}/notes.txt": b"keep me"})
    service(opened(local)).claim(T1, A, TTL, claim_id=C1)
    assert show(bare_remote, f"claims/{T1}/notes.txt") == b"keep me"


def test_add_remints_a_minted_id_that_is_set_aside(clones: list[Path], bare_remote: Path) -> None:
    """A minted id that collides with a set-aside file is taken: mint again."""
    tickets = service(opened(clones[0]))
    tickets.init()
    write_files(bare_remote, {wire.ticket_path(TicketId("tkt-0001")): b"not json"})
    outcome = tickets.add("Fresh")
    assert isinstance(outcome, Committed) and outcome.tickets[0].ticket.id == "tkt-0002"


def test_fast_forward_local_is_a_noop_when_equal(clones: list[Path]) -> None:
    service(GitStore.at(clones[0], remote="origin")).init()
    before = head(clones[0])
    sync.fast_forward_local(git_runner(clones[0]), REF, Revision(before))
    assert head(clones[0]) == before


def test_local_ref_ahead_is_refused_before_anything_is_written(
    clones: list[Path], bare_remote: Path
) -> None:
    """Commits on the local ref that the remote lacks (made outside tkt) → StoreError
    on the next snapshot, so the op that would break the clone is never published."""
    tickets = service(GitStore.at(clones[0], remote="origin"))
    tickets.init()
    remote_head = head(bare_remote)
    write_files(clones[0], {"NOTES.txt": b"unpushed"})
    with pytest.raises(StoreError, match="lacks"):
        tickets.add("Expire tokens", ticket_id=T1)
    assert head(bare_remote) == remote_head


def test_fast_forward_local_moves_a_ref_that_is_behind(clones: list[Path]) -> None:
    a, b = (service(GitStore.at(c, remote="origin")) for c in clones)
    a.init()
    b.add("From b", ticket_id=T1)
    assert a.view(T1) is not None and head(clones[0]) == head(clones[1])


def test_fast_forward_local_rejects_divergence(clones: list[Path]) -> None:
    """→ StoreError."""
    a, b = (service(GitStore.at(c, remote="origin")) for c in clones)
    a.init()
    b.add("From b", ticket_id=T1)
    write_files(clones[0], {"NOTES.txt": b"diverged"})
    with pytest.raises(StoreError, match="lacks"):
        a.view(T1)


def test_unreachable_remote_is_store_error(clones: list[Path]) -> None:
    with pytest.raises(StoreError):
        GitStore.at(clones[0], remote="no-such-remote").snapshot()


def test_rejection_by_a_remote_hook_is_store_error_not_conflict(
    clones: list[Path], bare_remote: Path
) -> None:
    """A hook or branch protection declining the push is not a lost race: StoreError,
    never retried as a Conflict. The hook's text is the server's, so it is left out."""
    tickets = service(GitStore.at(clones[0], remote="origin"))
    tickets.init()
    hook = bare_remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho protected >&2\nexit 1\n")
    hook.chmod(0o755)
    with pytest.raises(StoreError, match=r"refused by the server.*did not move") as exc:
        tickets.add("Expire tokens", ticket_id=T1)
    assert not isinstance(exc.value.__cause__, Conflict)
    assert "protected" not in str(exc.value) and "hook declined" not in str(exc.value)


def test_non_utf8_file_names_are_preserved(local: Path, bare_remote: Path) -> None:
    """git allows any bytes in a file name; tkt neither decodes nor drops them."""
    name = b"notes-\xff.txt"
    write_files(bare_remote, {name: b"latin"})
    write_files(bare_remote, {b"tickets/" + name: b"also"})
    tickets = service(opened(local))
    tickets.add("Second", ticket_id=T2)
    assert [v.ticket.id for v in tickets.list()] == [T1, T2]
    listing = git(bare_remote, "ls-tree", "-r", "-z", "--name-only", REF, raw=True).split(b"\0")
    assert {name, b"tickets/" + name} <= set(listing)


class CannedCatFile:
    """A real runner whose `cat-file --batch` answers with canned output."""

    def __init__(self, repo: Path, output: bytes) -> None:
        self._run, self._output = git_runner(repo), output

    def __call__(self, *args: str, stdin: bytes | None = None) -> bytes:
        if args[:2] == ("cat-file", "--batch"):
            return self._output
        return self._run(*args, stdin=stdin)


@pytest.mark.parametrize(
    "output", [b"0123 missing\n", b"", b"0123 blob x\n", b"0123 tree 4\nxxxx\n"]
)
def test_unexpected_cat_file_output_is_store_error(output: bytes, local: Path) -> None:
    with pytest.raises(StoreError, match="cannot read blob"):
        GitStore(CannedCatFile(local, output), remote="origin").snapshot()


def test_remote_is_required_for_git_store() -> None:
    """GitStore/GitStore.at take `remote` with no default; open_store defaults to origin."""
    for constructor in (GitStore.__init__, GitStore.at):
        remote = inspect.signature(constructor).parameters["remote"]
        assert remote.default is inspect.Parameter.empty
        assert remote.kind is inspect.Parameter.KEYWORD_ONLY
    assert inspect.signature(open_store).parameters["remote"].default == "origin"


def test_non_ascii_title_round_trips(local: Path) -> None:
    """cat-file --batch sizes are bytes: a non-ASCII title is decoded correctly."""
    tickets = service(opened(local))
    tickets.add("Ünïcödé — 日本語 ✓", ticket_id=T2)
    tickets.add("After", ticket_id=TicketId("tkt-0003"))
    view = tickets.view(T2)
    assert view is not None and view.ticket.title == "Ünïcödé — 日本語 ✓"
    assert [v.ticket.title for v in tickets.list()][-1] == "After"


def test_committed_revision_is_the_ref(local: Path, bare_remote: Path) -> None:
    outcome = service(opened(local)).add("Second", ticket_id=T2)
    assert isinstance(outcome, Committed) and outcome.revision == head(bare_remote)


def blobs_read(runner: HookedRunner) -> list[int]:
    """How many blobs each `cat-file --batch` was asked for."""
    return [len(data.split()) for data in runner.inputs_to("cat-file", "--batch")]


def test_snapshots_read_only_ticket_files_they_have_not_seen(
    local: Path, bare_remote: Path
) -> None:
    """Decoded tickets are cached by blob id: unchanged files are not read again, and
    tickets this store just wrote are not read back."""
    runner = HookedRunner(local)
    store = GitStore(runner, remote="origin")
    tickets = TicketStore(store, FakeClock(NOW), SequentialIds())
    tickets.add("Second", ticket_id=T2)  # snapshot reads T1; the commit writes T2
    assert blobs_read(runner) == [1]
    assert {v.ticket.id for v in tickets.list()} == {T1, T2}
    assert blobs_read(runner) == [1]  # T2 came from the commit, T1 from the cache
    write_files(bare_remote, {wire.ticket_path(T1): wire.encode_ticket(tkt(T1, title="Edited"))})
    view = tickets.view(T1)
    assert view is not None and view.ticket.title == "Edited"
    assert blobs_read(runner) == [1, 1]  # only the changed file


def test_a_cached_store_sees_the_same_tickets_as_a_fresh_one(
    local: Path, bare_remote: Path
) -> None:
    cached = TicketStore(opened(local), FakeClock(NOW), SequentialIds())
    for n in range(3, 6):
        cached.add(f"Ticket {n}", ticket_id=TicketId(f"tkt-{n:04}"))
    cached.claim(T1, A, TTL, claim_id=C1)
    write_files(bare_remote, {wire.ticket_path(T2): wire.encode_ticket(tkt(T2, title="By hand"))})
    fresh = opened(local).snapshot()
    assert cached.view(T1) is not None
    assert opened(local).snapshot() == fresh
    assert {v.ticket.id: v.ticket for v in cached.list()} == dict(fresh.tickets)


def test_every_commit_runs_gc_auto(local: Path) -> None:
    """Plumbing never triggers git's housekeeping, so the store runs `gc --auto` after each
    commit. (Whether it packs is git's decision: it estimates loose objects by sampling, so
    a test-sized store would not reliably cross the threshold.)"""
    runner = HookedRunner(local)
    tickets = TicketStore(GitStore(runner, remote="origin"), FakeClock(NOW), SequentialIds())
    for n in range(2, 5):
        tickets.add(f"Ticket {n}", ticket_id=TicketId(f"tkt-{n:04}"))
    tickets.view(T1)  # reads never run it
    assert runner.count("gc") == 3


def test_a_failing_gc_does_not_fail_the_commit(local: Path) -> None:
    def broken_gc(args: tuple[str, ...]) -> None:
        if args[0] == "gc":
            raise GitError(args, 128, b"", "fatal: gc is broken")

    store = GitStore(HookedRunner(local, broken_gc), remote="origin")
    outcome = TicketStore(store, FakeClock(NOW), SequentialIds()).add("Second", ticket_id=T2)
    assert isinstance(outcome, Committed)


def test_a_server_side_lost_race_is_retried_on_real_git(
    clones: list[Path], bare_remote: Path
) -> None:
    """The server's own compare-and-swap loses (an `update` hook moves the branch while our
    push is being received, once): the push is rejected, one `ls-remote` sees the branch
    moved, and the transaction retries and commits."""
    tickets = service(opened(clones[0]))
    tickets.init()
    tickets.add("Expire tokens", ticket_id=T1)
    hook = bare_remote / "hooks" / "update"
    hook.write_text(
        "#!/bin/sh\n"
        '[ -e "$GIT_DIR/moved" ] && exit 0\n'
        'touch "$GIT_DIR/moved"\n'
        'tree=$(git rev-parse "$1^{tree}")\n'
        'other=$(git -c user.name=other -c user.email=other@invalid commit-tree "$tree" '
        '-p "$2" -m "another writer")\n'
        'git update-ref "$1" "$other" "$2"\n'
    )
    hook.chmod(0o755)
    runner = HookedRunner(clones[0])
    outcome = service(GitStore(runner, remote="origin")).add("Second", ticket_id=T2)
    assert isinstance(outcome, Committed) and (bare_remote / "moved").exists()
    assert [args[0] for args in runner.calls].count("ls-remote") == 1
    assert {t.id for t in opened(clones[1]).snapshot().tickets.values()} == {T1, T2}
