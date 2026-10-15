# 0001 — A git branch is the store

**Status:** accepted (skeleton)

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
- Throughput is limited: every write is serialized on one ref, and against a hosted
  remote each op costs a fetch and a push (roughly a second). **Assumed adequate, not
  yet measured:** about 10 agents with 30-minute leases write ~0.02 times per second.
  Other git-backed tools suggest hosting copes, but most of them merge per-task files
  rather than compare-and-swap one ref, so their experience does not transfer directly.
  The first milestone measures it against a real protected branch. Falsified if retries
  are regularly exhausted or renewals fail under the expected load; the `Store` port
  keeps the alternatives (per-ticket refs, merge-based sync) open without touching the
  rules or the CLI.
- Queries are file scans; acceptable at thousands of tickets, revisit beyond.
- Alternatives considered: Postgres (better at scale, needs a server), object storage
  with conditional writes (no history, multi-object updates awkward).
