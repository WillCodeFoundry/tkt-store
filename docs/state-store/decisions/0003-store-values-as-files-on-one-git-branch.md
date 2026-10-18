# 0003: Store values as files on one git branch

**Status:** accepted

## Context

state-store provides consistent, all-or-nothing shared state without a server
([0001](0001-provide-consistent-all-or-nothing-shared-state.md)). Every writer can
already reach a git remote, and a git branch gives durability, history and
compare-and-swap updates. Holding the same facts in more than one form (say, files and
commit messages) would mean keeping them consistent.

## Decision

- state-store holds its values as files, keys to values, in the tree at the tip of one
  branch of one remote.
- The current state is always read directly from the tip. History is never read to
  work out what is true now; commit messages are for people reading `git log`, never
  data.
- Every change is one commit, published by compare-and-swap on that one branch.

## Alternatives rejected

- **Object storage with conditional writes:** atomic per object only, so a change
  spanning several keys cannot land whole.
- **Events in commit messages, with the state rebuilt by replaying them:** reads grow
  with all of history, which then needs checkpoints.
- **Several branches** (for example one per kind of data): a change spanning two
  cannot be atomic, and reads of two are not consistent with each other.
- **A per-clone cache of decoded state:** unnecessary when every read is a direct, keyed
  lookup, and it brings invalidation.

## Consequences

- Every commit is a push, so it costs a round trip to the remote.
- git's history is the audit trail.
