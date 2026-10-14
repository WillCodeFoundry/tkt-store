# 0004 — Status is derived, not stored

**Status:** accepted (skeleton)

## Context

Storing an availability status alongside the facts it summarises (stage, claim,
dependencies, lease) creates two sources of truth that can disagree.

The lifecycle position *is* stored, as a single `stage` field (its workflow
phases plus the terminal `done`/`cancelled`); that is one fact, not a summary of
others. What must not be stored is the availability `status`.

## Decision

Store facts only. `status` is computed from `stage`, `claim`, `lease_until`
versus *now*, and whether each `blocked_by` ticket is `done`.

## Consequences

- A ticket cannot be "claimed" with no claimant; `done`/`cancelled` come straight
  from the stored `stage`, so they cannot disagree with it.
- `expired` appears automatically as time passes, without a write.
- Status depends on *now* and on other tickets, so it needs the snapshot and the
  clock — it is a function, not a field.
