# 0001: tkt-store's state is files at the tip of one git branch

**Status:** accepted (2026-10-18)

## Context

tkt-store coordinates about ten AI agents working in parallel. They need shared state
that is durable and auditable, where a change can span several records and must land
whole or not at all, and they should not need a server to get it. The previous
implementation (0.1.0) kept its state on a git branch too, but in two forms at once
(files in the tree, and the same facts in commit messages), with a per-clone cache and
claim state encoded in file names, and much of its complexity came from keeping those
consistent.

## Decision

- All of tkt-store's state is files, keys to values, in the tree at the tip of one
  branch of one remote. tkt-store reads and writes them only through state-store.
- The current state is always read directly from the tip. History is never read to
  work out what is true now; commit messages are for people reading `git log`, never
  data.
- Every change is one commit, published by compare-and-swap on that one branch.
- The one thing assumed of the remote: it refuses force pushes and deletion of the
  branch.

## Alternatives rejected

- **A database:** needs a server.
- **Object storage with conditional writes:** atomic per object only, so a change
  spanning several records cannot land whole.
- **Events in commit messages, with the state rebuilt by replaying them:** reads grow
  with all of history, which then needs checkpoints and their own failure modes.
- **Several branches** (for example one for live work, one for finished work): a change
  spanning both cannot be atomic, and decisions reading both race.
- **A per-clone cache of decoded state:** unnecessary when every read is a direct, keyed
  lookup, and it brings invalidation.

## Consequences

- Throughput is about one commit per round trip to the remote, and any two concurrent
  commits conflict, even on unrelated records; one starts again.
- The audit trail is git's history, for free.
- Agents must never write to the branch with plain git: everything they write goes
  through tkt-store, which checks it.
