# 0001: The store is files at the tip of one git branch

**Status:** accepted (2026-10-18)

## Context

state-store's callers are many writers sharing state concurrently. They need it
durable and auditable, a change can span several keys and must land whole or not at
all, and they should not need a server to get it. An earlier design on a git branch
kept the same facts in two forms at once (files in the tree, and again in commit
messages), with a per-clone cache and state encoded in file names, and much of its
complexity came from keeping those consistent.

## Decision

- state-store holds its values as files, keys to values, in the tree at the tip of one
  branch of one remote.
- The current state is always read directly from the tip. History is never read to
  work out what is true now; commit messages are for people reading `git log`, never
  data.
- Every change is one commit, published by compare-and-swap on that one branch.
- The one thing assumed of the remote: it refuses force pushes and deletion of the
  branch.

## Alternatives rejected

- **A database:** needs a server.
- **Object storage with conditional writes:** atomic per object only, so a change
  spanning several keys cannot land whole.
- **Events in commit messages, with the state rebuilt by replaying them:** reads grow
  with all of history, which then needs checkpoints and their own failure modes.
- **Several branches** (for example one per kind of data): a change spanning two
  cannot be atomic, and a decision reading two races.
- **A per-clone cache of decoded state:** unnecessary when every read is a direct, keyed
  lookup, and it brings invalidation.

## Consequences

- Throughput is about one commit per round trip to the remote, and any two concurrent
  commits conflict, even on unrelated keys; one starts again.
- The audit trail is git's history, for free.
- Nothing may write to the branch with plain git: whatever bypasses state-store also
  bypasses its checks.
