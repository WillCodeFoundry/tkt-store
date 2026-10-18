# 0004: Corrupt state stops the operation that reads it

**Status:** accepted (2026-10-18)

## Context

The writers sharing a store may be buggy, confused or compromised, and anyone with
push access can write anything to the branch. A broken or forged entry must never lead
a caller to a wrong decision, and skipping it would let a decision be made on a view
missing exactly the entry that mattered.

## Decision

- Anything on the branch that state-store would never have written is a `StoreError`
  for the operation that reads it: never skipped, never partly used.
- Operations that do not read it are unaffected.
- The error never quotes what was read, since a forged value or name could carry
  instructions, and a caller may pass an error on to an AI agent.
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
