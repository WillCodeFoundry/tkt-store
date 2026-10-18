# 0002: Corrupt state stops the operation that reads it

**Status:** accepted (2026-10-18)

## Context

The agents sharing a store may be confused or compromised, and anyone with push access
can write anything to the branch. A broken or forged file must never lead tkt-store to
a wrong decision. The previous implementation set invalid files aside and carried on
without them, which took a lot of machinery and could decide on a view that was missing
exactly the file that mattered.

## Decision

- Anything in the store that tkt-store would never have written is an error for the
  operation that reads it: never skipped, never partly used.
- Operations that do not read it are unaffected.
- The error never quotes what was read, since a forged value or name could carry
  instructions aimed at an agent.
- An operator repairs the store with plain git.

## Alternatives rejected

- **Set the bad file aside and carry on** (the previous design): decisions made on an
  incomplete view, and machinery to track what was set aside.
- **Stop the whole store on any corruption:** a larger blast radius than needed when
  every read is a direct, keyed lookup.

## Consequences

- A bad file blocks the operations that touch it until an operator repairs it.
- state-store applies this to what it reads, including every entry of a tree a commit
  rewrites, so a bad entry is never carried forward ([state-store design](../../state-store/design.md), §5).
