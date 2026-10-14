# 0002 — One coordinator is the only writer

**Status:** accepted (skeleton)

## Context

On GitHub's free plan, private repos cannot protect branches, so any credential
that can push can also force-push or delete. Agents run sandboxed and should not
hold push credentials.

## Decision

The store lives in its own repository, written only by the coordinator process.
Agents never read or write it directly; they receive assignments from the
coordinator.

## Consequences

- No cross-writer contention in practice; compare-and-swap remains as a safety net.
- Agents cannot damage the store.
- The coordinator is a single point of failure for assigning work (not for data:
  the store is plain git and survives the coordinator).
- Multi-writer use stays possible (the design does not depend on a single writer),
  but then the remote must refuse force-pushes and deletions.
