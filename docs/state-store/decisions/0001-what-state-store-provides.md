# 0001: state-store provides consistent, all-or-nothing shared state without a server

**Status:** accepted (2026-10-18)

## Context

Some programs need state that many writers, on different machines, read and change
concurrently. A writer's change often spans several keys and is only correct if those
keys are seen as they were at one moment and changed together. Getting that right in
every caller is hard and easy to get subtly wrong, and running a server just to hold
the state is a cost these programs want to avoid.

## Decision

state-store provides its callers with shared state that:

- is read **consistently**: every read through one snapshot sees the same moment;
- changes **all or nothing**, across any number of keys;
- changes **one commit at a time, each decided on the latest state**: a commit based on
  anything older is refused, and the caller decides again;
- is **durable and auditable**: a commit that returns is kept, and every change can be
  traced;
- needs **no server** beyond a git remote the writers can already reach.

It deliberately does not provide per-key conflict detection, queries, locks, expiry or
retries. The exact contract is in the [README](../README.md#guarantees).

## Alternatives rejected

- **A server-based store** (a database, etcd and the like): it gives the same
  guarantees, but someone has to run it.
- **Weaker guarantees**, such as atomicity per key or conflict detection per key: two
  writers could each decide on a view the other had already changed, which is the
  mistake callers most need protecting from.
- **Leaving concurrency to each caller:** every caller would have to solve the hardest
  part again.

## Consequences

- Because any two concurrent commits conflict, throughput is about one commit per round
  trip to the remote: enough for a handful of writers, not for heavy write traffic.
