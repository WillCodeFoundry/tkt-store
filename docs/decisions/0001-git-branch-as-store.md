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
- Throughput is low (tens of ms per op). Fine for agent work measured in minutes.
- Queries are file scans; acceptable at thousands of tickets, revisit beyond.
- Alternatives considered: Postgres (better at scale, needs a server), object storage
  with conditional writes (no history, multi-object updates awkward).
