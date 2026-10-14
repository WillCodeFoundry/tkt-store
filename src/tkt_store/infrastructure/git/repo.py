"""The Store, implemented on git plumbing (ADR 0001).

No worktree, no index: a crash can only ever leave unreachable objects behind.

snapshot():
    [remote] remote.fetch + remote.fast_forward_local
    git rev-parse --verify <ref>              -> base (None if unborn)
    git ls-tree -r <base> tickets/            -> blob ids
    git cat-file --batch                      -> file contents -> wire.decode_ticket

commit(base, changes, record):
    git hash-object -w --stdin                 (one per changed ticket)
    git mktree                                 (base tree with replaced entries)
    git commit-tree <tree> -p <base> -F -      (message = wire.encode_message(record))
    [remote] remote.publish(new)               -> Conflict on non-fast-forward
    git update-ref <ref> <new> <base>          -> Conflict if the local ref moved
                                                  (for an unborn store: old value = zero id)
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

from tkt_store.application.store import HistoryEntry
from tkt_store.domain.outcomes import Change, OpRecord
from tkt_store.domain.ticket import Revision, Snapshot, TicketId
from tkt_store.infrastructure.git.runner import GitRunner, git_runner
from tkt_store.infrastructure.git.wire import DEFAULT_REF


class GitStore:
    """A Store backed by one ref in one git repository, optionally mirrored to a remote."""

    def __init__(
        self,
        git: GitRunner,
        ref: str = DEFAULT_REF,
        remote: str | None = None,
    ) -> None:
        self._git = git
        self._ref = ref
        self._remote = remote

    @classmethod
    def at(cls, repo: Path, ref: str = DEFAULT_REF, remote: str | None = None) -> GitStore:
        """Convenience constructor using git_runner(repo)."""
        return cls(git_runner(repo), ref=ref, remote=remote)

    def snapshot(self) -> Snapshot:
        raise NotImplementedError

    def commit(
        self,
        base: Revision | None,
        changes: Sequence[Change],
        record: OpRecord,
    ) -> Revision:
        raise NotImplementedError

    def history(
        self,
        ticket_id: TicketId | None = None,
        limit: int | None = None,
    ) -> Iterator[HistoryEntry]:
        """git log <ref> --format=%H%x00%ct%x00%B, decoded with wire.decode_message."""
        raise NotImplementedError
