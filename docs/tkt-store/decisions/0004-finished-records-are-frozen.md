# 0004: Finished records are frozen

**Status:** accepted (2026-10-18)

## Context

Most of tkt-store's records reach a state they can never leave (a resolved ticket, an
ended claim) and are only read from then on. Kept together with the records still
changing, they make every operation pay for all of history; the previous
implementation's cache existed to compensate.

## Decision

A record that reaches a state it can never leave is written once, in its final form,
apart from the records still changing, and never changed again.

## Alternatives rejected

- **Keeping every record in one changing set:** the cost of each operation grows with
  everything ever stored, which then needs a cache.

## Consequences

- The cost of working on live records stays proportional to the live records.
- Correcting a finished record needs a design of its own (TBD).
