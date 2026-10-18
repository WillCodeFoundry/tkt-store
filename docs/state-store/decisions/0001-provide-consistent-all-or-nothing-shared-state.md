# 0001: Provide consistent, all-or-nothing shared state

**Status:** accepted

## Context

Some programs need state that many writers, on different machines, read and change
concurrently. A writer's change often spans several keys and is only correct if those
keys are seen as they were at one moment and changed together. Getting that right is
hard to do in every caller, and these programs would rather not run a server just to
hold the state.

## Decision

state-store provides its callers, without a server, with shared state that:

- is read **consistently**: every read through one snapshot sees the same moment;
- changes **all or nothing**, across any number of keys;
- changes **one commit at a time, each decided on the latest state**: a commit based on
  anything older is refused, and the caller decides again;
- is **durable and auditable**: a commit that returns is kept, and every change can be
  traced;
- needs nothing the writers cannot already reach.

The exact contract, and what it leaves out, are in the [README](../README.md#guarantees).

## Alternatives rejected

- **A server-based store** (a database, etcd and the like): it gives the same
  guarantees, but someone has to run it.
- **Weaker guarantees**, such as atomicity per key or conflict detection per key: two
  writers could each act on data the other had already changed.
- **Leaving concurrency to each caller:** every caller would have to solve it again.

## Consequences

- Because any two concurrent commits conflict, throughput is about one commit per round
  trip to the remote: enough for a handful of writers, not for heavy write traffic.
