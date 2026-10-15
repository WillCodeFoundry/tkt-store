"""Remote synchronisation for a remote-backed git store.

The remote is authoritative; local refs are a cache (design.md §6). Everything
here goes through a GitRunner, so nothing in this module touches the git binary
directly.
"""

from __future__ import annotations

from tkt_store.domain.ticket import Revision
from tkt_store.infrastructure.git.runner import GitRunner


def fetch(git: GitRunner, remote: str, ref: str) -> Revision | None:
    """Fetch `ref` from `remote`; return the remote head (None if the ref does not exist).
    The returned revision is the snapshot's revision: read it from the fetch result, not
    from FETCH_HEAD or the shared local ref."""
    raise NotImplementedError


def fast_forward_local(git: GitRunner, ref: str, remote_head: Revision) -> None:
    """Bring the local ref (a cache of the remote) up to `remote_head`.

    - local equal to, or a descendant of, `remote_head` -> no-op (another process
      sharing this clone may have pushed and updated it in between);
    - local behind (crash between push and local update, or other writers' commits)
      -> move it with a compare-and-swap `update-ref <ref> <remote_head> <observed-local>`;
      losing that race to another process is fine;
    - diverged -> StoreError.
    """
    raise NotImplementedError


def publish(git: GitRunner, remote: str, ref: str, new: Revision) -> None:
    """Push `new` to `remote` `ref` as a fast-forward.
    Raises Conflict on non-fast-forward rejection (nothing published). Never force-pushes.
    Any other failure is a StoreError, which may hide a push that landed."""
    raise NotImplementedError
