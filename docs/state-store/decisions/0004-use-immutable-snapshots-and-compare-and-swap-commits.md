# 0004: Use immutable snapshots and compare-and-swap commits

**Status:** accepted

## Context

Callers need the promises of
[0001](0001-provide-consistent-all-or-nothing-shared-state.md) in a form they can use:
read several keys as they were at one moment, change several keys together, and learn
when someone else committed first. The interface should hide git entirely, and be as
small as that allows.

## Decision

The interface ([README](../README.md#interface)) is built on these choices:

- **Reads go through a snapshot:** an immutable view of one committed state, consistent
  however long it is kept.
- **Changes derive new snapshots,** leaving the original untouched, as `pathlib`'s
  `with_name` returns a new path.
- **Commits are compare-and-swap on the whole store:** a commit lands only if the store
  has not changed at all since its snapshot was taken.
- **The caller only has to tell two outcomes apart:** start again from a new snapshot,
  or stop. A caller's own bug is a `ValueError`.
- **One snapshot implementation for every store,** so the stores' semantics cannot
  drift.
- **Plain names:** "snapshot" and "commit", not figurative ones, and not
  "serializable", which reads as encoding.

## Alternatives rejected

- **A mutable transaction object** (`tx.put(…)`, `tx.commit()`): a snapshot is
  expected to be read-only, so changing one in place would be confusing.
- **Retrying inside the store:** it cannot redo the caller's decision.
- **More error types:** a caller only ever needs to know whether to start again or stop.

## Consequences

- Every caller writes the same small loop: take a snapshot, decide, commit, and start
  again on `StaleSnapshot`.
