"""Remote synchronisation for the git store.

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
    """The private ref a fetch writes the remote head to. Only this module writes it, so
    it holds exactly what tkt's last fetch brought in. (git may also update the matching
    remote-tracking branch, e.g. refs/remotes/origin/tkt-store, as on any fetch.)"""
    return f"refs/tkt-store-remotes/{remote}/{ref.removeprefix('refs/')}"


def fetch(git: GitRunner, remote: str, ref: str) -> Revision | None:
    """Fetch `ref` from `remote`; return the remote head (None if the ref does not exist).
    The returned revision is the snapshot's revision. It is read from the private ref
    the fetch just wrote, never from FETCH_HEAD or the local ref: only this module writes
    the private ref, and one process per clone is assumed (design.md §7), so it holds
    exactly what this fetch brought in."""
    try:
        git("fetch", "--no-tags", "--no-write-fetch-head", remote,
            f"+{ref}:{fetched_ref(remote, ref)}")  # fmt: skip
    except GitError:
        if not _remote_lacks(git, remote, ref):
            raise
        return None
    head = local_head(git, fetched_ref(remote, ref))
    if head is None:
        raise StoreError(f"git fetch {remote} {ref} succeeded but wrote no head")
    return head


def _remote_lacks(git: GitRunner, remote: str, ref: str) -> bool:
    """After a failed fetch: True only if the remote is reachable and has no `ref`."""
    try:
        return remote_head(git, remote, ref) is None
    except GitError:
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

    - local equal to `remote_head` -> no-op;
    - local missing or behind (crash between push and local update, or other writers'
      commits) -> move it with a compare-and-swap
      `update-ref <ref> <remote_head> <observed-local>`;
    - anything else (diverged, or ahead with commits the remote lacks) -> StoreError,
      before anything is written. A local ref that is ahead can only come from commits
      made outside tkt; tolerating it would let the next commit publish while its local
      update silently failed, and the clone would break one op later.
    """
    local = local_head(git, ref)
    if local == remote_head:
        return
    if local is not None and not is_ancestor(git, local, remote_head):
        raise StoreError(
            f"local {ref} ({local}) has commits the remote head ({remote_head}) lacks; "
            f"the remote is authoritative: reset it with "
            f"`git update-ref {ref} {remote_head}`"
        )
    git("update-ref", ref, remote_head, local or "")


def publish(git: GitRunner, remote: str, ref: str, new: Revision, base: Revision | None) -> None:
    """Push `new` to `remote` `ref` with `--force-with-lease=<ref>:<base>` (an empty
    expected value when `base` is None), so the push itself states the expected old value:
    it lands only if the remote ref is still `base`. Never a plain force-push.

    A rejected push publishes nothing. It is a lost race (Conflict, retried) if the branch
    moved, and a StoreError (stopped) if it was refused for another reason, e.g. branch
    protection or a hook. That is decided without reading the server's wording, which
    differs between servers:

    - "[rejected] (stale info)" comes from our own git client, whose lease check saw the
      branch move before anything was sent: a lost race, no round trip needed;
    - "[remote rejected] (...)" is the server's refusal of our update; one `ls-remote`
      then says whether the branch moved. If it already holds `new` (another writer
      built the identical commit, or the server misreported a push that landed), `new`
      is published and this returns normally, so a Conflict always means nothing of
      ours became visible.

    The `ls-remote` comes just after the rejection, so two rare overlaps are possible,
    both safe: a push refused for another reason while someone else moves the branch is
    taken for a lost race, and only becomes a StoreError on a retry whose window stays
    quiet (or ends in RetriesExhausted); and a server whose `ls-remote` lags behind its
    pushes would turn a lost race into a StoreError. Neither publishes anything.

    A failure without a status line (a timeout, a dropped connection) is the GitError
    itself, a StoreError that may hide a push that landed."""
    try:
        git(
            "push", "--porcelain", f"--force-with-lease={ref}:{base or ''}",
            remote, f"{new}:{ref}",
        )  # fmt: skip
    except GitError as error:
        status = [line for line in error.stdout.decode().splitlines() if line.startswith("!")]
        if any("\t[rejected]" in line for line in status):
            raise Conflict(base, None) from error
        if not status:
            raise
        reasons = "; ".join(line.split("\t")[-1] for line in status)
        try:
            head = remote_head(git, remote, ref)
        except GitError as check:
            raise StoreError(
                f"push to {remote} {reasons}, and the branch could not be re-read: {check}"
            ) from error
        if head == new:
            return
        if head != base:
            raise Conflict(base, head) from error
        raise StoreError(f"push to {remote} {reasons}: {error.stderr.strip()}") from error


def remote_head(git: GitRunner, remote: str, ref: str) -> Revision | None:
    """The remote's current value of `ref` (None if it does not exist), by `ls-remote`:
    one round trip, no objects transferred."""
    try:
        out = git("ls-remote", "--exit-code", remote, ref).decode()
    except GitError as error:
        if error.returncode == NO_SUCH_REF:
            return None
        raise
    for line in out.splitlines():
        oid, _, name = line.partition("\t")
        if name == ref:
            return Revision(oid)
    return None
