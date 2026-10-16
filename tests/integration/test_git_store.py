"""Real git: behaviour specific to the git adapter (format marker, file layout, the local
cache, local-only mode). Shared Store semantics live in tests/contract/."""

from __future__ import annotations

import inspect
import json
import subprocess
from pathlib import Path

import pytest

from tests.gitkit import HookedRunner, git, head, new_repo, paths, show, write_files
from tests.unit.builders import NOW, T1, T2, tkt
from tkt_store import open_store
from tkt_store.application.errors import Conflict, StoreError
from tkt_store.application.service import TicketStore
from tkt_store.application.transaction import Committed
from tkt_store.domain.operations import OpName
from tkt_store.domain.outcomes import OpRecord, WriteTicket
from tkt_store.domain.ticket import Revision, TicketId
from tkt_store.infrastructure.clock import FakeClock
from tkt_store.infrastructure.git import remote as sync
from tkt_store.infrastructure.git import wire
from tkt_store.infrastructure.git.repo import GitStore
from tkt_store.infrastructure.git.runner import git_runner
from tkt_store.infrastructure.ids import SequentialIds

pytestmark = pytest.mark.git

REF = wire.DEFAULT_REF


def service(store: GitStore) -> TicketStore:
    return TicketStore(store, FakeClock(NOW), SequentialIds())


@pytest.fixture
def local(tmp_path: Path) -> Path:
    """A local-only store, initialised, with one ticket."""
    repo = new_repo(tmp_path / "local")
    tickets = service(GitStore.at(repo, remote=None))
    tickets.init()
    tickets.add("Expire tokens", ticket_id=T1)
    return repo


@pytest.mark.parametrize("mode", ["remote", "local"])
def test_init_writes_store_meta(mode: str, clones: list[Path]) -> None:
    """The root commit contains tkt-store.json = {"mode": mode, "protocol": 1}."""
    repo = clones[0]
    service(GitStore.at(repo, remote="origin" if mode == "remote" else None)).init()
    assert json.loads(show(repo, "tkt-store.json")) == {"mode": mode, "protocol": 1}
    assert git(repo, "rev-list", "--count", REF).strip() == "1"


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


@pytest.mark.parametrize("opened_as", ["local_on_remote_store", "remote_on_local_store"])
def test_opening_in_the_other_mode_is_refused(
    opened_as: str, clones: list[Path], bare_remote: Path
) -> None:
    """A store opened in the mode it was not created with → StoreError, nothing written,
    so a stray --no-remote can never diverge a clone."""
    repo = clones[0]
    if opened_as == "local_on_remote_store":
        service(GitStore.at(repo, remote="origin")).init()
        wrong = GitStore.at(repo, remote=None)
    else:
        service(GitStore.at(repo, remote=None)).init()
        git(repo, "push", "--quiet", "origin", REF)
        wrong = GitStore.at(repo, remote="origin")
    before = head(repo), head(bare_remote)
    with pytest.raises(StoreError, match="cannot be opened"):
        service(wrong).add("Expire tokens", ticket_id=T1)
    assert (head(repo), head(bare_remote)) == before


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
def test_snapshot_rejects_bad_store_meta(meta: str, local: Path) -> None:
    """→ StoreError on every snapshot, never a silent misread."""
    data = {"missing": None, "newer": b'{"mode": "local", "protocol": 99}', "malformed": b"{"}
    write_files(local, {"tkt-store.json": data[meta]})
    store = GitStore.at(local, remote=None)
    for _ in range(2):
        with pytest.raises(StoreError):
            store.snapshot()


def test_stray_files_are_ignored_and_preserved(local: Path) -> None:
    """tickets/README.md, tickets/foo.json, and root files are never decoded and survive
    later commits."""
    stray = {
        "tickets/README.md": b"# notes\n",
        "tickets/foo.json": b"not a ticket",
        "tickets/sub/tkt-9.json": b"nested",
        "NOTES.txt": b"root file\n",
    }
    write_files(local, stray)
    tickets = service(GitStore.at(local, remote=None))
    tickets.add("Second", ticket_id=T2)
    assert [v.ticket.id for v in tickets.list()] == [T1, T2]
    assert paths(local) >= {*stray, "tkt-store.json", wire.ticket_path(T1), wire.ticket_path(T2)}
    assert all(show(local, path) == data for path, data in stray.items())


def test_foreign_commits_are_skipped_by_history(local: Path) -> None:
    write_files(local, {"NOTES.txt": b"x"}, message="Add notes by hand\n")
    tickets = service(GitStore.at(local, remote=None))
    assert [e.record.op for e in tickets.log()] == [OpName.ADD, OpName.INIT]


def test_filename_must_match_id(local: Path) -> None:
    """tickets/tkt-0001.json whose id is tkt-0002 → StoreError."""
    write_files(local, {"tickets/tkt-0001.json": wire.encode_ticket(tkt(TicketId("tkt-0002")))})
    with pytest.raises(StoreError, match="tkt-0001"):
        GitStore.at(local, remote=None).snapshot()


def test_corrupt_ticket_fails_the_whole_snapshot(local: Path) -> None:
    write_files(local, {wire.ticket_path(T2): b'{"id": "tkt-2"'})
    with pytest.raises(StoreError, match=wire.ticket_path(T2)):
        GitStore.at(local, remote=None).snapshot()


def test_local_only_stale_base_is_conflict(local: Path) -> None:
    """remote=None: update-ref is the compare-and-swap; a moved ref → Conflict."""
    store = GitStore.at(local, remote=None)
    stale = store.snapshot().revision
    moved = write_files(local, {"NOTES.txt": b"x"})
    with pytest.raises(Conflict) as exc:
        store.commit(stale, (WriteTicket(tkt(T2)),), OpRecord(OpName.ADD, at=NOW, ticket_ids=(T2,)))
    assert exc.value.actual == moved and head(local) == moved


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
    never retried as a Conflict."""
    tickets = service(GitStore.at(clones[0], remote="origin"))
    tickets.init()
    hook = bare_remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho protected >&2\nexit 1\n")
    hook.chmod(0o755)
    with pytest.raises(StoreError, match=r"\[remote rejected\].*protected") as exc:
        tickets.add("Expire tokens", ticket_id=T1)
    assert not isinstance(exc.value.__cause__, Conflict)


def test_non_utf8_file_names_are_preserved(local: Path) -> None:
    """git allows any bytes in a file name; tkt neither decodes nor drops them."""
    name = b"notes-\xff.txt"
    write_files(local, {name: b"latin"})
    write_files(local, {b"tickets/" + name: b"also"})
    tickets = service(GitStore.at(local, remote=None))
    tickets.add("Second", ticket_id=T2)
    assert [v.ticket.id for v in tickets.list()] == [T1, T2]
    listing = subprocess.run(
        ["git", "-C", str(local), "ls-tree", "-r", "-z", "--name-only", REF],
        capture_output=True, check=True,
    ).stdout.split(b"\0")  # fmt: skip
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
        GitStore(CannedCatFile(local, output), remote=None).snapshot()


def test_remote_is_required_for_git_store() -> None:
    """GitStore/GitStore.at take `remote` with no default; open_store defaults to origin."""
    for constructor in (GitStore.__init__, GitStore.at):
        remote = inspect.signature(constructor).parameters["remote"]
        assert remote.default is inspect.Parameter.empty
        assert remote.kind is inspect.Parameter.KEYWORD_ONLY
    assert inspect.signature(open_store).parameters["remote"].default == "origin"


def test_non_ascii_title_round_trips(local: Path) -> None:
    """cat-file --batch sizes are bytes: a non-ASCII title is decoded correctly."""
    tickets = service(GitStore.at(local, remote=None))
    tickets.add("Ünïcödé — 日本語 ✓", ticket_id=T2)
    tickets.add("After", ticket_id=TicketId("tkt-3"))
    view = tickets.view(T2)
    assert view is not None and view.ticket.title == "Ünïcödé — 日本語 ✓"
    assert [v.ticket.title for v in tickets.list()][-1] == "After"


def test_committed_revision_is_the_ref(local: Path) -> None:
    outcome = service(GitStore.at(local, remote=None)).add("Second", ticket_id=T2)
    assert isinstance(outcome, Committed) and outcome.revision == head(local)
