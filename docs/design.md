# tkt-store — design

Status: **skeleton for review.** This document is the authority on concepts,
boundaries and invariants.

## 1. Purpose and scope

tkt-store answers one question reliably: **which tickets exist, and who holds
which one right now.** It stores tickets on a git branch and changes them only by
atomic, compare-and-swap commits.

Out of scope (belongs to callers — agents, an optional coordinator — or later
packages): running agents, sandboxes, worktrees, delivering or merging code,
approvals, notifications, syncing with Jira/GitHub, multiple stores.

## 2. Concepts

| Term | Meaning |
|---|---|
| **Store** | One git ref (default `refs/heads/tkt`) holding `tickets/<id>.json`, normally backed by a remote (`origin`). The unit of consistency: every op is decided on a snapshot of the whole store (see §7). |
| **Ticket** | A unit of work: title, body, kind (story/task/bug), project, priority, dependencies, tags; plus a content `version` for optimistic concurrency on edits. |
| **Project** | An opaque identifier for the code repo a ticket belongs to. Supplied by the caller; the store neither derives nor interprets it. |
| **Claim** | Exclusive holding of a ticket: `agent`, `claim_id`, `lease_until`, `claimed_at`. Stored inside the ticket. Exclusivity is enforced by the claim id (fencing); the lease is advisory. |
| **Lease** | The claim's expiry. Renewed by the holder; once past, the claim reads *expired*. It may be taken over or reaped only after a further `SKEW_GRACE` (60 s), which absorbs clock skew between writers. |
| **Claim id** | A single-use token per claim: 32 hex characters, random or supplied by the caller. Fences stale holders: renew/release/done must present it; once its claim ends the ticket remembers it (`done_by`, or `last_claim_id`), and it is fenced: while it is any ticket's `done_by` or `last_claim_id` it cannot claim again (`NOT_HOLDER`). One claim id names one claim on one ticket. |
| **Stage** | *Stored* lifecycle position: the workflow phases `development`/`review`/`qa` (no forced order) plus the terminal `done`/`cancelled`. A terminal ticket is never claimable again. |
| **Status** | *Derived*, never stored — the availability axis: `open`, `blocked`, `claimed`, `expired`, plus `done`/`cancelled` surfaced from a terminal stage. |
| **Op** | A requested change, carrying the identities it needs (ticket id, and where relevant agent and claim id). |
| **Decision** | What the rules say about an op against a snapshot: apply these changes, no-op, or refuse. |
| **Snapshot** | An immutable view of the store at one revision (`revision`). |
| **Revision** | An opaque handle to one committed state (a git commit id, but never parsed or ordered). |
| **Op record** | The commit message trailers describing an applied op — the audit log entry, including the injected time (`tkt-time`). |

## 3. Layers and boundaries

Four layers, with dependencies pointing **inward only**. An inner layer never
names an outer one; outer layers depend on inner ones through small ports
(protocols) that the inner layer owns.

```text
domain/          ticket · status · operations · outcomes · rules · errors
                   pure values and decisions; imports nothing but itself

application/     store (port) · clock (port) · ids (port)
                 transaction · service · history · errors
                   the use cases; depends on domain + its own ports

infrastructure/  git/{runner · wire · remote · repo} · memory · clock · ids
                   concrete adapters that implement the ports

cli              the `tkt` command (an interface adapter)
__init__         the composition root: `open_store()` wires infrastructure into application
```

Dependency directions:

```text
cli ──► application ──► domain
cli ──► __init__ (open_store)
infrastructure ──► application ──► domain
__init__ ──► application + infrastructure     (the only cross-layer wiring)
```

Ports live with the layer that needs them: `Store`, `Clock` and `IdSource` are
defined in `application/`, and their concrete implementations
(`GitStore`/`MemStore`, `SystemClock`/`FakeClock`, `RandomIds`/`SequentialIds`)
live in `infrastructure/`. `tkt_store.open_store(repo)` is the one place that
chooses those implementations.

Rules (checked by `tests/unit/test_architecture.py`, which also resolves relative
imports and names imported from the package root):

1. **Inward-only.** `domain` imports `domain`; `application` imports
   `domain`+`application`; `infrastructure` imports `domain`+`application`+itself;
   `cli` imports `application` (and `domain` types) + the `open_store` composition
   root (`__init__`); never `infrastructure`. Only the composition root
   (`__init__`, `__main__`) may import across every layer.
2. **Pure domain.** No `domain` module touches IO, git, time or randomness.
3. **One door to git.** Only modules under `infrastructure/git/` invoke `git`/subprocess.
4. **Time and randomness are injected.** Only `infrastructure/clock.py` reads the
   system clock; only `infrastructure/ids.py` creates random values.

The transaction loop depends on the `Store` port, never on a concrete store, so
it is agnostic to git vs in-memory by construction.

## 4. The transaction

Every mutation goes through `application.transaction.transact(store, op, clock)`:

```text
1. snap  = store.snapshot()                 # revision + tickets
2. dec   = rules.decide(snap, op, now)      # pure; dec.record.at = now
3. if dec is Refusal → return Refused       # nothing written
   if dec is NoOp    → return Unchanged     # idempotent repeat
4. try store.commit(snap.revision, dec.changes, dec.record)
       → return Committed(revision, record, tickets)
   except Conflict → goto 1 (bounded attempts), rules re-run on fresh state
```

The **expected old value** in step 4 is the base the decision was computed from,
never a fresh read (lesson from balls' bl-cdec G1).

## 5. Invariants

1. **At most one recorded claim per ticket; stale holders are fenced.** `claim` is refused
   while another claim is not yet takeable (live, or lapsed within `SKEW_GRACE`). Skewed
   clocks can make two writers briefly believe they hold a ticket; what is guaranteed is
   that only the recorded claim id can change it.
2. **One op = one commit**, published by compare-and-swap against its base.
3. **Re-validate after conflict.** Rules always run against the snapshot being committed on.
4. **Fencing.** `renew`, `release`, `done` require the current `claim_id`; otherwise
   `NOT_HOLDER`, or `NOT_CLAIMED` when there is no claim (exact rules in the table below).
   Fencing survives the end of a claim: a completed ticket records the completing claim
   (`done_by`), and the last claim that ended otherwise is recorded too (`last_claim_id`);
   while an id is recorded there on any ticket it cannot claim again (`NOT_HOLDER`). A holder whose lease lapsed may still renew, release or
   complete until someone takes the claim over or reaps it.
5. **Idempotence.** Repeating an op whose effect is already present yields `NoOp`, not an error
   (e.g. `done` on a ticket already done by the same claim, a re-run of a landed `release`,
   a re-run of `claim`/`claim-next` with the same claim id and agent, `add` with an id that
   exists with identical content). Committed and Unchanged outcomes carry the affected
   tickets, and failures carry the op with its ids, so a caller can always re-run with the
   same ids.
6. **Derived status.** No status field is stored; status comes from the stored `stage`
   plus the claim. History comes from the commit trailers. (`stage` itself is stored.)
7. **Carried identity.** Ops carry the identities they need (ticket id, and where
   relevant agent and claim id). Ticket and claim ids are minted *before* the transaction,
   or supplied by the caller, so retries and re-runs reuse them and converge. **Claim ids
   are single-use:** re-use one only to retry the same claim attempt. A claim id names one
   claim on one ticket, and it is fenced once its claim ends; reuse after a later claim
   cycle on that ticket has replaced its `last_claim_id` is not detected.
8. **Injected time.** Lease checks and audit times (`tkt-time`) use the injected clock.
   Expiry is acted on only by `reap` (or by a claim that takes over a lapsed claim), and
   only from `lease_until + SKEW_GRACE` — never implicitly on read. Audit times are
   informational across writers; nothing that grants exclusivity depends on them.
   A lease TTL is bounded: `0 < ttl <= MAX_TTL` (24 h).
9. **Terminal stages are final.** A ticket in `done` or `cancelled` cannot be claimed,
   renewed, released, re-staged or reopened, nor created in a terminal stage. `done` is
   reached only by its holder; `cancel` is administrative. The non-terminal stages carry
   no forced order (rework can move back).
10. **Dependencies gate claims.** While any `blocked_by` entry is not yet `done`, a ticket
    cannot be claimed — even if it carries a lapsed claim — and reads `blocked` unless it
    is live-claimed. A *cancelled* blocker
    does not satisfy a dependency. Blockers do not gate completion: `update` may add a
    blocker to a claimed ticket without disturbing the claim, and the holder may still
    finish it.
11. **No silent overwrite of edits.** `update` names the content `version` it was based
    on; if the ticket was updated since, it is refused `STALE`, never last-writer-wins.
    The version counts content edits only (`add` sets 1, each `update` adds 1), so claims
    and renewals never make an edit stale. Edits to different fields compose: an update
    only writes the fields it names, and every retry re-decides on fresh state.
12. **Validated input.** Ticket ids match `^tkt-[0-9a-f]+$` (they are file names), claim ids
    are exactly 32 lowercase hex characters, `agent`/`reason`/`title` contain no control
    characters (they are written into the commit message), TTLs are within bounds, and
    an update's `expected_version` is at least 1.
    Otherwise `INVALID`.

### Holder ops (`renew`, `release`, `done`)

The single reference for these three ops; the `decide_*` docstrings point here. Checked
in this order after `NOT_FOUND`, the first that applies deciding:

1. terminal stage (first table);
2. `INVALID` `to_stage` (release only: a terminal `to_stage`; use done/cancel);
3. the current claim has `op.claim_id`;
4. an ended claim has it (`op.claim_id == last_claim_id`);
5. no claim;
6. claimed by another.

| op | terminal ticket |
|---|---|
| renew | `TERMINAL` |
| release | `TERMINAL` |
| done | CANCELLED → `TERMINAL`; DONE and `done_by == op.claim_id` → NoOp; DONE otherwise → `NOT_HOLDER` |

| op | 3. current claim matches | 4. ended claim matches | 5. no claim | 6. claimed by another |
|---|---|---|---|---|
| renew | Apply | `NOT_HOLDER` | `NOT_CLAIMED` | `NOT_HOLDER` |
| release | Apply | `to_stage` absent or equal to the current stage → NoOp ("claim ended"); otherwise `NOT_HOLDER` | `NOT_CLAIMED` | `NOT_HOLDER` |
| done | Apply | `NOT_HOLDER` | `NOT_CLAIMED` | `NOT_HOLDER` |

- A matching current claim is accepted even if lapsed, as long as nobody took it over.
- `last_claim_id` is set whenever a claim ends other than by `done`: release, reap,
  takeover, cancel. Because the terminal check comes first, cancel setting it never
  changes a holder-op result.
- A re-run of a landed release (including after a push that landed but was retried, or
  after someone else claimed the ticket) is a NoOp at step 4. A fenced agent cannot move
  the stage: its `release --to-stage X` is refused unless the ticket is already at `X`.

### Other ops

| op | refusals (in order) | NoOp | Apply |
|---|---|---|---|
| init | — | store exists | empty tree (the git store also writes `tkt-store.json` into the root commit) |
| add | `NOT_INITIALISED`, `INVALID` (empty title, unknown/self blocker, terminal stage), `DUPLICATE_ID` | same id and identical AddOp fields (`created`/`updated` not compared) | new ticket |
| update | `NOT_FOUND`, `TERMINAL`, `INVALID` (empty title, unknown/self blocker, cycle); then, unless it is a NoOp, `STALE` if `version != expected_version` | every field it sets already has that value (checked before the version, so a landed re-run converges) | changed fields, `version + 1` |
| claim | `NOT_FOUND`, `TERMINAL`; this ticket's claim has the id, other agent → `ALREADY_CLAIMED`; the id is the current claim on another ticket → `ALREADY_CLAIMED`; ended claim id on any ticket → `NOT_HOLDER`; `BLOCKED`; `ALREADY_CLAIMED` | this ticket's current claim has the same id and agent (live or lapsed) | new claim; a takeover fences the old id |
| claim-next | same claim id on any ticket, other agent → `ALREADY_CLAIMED`; ended claim id on any ticket → `NOT_HOLDER`; `NOTHING_CLAIMABLE` (a `--project` filter matches that exact project only) | some ticket's current claim has the same id and agent (names it) | as claim, on the most urgent claimable match |
| cancel | `NOT_FOUND`, `TERMINAL` (done) | already cancelled | `cancelled`, claim cleared |
| reap | — | no claim past the grace | every claim past the grace cleared, one record |

`validate_op` (shape checks, `INVALID`) runs before all of these.

## 6. Failure model

| Failure | Outcome | Recovery |
|---|---|---|
| Lost race (ref moved) | `Conflict` inside the transaction loop → retry with fresh snapshot | Automatic, bounded (10 attempts) |
| Retries exhausted | `RetriesExhausted(op)` | Caller re-runs `op` with the same ids (idempotent) |
| Crash before push | Unreachable git objects only | Re-run; `git gc` collects garbage |
| Crash after push, before local update | Local behind remote | Next snapshot fetches and fast-forwards (`remote.fetch`, `remote.fast_forward_local`) |
| Remote moved since the snapshot | Push rejected as non-fast-forward → `Conflict` | Transaction re-decides on the fresh snapshot; a manual re-run converges |
| Push landed, local update failed (e.g. another process on the clone moved the ref) | Ignored: the commit is published, `commit` returns it | Next snapshot repairs the local cache |
| Push failed ambiguously (timeout) | `StoreError(op=…)`; the commit may have landed | Re-run `op` with the same ids: converges either way |
| Holder dies | Lease lapses → `expired` status | After `SKEW_GRACE`, `reap` or a new `claim` takes over; old holder fenced by claim id |
| Remote unreachable or not configured | `StoreError` | Retry later; never falls back to local-only |
| Corrupt ticket file, or format version missing/newer | `StoreError` on every snapshot (no partial views) | Fix the file with an ordinary git commit (deliberately bypassing `tkt`), or upgrade the client |

Remote-backed commit order: build objects on `base` → push `new:ref` with `remote.publish`
(non-fast-forward ⇒ `Conflict`, nothing published) → `update-ref ref new base` locally,
best-effort. The remote is authoritative; local refs are a cache. A local-only store has
no push: there `update-ref ref new base` is the compare-and-swap, and a moved ref is a
`Conflict`.

Only `tkt-store.json` and `tickets/tkt-<hex>.json` files are read; any other path is
preserved and ignored.
The store's format version lives in `tkt-store.json` at the tree root and is checked on
every snapshot.

## 7. Deployment model

**Multi-writer: agents read and write the store directly**, each through `tkt`, with
`origin` as the shared remote. Agents normally use their own clone; several processes
sharing one clone are also supported (the local ref is only a cache). A coordinator is
at most an optional convenience, never a safety mechanism. Correctness rests on:

- compare-and-swap on the ref (one op = one commit; lost races retry), and
- claim-id fencing (a stale holder can no longer change the ticket), and
- **a remote that refuses non-fast-forward pushes and deletion of the store branch** — a
  deployment precondition (a self-hosted pre-receive hook, or branch protection on a
  plan that offers it).

**Consistency boundary.** The whole store (one ref) is the unit of consistency: every
op is decided against a snapshot of all tickets and committed by compare-and-swap on that
ref. That is what makes `claim-next`, `reap` and dependency checks safe across tickets,
and it means every write is serialized. `Ticket` is a value inside that boundary, not an
aggregate of its own.

**Trust model.** Agents are trusted to mutate the store *only through `tkt`*. The
remote rules protect history and prevent lost updates; they do not stop a credential
holder from bypassing `tkt` and committing arbitrary content. CAS and fencing bind only
writers that go through the library. Defending against a malicious agent would need
coordinator-gated writes and is out of scope.

**Clocks.** Each writer uses its own clock, so clocks may skew. Leases are advisory and
acted on only after `SKEW_GRACE`; a TTL should comfortably exceed
`renew interval + SKEW_GRACE + expected skew`, and may not exceed `MAX_TTL` (24 h).
Fencing is authoritative.

**Reaping.** `reap` is an idempotent job any writer may run on a schedule (cron, CI).
Concurrent reapers simply conflict and converge.

A local-only store (no remote) remains supported for single-machine use and tests; it
is selected explicitly (`--no-remote`, or `remote=None` in the library), never as a
fallback.

## 8. Open questions and deferred work

- Q1: Should terminal (done/cancelled) tickets be kept on the branch (current design) or moved to `archive/`?
- Q2: Project identity is now the caller's concern (an opaque string). Should callers
  standardise on root-commit hash (stable, but multi-root repos) or
  normalised remote URL (renames)? Out of scope for the store itself.
- Q3: Should `claim_next` (pick highest-priority claimable) be an op (atomic choice) — current design — or a read + claim?
- Q4: Lease units: integer seconds since epoch (current) vs ISO timestamps in files.
- Deferred: jittered backoff between conflict retries (via a future `Clock.sleep` and a
  randomness port in `infrastructure/ids.py`, never `IdSource`); today retries are
  bounded at 10 and fetch/push round trips spread writers.
- Deferred: an administrative release that frees a dead holder's ticket without
  cancelling it, before `MAX_TTL` plus the grace.
- Deferred: `claim-next` choosing randomly among the top candidates to spread contention.
