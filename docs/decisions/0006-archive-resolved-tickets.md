# 0006 — Resolved tickets are archived

**Status:** accepted; implemented for 0.2.0 (protocol 2, with ADR 0005)

## Context

Every operation reads every ticket file on the branch, resolved ones included, so its
local cost grows with the store's whole history (ADR 0001, *Store size*), and every
commit rewrites a `tickets/` tree listing every ticket. Over time almost every ticket is
resolved, so most of that cost is history no operation needs. This was open question
Q1.

## Decision

**Layout.** Open tickets stay at `tickets/tkt-<hex>.json`. In the same commit as `done`
or `cancel`, the file moves to `archive/done/<xx>/tkt-<hex>.json` or
`archive/cancelled/<xx>/tkt-<hex>.json`, where `<xx>` is the first two hex digits of
the SHA-256 of the ticket id (256 shards). Hashing spreads tickets evenly whatever ids
callers choose; sequential ids would otherwise crowd a few shards. A resolved ticket is
final, so an archived file never changes again.

**Snapshots read only `tickets/`:** the open tickets (unclaimed, held, blocked or
expired). Archived tickets are looked up by path, only when an operation needs a
specific one, several at a time in one git call (`cat-file --batch-check`, then reading
the few files found):

- **Blockers:** a blocker is done when a valid ticket with resolution `done` is at its
  `archive/done/` path. A candidate's blockers (at most 20) are looked up together.
- **`add`:** an id is taken if it exists under `tickets/` or either archive path
  (`DUPLICATE_ID`, as for a set-aside ticket).
- **`show` and `log` of a resolved ticket,** and re-runs of `done` or `cancel` on one
  (`Unchanged` versus a refusal depends on its claim history): that one file is read.
- **Holder ops and `edit`/`revoke` on a resolved ticket:** `TERMINAL`, as today, after
  reading its archived file.
- **`list`** shows open tickets; `list --status done` or `--status cancelled` reads that
  part of the archive, on request.

**Fencing is scoped to open tickets.** "An ended claim hash never claims again" is
checked against open tickets' histories only, not archived ones. Claim ids are random
128-bit values minted by each agent, so reuse across tickets only happens by mistake;
on the ticket a claim belonged to, now resolved, every holder op is refused anyway.

**Validation (ADR 0005) applies to archived files when they are read,** plus: the file
must sit where its id and resolution say (the right archive directory and shard); an id
present in more than one place (open and archived, or in both archives) has every copy
set aside and reported. Unknown files anywhere stay preserved and never read.

**No ticket cache.** With only open tickets read, a snapshot is one batched read of a
few dozen to a few hundred small files, far cheaper than the fetch and push around it,
and the CLI starts a new process for every command anyway. The in-memory cache by blob
id is removed, along with the plan to cache invalid tickets. `git gc --auto` after each
commit stays.

## Alternatives rejected

- **Sharding by month:** callers' clocks skew, and a shard per month still grows without
  bound in a busy month.
- **Sharding by the id's own prefix:** callers choose ids, so sequential or prefixed ids
  would crowd a few shards.
- **Moving invalid tickets into a `quarantine/` area:** a move is a write, so reading
  would start committing, any agent could trigger it, and those writes would conflict.
  Invalid tickets stay where they are and `tkt audit` reports them.
- **An on-disk or id cache:** archived tickets are found by path, so nothing needs the
  whole archive, and resolved tickets never change.

## Consequences

- A snapshot's cost tracks open tickets, not history. A `done` or `cancel` commit
  rewrites one archive shard (about 1/256 of that archive), its 256-entry directory and
  the root; other commits do not touch the archive.
- `list --status done` costs in proportion to that archive; it is a deliberate query.
- Spam *open* tickets still cost every commit (they sit in `tickets/`), and so do junk
  files there; archiving bounds history, not abuse (ADR 0005, *not defended*).
- Part of protocol 2: the store layout changes, which `docs/format.md` describes when it
  lands.
