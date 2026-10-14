# 0002 — Agents read and write the store directly

**Status:** accepted (skeleton)

## Context

Agents run unattended and need to pick up, renew and hand off work without waiting
on another process. Funnelling every write through one coordinator would make that
coordinator a bottleneck and a single point of failure for all progress.

Any credential that can push to the store's remote can, by default, also
force-push or delete the branch, and can commit arbitrary content.

## Decision

The store lives in its own repository. Each agent works in its own clone and reads
and writes the store directly through `tkt`, with `origin` as the shared remote.

Safety rests on:

- compare-and-swap on the ref — one op is one commit; a lost race is retried and
  re-decided on fresh state;
- claim-id fencing — a stale holder can no longer change a ticket;
- a remote that **refuses non-fast-forward pushes and deletion of the store branch**,
  as a deployment precondition (a self-hosted pre-receive hook, or branch protection
  on a plan that offers it).

**Trust model:** agents are trusted to mutate the store only through `tkt`. The
remote rules protect history and prevent lost updates; they do not stop a
credential holder from bypassing `tkt` and committing arbitrary content. CAS and
fencing bind only writers that use the library. Defending against a malicious
agent would require coordinator-gated writes and is out of scope.

## Consequences

- No single process gates progress; any agent can claim, renew, hand off and reap.
- Writers contend on one ref; compare-and-swap turns contention into retries, which
  is acceptable at agent timescales (minutes per ticket).
- Each writer has its own clock, so leases are advisory and fencing is authoritative
  (ADR 0003).
- A coordinator remains possible as an optional convenience (for example to assign
  work or run `reap`), but correctness never depends on it.
- The remote precondition is mandatory: without it, one faulty push could rewrite or
  delete the shared history.
