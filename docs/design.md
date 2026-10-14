# tkt-store — design

Status: **skeleton for review.** This document is the authority on concepts,
boundaries and invariants.

## 1. Purpose and scope

tkt-store answers one question reliably: **which tickets exist, and who holds
which one right now.** It stores tickets on a git branch and changes them only by
atomic, compare-and-swap commits.

Out of scope (belongs to the coordinator or later packages): running agents,
sandboxes, worktrees, delivering or merging code, approvals, notifications,
syncing with Jira/GitHub, multiple stores.

## 2. Concepts

| Term | Meaning |
|---|---|
| **Store** | One git ref (default `refs/heads/tkt`) holding `tickets/<id>.json`, optionally backed by a remote. |
| **Ticket** | A unit of work: title, body, kind (story/task/bug), project, priority, dependencies, tags. |
| **Project** | An opaque identifier for the code repo a ticket belongs to. Supplied by the caller; the store neither derives nor interprets it. |
| **Claim** | Exclusive, time-limited holding of a ticket: `agent`, `claim_id`, `lease_until`. Stored inside the ticket. |
| **Lease** | The claim's expiry. Renewed by the holder; once past, the claim is *expired* and may be reaped or taken. |
| **Claim id** | A random token minted per claim. Fences stale holders: renew/release/done must present it. |
| **Stage** | *Stored* lifecycle position: the workflow phases `development`/`review`/`qa` (no forced order) plus the terminal `done`/`cancelled`. A terminal ticket is never claimable again. |
| **Status** | *Derived*, never stored — the availability axis: `open`, `blocked`, `claimed`, `expired`, plus `done`/`cancelled` surfaced from a terminal stage. |
| **Op** | A requested change, carrying every identity it needs (ticket id, agent, claim id). |
| **Decision** | What the rules say about an op against a snapshot: apply these changes, no-op, or refuse. |
| **Snapshot** | An immutable view of the store at one revision (`base`). |
| **Revision** | An opaque handle to one committed state (a git commit id, but never parsed or ordered). |
| **Op record** | The commit message trailers describing an applied op — the audit log entry. |

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

Rules (checked by `tests/unit/test_architecture.py`):

1. **Inward-only.** `domain` imports `domain`; `application` imports
   `domain`+`application`; `infrastructure` imports `domain`+`application`+itself;
   `cli` imports `domain`+`application`+ the composition root. Only the composition
   root (`__init__`, `__main__`) may import across every layer.
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
2. dec   = rules.decide(snap, op, now)      # pure
3. if dec is Refusal → return Refused       # nothing written
   if dec is NoOp    → return Unchanged     # idempotent repeat
4. try store.commit(snap.base, dec.changes, dec.record)
       → return Committed(new_revision)
   except Conflict → goto 1 (bounded attempts), rules re-run on fresh state
```

The **expected old value** in step 4 is the base the decision was computed from,
never a fresh read (lesson from balls' bl-cdec G1).

## 5. Invariants

1. **At most one live holder per ticket.** `claim` is refused if a non-expired claim exists.
2. **One op = one commit**, published by compare-and-swap against its base.
3. **Re-validate after conflict.** Rules always run against the snapshot being committed on.
4. **Fencing.** `renew`, `release`, `done` require the current `claim_id`; otherwise `NOT_HOLDER`.
5. **Idempotence.** Repeating an op whose effect is already present yields `NoOp`, not an error
   (e.g. `done` on a ticket already done by the same claim; `add` with an id that exists with identical content).
6. **Derived status.** No status field is stored; status comes from the stored `stage`
   plus the claim, and claim age and history come from git. (`stage` itself is stored.)
7. **Carried identity (A4).** Ops carry ticket id, agent and claim id. Ticket and claim ids are
   minted *before* the transaction, so retries reuse them.
8. **Injected time.** Lease checks use the injected clock. Expiry is acted on only by `reap`
   (or by a claim that takes over an expired ticket) — never implicitly on read.
9. **Terminal stages are final.** A ticket in `done` or `cancelled` cannot be claimed,
   renewed, released, re-staged or reopened. `done` is reached only by its holder; `cancel`
   is administrative. The non-terminal stages carry no forced order (rework can move back).
10. **Dependencies gate claims.** A ticket is `blocked` while any `blocked_by` entry is not yet
    `done`, and cannot be claimed. A *cancelled* blocker does not satisfy a dependency.

## 6. Failure model

| Failure | Outcome | Recovery |
|---|---|---|
| Lost race (ref moved) | `Conflict` inside the transaction loop → retry with fresh snapshot | Automatic, bounded |
| Retries exhausted | `RetriesExhausted` raised | Caller re-runs the op (idempotent) |
| Crash before commit | Unreachable git objects only | Re-run; `git gc` collects garbage |
| Crash after local update, before push (remote-backed) | Local ahead of remote | Next op/`sync` pushes, or rebases a single-ticket commit if remote moved |
| Crash after push, before local update | Local behind remote | Next snapshot fetches and fast-forwards |
| Holder dies | Lease expires → `expired` status | `reap` or a new `claim` takes over; old holder fenced by claim id |
| Remote unreachable | `StoreError` | Retry later; local-only stores are unaffected |

Remote-backed commit order: build objects on `base` → push `new:ref` (non-fast-forward ⇒ `Conflict`)
→ `update-ref ref new base` locally. The remote is authoritative; local refs are a cache.

## 7. Deployment assumption

The intended deployment is **one coordinator as the only writer** to one store
repository. Agents never write the store. Multi-writer use is supported by the
compare-and-swap design but is not the primary target.

## 8. Open questions for review

- Q1: Should terminal (done/cancelled) tickets be kept on the branch (current design) or moved to `archive/`?
- Q2: Project identity is now the caller's concern (an opaque string). Should the
  coordinator standardise on root-commit hash (stable, but multi-root repos) or
  normalised remote URL (renames)? Out of scope for the store itself.
- Q3: Should `claim_next` (pick highest-priority claimable) be an op (atomic choice) — current design — or a read + claim?
- Q4: Lease units: integer seconds since epoch (current) vs ISO timestamps in files.
