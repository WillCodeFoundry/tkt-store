# 0003 — Claims have leases and are fenced by a claim id

**Status:** accepted (skeleton)

## Context

Agents run unattended and can die silently. balls deliberately has no leases and
relies on manual takeover; that does not suit unattended fleets.

## Decision

- A claim records `lease_until`. Holders renew; once past, the claim is *expired*.
- An expired claim may be acted on — reaped, or taken over by `claim` — only from
  `lease_until + SKEW_GRACE` (60 s). Until someone does, its holder may still renew,
  release or complete it.
- `reap` releases claims past the grace. It is idempotent, and any writer may run it
  on a schedule (cron, CI).
- Each claim gets a `claim_id` (random, or supplied by the caller). `renew`,
  `release` and `done` must present it, and a completed ticket records it
  (`done_by`), so fencing survives completion.

## Consequences

- A dead agent's ticket returns to the pool automatically (via a scheduled `reap`).
- A slow agent that comes back after takeover is refused (`NOT_HOLDER`) instead of
  overwriting the new holder's work.
- Multiple writers ⇒ clocks may skew ⇒ leases are advisory and fencing is
  authoritative. The grace keeps a fast-clocked writer from taking a claim its holder
  still considers live; a TTL should exceed the renew interval plus the grace plus the
  expected skew.
