# 0004 — Status is derived, not stored

**Status:** accepted (skeleton)

## Context

Storing an availability status alongside the facts it summarises (resolution, claim,
dependencies, lease) creates two sources of truth that can disagree.

The lifecycle position *is* stored, as two independent facts: the workflow `phase`
and, once finished, the `resolution` (`done`/`cancelled`); each is one fact, not a summary of
others. What must not be stored is the availability `status`.

## Decision

Store facts only. `status` is computed from `resolution`, `claim`, `lease_until`
versus *now*, and whether each `blocked_by` ticket is `done`.

## Consequences

- A ticket cannot be "claimed" with no claimant; `done`/`cancelled` come straight
  from the stored `resolution`, so they cannot disagree with it.
- `expired` appears automatically as time passes, without a write.
- Status depends on *now* and on other tickets, so it needs the snapshot and the
  clock — it is a function, not a field.
