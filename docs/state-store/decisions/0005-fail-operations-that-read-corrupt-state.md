# 0005: Fail operations that read corrupt state

**Status:** accepted

## Context

The threat model
([0003](0003-trust-only-the-callers-machine-and-the-remotes-handling-of-pushes.md))
treats every entry on the branch as untrusted. A broken or forged entry must not lead to a wrong
result, and skipping it would mean deciding without the entry that mattered.

## Decision

- Anything on the branch that state-store would never have written is a `StoreError`
  for the operation that reads it: never skipped, never partly used.
- Operations that do not read it are unaffected.

## Alternatives rejected

- **Set the bad entry aside and carry on:** decisions made on an incomplete view, and
  machinery to track what was set aside.
- **Stop the whole store on any corruption:** it stops more than needed, since every
  read is a direct, keyed lookup.

## Consequences

- A bad entry blocks the operations that touch it until an operator repairs the branch
  ([design](../design.md#reading)).
