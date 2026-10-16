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
| **Store** | One git ref (default `refs/heads/tkt-store`, the branch `tkt-store`) holding `tickets/<id>.json`, published to a shared remote (normally `origin`) and cached in each agent's clone. The unit of consistency: every op is decided on a snapshot of the whole store (see §7). |
| **Ticket** | A unit of work. Its fields fall into five groups, each changed one way (see *Data model* below). |
| **Project** | An opaque identifier for the code repo a ticket belongs to. Supplied by the caller; the store neither derives nor interprets it. |
| **Claim** | Exclusive holding of a ticket: `agent`, `claim_id`, `lease_until`, `claimed_at`. Stored inside the ticket. Exclusivity is enforced by the claim id (fencing); the lease is advisory. |
| **Lease** | The claim's expiry. Renewed by the holder; once past, the claim reads *expired*. It may be taken over or reaped only after a further `SKEW_GRACE` (60 s), which absorbs clock skew between writers. |
| **Claim id** | A single-use token per claim: 32 hex characters, random or supplied by the caller. Fences stale holders: renew/move/release/done must present it; once its claim ends the ticket records it in `ended_claim_ids` (the full history), and an id in any ticket's `ended_claim_ids` can never claim again (`NOT_HOLDER`). One claim id names one claim on one ticket. |
| **Phase** | *Stored* workflow position: which kind of work (or agent role) the ticket waits for. A fixed set named after swarm-forge's roles plus common human steps: `triage`, `specification`, `implementation`, `cleanup`, `architecture`, `hardening`, `qa`, `review`, `release`. No forced order. Moved only by the holder's `move`. |
| **Resolution** | *Stored*, set once: `done` (by the holder) or `cancelled` (by anyone). A resolved ticket is terminal: never claimable or editable again. |
| **Status** | *Derived*, never stored — the availability axis: `open`, `blocked`, `claimed`, `expired`, plus `done`/`cancelled` surfaced from the resolution. |
| **Op** | A requested change, carrying the identities it needs (ticket id, and where relevant agent and claim id). |
| **Decision** | What the rules say about an op against a snapshot: apply these changes, no-op, or refuse. |
| **Snapshot** | An immutable view of the store at one revision (`revision`). |
| **Revision** | An opaque handle to one committed state (a git commit id, but never parsed or ordered). |
| **Op record** | The commit message trailers describing an applied op — the audit log entry, including the injected time (`tkt-time`). |

### Data model

Every ticket field belongs to exactly one group, and each group has one way to change.
That is the whole mental model: to know how a field behaves, find its group.

| Group | Fields | Changed by | Guard |
|---|---|---|---|
| Identity | `id`, `kind`, `project`, `created` | `add` only | never changes |
| Content | `title`, `body`, `priority`, `blocked_by`, `tags`, `content_version` | `edit`, by anyone (from 0.2.0: only the holder while held, §5) | not resolved; must name the `content_version` it was based on (`STALE` otherwise) |
| Workflow | `phase`, `resolution` | `move` (holder), `done` (holder), `cancel` (anyone): the lifecycle table below | per transition; `resolution` is set once |
| Occupancy | `claim`, `ended_claim_ids` | `claim`, `claim-next`, `renew`, `release`, `done`, `reap`, `cancel` | holder ops (`renew`, `move`, `release`, `done`) fenced by claim id (holder-op table, §5); `reap` and `cancel` deliberately unfenced |
| Bookkeeping | `updated`, unknown keys | the system | — |

Lifecycle (workflow group):

| From | Op | To | Who |
|---|---|---|---|
| — | `add --phase P` | phase P, unresolved | anyone |
| unresolved, held | `move --to-phase P` | phase P, still held | the holder |
| unresolved, held | `release` | same phase, unheld | the holder |
| unresolved, held | `done` | resolution `done` | the holder |
| unresolved | `cancel` | resolution `cancelled` (any claim ended) | anyone — deliberately unfenced |
| resolved | anything | refused `TERMINAL`, except: `done` by the same claim → no-op, `done` by another claim → `NOT_HOLDER`, `cancel` when already cancelled → no-op | — |

Every command changes one group, with two deliberate exceptions: `done` and `cancel` end
the claim (occupancy) as they resolve the ticket (workflow), because a finished ticket
cannot stay held. A handoff is two commands, `move` then `release`. In that order the
in-between state is "still held, already in the new phase", which is harmless: if the
holder crashes between them, the lease lapses and the ticket becomes available in the
right phase. A resolved ticket keeps the phase it finished in.

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
__init__         the composition root: `open_store()` wires infrastructure into application;
                 `new_id_source()` gives callers that mint ids themselves (`tkt mint`) the
                 production id source
```

Dependency directions:

```text
cli ──► application ──► domain
cli ──► __init__ (open_store, new_id_source)
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
   `cli` imports `application` (and `domain` types) + the composition root
   (`__init__`: `open_store`, `new_id_source`); never `infrastructure`. The CLI prints
   tickets with `Ticket.to_dict()`, the same plain data the git store serialises. Only the composition root
   (`__init__`, `__main__`) may import across every layer.
2. **Pure domain.** No `domain` module touches IO, git, time or randomness.
3. **One door to git.** Only modules under `infrastructure/git/` invoke `git`/subprocess.
4. **Time and randomness are injected.** Only `infrastructure/clock.py` reads the
   system clock (and sleeps); only `infrastructure/ids.py` creates random values
   (ids, and backoff jitter).

The transaction loop depends on the `Store` port, never on a concrete store, so
it is agnostic to git vs in-memory by construction.

## 4. The transaction

Every mutation goes through `application.transaction.transact(store, op, clock, *, backoff)`:

```text
0. wait_after_loss = backoff.begin()        # an attempt starts (it is timed)
1. snap  = store.snapshot()                 # revision + tickets
2. dec   = rules.decide(snap, op, now)      # pure; dec.record.at = now
3. if dec is Refusal → return Refused       # nothing written
   if dec is NoOp    → return Unchanged     # idempotent repeat
4. try store.commit(snap.revision, dec.changes, dec.record)
       → return Committed(revision, record, tickets)
   except Conflict → wait_after_loss(attempt), goto 0 (bounded attempts), rules
                     re-run on fresh state
```

**Backoff.** Between lost races the loop waits through the `Backoff` port: the
production `JitteredBackoff` (`infrastructure/backoff.py`, wired by `open_store`) waits a
uniform random time ("full jitter") from a window counted in *slots*, where a slot is
how long the attempt that lost took: 1, 2, 4, … slots, capped at 60 s. Attempts take
seconds against GitHub and milliseconds against a local ref, so the same policy fits
both without tuning, and contending writers spread out instead of colliding again.
The cap bounds the total: at most 9 waits of 60 s (9 minutes) plus the 10 attempts
themselves, however slow; with ~3.5 s attempts, about 6 minutes at worst and 3 on
average. That fits the 10 minutes (plus the 60 s grace) a renewal at two-thirds of a
30-minute lease leaves, so the cap should not exceed 60 s. The backoff keeps no state
between attempts. Without a backoff the loop retries at once (tests). Measured effect:
ADR 0001.

The **expected old value** in step 4 is the base the decision was computed from,
never a fresh read (lesson from balls' bl-cdec G1).

## 5. Invariants

1. **At most one recorded claim per ticket; stale holders are fenced.** `claim` is refused
   while another claim is not yet takeable (live, or lapsed within `SKEW_GRACE`). Skewed
   clocks can make two writers briefly believe they hold a ticket; what is guaranteed is
   that only the recorded claim id can change it.
2. **One op = one commit**, published by compare-and-swap against its base.
3. **Re-validate after conflict.** Rules always run against the snapshot being committed on.
4. **Fencing.** `renew`, `move`, `release`, `done` require the current `claim_id`;
   otherwise `NOT_HOLDER`, or `NOT_CLAIMED` when there is no claim (exact rules in the
   table below). Fencing survives the end of a claim: every claim that ends (released,
   reaped, taken over, cancelled, done) is appended to the ticket's `ended_claim_ids`, a
   complete history, and an id recorded there on any ticket can never claim again
   (`NOT_HOLDER`). A holder whose lease lapsed may still renew, move, release or
   complete until someone takes the claim over or reaps it.
5. **Idempotence.** Repeating an op whose effect is already present yields `NoOp`, not an error
   (e.g. `done` on a ticket already done by the same claim, a re-run of a landed `move` or
   `release` however many claims came since, a re-run of `claim`/`claim-next` with the
   same claim id and agent (which renews the claim if it lapsed), a re-run of `add` —
   see the add row below). Committed and Unchanged outcomes carry the affected
   tickets, and failures carry the op with its ids, so a caller can always re-run with the
   same ids.
6. **Derived status.** No status field is stored; status comes from the stored
   `resolution`, the claim and the blockers. History comes from the commit trailers.
   (`phase` and `resolution` themselves are stored.)
7. **Carried identity.** Ops carry the identities they need (ticket id, and where
   relevant agent and claim id). Ticket and claim ids are minted *before* the transaction,
   or supplied by the caller, so retries and re-runs reuse them and converge. **Claim ids
   are single-use:** re-use one only to retry the same claim attempt. A claim id names one
   claim on one ticket, and it is fenced for good once its claim ends.
8. **Injected time.** Lease checks and audit times (`tkt-time`) use the injected clock.
   Expiry is acted on only by `reap` (or by a claim that takes over a lapsed claim), and
   only from `lease_until + SKEW_GRACE` — never implicitly on read. Audit times are
   informational across writers; nothing that grants exclusivity depends on them.
   A lease TTL is bounded: `0 < ttl <= MAX_TTL` (2 h).
9. **Resolution is final.** A resolved ticket (`done` or `cancelled`) cannot be claimed,
   renewed, released, edited, re-phased or reopened; a ticket cannot be created resolved.
   `done` is reached only by its holder; `cancel` is administrative. Phases carry no
   forced order (rework can move back).
10. **Dependencies gate claims.** While any `blocked_by` entry is not yet `done`, a ticket
    cannot be newly claimed — even if it carries a lapsed claim (the holder's own re-run
    still renews it, like `renew`) — and reads `blocked` unless it
    is live-claimed. A *cancelled* blocker
    does not satisfy a dependency. Blockers do not gate completion: `edit` may add a
    blocker to a claimed ticket without disturbing the claim (from 0.2.0 only its holder
    may), and the holder may still finish it.
11. **No silent overwrite of edits.** `edit` names the `content_version` it was based
    on; if it was edited since (its `content_version` moved on), it is refused `STALE`,
    never last-writer-wins.
    It counts content edits only (`add` sets 1, each `edit` adds 1), so claims
    and renewals never make an edit stale. Edits to different fields compose: an edit
    only writes the fields it names, and every retry re-decides on fresh state.
12. **Validated input.** Ticket ids match `^tkt-[0-9a-f]+$` (they are file names), claim ids
    are exactly 32 lowercase hex characters, `agent`/`reason`/`title` contain no control
    characters (they are written into the commit message), TTLs are within bounds, and
    an edit's `expected_version` is at least 1.
    Otherwise `INVALID`.

### Holder ops (`renew`, `move`, `release`, `done`)

The single reference for these four ops; the `decide_*` docstrings point here. Checked
in this order after `NOT_FOUND`, the first that applies deciding:

1. resolved ticket (first table);
2. the current claim has `op.claim_id`;
3. an ended claim has it (`op.claim_id in ended_claim_ids`);
4. no claim;
5. claimed by another.

| op | resolved ticket |
|---|---|
| renew | `TERMINAL` |
| move | `TERMINAL` |
| release | `TERMINAL` |
| done | cancelled → `TERMINAL`; done and `op.claim_id` is the last of `ended_claim_ids` → NoOp; done otherwise → `NOT_HOLDER` |

| op | 2. current claim matches | 3. ended claim matches | 4. no claim | 5. claimed by another |
|---|---|---|---|---|
| renew | Apply | `NOT_HOLDER` | `NOT_CLAIMED` | `NOT_HOLDER` |
| move | already in `to_phase` → NoOp; otherwise Apply | already in `to_phase` → NoOp; otherwise `NOT_HOLDER` ("claim ended before the move") | `NOT_CLAIMED` | `NOT_HOLDER` |
| release | Apply | NoOp ("claim already ended") | `NOT_CLAIMED` | `NOT_HOLDER` |
| done | Apply | `NOT_HOLDER` | `NOT_CLAIMED` | `NOT_HOLDER` |

- A matching current claim is accepted even if lapsed, as long as nobody took it over.
- Every claim end appends to `ended_claim_ids`: release, reap, takeover, cancel, done.
  The list is never truncated, so step 3 recognises an ended claim however many claims
  came after it. A ticket only accumulates a handful of claims in its life, so the list
  stays small.
- A re-run of a landed `move` or `release` (including after a push that landed but was
  retried, or after other claims came and went) is a NoOp at step 3. A fenced agent
  cannot move the phase: its `move` is refused unless the ticket is already there.
- Refusal messages say which case applied: "claim already ended on this ticket" (step 3
  for renew/done), "claim was never used on this ticket", or "held by another claim".

### Other ops

| op | refusals (in order) | NoOp | Apply |
|---|---|---|---|
| init | — | store exists | empty tree (the git store also writes `tkt-store.json` into the root commit) |
| add | `NOT_INITIALISED`, `INVALID` (empty title, unknown/self blocker); id exists: `DUPLICATE_ID` if `kind`/`project` differ, or if never edited and the content differs | id exists with the same identity, and either the same content or edited since (workflow and occupancy are never compared) | new ticket |
| edit | `NOT_FOUND`, `TERMINAL`, `INVALID` (empty title, unknown/self blocker, cycle); then, unless it is a NoOp, `STALE` if `content_version != expected_version` | every field it sets already has that value (checked before the version, so a landed re-run converges) | changed fields, `content_version + 1` |
| claim | `NOT_FOUND`, `TERMINAL`; this ticket's claim has the id, other agent → `ALREADY_CLAIMED`; the id is the current claim on another ticket → `ALREADY_CLAIMED`; ended claim id on any ticket → `NOT_HOLDER`; `BLOCKED`; `ALREADY_CLAIMED` | this ticket's current claim has the same id and agent and is live | new claim; a takeover fences the old id; the same id and agent on a lapsed claim renews it |
| claim-next | same claim id on any ticket, other agent → `ALREADY_CLAIMED`; ended claim id on any ticket → `NOT_HOLDER`; `NOTHING_CLAIMABLE` (a `--project` filter matches that exact project only) | some ticket's current claim has the same id and agent and is live (names it) | as claim, on the most urgent claimable match; the same id and agent on a lapsed claim renews it |
| cancel | `NOT_FOUND`, `TERMINAL` (done) | already cancelled | resolution `cancelled`, claim cleared |
| reap | — | no claim past the grace | every claim past the grace cleared, one record |

`validate_op` (shape checks, `INVALID`) runs before all of these.

### Changes in 0.2.0 (ADR 0005, §8)

- **Claims store a hash.** `claim.claim_id` and `ended_claim_ids` hold the SHA-256 of
  each claim id (64 lowercase hex), and so does the `tkt-claim` trailer. Every rule above
  compares hashes, so fencing and re-runs are unchanged; a re-run is recognised by the
  hash alone (no agent comparison). Callers always supply claim ids (the CLI already
  does; the library stops minting them), since a minted id could not be read back.
- **The holder is recorded, not declared.** No op takes an agent name. A claim records
  `holder`: the claimer's git name, mapped to an identifier (accents folded, each run of
  other characters one `-`, ends trimmed, at most 39 characters; refused only if nothing
  is left). Who did each op is the commit's author.
- **edit while held** needs the holder's claim id; anyone else is refused `NOT_HOLDER`.
  An unheld ticket may be edited by anyone, as before.
- **revoke** (new, anyone, optional reason): `NOT_FOUND`; `TERMINAL` if resolved; NoOp
  if not claimed; otherwise the claim ends (its hash appended to `ended_claim_ids`) and
  the ticket stays open in its phase. The holder's next `renew`, `move` or `done` is
  `NOT_HOLDER`, its `release` a NoOp, and both messages say the claim was revoked.
- **add** of an id whose file is set aside on reading (§8) is `DUPLICATE_ID`: the id is
  taken, and the file is evidence.
- **Blockers:** writes still refuse unknown or self blockers; on reading, a blocker that
  is missing or set aside counts as not done.
- **Leases:** a lease ending more than `MAX_TTL` + `SKEW_GRACE` after now is treated as
  takeable (and reads expired); honest leases never are, since the cap is relative to
  now.

## 6. Failure model

| Failure | Outcome | Recovery |
|---|---|---|
| Lost race (ref moved) | `Conflict` inside the transaction loop → jittered backoff, retry with fresh snapshot | Automatic, bounded (10 attempts) |
| Retries exhausted | `RetriesExhausted(op)` | Caller re-runs `op` with the same ids (idempotent) |
| Crash before push | Unreachable git objects only | Re-run; `git gc` collects garbage |
| Crash after push, before local update | Local behind remote | Next snapshot fetches and fast-forwards (`remote.fetch`, `remote.fast_forward_local`) |
| Remote moved since the snapshot | Push rejected, nothing published: by our own git client's lease check (`[rejected] (stale info)`) → `Conflict`; or by the server (`[remote rejected] (…)`, whatever the wording), after which one `ls-remote` shows whether the branch moved → `Conflict`, or not (refused for another reason: protection, a hook) → `StoreError`; if it already holds our commit, the push counts as published | Transaction re-decides on the fresh snapshot; a manual re-run converges |
| Push landed, local update failed | Ignored: the commit is published, `commit` returns it | Next snapshot repairs the local cache |
| Push failed ambiguously (timeout) | `StoreError(op=…)`; the commit may have landed | Re-run `op` with the same ids: converges either way |
| Holder dies | Lease lapses → `expired` status | After `SKEW_GRACE`, `reap` or a new `claim` takes over; old holder fenced by claim id |
| Remote unreachable or not configured | `StoreError` | Retry later |
| Corrupt ticket file (until 0.2.0), or format version missing/newer | `StoreError` on every snapshot (no partial views) | An operator fixes the file with an ordinary git commit, or upgrades the client. From 0.2.0 an invalid ticket is set aside and reported instead (§8) |

Commit order: build objects on `base` → push `new:ref` with `remote.publish`
(a rejection with the branch moved ⇒ `Conflict`, nothing published; with the branch
unmoved, e.g. branch protection or a hook ⇒ `StoreError`; no server wording is parsed) → `update-ref ref new base` locally, best-effort. A snapshot
fetches the ref into a private ref (`refs/tkt-store-remotes/<remote>/…`) that only this
code writes, and takes its revision from that ref. It then catches the local ref up by
compare-and-swap; a local ref with commits the remote lacks (made outside `tkt`) is a
`StoreError` before anything is written. The remote is authoritative; local refs are a
cache.

Only `tkt-store.json` and `tickets/tkt-<hex>.json` files are read; any other path is
preserved and ignored.
The store's format version lives in `tkt-store.json` at the tree root and is checked on
every snapshot. The push states its
expected old value (`--force-with-lease=<ref>:<base>`), so compare-and-swap does not rely
on branch protection alone.

## 7. Deployment model

**Multi-writer: agents read and write the store directly**, each through `tkt`, with
`origin` as the shared remote. **One process per clone** is the recommended setup: each
agent gets its own clone. A coordinator
is at most an optional convenience, never a safety mechanism. Correctness rests on:

- compare-and-swap on the ref (one op = one commit; lost races retry), and
- claim-id fencing (a stale holder can no longer change the ticket), and
- **a remote that refuses non-fast-forward pushes and deletion of the store branch**
  (`tkt-store` by default) — a deployment precondition: on GitHub, a ruleset on the
  branch; on a self-hosted bare repository, `receive.denyNonFastForwards` and
  `receive.denyDeletes`. `scripts/check_remote.py` verifies it (README, *Deploying*).

**Consistency boundary.** The whole store (one ref) is the unit of consistency: every
op is decided against a snapshot of all tickets and committed by compare-and-swap on that
ref. That is what makes `claim-next`, `reap` and dependency checks safe across tickets,
and it means every write is serialized. `Ticket` is a value inside that boundary, not an
aggregate of its own.

**Trust model.** Agents are confined to `tkt`: they never run git against the store.
The remote rules protect history and prevent lost updates; they do not stop a credential
holder from bypassing `tkt` and committing arbitrary content. CAS, fencing and validation
bind only writers that go through `tkt`. What one compromised agent can and cannot do
to the others is §8.

**Clocks.** Each writer uses its own clock, so clocks may skew. Leases are advisory and
acted on only after `SKEW_GRACE`; a TTL should comfortably exceed
`renew interval + SKEW_GRACE + expected skew`, and may not exceed `MAX_TTL` (2 h).
Fencing is authoritative.

**Scale.** Designed for about 10 agents working in parallel on tasks of tens of minutes.
Every write is a push, so throughput is bounded by the remote's round trip and by any
push-rate limit a hosting service sets. Measurements and the options beyond: ADR 0001.

**Crash recovery is lease expiry.** A crashed agent's ticket becomes takeable at most
`ttl + SKEW_GRACE` after its last renewal (about 31 minutes with a 30-minute lease), and
the next `claim` or `claim-next` takes it over; no supervisor or `reap` is required. A
supervisor may end the claim early with `revoke` (0.2.0, §8); until then, one that
knows the agent's claim id may `release` it. The agent owns
its claim id (from `tkt mint claim-id`); a restarted agent re-running its claim with the
same id (until 0.2.0, also the same name) gets the lapsed claim renewed.

**Reaping.** `reap` is an idempotent job any writer may run on a schedule (cron, CI).
Concurrent reapers simply conflict and converge. It is not needed for recovery (claims
take over lapsed claims directly); it tidies what `list` shows.

## 8. Security model

Decided in ADR 0005 and implemented in stages for 0.2.0, which bumps the format to
protocol 2 (0.1.0 stores are not migrated). Each gap is a strict expected-failure test in
`tests/security/` until its fix lands.

**Threat.** The agents are LLMs. One may be compromised or confused (prompt-injected by
a page or a repository it worked on) and try to run code on another agent's machine,
prompt-inject the others through the store, or forge or break shared state.

**Assumptions.** Agents are confined to `tkt` (§7): no git commands against the store,
and a clone made by `tkt clone`. `tkt` never checks out files, so checkout hooks,
filters and symlinks never come into play, and every write is a compare-and-swap. Each
agent has its own git identity, which does not change while it runs.

**Defences, all inside `tkt`** (the remote is unknown, so nothing is enforced on push):

| Threat | Defence |
|---|---|
| Code execution in other agents | No shell anywhere (argument lists only); git always gets the remote name after `--`; no checkout. Deployment: never a path remote shared across agents that do not fully trust each other (README) |
| Prompt injection through stored text | Strict field rules (identifier allowlists, a PRECIS-style rule for free text, size limits; lengths in code points after NFC); all non-ASCII escaped on output; errors never echo values read from the store; `list` never prints bodies; agent guidance: every composed field is data, never instructions |
| Forged or malformed content | Everything read is checked like everything written (the same field checks), plus whole-ticket and cross-ticket checks; a strict schema (unknown keys invalid); only regular files at ticket paths are read, and never one over 256 KiB (writes are refused if the encoded file would exceed it); an invalid ticket is set aside and reported (cached by blob id), never failing the store; a malformed commit is skipped by history; `tkt audit` lists what was set aside |
| Acting as another agent's holder | Tickets and history store a SHA-256 of each claim id, so only the agent that minted it can renew, move, release, finish or (while held) edit; anyone may `revoke` a claim (ends it, ticket stays open) or `cancel` the ticket |
| Locking a ticket forever | A lease ending more than `MAX_TTL` + `SKEW_GRACE` after now is treated as takeable |

**A partial view is acceptable.** Setting an invalid ticket aside means a snapshot may
miss tickets. That is safe because a missing blocker counts as not done (nothing is
claimed too early) and the worst case is `claim-next` choosing a less urgent ticket, far
better than one bad file stopping every agent. When two tickets carry the same current
claim hash, both are set aside (deterministic for every reader).

**Identity.** `tkt` uses the author identity git would put on the commit (`git var
GIT_AUTHOR_IDENT`: the clone's config, then global and system, and the `GIT_AUTHOR_*`
variables) and refuses to write if none is set. The commit author is the record of who
did each op; `tkt log` shows its name and email, unverified. A claim also stores
`holder`, the git name mapped to an identifier (accents folded, runs of other characters
to one `-`, ends trimmed, at most 39 characters), so `show` and `list` say who is working
on what. `tkt clone` prints the identity and the holder name; every write reports them.
Hashed claim ids still prove that the agent acting on a claim is the one that took it.

**Not defended.** The agent that works a ticket reads its body, so prompt injection is
reduced, not prevented; confinement, guidance and narrow agent permissions do the rest.
An agent with plain git and push access can forge well-formed tickets and history, or get
a genuine held ticket set aside by pushing another ticket with the same claim hash
(branch protection only stops rewrites). Junk files and spam tickets cost every commit
until tickets are separated or sharded (Q1).

## 9. Open questions, accepted limitations and deferred work

Accepted limitations (decided; revisit only if they cause trouble):

- No administrative release until `revoke` (0.2.0, §8): a dead holder blocks a ticket
  for at most its lease plus the grace (30-minute default, `MAX_TTL` 2 h), unless the
  ticket is cancelled.
- Who acted is not authenticated: today the `--as` name, from 0.2.0 the git author
  identity (and the claim's `holder`, derived from it). It is trusted under the trust
  model; commit signing could authenticate it (deferred).
- Resolved tickets stay on the branch for good (Q1); fine at the expected scale.
- `SKEW_GRACE` stays a fixed 60-second constant.
- Phases and kinds are fixed enums; a new phase is a format change.

Open questions:


- Q1: Should resolved (done/cancelled) tickets be kept on the branch (current design) or moved to `archive/`?
  Every op reads every ticket file, so a CLI op costs ~0.25 s at 5,000 tickets and ~1 s
  at 20,000 on a local store (ADR 0001, *Store size*). Archiving would need blockers,
  re-runs of `done` and claim-id fencing to work without reading archived tickets.
- Q2: Project identity is the caller's concern. From 0.2.0 it must be `[owner/]repo`
  (§8), which a root-commit hash or an `owner/repo` name fits and a remote URL does not.
- Q3: Should `claim_next` (pick highest-priority claimable) be an op (atomic choice) — current design — or a read + claim?
- Q4: Lease units: integer seconds since epoch (current) vs ISO timestamps in files.
- Deferred: `claim-next` choosing randomly among the top candidates to spread contention.
  On one ref any two concurrent writes conflict, whichever ticket they touch, so this
  only pays off with one ref per ticket (ADR 0001).
