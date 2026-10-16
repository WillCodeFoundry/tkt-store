# 0006 — Each clone caches resolved and invalid tickets

**Status:** accepted; implemented for 0.2.0 in stage 2b

## Context

Every op reads every ticket file on the branch, resolved ones included, so its local
cost grows with the store's whole history (ADR 0001, *Store size*). This was open
question Q1. Measured on a packed store of 20,000 tickets, per op:

| Step | Time |
|---|---|
| list `tickets/` with blob ids (`ls-tree -r`) | ~20 ms |
| read every ticket file (`cat-file --batch`) | ~350 ms |
| decode every ticket (JSON parse, building `Ticket`s) | ~300 ms |
| rebuild the `tickets/` tree for a commit | ~40 ms |

Reading and decoding dominate; listing files and rebuilding the tree do not. From 0.2.0
decoding also validates every field (ADR 0005), character by character, which adds to
the decoding cost. Over time almost every ticket is resolved, and a resolved ticket
never changes.

## Decision

**The layout stays as it is:** one `tickets/` directory, one file per ticket, wherever
its state. Nothing moves when a ticket is resolved.

**Each clone keeps a cache file** at `tkt-store/cache.json` in the clone's git directory
(`git rev-parse --absolute-git-dir`; never pushed). Its entries are keyed by blob id, and
a blob id names exact content, so an entry is never stale:

- a valid resolved ticket: the ticket;
- an invalid ticket file: that it is invalid and which check failed (the check, not the
  value read, ADR 0005), so it is not read and checked again on every op.

Open tickets are not saved to the file: they are few and change on most ops. A
long-running process keeps them in an in-memory map by blob id.

**Only what depends on the file's bytes alone is cached:** decoding and the size,
schema, field and whole-ticket checks. Checks that relate a file to its path (the id
matches the file name), to other tickets (blockers) or to claims (ADR 0007) run on
every snapshot over cached and freshly read tickets alike, as do
derived values such as status. No cached check reads the clock: time-dependent ones,
such as a claim made in the future or the lease cap, live in the rules and run on every
op, so a verdict never depends on when it was made.

**A snapshot** lists `tickets/` with blob ids, takes the cached entries, and reads and
checks the remaining files in one `cat-file --batch`. When it finds new resolved or
invalid files, or the cache holds blob ids that are no longer listed, it rewrites the
file: only the current listing's entries, to a temporary file with a unique name in the
same directory, renamed over the old one. A crash never leaves a torn cache, and the
cache never holds more than the store. If two processes share a clone anyway (against
the one-clone-per-process rule), the last rename wins and a lost entry only costs a
re-read.

**The cache is a convenience, never the source of truth.** It records a cache version,
a constant bumped whenever the decoder or a cached check changes, and the tkt-store
version that wrote it; a cache with either different, one that does not parse, or one
whose entries have the wrong shape is discarded, and the next snapshot rebuilds it with
one full read. Cached tickets are loaded through the same decoder as ticket files,
without the field checks. Deleting the cache is always safe. It is JSON, never pickle:
loading a pickle can run code.

**The cache is trusted like the rest of the clone.** An entry is believed without reading
its blob, so whoever can write the clone's git directory can make a forged ticket look
valid. That adds no exposure: writing it already lets them change hooks or config and
run code in that clone (ADR 0005).

## Alternatives rejected

- **Archiving resolved tickets** (moving them under `archive/` in the `done` or `cancel`
  commit, sharded by a hash of the id): snapshots would read only open tickets, but every
  rule that touches resolved tickets (blockers, duplicate ids, re-runs of `done` and
  `cancel`, claim-id fencing) would need a lookup by path, an id could sit in two places,
  and fencing would need a separate index of ended claim ids. It also changes the store
  format, which every writer must follow.
- **Sharding `tickets/` by a hash of the id:** it only speeds up rebuilding the tree
  (~40 ms down to ~7 ms at 20,000 tickets), not reading.
- **Moving invalid tickets into a `quarantine/` area:** a move is a write, so reading
  would start committing, any agent could trigger it, and those writes would conflict.
  Invalid tickets stay where they are and `tkt audit` reports them.
- **Caching open tickets on disk too:** their entries would go stale on most ops and need
  pruning on every write, for little gain.
- **Caching only what ops need from resolved tickets** (id, resolution, ended claim
  hashes): faster to load, but rules would have to work on partial tickets.

## Consequences

- An op skips reading and checking resolved and invalid files, and listing or parsing
  resolved tickets' claims folders. It still parses the cache, lists every file and
  rebuilds the `tickets/` tree, so its cost still grows with history, only more slowly;
  accepted (design.md §9).
- Measured in stage 2b at 20,000 tickets (90% resolved) with three claims each, per op:
  a new process (the CLI) takes about 1.1 s instead of 2.4 s, a long-running one about
  0.35 s instead of 0.77 s; at 2,000 tickets, about 120 ms and 50 ms instead of 260 ms
  and 95 ms. The first estimate (about 350 ms for the CLI) predated 0.2.0's validation
  on read, which makes reading a ticket costlier and the cache worth more; what remains
  is mostly decoding the cached tickets and parsing claim names.
- The first op in a new clone, and the first after an upgrade, reads every file once.
- The cache grows with resolved tickets: about the size of their files (about 17 MB at
  20,000 tickets with short bodies).
- The cache changes no format: it is local to each clone and to the GitStore adapter.
- Claims (ADR 0007) have no content to cache, but listing and parsing their names cost
  about 430 ms per op at that size (measured in stage 2a). So the cache also keeps each
  resolved ticket's claim file names by the id of its `claims/<id>/` tree (names only,
  never verdicts, which depend on the ticket), and a process keeps every folder it read
  by tree id in memory: a snapshot lists `claims/` without recursing and reads only the
  folders it does not know, together, in one batch. Assembling the snapshot looks at
  repeated hashes only, and is about 170 ms at that size.
