# CLI — `tkt`

Global options:

- `--repo PATH` — the store repository; default `$TKT_REPO`. If neither is set,
  `tkt` exits with a usage error (there is no cwd fallback: the store lives in its
  own repository).
- `--ref REF` — default `refs/heads/tkt`.
- `--remote NAME` — default `origin`. Each agent works in its own clone, so the
  store is remote-backed by default. If the remote is not configured, **every**
  command (`init` included) fails with a store error; there is no silent
  local-only fallback.
- `--no-remote` — use a local-only store (single machine, tests). `tkt init
  --no-remote` creates only the local ref and does no fetch/push.
- `--json` — machine-readable output (see below).

| Command | Purpose | Key options |
|---|---|---|
| `tkt init` | Create the store ref with an empty `tickets/` tree | |
| `tkt add TITLE` | Create a ticket; prints its id | `--id ID`, `--kind`, `--body`, `--project`, `--priority`, `--blocked-by ID`…, `--tag`…, `--stage` (non-terminal; `done`/`cancelled` are refused) |
| `tkt update ID` | Edit title/body/priority/tags/dependencies | `--title`, `--body`, `--priority`, `--blocked-by ID`…, `--tag`… |
| `tkt list` | List tickets (derived status) | `--status`, `--stage`, `--project`, `--agent`, `--kind` |
| `tkt show ID` | One ticket, with derived status and claim age | |
| `tkt claim ID` | Claim a ticket; prints the claim id | `--as AGENT` (required), `--ttl DURATION`, `--claim-id CLAIM_ID` |
| `tkt claim-next` | Claim the most urgent claimable ticket | `--as AGENT`, `--ttl`, `--claim-id CLAIM_ID`, `--project`, `--kind`, `--stage` |
| `tkt renew ID` | Extend a lease | `--claim-id CLAIM_ID`, `--ttl` |
| `tkt release ID` | Give a claim back; optionally hand off to another stage | `--claim-id CLAIM_ID`, `--reason`, `--to-stage` |
| `tkt done ID` | Complete it (terminal `done`) | `--claim-id CLAIM_ID` |
| `tkt cancel ID` | Abandon it (terminal `cancelled`, no claim needed) | `--reason` |
| `tkt reap` | Release every claim lapsed past the skew grace | |
| `tkt log [ID]` | History from commit trailers | `--limit` |

Notes:

- **Ids for safe re-runs.** `--id` (add) and `--claim-id` (claim, claim-next) let a
  caller choose the id up front, so re-running the same command converges instead of
  creating a second ticket or claim. Ticket ids must match `^tkt-[0-9a-f]+$`, claim
  ids `^[0-9a-f]+$`. Without them, ids are generated.
- **`update` limits.** `kind` and `project` cannot be changed. `--priority` cannot be
  reset to null in v1 (an omitted option means "unchanged").
- **Text fields.** `--as`, `--reason` and `TITLE`/`--title` must not contain newlines
  or other control characters (they are written into the commit message).
- **Durations.** `--ttl` takes `Ns`, `Nm`, `Nh` or bare seconds (`90s`, `30m`, `2h`,
  `1800`). Default: 30 minutes.
- **Expiry.** A claim reads `expired` from its `lease_until`, but can be taken over or
  reaped only 60 s later (the fixed skew grace). A ticket that is both blocked and
  expired reads `blocked`, so `list --status expired` omits it; `reap` still releases
  its claim. Choose a TTL well above your renew interval plus the grace and expected
  clock skew.
- **Reaping.** `tkt reap` is idempotent; any writer can run it on a schedule.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Committed, or unchanged (idempotent repeat) |
| 1 | Refused by the rules (e.g. already claimed, not holder, blocked, invalid input) |
| 2 | Usage error (including no `--repo` and no `$TKT_REPO`) |
| 3 | Retries exhausted after repeated conflicts — safe to re-run |
| 4 | Store error (git failure, remote unreachable or not configured, corrupt data) |

## JSON output

With `--json`, each command prints one JSON value. Mutations print an object:

```json
{"outcome": "committed", "revision": "a1b2c3…", "ticket": {…}}
{"outcome": "unchanged", "reason": "already done by this claim"}
{"outcome": "refused", "code": "ALREADY_CLAIMED", "message": "held by coder-3 until …"}
```

- Single-ticket mutations (`add`, `update`, `claim`, `claim-next`, `renew`, `release`,
  `done`, `cancel`) include `ticket` when committed.
- `init` and `reap` print `{"outcome", "revision"}` (plus `"tickets": [ids…]` for
  `reap`) without a `ticket`.
- `show` prints the ticket object with its derived `status` and `claim_age`.
- `list` prints an array of tickets; `log` prints an array of history entries.
