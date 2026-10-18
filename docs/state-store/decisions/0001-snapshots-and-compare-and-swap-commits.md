# 0001: A key/value interface of immutable snapshots and compare-and-swap commits

**Status:** accepted (2026-10-18)

## Context

tkt-store needs to read several records as they were at one moment, and to change
several records together, all or nothing, while other agents change the same store
concurrently. The interface should hide git entirely, and be as small as that allows.

## Decision

- **Keys and values:** keys are path-like strings grouped in namespaces; values are
  bytes, never interpreted.
- **Reads go through a snapshot:** an immutable view of one committed state (`get`,
  `keys`), consistent however long it is kept.
- **Changes derive new snapshots:** `with_value` and `without` return a new snapshot
  carrying the change and leave the original untouched, named like `pathlib`'s
  `with_name` so that "returns a new object" is clear.
- **Commits are compare-and-swap:** `store.commit(snapshot, message)` publishes a
  snapshot's changes only if the store has not changed at all since the snapshot was
  taken, so commits apply one at a time, each on the latest state.
- **Two outcomes for the caller:** `StaleSnapshot` means take a new snapshot and decide
  again (`UnknownOutcome`, a kind of it, when a push may or may not have landed);
  `StoreError` means stop. A caller's own bug is a `ValueError` (`KeyCollision`, a kind
  of it, for a key that is both a value and a namespace).
- **No retries inside the store:** only the caller can redo its decision on new data.
- **Two implementations, one snapshot class:** `GitStateStore` and `MemoryStateStore`
  share `StateSnapshot`, so their semantics cannot drift.
- **Literal names:** "snapshot", "commit"; not "serializable", which reads as
  encoding, nor figurative names.

## Alternatives rejected

- **A mutable transaction object** (`tx.put(…)`, `tx.commit()`): a snapshot reads as
  read-only, and changing one in place confuses that.
- **Conflict detection per key** (snapshot isolation): two writers that read the same
  keys and write different ones could both land, deciding on views already out of date.
- **An object-store interface** (S3-like): atomic per object only.
- **Retrying inside the store:** it cannot redo the caller's decision.
- **More error types:** a caller only ever needs to know whether to start again or stop.

## Consequences

- Any two concurrent commits conflict, even on unrelated keys, and one starts again;
  throughput is about one commit per round trip to the remote.
- Every caller writes the same small loop: take a snapshot, decide, commit, and start
  again on `StaleSnapshot`.
