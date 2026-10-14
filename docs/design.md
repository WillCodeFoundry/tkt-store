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
| **Store** | One git ref (default `refs/heads/tkt`) holding `tickets/<id>.json`, normally backed by a remote (`origin`). |
| **Ticket** | A unit of work: title, body, kind (story/task/bug), project, priority, dependencies, tags. |
| **Project** | An opaque identifier for the code repo a ticket belongs to. Supplied by the caller; the store neither derives nor interprets it. |
| **Claim** | Exclusive holding of a ticket: `agent`, `claim_id`, `lease_until`. Stored inside the ticket. Exclusivity is enforced by the claim id (fencing); the lease is advisory. |
| **Lease** | The claim's expiry. Renewed by the holder; once past, the claim reads *expired*. It may be taken over or reaped only after a further `SKEW_GRACE` (60 s), which absorbs clock skew between writers. |
| **Claim id** | A token per claim (random, or supplied by the caller). Fences stale holders: renew/release/done must present it, and a completed ticket remembers it (`closed_by`). |
| **Stage** | *Stored* lifecycle position: the workflow phases `development`/`review`/`qa` (no forced order) plus the terminal `done`/`cancelled`. A terminal ticket is never claimable again. |
| **Status** | *Derived*, never stored — the availability axis: `open`, `blocked`, `claimed`, `expired`, plus `done`/`cancelled` surfaced from a terminal stage. |
| **Op** | A requested change, carrying the identities it needs (ticket id, and where relevant agent and claim id). |
| **Decision** | What the rules say about an op against a snapshot: apply these changes, no-op, or refuse. |
| **Snapshot** | An immutable view of the store at one revision (`base`). |
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
1. snap  = store.snapshot()                 # base revision + tickets
2. dec   = rules.decide(snap, op, now)      # pure; dec.record.at = now
3. if dec is Refusal → return Refused       # nothing written
   if dec is NoOp    → return Unchanged     # idempotent repeat
4. try store.commit(snap.base, dec.changes, dec.record)
       → return Committed(new_revision)
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
4. **Fencing.** `renew`, `release`, `done` require the current `claim_id`; otherwise `NOT_HOLDER`.
   Fencing survives completion: a `done` ticket records the completing claim (`closed_by`).
   A holder whose lease lapsed may still renew, release or complete until someone takes
   the claim over or reaps it.
5. **Idempotence.** Repeating an op whose effect is already present yields `NoOp`, not an error
   (e.g. `done` on a ticket already done by the same claim, `release --to-stage X` on an
   unclaimed ticket already at `X`, `add` with an id that exists with identical content).
6. **Derived status.** No status field is stored; status comes from the stored `stage`
   plus the claim. History comes from the commit trailers. (`stage` itself is stored.)
7. **Carried identity (A4).** Ops carry the identities they need (ticket id, and where
   relevant agent and claim id). Ticket and claim ids are minted *before* the transaction,
   or supplied by the caller, so retries and re-runs reuse them and converge.
8. **Injected time.** Lease checks and audit times (`tkt-time`) use the injected clock.
   Expiry is acted on only by `reap` (or by a claim that takes over a lapsed claim), and
   only from `lease_until + SKEW_GRACE` — never implicitly on read. Audit times are
   informational across writers; nothing that grants exclusivity depends on them.
9. **Terminal stages are final.** A ticket in `done` or `cancelled` cannot be claimed,
   renewed, released, re-staged or reopened, nor created in a terminal stage. `done` is
   reached only by its holder; `cancel` is administrative. The non-terminal stages carry
   no forced order (rework can move back).
10. **Dependencies gate claims.** A ticket is `blocked` while any `blocked_by` entry is not yet
    `done`, and cannot be claimed — even if it carries a lapsed claim. A *cancelled* blocker
    does not satisfy a dependency.
11. **Validated input.** Ticket ids match `^tkt-[0-9a-f]+$` (they are file names), claim ids
    `^[0-9a-f]+$`, and `agent`/`reason`/`title` contain no control characters (they are
    written into the commit message). Otherwise `INVALID`.

## 6. Failure model

| Failure | Outcome | Recovery |
|---|---|---|
| Lost race (ref moved) | `Conflict` inside the transaction loop → retry with fresh snapshot | Automatic, bounded |
| Retries exhausted | `RetriesExhausted` raised | Caller re-runs the op with the same ids (idempotent) |
| Crash before push | Unreachable git objects only | Re-run; `git gc` collects garbage |
| Crash after push, before local update | Local behind remote | Next snapshot fetches and fast-forwards (`remote.fetch`, `remote.fast_forward_local`) |
| Remote moved since the snapshot | Push rejected as non-fast-forward → `Conflict` | Transaction re-decides on the fresh snapshot; a manual re-run converges |
| Holder dies | Lease lapses → `expired` status | After `SKEW_GRACE`, `reap` or a new `claim` takes over; old holder fenced by claim id |
| Remote unreachable or not configured | `StoreError` | Retry later; never falls back to local-only |

Remote-backed commit order: build objects on `base` → push `new:ref` with `remote.publish`
(non-fast-forward ⇒ `Conflict`) → `update-ref ref new base` locally. The local ref only
moves after the push, so local is never ahead of the remote. The remote is authoritative;
local refs are a cache.

## 7. Deployment model

**Multi-writer: agents read and write the store directly**, each through `tkt` in its
own clone of the store repository, with `origin` as the shared remote. A coordinator
is at most an optional convenience, never a safety mechanism. Correctness rests on:

- compare-and-swap on the ref (one op = one commit; lost races retry), and
- claim-id fencing (a stale holder can no longer change the ticket), and
- **a remote that refuses non-fast-forward pushes and deletion of the store branch** — a
  deployment precondition (a self-hosted pre-receive hook, or branch protection on a
  plan that offers it).

**Trust model.** Agents are trusted to mutate the store *only through `tkt`*. The
remote rules protect history and prevent lost updates; they do not stop a credential
holder from bypassing `tkt` and committing arbitrary content. CAS and fencing bind only
writers that go through the library. Defending against a malicious agent would need
coordinator-gated writes and is out of scope.

**Clocks.** Each writer uses its own clock, so clocks may skew. Leases are advisory and
acted on only after `SKEW_GRACE`; a TTL should comfortably exceed
`renew interval + SKEW_GRACE + expected skew`. Fencing is authoritative.

**Reaping.** `reap` is an idempotent job any writer may run on a schedule (cron, CI).
Concurrent reapers simply conflict and converge.

A local-only store (no remote) remains supported for single-machine use and tests; it
is selected explicitly (`--no-remote`), never as a fallback.

## 8. Open questions for review

- Q1: Should terminal (done/cancelled) tickets be kept on the branch (current design) or moved to `archive/`?
- Q2: Project identity is now the caller's concern (an opaque string). Should callers
  standardise on root-commit hash (stable, but multi-root repos) or
  normalised remote URL (renames)? Out of scope for the store itself.
- Q3: Should `claim_next` (pick highest-priority claimable) be an op (atomic choice) — current design — or a read + claim?
- Q4: Lease units: integer seconds since epoch (current) vs ISO timestamps in files.
