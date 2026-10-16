# 0001 — A git branch is the store

**Status:** accepted; validated against GitHub in milestone 1 (below)

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
  remote each op costs a fetch and a push. On GitHub the binding limit is its push-rate
  guidance, not git (below).
- Queries are file scans, so an op's local cost grows with every ticket on the branch,
  resolved ones included (below).
- Alternatives considered: Postgres (better at scale, needs a server), object storage
  with conditional writes (no history, multi-object updates awkward).

## Validation (milestone 1)

Measured with `scripts/bench.py` against a dedicated GitHub repository whose `tkt-store`
branch is protected (deletion and force-push blocked). The detailed results are in this
file's git history.

- **One ref serialises every write.** Throughput is about one commit per fetch-and-push
  round trip (about 20 per minute against GitHub), however many agents there are; more
  agents only add lost races, which the transaction loop retries with backoff
  (design.md §4). Lost races are told apart from refusals without depending on how a
  server words them (design.md §6).
- **The binding limit is GitHub's guidance, not git:** "The recommended maximum limit
  is 6 pushes per minute per repository" ([repository limits](https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits)).
  Every write is a push, including renewals and pushes that lose a race.
- **Store size.** An op reads every ticket file, so its local cost grows linearly with
  the number of tickets: it matters when the remote is on the same machine or
  self-hosted from about a thousand, on GitHub (seconds of network per op) only at tens
  of thousands. The store keeps itself packed (`git gc --auto`); from 0.2.0 resolved
  tickets are archived, so an op reads only open ones (ADR 0006).
- **Budget:** pushes per minute ≈ agents × (pushes per ticket ÷ minutes per ticket + 1 ÷
  renew interval in minutes), plus lost races. With 10 agents, about 5 pushes per
  ticket and renewals every 20 minutes, tasks of 20 minutes need about 3 pushes per
  minute (fits); tasks of 5 minutes about 10 (does not).

**Verdict.** The decision holds for its stated scope, about 10 agents on tasks of tens of
minutes renewing at about two-thirds of the lease (`docs/cli.md`), within GitHub's push
guidance. It does not hold for many short tasks on GitHub; a self-hosted remote has no
such guidance.

**If the budget is exceeded,** in increasing cost:

1. fewer pushes per ticket (longer leases renewed less often; a one-commit handoff
   instead of `move` + `release`, which would revisit that decision);
2. one ref per ticket (as git-bug and Gerrit's NoteDb do), with `git push --atomic` and a
   lease per ref for multi-ticket ops: removes races between different tickets, but not
   the per-repository push guidance, and weakens cross-ticket checks;
3. a database behind the same `Store` port; the rules and the CLI do not change.
