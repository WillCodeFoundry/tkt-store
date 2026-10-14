# 0003 — Claims have leases and are fenced by a claim id

**Status:** accepted (skeleton)

## Context

Agents run unattended and can die silently. balls deliberately has no leases and
relies on manual takeover; that does not suit unattended fleets.

## Decision

- A claim records `lease_until`. Holders renew; once past, the claim is *expired*.
- `reap` releases expired claims; `claim` may also take over an expired ticket.
- Each claim gets a random `claim_id`. `renew`, `release` and `done` must present it.

## Consequences

- A dead agent's ticket returns to the pool automatically (via `reap` on a timer).
- A slow agent that comes back after takeover is refused (`NOT_HOLDER`) instead of
  overwriting the new holder's work.
- Clock skew matters only for the writer's clock (single writer ⇒ one clock).
