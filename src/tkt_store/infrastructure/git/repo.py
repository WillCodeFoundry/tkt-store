"""The Store, implemented on git plumbing (ADR 0001).

No worktree, no index: a crash can only ever leave unreachable objects behind.
One process per clone is assumed (design.md §7); the local ref is only a cache of the
remote.

snapshot():
    [remote] remote.fetch -> remote head (the snapshot's revision; read from the fetch
             result, never re-read from the local ref or FETCH_HEAD)
    [remote] remote.fast_forward_local(remote head)
    [local]  git rev-parse --verify <ref>    -> revision (None if unborn)
    git cat-file <revision>:tkt-store.json   -> wire.decode_store_meta; StoreError if
                                                missing on a born ref, a newer protocol,
                                                or a mode that is not this store's (a
                                                remote-backed store opened with remote=None,
                                                or a local-only one opened with a remote)
    git ls-tree -r <revision> tickets/       -> blob ids of wire.is_ticket_path entries only
    git cat-file --batch                     -> file contents (bytes) -> wire.decode_ticket;
                                                one corrupt ticket fails the whole snapshot

commit(base, changes, record):
    git hash-object -w --stdin                (one per changed ticket)
    git mktree                                (base tree with replaced entries; when base
                                               is None, also wire.encode_store_meta(mode)
                                               as tkt-store.json in the root commit, mode
                                               "remote" or "local" by self._remote)
    git commit-tree <tree> [-p <base>] -F -   (message = wire.encode_message(record))
    [remote] remote.publish(new, base)        -> push with --force-with-lease=<ref>:<base>;
                                               Conflict if the lease fails; nothing published
    [remote] git update-ref <ref> <new> <base> best-effort: once published, any failure
                                               (ref moved, cannot lock ref, ...) is ignored
                                               and commit returns `new`; the next snapshot
                                               repairs the cache
    [local]  git update-ref <ref> <new> <base> -> Conflict if the ref moved: here update-ref
                                               IS the compare-and-swap
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
    """A Store backed by one ref in one git repository.

    `remote` has no default: name the shared remote (normally "origin"), or pass None
    to choose a local-only store explicitly. It is never a silent fallback.
    """

    def __init__(
        self,
        git: GitRunner,
        *,
        remote: str | None,
        ref: str = DEFAULT_REF,
    ) -> None:
        self._git = git
        self._ref = ref
        self._remote = remote

    @classmethod
    def at(cls, repo: Path, *, remote: str | None, ref: str = DEFAULT_REF) -> GitStore:
        """Convenience constructor using git_runner(repo)."""
        return cls(git_runner(repo), remote=remote, ref=ref)

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
        """git log <ref> --format=%H%x00%B, decoded with wire.decode_message.
        Times come from the tkt-time trailer (`record.at`), never git's commit date."""
        raise NotImplementedError
