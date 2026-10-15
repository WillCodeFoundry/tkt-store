# CLI — `tkt`

Global options:

- `--repo PATH` — the store repository; default `$TKT_REPO`. If neither is set,
  `tkt` exits with a usage error (there is no cwd fallback: the store lives in its
  own repository).
- `--ref REF` — default `refs/heads/tkt`.
- `--remote NAME` — default `origin`. Each agent works in its own clone (several
  processes may share one), so the store is remote-backed by default. If the remote is not configured, **every**
  command (`init` included) fails with a store error; there is no silent
  local-only fallback.
- `--no-remote` — use a local-only store (single machine, tests). `tkt init
  --no-remote` creates only the local ref and does no fetch/push.
- `--json` — machine-readable output (see below).

| Command | Purpose | Key options |
|---|---|---|
| `tkt init` | Create the store ref with an empty `tickets/` tree and `tkt-store.json` | |
| `tkt add TITLE` | Create a ticket; prints its id | `--id ID`, `--as AGENT`, `--kind`, `--body`, `--project`, `--priority`, `--blocked-by ID`…, `--tag`…, `--stage` (non-terminal; `done`/`cancelled` are refused) |
| `tkt update ID` | Edit title/body/priority/tags/dependencies | `--if-version N` (required), `--as AGENT`, `--title`, `--body`, `--priority N\|none`, `--blocked-by ID`…, `--tag`… |
| `tkt list` | List tickets (derived status) | `--status`, `--stage`, `--project`, `--agent`, `--kind` |
| `tkt show ID` | One ticket, with derived status, claim age and its content `version` | |
| `tkt claim ID` | Claim a ticket; prints the claim id | `--as AGENT` (required), `--ttl DURATION`, `--claim-id CLAIM_ID` |
| `tkt claim-next` | Claim the most urgent claimable ticket | `--as AGENT` (required), `--ttl`, `--claim-id CLAIM_ID`, `--project`, `--kind`, `--stage` |
| `tkt renew ID` | Extend a lease | `--claim-id CLAIM_ID`, `--ttl` |
| `tkt release ID` | Give a claim back; optionally hand off to another stage | `--claim-id CLAIM_ID`, `--reason`, `--to-stage` |
| `tkt done ID` | Complete it (terminal `done`) | `--claim-id CLAIM_ID` |
| `tkt cancel ID` | Abandon it (terminal `cancelled`, no claim needed) | `--as AGENT`, `--reason` |
| `tkt reap` | Release every claim lapsed past the skew grace | |
| `tkt log [ID]` | History from commit trailers | `--limit` |

Notes:

- **Ids for safe re-runs.** `--id` (add) and `--claim-id` (claim, claim-next) let a
  caller choose the id up front, so re-running the same command converges instead of
  creating a second ticket or claim. Ticket ids must match `^tkt-[0-9a-f]+$`; claim
  ids are exactly 32 lowercase hex characters. Without them, ids are generated, and a
  failure prints the generated ids so the command can be re-run with them. A claim id
  is single-use and names one claim on one ticket: re-use it only to retry the same
  claim. After its claim ends it is refused (`NOT_HOLDER`) while the ticket still
  records it.
- **Re-runs of holder ops.** Re-running a `release` that landed is a no-op even if
  someone has claimed the ticket since (with `--to-stage`, only while the ticket is still
  at that stage; otherwise `NOT_HOLDER`). Re-running a landed `done` is a no-op. The exact rules are the
  holder-op table in `docs/design.md` §5.
- **Actor.** `--as` on `add`, `update` and `cancel` is optional and only recorded in the
  audit trailer (`tkt-agent`).
- **`update`.** An omitted option means "unchanged"; `--priority none` clears the
  priority. `kind` and `project` cannot be changed. `--if-version N` is required: the
  ticket's `version` you based the edit on (from `tkt show`). If someone updated the
  ticket since, the edit is refused `STALE` (exit 1) instead of overwriting theirs:
  re-read and retry. Re-running an update that already landed is a no-op. Only `update`
  changes the version, so claims and renewals never cause `STALE`.
- **Text fields.** `--as`, `--reason` and `TITLE`/`--title` must not contain newlines
  or other control characters (they are written into the commit message).
- **Durations.** `--ttl` takes `Ns`, `Nm`, `Nh` or bare seconds (`90s`, `30m`, `2h`,
  `1800`). Default: 30 minutes; maximum 24 hours.
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
| 1 | Refused by the rules (e.g. already claimed, not holder, blocked, invalid input, stale update) |
| 2 | Usage error (including no `--repo` and no `$TKT_REPO`) |
| 3 | Retries exhausted after repeated conflicts; nothing written — re-run with the printed ids |
| 4 | Store error (git failure, remote unreachable or not configured, corrupt data). A failure during the push may mean the commit landed: re-run with the printed ids, which converges either way |

## JSON output

With `--json`, each command prints one JSON value. Every mutation prints an object. For
`committed` and `unchanged`, `tickets` lists the affected tickets as they are after the op
(empty for `init`); refusals carry a code and message, failures carry the op:

```json
{"outcome": "committed", "revision": "a1b2c3…", "tickets": [{…}]}
{"outcome": "unchanged", "reason": "already done by this claim", "tickets": [{…}]}
{"outcome": "refused", "code": "ALREADY_CLAIMED", "message": "held by coder-3 until …"}
{"outcome": "error", "exit": 4, "message": "push failed: …", "op": {"op": "claim", "ticket_id": "tkt-7f3a91c2", "claim_id": "…"}}
```

- An `unchanged` claim or claim-next still shows the claim it holds, so the claim id is
  never lost on a re-run.
- Failures (exit 3 and 4) print the op with the ids it was last tried with; without
  `--json` they go to stderr with a "re-run with `--id`/`--claim-id`" hint.
- `show` prints the ticket object with its derived `status` and `claim_age` (seconds since
  `claim.claimed_at`).
- `list` prints an array of tickets; `log` prints an array of history entries.
