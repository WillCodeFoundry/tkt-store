# 0005: Corrupt state stops the operation that reads it

**Status:** accepted

## Context

The threat model ([0002](0002-threat-model.md)) treats every entry on the branch as
untrusted. A broken or forged entry must not lead to a wrong result, and skipping it
would mean deciding without the entry that mattered.

## Decision

- Anything on the branch that state-store would never have written is a `StoreError`
  for the operation that reads it: never skipped, never partly used.
- Operations that do not read it are unaffected.
- An operator repairs the branch with plain git.

## Alternatives rejected

- **Set the bad entry aside and carry on:** decisions made on an incomplete view, and
  machinery to track what was set aside.
- **Stop the whole store on any corruption:** a larger blast radius than needed when
  every read is a direct, keyed lookup.

## Consequences

- A bad entry blocks the operations that touch it until an operator repairs it,
  including any commit that would rewrite the tree holding it
  ([design](../design.md), §5).
