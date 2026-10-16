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
expired). Archived files are looked up by path, at the snapshot's revision (never a
newer one, so a decision sees one state), several at a time in one git call
(`cat-file --batch-check`, then reading the few files found). Each op makes at most one
such batch per kind of lookup:

- **Blockers:** a blocker is done when a valid ticket with resolution `done` is at its
  `archive/done/` path. `list` and `claim-next` need the blockers of every open ticket,
  `claim` those of its ticket; each looks up the blockers not open in one batch. `add`
  and `edit` find a blocker in the archive the same way, so a resolved blocker is not
  refused as unknown.
- **An id that is not open:** `add` finds it taken if it is at either archive path
  (`DUPLICATE_ID`, as for a set-aside ticket). `claim`, `show`, holder ops, `edit`,
  `revoke` and re-runs of `done` or `cancel` read its archived file: `TERMINAL` for a
  claim, holder op, edit or revoke, as today; `NoOp` or a refusal for a re-run of `done`
  or `cancel`, from its claim history; `NOT_FOUND` only if it is in neither archive.
- **`list`** shows open tickets; `list --status done` or `--status cancelled` reads that
  part of the archive, on request. `log` reads commits, not ticket files.

**Fencing stays global, through a claim index.** "An ended claim hash never claims
again" must cover archived tickets: an agent that re-runs `claim-next` with the same
claim id after its ticket was resolved must be refused, not given a second ticket. So
the `done` or `cancel` commit also writes, for each hash in the ticket's
`ended_claim_ids`, a file `archive/claims/<hh>/<hash>` holding the ticket's id, where
`<hh>` is the hash's first two digits. `claim` and `claim-next` check the one path for
their hash, in the same batch as their other lookups; a hash found there is
`NOT_HOLDER`, as an ended claim on an open ticket is today. Open tickets' histories are
checked as before.

**Validation (ADR 0005) applies to archived files when they are read,** plus:

- A ticket file must sit where its state says: a resolved ticket under `tickets/`, an
  open one in the archive, or one in the wrong archive directory or shard is invalid.
- An id in more than one place (open and archived, or in both archives) has every copy
  set aside and reported. A snapshot checks both archive paths of every open id in one
  batch, and a lookup of an archived ticket also checks `tickets/` and the other
  archive.
- A claim index entry counts by its path alone; its content (the ticket id) is for
  `tkt audit`, which reports entries whose content is not an archived ticket carrying
  that hash. A forged entry can only fence a claim id, which an agent pushing with plain
  git can do anyway (ADR 0005).
- Unknown files anywhere stay preserved and never read.

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
- **Fencing against open tickets only:** a re-run of `claim-next` after its ticket was
  resolved would take a second ticket, breaking "one claim id names one claim on one
  ticket".
- **An on-disk or id cache:** archived tickets and ended claims are found by path, so
  nothing needs the whole archive, and resolved tickets never change.

## Consequences

- A snapshot's cost tracks open tickets, not history; lookups add a few batched git
  calls per op. A `done` or `cancel` commit rewrites `tickets/`, one archive shard
  (about 1/256 of that archive) and its 256-entry directory, a few claim index shards
  and theirs, `archive/` and the root; other commits do not touch the archive.
- The archive grows by one ticket file and one index file per claim ever ended; nothing
  reads it whole except `list --status done|cancelled`.
- `list --status done` costs in proportion to that archive; it is a deliberate query.
- Spam *open* tickets still cost every commit (they sit in `tickets/`), and so do junk
  files there; archiving bounds history, not abuse (ADR 0005, *not defended*).
- Part of protocol 2: the store layout changes, which `docs/format.md` describes when it
  lands.
