"""Remote synchronisation for a remote-backed git store.

The remote is authoritative; local refs are a cache (design.md §6). Everything
here goes through a GitRunner, so nothing in this module touches the git binary
directly.
"""

from __future__ import annotations

from tkt_store.domain.ticket import Revision
from tkt_store.infrastructure.git.runner import GitRunner


def fetch(git: GitRunner, remote: str, ref: str) -> Revision | None:
    """Fetch `ref` from `remote`; return the remote head (None if the ref does not exist)."""
    raise NotImplementedError


def fast_forward_local(git: GitRunner, ref: str, remote_head: Revision) -> None:
    """Move the local ref to `remote_head` if it is a descendant of the local head
    (local is behind after a crash between push and local update, or after another
    writer's commits). The local ref only moves after a successful push, so local is
    never ahead through tkt; a local ref that is ahead or diverged is a StoreError."""
    raise NotImplementedError


def publish(git: GitRunner, remote: str, ref: str, new: Revision) -> None:
    """Push `new` to `remote` `ref` as a fast-forward.
    Raises Conflict on non-fast-forward rejection. Never force-pushes."""
    raise NotImplementedError
