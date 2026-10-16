"""How remote.publish classifies a failed push (docs/design.md §6), from canned
`git push --porcelain` output: a lost race is a Conflict (retried), anything else is a
StoreError (never retried)."""

from __future__ import annotations

import pytest

from tkt_store.application.errors import Conflict, StoreError
from tkt_store.domain.ticket import Revision
from tkt_store.infrastructure.git.remote import publish
from tkt_store.infrastructure.git.runner import GitError

REF = "refs/heads/tkt-store"
NEW, BASE = Revision("b" * 40), Revision("a" * 40)


class FailingPush:
    """A runner whose every command fails with the given porcelain stdout."""

    def __init__(self, stdout: str, stderr: str = "error: failed to push some refs") -> None:
        self.stdout, self.stderr = stdout.encode(), stderr
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str, stdin: bytes | None = None) -> bytes:
        self.calls.append(args)
        raise GitError(args, 1, self.stdout, self.stderr)


def status(flag_and_reason: str) -> str:
    return f"To origin\n!\t{NEW}:{REF}\t{flag_and_reason}\nDone\n"


@pytest.mark.parametrize(
    "reason",
    [
        "[rejected] (stale info)",
        "[rejected] (fetch first)",
        "[remote rejected] (incorrect old value provided)",
        # GitHub, observed in the ADR 0001 benchmark
        f"[remote rejected] (cannot lock ref '{REF}': is at {'c' * 40} but expected {BASE})",
    ],
)
def test_lost_race_is_conflict(reason: str) -> None:
    with pytest.raises(Conflict):
        publish(FailingPush(status(reason)), "origin", REF, NEW, BASE)


def test_failed_ref_update_with_a_moved_ref_on_the_remote_is_conflict() -> None:
    """git daemon / receive-pack over SSH: the generic status, the reason on stderr."""
    stderr = (
        f"remote: error: cannot lock ref '{REF}': is at {'c' * 40} but expected {BASE}\n"
        "error: failed to push some refs to 'git://host/tkt.git'"
    )
    with pytest.raises(Conflict):
        publish(FailingPush(status("[remote rejected] (failed to update ref)"), stderr),
                "origin", REF, NEW, BASE)  # fmt: skip


def test_failed_ref_update_for_another_reason_is_a_store_error() -> None:
    stderr = f"remote: error: cannot lock ref '{REF}': Unable to create '{REF}.lock': File exists"
    with pytest.raises(StoreError) as exc:
        publish(FailingPush(status("[remote rejected] (failed to update ref)"), stderr),
                "origin", REF, NEW, BASE)  # fmt: skip
    assert not isinstance(exc.value, Conflict)


@pytest.mark.parametrize(
    "reason",
    [
        "[remote rejected] (pre-receive hook declined)",
        "[remote rejected] (protected branch hook declined)",
        "[remote rejected] (failed to update ref)",
        f"[remote rejected] (cannot lock ref '{REF}': Unable to create '{REF}.lock': File exists)",
    ],
)
def test_other_rejections_are_store_errors_that_say_why(reason: str) -> None:
    with pytest.raises(StoreError, match=r"\(") as exc:
        publish(FailingPush(status(reason), "remote: no"), "origin", REF, NEW, BASE)
    assert not isinstance(exc.value, Conflict) and reason in str(exc.value)


def test_failure_without_status_is_the_git_error() -> None:
    with pytest.raises(GitError):
        publish(FailingPush("", "fatal: could not read from remote"), "origin", REF, NEW, BASE)


@pytest.mark.parametrize(("base", "lease"), [(BASE, f"{REF}:{BASE}"), (None, f"{REF}:")])
def test_push_states_the_expected_old_value(base: Revision | None, lease: str) -> None:
    runner = FailingPush(status("[rejected] (stale info)"))
    with pytest.raises(Conflict):
        publish(runner, "origin", REF, NEW, base)
    (push,) = runner.calls
    assert f"--force-with-lease={lease}" in push and push[-2:] == ("origin", f"{NEW}:{REF}")
