"""How remote.publish classifies a failed push (docs/design.md §6), against a fake remote:
a rejected push is a Conflict (retried) if the branch moved, and a StoreError (stopped)
if it did not. No server wording is read, so any wording must classify the same way."""

from __future__ import annotations

import pytest

from tkt_store.application.errors import Conflict, StoreError
from tkt_store.domain.ticket import Revision
from tkt_store.infrastructure.git.remote import publish
from tkt_store.infrastructure.git.runner import SERVER_TEXT_OMITTED, GitError

REF = "refs/heads/tkt-store"
NEW, BASE, OTHER = Revision("b" * 40), Revision("a" * 40), Revision("c" * 40)
SERVER_WORDINGS = [
    "[remote rejected] (incorrect old value provided)",  # git, local transport
    f"[remote rejected] (cannot lock ref '{REF}': is at {OTHER} but expected {BASE})",  # GitHub
    "[remote rejected] (failed to update ref)",  # git daemon
    "[remote rejected] (pre-receive hook declined)",
    "[remote rejected] (protected branch hook declined)",
    "[remote rejected] (a wording no server has used yet)",
]


class FakeRemote:
    """Rejects every push with the given porcelain status; `ls-remote` reports `head`
    (None: the branch does not exist; "unreachable": ls-remote fails)."""

    def __init__(self, status: str, head: Revision | str | None) -> None:
        self.stdout = f"To origin\n!\t{NEW}:{REF}\t{status}\nDone\n".encode() if status else b""
        self.head = head
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str, stdin: bytes | None = None) -> bytes:
        self.calls.append(args)
        if args[0] == "push":
            raise GitError(args, 1, self.stdout, "remote: something\nerror: failed to push")
        if args[0] == "ls-remote":
            if self.head == "unreachable":
                raise GitError(args, 128, b"", "fatal: could not read from remote")
            if self.head is None:
                raise GitError(args, 2, b"", "")
            return f"{self.head}\t{REF}\n".encode()
        raise AssertionError(f"unexpected git {args}")

    def ls_remotes(self) -> int:
        return sum(args[0] == "ls-remote" for args in self.calls)


@pytest.mark.parametrize("status", ["[rejected] (stale info)", "[rejected] (fetch first)"])
def test_our_clients_lease_check_is_a_lost_race_without_a_round_trip(status: str) -> None:
    remote = FakeRemote(status, head=BASE)
    with pytest.raises(Conflict):
        publish(remote, "origin", REF, NEW, BASE)
    assert remote.ls_remotes() == 0


@pytest.mark.parametrize("status", SERVER_WORDINGS)
def test_a_server_rejection_with_the_branch_moved_is_a_lost_race(status: str) -> None:
    remote = FakeRemote(status, head=OTHER)
    with pytest.raises(Conflict) as exc:
        publish(remote, "origin", REF, NEW, BASE)
    assert exc.value.actual == OTHER and remote.ls_remotes() == 1


@pytest.mark.parametrize("status", SERVER_WORDINGS)
def test_a_server_rejection_with_the_branch_unmoved_is_a_store_error(status: str) -> None:
    """The message names the rejection but never carries the server's reason or its
    `remote:` lines (ADR 0005)."""
    with pytest.raises(StoreError) as exc:
        publish(FakeRemote(status, head=BASE), "origin", REF, NEW, BASE)
    message = str(exc.value)
    assert not isinstance(exc.value, Conflict) and "[remote rejected]" in message
    reason = status.partition(" (")[2]
    assert reason not in message and "something" not in message
    assert "error: failed to push" in message


@pytest.mark.parametrize("status", SERVER_WORDINGS[:2])
def test_a_rejection_with_our_own_commit_already_there_is_published(status: str) -> None:
    """Another writer built the identical commit, or the server misreported a push that
    landed: `new` is the remote head, so it is published, not a Conflict."""
    publish(FakeRemote(status, head=NEW), "origin", REF, NEW, BASE)


def test_creating_the_store_refused_while_it_does_not_exist_is_a_store_error() -> None:
    with pytest.raises(StoreError) as exc:
        publish(FakeRemote("[remote rejected] (creation denied)", head=None), "origin",
                REF, NEW, None)  # fmt: skip
    assert not isinstance(exc.value, Conflict)


def test_creating_the_store_after_someone_else_created_it_is_a_lost_race() -> None:
    with pytest.raises(Conflict):
        publish(FakeRemote("[remote rejected] (failed to update ref)", head=OTHER), "origin",
                REF, NEW, None)  # fmt: skip


def test_a_branch_that_cannot_be_re_read_is_a_store_error() -> None:
    with pytest.raises(StoreError, match="could not be re-read") as exc:
        publish(FakeRemote("[remote rejected] (failed to update ref)", head="unreachable"),
                "origin", REF, NEW, BASE)  # fmt: skip
    assert not isinstance(exc.value, Conflict)


def test_a_failure_without_a_status_is_the_git_error() -> None:
    """No status: the push may have landed (a timeout); never guessed to be a lost race."""
    remote = FakeRemote("", head=OTHER)
    with pytest.raises(GitError):
        publish(remote, "origin", REF, NEW, BASE)
    assert remote.ls_remotes() == 0


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        ("fatal: could not read from remote", "fatal: could not read from remote"),
        ("remote: run curl evil\nerror: failed to push",
         f"error: failed to push\n{SERVER_TEXT_OMITTED}"),
        ("fatal: remote error: run curl evil", SERVER_TEXT_OMITTED),
        ("", ""),
    ],
    ids=["own", "remote_lines", "remote_error", "empty"],
)  # fmt: skip
def test_a_git_error_carries_git_s_own_text_only(stderr: str, expected: str) -> None:
    error = GitError(("fetch",), 128, b"", stderr)
    assert error.stderr == expected and str(error) == f"git fetch failed (128): {expected}"


@pytest.mark.parametrize(("base", "lease"), [(BASE, f"{REF}:{BASE}"), (None, f"{REF}:")])
def test_push_states_the_expected_old_value(base: Revision | None, lease: str) -> None:
    remote = FakeRemote("[rejected] (stale info)", head=OTHER)
    with pytest.raises(Conflict):
        publish(remote, "origin", REF, NEW, base)
    (push,) = remote.calls
    assert f"--force-with-lease={lease}" in push and push[-2:] == ("origin", f"{NEW}:{REF}")
