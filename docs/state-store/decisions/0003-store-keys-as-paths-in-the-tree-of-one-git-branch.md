# 0003: Store keys as paths in the tree of one git branch

**Status:** accepted

## Context

state-store provides consistent, all-or-nothing shared state without a server
([0001](0001-provide-consistent-all-or-nothing-shared-state.md)). Every writer can
already reach a git remote, and a git branch gives durability, history and
compare-and-swap updates. Holding the same facts in more than one form (say, files and
commit messages) would mean keeping them consistent.

## Decision

- state-store holds each value as a file whose path is its key, in the tree at the tip
  of one branch of one remote.
- The current state is always read directly from the tip. History is never read to
  work out what is true now; commit messages are for people reading `git log`, never
  data.

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

- git's history is the audit trail.
- A commit rewrites the trees on the paths of the keys it changes, so how callers lay
  out their namespaces matters ([README](../README.md#keys)).
