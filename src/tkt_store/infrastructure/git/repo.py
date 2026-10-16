"""The Store, implemented on git plumbing (ADR 0001).

No worktree, no index: a crash can only ever leave unreachable objects behind.
One process per clone is assumed (design.md §7); the local ref is only a cache of the
remote.

snapshot():
    [remote] remote.fetch -> remote head (the snapshot's revision; read from the private
             ref the fetch wrote, never from the local ref or FETCH_HEAD)
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
from contextlib import suppress
from itertools import islice
from pathlib import Path
from types import MappingProxyType

from tkt_store.application.errors import Conflict, StoreError
from tkt_store.application.store import HistoryEntry
from tkt_store.domain.outcomes import Change, OpRecord
from tkt_store.domain.ticket import Revision, Snapshot, Ticket, TicketId
from tkt_store.infrastructure.git import remote as sync
from tkt_store.infrastructure.git import wire
from tkt_store.infrastructure.git.runner import GitError, GitRunner, git_runner
from tkt_store.infrastructure.git.wire import DEFAULT_REF, StoreMode

TREE_MODE = "040000"
BLOB_MODE = "100644"


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

    @property
    def mode(self) -> StoreMode:
        return "local" if self._remote is None else "remote"

    def snapshot(self) -> Snapshot:
        revision = self._head()
        if revision is None:
            return Snapshot(None, MappingProxyType({}))
        self._check_meta(revision)
        listing = self._git("ls-tree", "-r", "-z", revision, "--", f"{wire.TICKETS_DIR}/")
        paths, blobs = [], []
        for entry in _entries(listing):
            path = entry.name.decode(errors="replace")  # undecodable: never a ticket path
            if entry.kind == "blob" and wire.is_ticket_path(path):
                paths.append(path)
                blobs.append(entry.oid)
        tickets: dict[TicketId, Ticket] = {}
        for path, data in zip(paths, self._read_blobs(blobs), strict=True):
            try:
                ticket = wire.decode_ticket(data)
            except StoreError as error:
                raise StoreError(f"{path} at {revision}: {error}") from error
            if wire.ticket_path(ticket.id) != path:
                raise StoreError(f"{path} at {revision} holds ticket {ticket.id}")
            tickets[ticket.id] = ticket
        return Snapshot(revision, MappingProxyType(tickets))

    def commit(
        self,
        base: Revision | None,
        changes: Sequence[Change],
        record: OpRecord,
    ) -> Revision:
        tree = self._tree(base, changes)
        parents = () if base is None else ("-p", base)
        message = wire.encode_message(record).encode()
        new = Revision(
            self._git("commit-tree", tree, *parents, "-F", "-", stdin=message).decode().strip()
        )
        if self._remote is not None:
            sync.publish(self._git, self._remote, self._ref, new, base)
            # published: the local ref is only a cache, repaired by the next snapshot
            with suppress(GitError):
                self._git("update-ref", self._ref, new, base or "")
            return new
        try:
            self._git("update-ref", self._ref, new, base or "")
        except GitError as error:
            actual = sync.local_head(self._git, self._ref)
            if actual != base:
                raise Conflict(base, actual) from error
            raise
        return new

    def history(
        self,
        ticket_id: TicketId | None = None,
        limit: int | None = None,
    ) -> Iterator[HistoryEntry]:
        """git log <ref> --format=%H%x00%B, decoded with wire.decode_message.
        Times come from the tkt-time trailer (`record.at`), never git's commit date."""
        revision = self._head()
        if revision is None:
            return iter(())
        out = self._git("log", "-z", "--format=%H%x00%B", revision).decode(errors="replace")
        fields = out.split("\0")

        def entries() -> Iterator[HistoryEntry]:
            for commit, message in zip(fields[::2], fields[1::2], strict=False):
                record = wire.decode_message(message)
                if record is None:
                    continue
                if ticket_id is None or ticket_id in record.ticket_ids:
                    yield HistoryEntry(Revision(commit.strip()), record)

        return islice(entries(), limit)

    def _head(self) -> Revision | None:
        """The store's current revision: the remote head (bringing the local cache up to
        it) when remote-backed, the local ref when local-only."""
        if self._remote is None:
            return sync.local_head(self._git, self._ref)
        head = sync.fetch(self._git, self._remote, self._ref)
        if head is not None:
            sync.fast_forward_local(self._git, self._ref, head)
        return head

    def _check_meta(self, revision: Revision) -> None:
        try:
            data = self._git("cat-file", "blob", f"{revision}:{wire.STORE_META_PATH}")
        except GitError as error:
            raise StoreError(
                f"{self._ref} at {revision} has no {wire.STORE_META_PATH}: not a tkt store"
            ) from error
        _protocol, mode = wire.decode_store_meta(data)
        if mode != self.mode:
            how = "with --no-remote" if self._remote is None else f"with remote {self._remote}"
            raise StoreError(f"this is a {mode} store; it cannot be opened {how}")

    def _read_blobs(self, oids: list[str]) -> list[bytes]:
        """Contents of `oids`, in order, from one `cat-file --batch`. Sizes are bytes.
        Output that is not "<oid> blob <size>" then the content (e.g. "<oid> missing" in
        a damaged repository) is a StoreError."""
        if not oids:
            return []
        out = self._git("cat-file", "--batch", stdin="".join(f"{o}\n" for o in oids).encode())
        contents, at = [], 0
        for oid in oids:
            header_end = out.find(b"\n", at)
            header = out[at:header_end] if header_end >= 0 else out[at:]
            fields = header.split()
            if len(fields) != 3 or fields[1] != b"blob" or not fields[2].isdigit():
                raise StoreError(f"cannot read blob {oid}: {header!r}")
            size = int(fields[2])
            contents.append(out[header_end + 1 : header_end + 1 + size])
            at = header_end + 1 + size + 1  # content, then a newline
        return contents

    def _tree(self, base: Revision | None, changes: Sequence[Change]) -> str:
        """The new root tree: `base`'s tree with each changed ticket's file replaced.
        Every other entry, known or not, is carried over untouched (names stay bytes, so
        a name that is not UTF-8 survives too)."""
        root = {} if base is None else _by_name(self._git("ls-tree", "-z", f"{base}^{{tree}}"))
        if base is None:
            meta = self._hash(wire.encode_store_meta(self.mode))
            name = wire.STORE_META_PATH.encode()
            root[name] = _Entry(BLOB_MODE, "blob", meta, name)
        tickets_dir = wire.TICKETS_DIR.encode()
        current = root.get(tickets_dir)
        if current is not None and current.kind != "tree":
            raise StoreError(f"{wire.TICKETS_DIR} at {base} is not a directory")
        tickets = {} if current is None else _by_name(self._git("ls-tree", "-z", current.oid))
        for change in changes:
            name = wire.ticket_path(change.ticket.id).removeprefix(f"{wire.TICKETS_DIR}/").encode()
            oid = self._hash(wire.encode_ticket(change.ticket))
            tickets[name] = _Entry(BLOB_MODE, "blob", oid, name)
        if tickets:
            oid = self._mktree(tickets)
            root[tickets_dir] = _Entry(TREE_MODE, "tree", oid, tickets_dir)
        return self._mktree(root)

    def _hash(self, data: bytes) -> str:
        return self._git("hash-object", "-w", "--stdin", stdin=data).decode().strip()

    def _mktree(self, entries: dict[bytes, _Entry]) -> str:
        listing = b"".join(e.line() for e in entries.values())
        return self._git("mktree", "-z", stdin=listing).decode().strip()


class _Entry:
    """One `ls-tree -z` / `mktree -z` record: "<mode> <type> <oid>\t<name>". The name is
    kept as bytes: git does not require file names to be UTF-8."""

    __slots__ = ("kind", "mode", "name", "oid")

    def __init__(self, mode: str, kind: str, oid: str, name: bytes) -> None:
        self.mode, self.kind, self.oid, self.name = mode, kind, oid, name

    def line(self) -> bytes:
        return f"{self.mode} {self.kind} {self.oid}\t".encode() + self.name + b"\0"


def _entries(listing: bytes) -> Iterator[_Entry]:
    for raw in listing.split(b"\0"):
        if raw:
            meta, name = raw.split(b"\t", 1)
            mode, kind, oid = meta.decode().split()
            yield _Entry(mode, kind, oid, name)


def _by_name(listing: bytes) -> dict[bytes, _Entry]:
    return {e.name: e for e in _entries(listing)}
