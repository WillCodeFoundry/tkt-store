# CLI — `tkt`

The CLI is built for agents. It is deliberately thin and explicit:

- every store command maps to one `TicketStore` method, and its flags to that method's
  arguments;
- every input is an explicit flag: no environment-variable defaults, no inferred ticket
  or claim ids, no local state;
- every store command prints one JSON value on stdout (see *Output*).

It is verbose and repetitive by design: an agent re-runs a command by repeating it
unchanged, and there is nothing implicit to get wrong.

## Store options (required on every store command)

| Option | Meaning |
|---|---|
| `--repo PATH` | The store repository: this agent's clone of the store repository (one process per clone). |
| `--remote NAME` or `--no-remote` | Exactly one. `--remote` names the shared remote (normally `origin`); if it is not configured, every command fails with a store error. `--no-remote` selects a local-only store (single machine, tests). A store records its mode when it is created; using the other mode is refused. |

They may appear anywhere after the command name:
`tkt claim tkt-7f3a91c2 --as coder-7 … --repo /work/tasks --remote origin`. Every command
except `mint` takes them.

## Commands

Commands are grouped by the part of the ticket they change (docs/design.md, *Data
model*). Flags in **Required** must be given; flags in **Optional** may be.

### Setup

| Command | Purpose | Required | Optional |
|---|---|---|---|
| `tkt mint claim-id\|ticket-id` | Print a fresh random id; no store access, no store options | | |
| `tkt init` | Create the store ref with an empty `tickets/` tree and `tkt-store.json` | | |

### Content

| Command | Purpose | Required | Optional |
|---|---|---|---|
| `tkt add` | Create a ticket | `--id ID`, `--title TEXT`, `--kind KIND`, `--phase PHASE` | `--body TEXT`, `--project PROJECT`, `--priority N`, `--blocked-by ID`…, `--tag TAG`…, `--as AGENT` |
| `tkt edit ID` | Change content fields | `--if-version N` | `--title TEXT`, `--body TEXT`, `--priority N` or `--clear-priority`, `--blocked-by ID`… or `--clear-blocked-by`, `--tag TAG`… or `--clear-tags`, `--as AGENT` |

### Work (occupancy)

| Command | Purpose | Required | Optional |
|---|---|---|---|
| `tkt claim ID` | Claim a ticket | `--as AGENT`, `--ttl SECONDS`, `--claim-id CLAIM_ID` | |
| `tkt claim-next` | Claim the most urgent claimable ticket | `--as AGENT`, `--ttl SECONDS`, `--claim-id CLAIM_ID` | `--phase PHASE`, `--project PROJECT`, `--kind KIND` |
| `tkt renew ID` | Extend a lease | `--claim-id CLAIM_ID`, `--ttl SECONDS` | |
| `tkt release ID` | Give a claim back (the phase is untouched) | `--claim-id CLAIM_ID` | `--reason TEXT` |
| `tkt reap` | Release every claim lapsed past the skew grace | | |

### Workflow

| Command | Purpose | Required | Optional |
|---|---|---|---|
| `tkt move ID` | Move it to another phase, keeping the claim (holder only) | `--claim-id CLAIM_ID`, `--to-phase PHASE` | |
| `tkt done ID` | Complete it: resolution `done`, final (holder only) | `--claim-id CLAIM_ID` | |
| `tkt cancel ID` | Abandon it: resolution `cancelled`, final (no claim needed) | | `--reason TEXT`, `--as AGENT` |

### Read

| Command | Purpose | Required | Optional |
|---|---|---|---|
| `tkt list` | List tickets | | `--status STATUS`, `--phase PHASE`, `--project PROJECT`, `--agent AGENT`, `--kind KIND` |
| `tkt show ID` | One ticket with its derived status | | |
| `tkt log [ID]` | History from commit trailers | | `--limit N` |

Values: `KIND` is `story`, `task` or `bug`; `PHASE` is `triage`, `specification`,
`implementation`, `cleanup`, `architecture`, `hardening`, `qa`, `review` or `release`;
`STATUS` is `open`, `blocked`, `claimed`, `expired`, `done` or `cancelled`. Repeated
flags (`…`) may be given several times.

## Rules worth knowing

- **Ids.** The caller supplies every id: ticket ids match `^tkt-[0-9a-f]+$`; claim ids
  are exactly 32 lowercase hex characters. Re-running a command with the same ids
  converges (`unchanged`) instead of creating a second ticket or claim. A claim id is
  single-use and names one claim on one ticket; after its claim ends it is refused
  (`NOT_HOLDER`) for good: every ticket records its full claim history (`ended_claim_ids`).
- **TTL** is an integer number of seconds, `0 < ttl <= 7200` (2 h); 1800 (30 min) is a
  sensible default. Renew at about two-thirds of the lease (every ~20 min for 30 min):
  every renewal is a push, and the host's push rate is the store's budget (ADR 0001).
  The TTL must exceed the renew interval plus the 60 s skew grace plus the expected clock
  skew, with room for a renewal that has to retry.
- **Expiry.** A claim reads `expired` from its `lease_until`, but can be taken over or
  reaped only 60 s later. A ticket that is both blocked and expired reads `blocked`;
  `reap` still releases its claim. `reap` is idempotent; any writer may run it on a
  schedule.
- **Edit.** An omitted option leaves that field unchanged; `--clear-…` empties it.
  `--if-version` is the ticket's `content_version` you based the edit on (from
  `tkt show`): if it was edited since, the edit is refused `STALE` instead of
  overwriting. Re-running an edit that already landed is `unchanged`. Only `edit` changes
  the content version, so claims and renewals never cause `STALE`. `kind` and `project`
  cannot be changed.
- **Handoff** is two commands: `move --to-phase P`, then `release`. In that order the
  ticket is never unheld in the old phase; if the agent dies between them, the lease
  lapses and the ticket becomes available in the new phase.
- **Re-runs of holder commands** converge: re-running a `move` or `release` that landed
  is `unchanged`, however many claims came since (`move` only while the ticket is still
  in that phase). Re-running a landed `done` is `unchanged`. Refusals say whether your
  claim already ended, was never used on the ticket, or the ticket is held by another
  claim. The exact rules are the holder-op table in `docs/design.md` §5.
- **Claim re-runs** with the same `--claim-id` and `--as` are `unchanged` while the claim
  is live, and renew it if it lapsed (nobody took it over), so a restarted agent gets a
  live claim back.
- **Text.** `--title`, `--reason` and `--as` must not contain newlines or other control
  characters (they are written into the commit message).
- **Actor.** `--as` on `add`, `edit` and `cancel` is optional and only recorded in the
  audit trailer (`tkt-agent`).

## Output

| What | Output |
|---|---|
| Any command that reads or writes the store | one JSON value on stdout |
| `mint` | the bare id on stdout (`CLAIM_ID=$(tkt mint claim-id)`) |
| Usage errors (missing or conflicting flags) | argparse's plain text on stderr, exit 2 |

Mutations print an object:

```json
{"outcome": "committed", "revision": "a1b2c3…", "tickets": [{…}]}
{"outcome": "unchanged", "reason": "already done by this claim", "tickets": [{…}]}
{"outcome": "refused", "code": "ALREADY_CLAIMED", "message": "held by coder-3 until …"}
{"outcome": "error", "exit": 4, "message": "push failed: …", "op": {"op": "claim", "ticket_id": "tkt-7f3a91c2", "claim_id": "…"}}
```

- `tickets` lists the affected tickets as they are after the op, in their on-branch
  form (docs/format.md): exactly one for single-ticket commands, none for `init`, zero
  or more for `reap`. An `unchanged` claim or claim-next still shows the claim it holds.
- Refusals carry a `code` and `message`; failures carry the `op` with the ids it was
  last tried with, so the same command can simply be re-run.
- Reads, each taken from a single snapshot: `show` prints `{"ticket": {…}, "status": "…"}`
  (or a refused `NOT_FOUND` object for an unknown id); `list` prints a JSON array of
  those objects; `log` prints a JSON array of history entries
  `{"revision", "at", "op", "ticket_ids", "agent", "claim_id", "phase", "reason"}`.
- Output is never partial: a result is printed only once it is complete, and a failure
  prints only the error object. Check the exit code first.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Committed, unchanged, a successful read, or `mint` |
| 1 | Refused by the rules (e.g. already claimed, not holder, blocked, invalid input, stale edit, not found) |
| 2 | Usage error (missing or conflicting flags) |
| 3 | Retries exhausted after repeated conflicts; nothing written — re-run the same command |
| 4 | Store error (git failure, remote unreachable or not configured, corrupt data). A failure during the push may mean the commit landed: re-run the same command, which converges either way |
