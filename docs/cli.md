# CLI — `tkt`

Global options: `--repo PATH` (store repository; default: `$TKT_REPO` or cwd),
`--ref REF` (default `refs/heads/tkt`), `--remote NAME` (optional), `--json`.

| Command | Purpose | Key options |
|---|---|---|
| `tkt init` | Create the store ref with an empty `tickets/` tree | |
| `tkt add TITLE` | Create a ticket; prints its id | `--kind`, `--body`, `--project`, `--priority`, `--blocked-by ID`…, `--tag`…, `--stage` |
| `tkt update ID` | Edit title/body/priority/tags/dependencies | same as `add` (not claim/stage) |
| `tkt list` | List tickets (derived status) | `--status`, `--stage`, `--project`, `--agent`, `--kind` |
| `tkt show ID` | One ticket, with derived status and claim age | |
| `tkt claim ID` | Claim a ticket; prints the claim id | `--as AGENT` (required), `--ttl DURATION` |
| `tkt claim-next` | Claim the most urgent claimable ticket | `--as AGENT`, `--ttl`, `--project`, `--kind`, `--stage` |
| `tkt renew ID` | Extend a lease | `--claim CLAIM_ID`, `--ttl` |
| `tkt release ID` | Give a claim back; optionally hand off to another stage | `--claim CLAIM_ID`, `--reason`, `--to-stage` |
| `tkt done ID` | Complete it (terminal `done`) | `--claim CLAIM_ID` |
| `tkt cancel ID` | Abandon it (terminal `cancelled`, no claim needed) | `--reason` |
| `tkt reap` | Release every expired claim | |
| `tkt log [ID]` | History from commit trailers | `--limit` |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Committed, or unchanged (idempotent repeat) |
| 1 | Refused by the rules (e.g. already claimed, not holder, blocked) |
| 2 | Usage error |
| 3 | Retries exhausted after repeated conflicts — safe to re-run |
| 4 | Store error (git failure, remote unreachable, corrupt data) |

## JSON output

With `--json`, every command prints one object:

```json
{"outcome": "committed", "ticket": {…}, "revision": "a1b2c3…"}
{"outcome": "unchanged", "reason": "already done by this claim"}
{"outcome": "refused", "code": "ALREADY_CLAIMED", "message": "held by coder-3 until …"}
```
