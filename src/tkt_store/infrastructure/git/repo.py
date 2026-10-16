"""The Store, implemented on git plumbing (ADR 0001).

No worktree, no index: a crash can only ever leave unreachable objects behind.
The remote is authoritative; the local ref is only a cache of it. One process per clone
(design.md §7).

snapshot():
    remote.fetch                             -> remote head (the snapshot's revision; read
                                                from the private ref the fetch wrote, never
                                                from the local ref or FETCH_HEAD)
    remote.fast_forward_local(remote head)
    git cat-file <revision>:tkt-store.json   -> wire.decode_store_meta; StoreError unless
                                                exactly protocol 2
    git ls-tree -l <revision> tickets/       -> modes, blob ids and sizes of ticket paths (not
                                                recursive: a tree at a ticket path is set
                                                aside, never recursed into)
    git cat-file --batch                     -> contents of the regular ticket files within
                                                the cap whose blob this store has not
                                                checked before -> wire.decode_ticket and
                                                fields.ticket_problem; a bad file is set
                                                aside, never fatal (ADR 0005)
    git ls-tree -r <revision> claims/        -> claim files, from their names alone
                                                (wire.claim_of; ADR 0007)
    occupancy.assemble                       -> the snapshot

commit(base, changes, record):
    git hash-object -w --stdin                (one per changed ticket; the empty blob for
                                               claim files)
    git mktree                                (each touched tree, bottom up: replaced ticket
                                               files, renamed claim files; when base is
                                               None, also wire.encode_store_meta() as
                                               tkt-store.json in the root commit)
    git commit-tree <tree> [-p <base>] -F -   (message = wire.encode_message(record))
    remote.publish(new, base)                 -> push with --force-with-lease=<ref>:<base>;
                                               rejected: Conflict if the branch moved,
                                               StoreError if not; nothing published
    git update-ref <ref> <new> <base>         best-effort: once published, any failure
                                               (ref moved, cannot lock ref, ...) is ignored
                                               and commit returns `new`; the next snapshot
                                               repairs the cache
    git gc --auto                             (housekeeping: plumbing never triggers it)
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import suppress
from itertools import islice
from pathlib import Path
from types import MappingProxyType

from tkt_store.application.errors import StoreError
from tkt_store.application.store import HistoryEntry
from tkt_store.domain import fields
from tkt_store.domain.occupancy import assemble
from tkt_store.domain.outcomes import Change, OpRecord, WriteClaim, WriteTicket
from tkt_store.domain.ticket import ClaimFile, Revision, Snapshot, Ticket, TicketId
from tkt_store.infrastructure.git import remote as sync
from tkt_store.infrastructure.git import wire
from tkt_store.infrastructure.git.runner import GitError, GitRunner, git_runner
from tkt_store.infrastructure.git.wire import DEFAULT_REF

TREE_MODE = "040000"
BLOB_MODE = "100644"


class GitStore:
    """A Store backed by one ref, published to a remote and cached in a clone.

    `remote` is the shared remote's name (normally "origin"); it has no default here.
    """

    def __init__(
        self,
        git: GitRunner,
        *,
        remote: str,
        ref: str = DEFAULT_REF,
    ) -> None:
        self._git = git
        self._ref = ref
        self._remote = remote
        self._verdicts: dict[str, Ticket | str] = {}
        """Ticket files already checked, by blob id: the valid ticket, or the check that
        failed. A blob id names exact content, so an entry can never be stale; a snapshot
        reads and checks only the files whose content it has not seen. Pruned to the
        latest snapshot's files, so it stays bounded."""
        self._empty: str | None = None

    @classmethod
    def at(cls, repo: Path, *, remote: str, ref: str = DEFAULT_REF) -> GitStore:
        """Convenience constructor using git_runner(repo)."""
        return cls(git_runner(repo), remote=remote, ref=ref)

    def snapshot(self) -> Snapshot:
        revision = self._head()
        if revision is None:
            return Snapshot(None, MappingProxyType({}))
        self._check_meta(revision)
        self._check_layout(revision)
        tickets, set_aside = self._tickets(revision)
        claims, not_folders = self._claims(revision)
        return assemble(revision, tickets, set_aside, claims, not_folders)

    def _check_layout(self, revision: Revision) -> None:
        """`tickets` and `claims`, where present, must be folders: the store's own layout,
        like `tkt-store.json`. Anything else is a StoreError that names no value, since
        nothing could be written until an operator repairs it (ADR 0007)."""
        for entry in _entries(self._git("ls-tree", "-z", revision)):
            name = entry.name.decode(errors="replace")
            if name in (wire.TICKETS_DIR, wire.CLAIMS_DIR) and entry.kind != "tree":
                raise StoreError(
                    f"{self._ref} at {revision}: {name} is not a folder; an operator must "
                    "repair the store"
                )

    def _tickets(self, revision: Revision) -> tuple[dict[TicketId, Ticket], dict[TicketId, str]]:
        """Every ticket file, checked (ADR 0005): only a regular file of at most
        TICKET_FILE_MAX (both known from the listing, before reading) is read; it must
        decode strictly, follow the field rules and be named by its id. The others are
        set aside, with the check that failed. Verdicts are kept by blob id: a blob id
        names exact content, so a file is never read or checked twice."""
        listing = self._git("ls-tree", "-l", "-z", revision, "--", f"{wire.TICKETS_DIR}/")
        set_aside: dict[TicketId, str] = {}
        to_check: dict[TicketId, str] = {}  # id -> blob id
        for raw in listing.split(b"\0"):
            if not raw:
                continue
            meta, name = raw.split(b"\t", 1)
            mode, kind, oid, size = meta.decode().split()
            ticket_id = wire.ticket_id_of(name.decode(errors="replace"))
            if ticket_id is None:
                continue  # not a ticket path: preserved, never interpreted
            if mode != BLOB_MODE or kind != "blob":
                set_aside[ticket_id] = "not a regular file"
            elif int(size) > fields.TICKET_FILE_MAX:
                set_aside[ticket_id] = f"larger than {fields.TICKET_FILE_MAX // 1024} KiB"
            else:
                to_check[ticket_id] = oid
        verdicts = {oid: self._verdicts[oid] for oid in to_check.values() if oid in self._verdicts}
        unseen = [oid for oid in dict.fromkeys(to_check.values()) if oid not in verdicts]
        for oid, data in zip(unseen, self._read_blobs(unseen), strict=True):
            verdicts[oid] = _verdict(data)
        tickets: dict[TicketId, Ticket] = {}
        for ticket_id, oid in to_check.items():
            match verdicts[oid]:
                case Ticket() as ticket if ticket.id == ticket_id:
                    tickets[ticket_id] = ticket
                case Ticket():
                    set_aside[ticket_id] = "its id is not its file name"
                case str() as problem:
                    set_aside[ticket_id] = problem
        self._verdicts = verdicts
        return tickets, set_aside

    def _claims(self, revision: Revision) -> tuple[list[ClaimFile], list[TicketId]]:
        """Every claim file (ADR 0007), from the listing alone: an empty regular file whose
        path parses (`wire.claim_of`). Nothing in a claim file is read; any other path
        under claims/ is an unknown file, preserved and never interpreted. Also the ticket
        ids whose `claims/<id>` is not a folder."""
        listing = self._git("ls-tree", "-r", "-z", revision, "--", f"{wire.CLAIMS_DIR}/")
        empty = self._empty_blob()
        claims, not_folders = [], []
        for entry in _entries(listing):
            path = entry.name.decode(errors="replace")
            empty_file = entry.mode == BLOB_MODE and entry.kind == "blob" and entry.oid == empty
            if empty_file and (claim := wire.claim_of(path)) is not None:
                claims.append(claim)
            elif (ticket_id := wire.claims_folder_of(path)) is not None:
                not_folders.append(ticket_id)
        return claims, not_folders

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
        sync.publish(self._git, self._remote, self._ref, new, base)
        # published: the local ref is only a cache, repaired by the next snapshot
        with suppress(GitError):
            self._git("update-ref", self._ref, new, base or "")
        self._housekeeping()
        return new

    def _housekeeping(self) -> None:
        """`git gc --auto` after each commit. Plumbing never triggers git's automatic
        housekeeping, so without this every ticket version stays a loose object, and
        reading thousands of loose objects is about 3x slower than reading a pack
        (ADR 0001). It returns at once below git's thresholds and otherwise packs in the
        background (gc.autoDetach); a failure only costs speed, so it is ignored."""
        with suppress(GitError):
            self._git("gc", "--auto", "--quiet")

    def history(
        self,
        ticket_id: TicketId | None = None,
        limit: int | None = None,
    ) -> Iterator[HistoryEntry]:
        """git log <ref> --format=%H%x00%B, decoded with wire.decode_message. Foreign and
        malformed commits are skipped, so one bad commit never breaks history. Times come
        from the tkt-time trailer (`record.at`), never git's commit date."""
        revision = self._head()
        if revision is None:
            return iter(())
        out = self._git("log", "-z", "--format=%H%x00%B", revision).decode(errors="replace")
        parts = out.split("\0")

        def entries() -> Iterator[HistoryEntry]:
            for commit, message in zip(parts[::2], parts[1::2], strict=False):
                try:
                    record = wire.decode_message(message)
                except wire.Invalid:
                    continue  # a malformed tkt commit (pushed by hand) is skipped
                if record is None:
                    continue
                if ticket_id is None or ticket_id in record.ticket_ids:
                    yield HistoryEntry(Revision(commit.strip()), record)

        return islice(entries(), limit)

    def _head(self) -> Revision | None:
        """The store's current revision: the remote head, bringing the local cache up to
        it."""
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
        wire.decode_store_meta(data)

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
        """The new root tree: `base`'s tree with each change applied. A ticket replaces its
        file; a claim adds its file (git's empty blob) and removes the name it replaces, so
        a renewal or an end is a rename. Every other entry, known or not, is carried over
        untouched (names stay bytes, so a name that is not UTF-8 survives too)."""
        edits: dict[str, str | None] = {}  # path -> blob id, or None to remove
        if base is None:
            edits[wire.STORE_META_PATH] = self._hash(wire.encode_store_meta())
        for change in changes:
            match change:
                case WriteTicket(ticket=ticket):
                    oid = self._hash(wire.encode_ticket(ticket))
                    self._verdicts[oid] = ticket  # encoding round-trips: no need to read it
                    edits[wire.ticket_path(ticket.id)] = oid
                case WriteClaim(claim=claim, replaces=replaced):
                    if replaced is not None:
                        edits[wire.claim_path(replaced)] = None
                    edits[wire.claim_path(claim)] = self._empty_blob(write=True)
        return self._edit_tree(None if base is None else f"{base}^{{tree}}", edits)

    def _edit_tree(self, tree: str | None, edits: dict[str, str | None]) -> str:
        """`tree` (None: empty) with `edits` applied, paths relative to it; returns the new
        tree's id. Only the subtrees an edit touches are read and rewritten."""
        entries = {} if tree is None else _by_name(self._git("ls-tree", "-z", tree))
        nested: dict[str, dict[str, str | None]] = {}
        for path, oid in edits.items():
            head, slash, rest = path.partition("/")
            if slash:
                nested.setdefault(head, {})[rest] = oid
            elif oid is None:
                entries.pop(head.encode(), None)
            else:
                entries[head.encode()] = _Entry(BLOB_MODE, "blob", oid, head.encode())
        for name, sub_edits in nested.items():
            current = entries.get(name.encode())
            if current is not None and current.kind != "tree":
                raise StoreError(f"{name} is not a directory")
            oid = self._edit_tree(None if current is None else current.oid, sub_edits)
            entries[name.encode()] = _Entry(TREE_MODE, "tree", oid, name.encode())
        return self._mktree(entries)

    def _empty_blob(self, *, write: bool = False) -> str:
        """The id of git's empty blob in this repository (its hash depends on the object
        format), written to the object store when a claim file needs it."""
        if write or self._empty is None:
            args = ("hash-object", "-w", "--stdin") if write else ("hash-object", "--stdin")
            self._empty = self._git(*args, stdin=b"").decode().strip()
        return self._empty

    def _hash(self, data: bytes) -> str:
        return self._git("hash-object", "-w", "--stdin", stdin=data).decode().strip()

    def _mktree(self, entries: dict[bytes, _Entry]) -> str:
        listing = b"".join(e.line() for e in entries.values())
        return self._git("mktree", "-z", stdin=listing).decode().strip()


def _verdict(data: bytes) -> Ticket | str:
    """A ticket file's content checked on its own: the ticket, or the check that failed."""
    try:
        ticket = wire.decode_ticket(data)
    except wire.Invalid as invalid:
        return str(invalid)
    return fields.ticket_problem(ticket) or ticket


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
