# 0001 — A git branch is the store

**Status:** accepted; throughput measured 2026-10-15 (below)

## Context

Agents need a shared, durable, auditable record of tickets and claims, with atomic
updates, and without running a database server.

## Decision

Store tickets as JSON files on a dedicated ref. Update them only with git
plumbing (`hash-object`, `mktree`, `commit-tree`, `update-ref <ref> <new> <old>`,
fast-forward push), never with a worktree or index.

## Consequences

- Atomicity comes from compare-and-swap on a ref; a crash leaves only unreachable objects.
- History is the audit log for free.
- Throughput is limited: every write is serialised on one ref, and against a hosted
  remote each op costs a fetch and a push. Measured below; the binding limit on GitHub
  is its push-rate guidance, not git.
- Queries are file scans, so an op's local cost grows with every ticket on the branch,
  resolved ones included (measured below, *Store size*).
- Alternatives considered: Postgres (better at scale, needs a server), object storage
  with conditional writes (no history, multi-object updates awkward).

## Measurement (milestone 1)

Run with `scripts/bench_github.py` against a dedicated private GitHub repository whose
`tkt-store` branch is protected by a ruleset (deletion and force-push blocked; no
signed-commit or pull-request requirement). git 2.53.0 over SSH, from a sandbox whose
traffic goes through a proxy, so latencies are an upper bound.

**Protection.** A force-push and a deletion of the store branch are both refused,
`[remote rejected] (protected branch hook declined)`; `tkt` reports that as a store error
and never retries it.

**Latency, one writer.** Medians of 10 rounds: `add` 4.1 s, `claim` 4.1 s, `renew` 4.1 s,
`done` 4.0 s (worst 4.6 s); `show` 1.6 s; `init` 5.6 s. A write is one fetch and one push,
about 12 git invocations in all; the network round trips dominate.

**How GitHub reports a lost race.** Two shapes, both meaning nothing was published, so
both are a `Conflict` and retried:

- `[rejected] (stale info)`: the client's lease check saw the ref move before pushing;
- `[remote rejected] (cannot lock ref '<ref>': is at <oid> but expected <oid>)`: GitHub's
  own compare-and-swap lost a concurrent push. (Plain git says
  `(incorrect old value provided)` over the local transport, and `(failed to update ref)`
  with the "is at … but expected …" detail on the remote's stderr from `git daemon`.)
  Before this was recognised, contending agents got
  store errors instead of retries.

**Contention.** K agents, each in its own clone, drain K × 4 tickets with `claim-next`
then `done`, with no work between ops (the worst case):

| Agents | Backoff | Commits/s | Pushes lost | Ops out of attempts (10) | Op latency median / p90 / max |
|---|---|---|---|---|---|
| 2 | none | 0.26 | 14 of 29 | 1 | 3.7 / 4.2 / 8.2 s |
| 5 | none | 0.28 | 152 of 191 | 11 | 3.6 / 7.2 / 21.7 s |
| 10 | none | 0.28 | 693 of 771 (90%) | 62 | 3.5 / 4.3 / 31.1 s |
| 10 | jittered | 0.34 | 347 of 443 (78%) | 10 | 11.2 / 46.7 / 87.0 s |

Without backoff the latency column counts only operations that succeeded; the others
gave up after about 35 s. The jittered row used full jitter with a fixed window doubling
from 1 s to 16 s; it turns most of those into slower successes. Its first windows were
shorter than one attempt (~3.5 s), so early retries still collided; the backoff now
counts its window in slots, the duration of the attempt that lost (design.md §4). That
version is not yet measured.

**Findings.**

- One ref serialises every write: throughput is about one commit per round trip (here
  0.28–0.34 per second, about 20 per minute) however many agents there are. More agents
  only add lost races.
- **The binding limit is GitHub's guidance, not git:** "The recommended maximum limit
  is 6 pushes per minute per repository" ([repository limits](https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits)),
  counting pushes that lose a race. The benchmark exceeded it by far for a few minutes
  without visible throttling, but a deployment should stay within it.
- Budget: pushes per minute ≈ agents × (pushes per ticket ÷ minutes per ticket + 1 ÷
  renew interval in minutes), plus lost races. With 10 agents, about 5 pushes per
  ticket (claim, a renewal or two, move, release or done) and renewals every 20 minutes:
  tasks of 20 minutes give about 3 pushes per minute (fits); tasks of 5 minutes about
  10 (does not).

**Verdict.** The assumption holds for its stated scope, about 10 agents on tasks of tens
of minutes, renewing at about two-thirds of the lease (`docs/cli.md`), within GitHub's
push guidance. It does not hold for many short tasks.

**If the budget is exceeded,** in increasing cost:

1. fewer pushes per ticket (longer leases renewed less often; a one-commit handoff
   instead of `move` + `release`, which would revisit that decision);
2. one ref per ticket (as git-bug and Gerrit's NoteDb do), with `git push --atomic` and a
   lease per ref for multi-ticket ops: removes races between different tickets, but not
   the per-repository push guidance, and weakens cross-ticket checks;
3. a database behind the same `Store` port; the rules and the CLI do not change.

## Store size (measured 2026-10-16)

A snapshot lists and decodes every ticket file and a commit rewrites the `tickets/` tree,
so an op's local cost grows linearly with the number of tickets. One writer, local-only
store (`claim-next` and `release`, ms per op):

| Tickets | Loose objects (before) | Packed, new store per op (the CLI) | Packed, long-lived store (library) |
|---|---|---|---|
| 1,000 | 162 | 76 | 35 |
| 5,000 | 849 | 254 | 74 |
| 20,000 | 2,529 | 900–1,200 | 210–255 |

- Plumbing never triggers git's housekeeping, so a store accumulated loose objects; the
  store now runs `git gc --auto` after each commit (packs in the background).
- `GitStore` caches decoded tickets by blob id, so a long-lived store reads only files
  whose content changed. Each CLI invocation is a new process and gets no benefit; an
  on-disk cache in the git directory would help it partly (deferred).
- Against GitHub an op is ~4 s of network, so store size matters there only at tens of
  thousands of tickets; on local and self-hosted stores it matters from about a thousand.
- The lever that makes the CLI's cost independent of history is archiving resolved
  tickets (design.md §8, Q1). Sharding `tickets/` would only remove the tree rewrite,
  about 6% of a packed op at 20,000 tickets.
