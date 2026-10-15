"""Remote synchronisation for a remote-backed git store.

The remote is authoritative; local refs are a cache (design.md §6). Everything
here goes through a GitRunner, so nothing in this module touches the git binary
directly. One process per clone is assumed (design.md §7).
"""

from __future__ import annotations

from tkt_store.application.errors import Conflict, StoreError
from tkt_store.domain.ticket import Revision
from tkt_store.infrastructure.git.runner import GitError, GitRunner

NO_SUCH_REF = 2
"""`git ls-remote --exit-code` status when the remote has no matching ref."""


def fetched_ref(remote: str, ref: str) -> str:
    """The private ref a fetch writes the remote head to. Only this module writes it,
    so it never disturbs the user's remote-tracking branches."""
    return f"refs/tkt-store-remotes/{remote}/{ref.removeprefix('refs/')}"


def fetch(git: GitRunner, remote: str, ref: str) -> Revision | None:
    """Fetch `ref` from `remote`; return the remote head (None if the ref does not exist).
    The returned revision is the snapshot's revision: read it from the fetch result, not
    from FETCH_HEAD or the local ref."""
    try:
        out = git(
            "fetch", "--porcelain", "--verbose", "--no-tags", "--no-write-fetch-head",
            remote, f"+{ref}:{fetched_ref(remote, ref)}",
        )  # fmt: skip
    except GitError:
        if not _remote_lacks(git, remote, ref):
            raise
        return None
    # one line per ref, up to date ones too (--verbose): "<flag> <old> <new> <local-ref>",
    # where the flag is one character and may itself be a space (a fast-forward)
    for line in out.decode().splitlines():
        _old, new, local = line[2:].split(" ", 2)
        if local == fetched_ref(remote, ref):
            return Revision(new)
    raise StoreError(f"git fetch {remote} {ref} did not report the fetched head")


def _remote_lacks(git: GitRunner, remote: str, ref: str) -> bool:
    """After a failed fetch: True only if the remote is reachable and has no `ref`."""
    try:
        git("ls-remote", "--exit-code", remote, ref)
    except GitError as error:
        return error.returncode == NO_SUCH_REF
    return False


def local_head(git: GitRunner, ref: str) -> Revision | None:
    """The commit `ref` points to in this repository, or None if it does not exist."""
    try:
        return Revision(
            git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").decode().strip()
        )
    except GitError as error:
        if error.returncode == 1:
            return None
        raise


def is_ancestor(git: GitRunner, ancestor: Revision, descendant: Revision) -> bool:
    try:
        git("merge-base", "--is-ancestor", ancestor, descendant)
    except GitError as error:
        if error.returncode == 1:
            return False
        raise
    return True


def fast_forward_local(git: GitRunner, ref: str, remote_head: Revision) -> None:
    """Bring the local ref (a cache of the remote) up to `remote_head`.

    - local equal to, or a descendant of, `remote_head` -> no-op;
    - local behind (crash between push and local update, or other writers' commits)
      -> move it with a compare-and-swap `update-ref <ref> <remote_head> <observed-local>`;
    - diverged -> StoreError.
    """
    local = local_head(git, ref)
    if local == remote_head:
        return
    if local is not None and is_ancestor(git, remote_head, local):
        return
    if local is not None and not is_ancestor(git, local, remote_head):
        raise StoreError(
            f"local {ref} ({local}) has diverged from the remote ({remote_head}); "
            "the remote is authoritative: reset the local ref to it"
        )
    git("update-ref", ref, remote_head, local or "")


def publish(git: GitRunner, remote: str, ref: str, new: Revision, base: Revision | None) -> None:
    """Push `new` to `remote` `ref` with `--force-with-lease=<ref>:<base>` (an empty
    expected value when `base` is None), so the push itself states the expected old value:
    it lands only if the remote ref is still `base`. Never a plain force-push.
    A rejected lease or non-fast-forward raises Conflict (nothing published). Any other
    failure is a StoreError, which may hide a push that landed."""
    try:
        git(
            "push", "--porcelain", f"--force-with-lease={ref}:{base or ''}",
            remote, f"{new}:{ref}",
        )  # fmt: skip
    except GitError as error:
        status = [line for line in error.stdout.decode().splitlines() if line.startswith("!")]
        if any(_lost_race(line) for line in status):
            raise Conflict(base, None) from error
        raise


LOST_RACE = ("\t[rejected]", "(incorrect old value provided)")
"""Porcelain push status that proves nothing was published because the ref moved:
the client-side lease check ("!\t<src>:<dst>\t[rejected] (stale info)") or the remote's
own compare-and-swap losing a concurrent update ("[remote rejected] (incorrect old value
provided)"). Any other "[remote rejected]" (a hook, branch protection) stays a StoreError."""


def _lost_race(line: str) -> bool:
    return any(marker in line for marker in LOST_RACE)
