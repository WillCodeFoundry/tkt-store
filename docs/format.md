# On-branch format — tkt-protocol 1

## Branch layout

Default ref: `refs/heads/tkt`.

```text
tkt-store.json
tickets/
  tkt-7f3a.json
  tkt-91c2.json
```

- `tkt-store.json` records the format version, `{"protocol": 1}`. `init` writes it into
  the root commit; every snapshot checks it and fails (`StoreError`) if it is missing or
  newer than the client supports.
- One file per ticket, `tickets/tkt-<hex>.json`; the id is both the filename stem and the
  `id` field (a mismatch is an error).
- Files are canonical JSON: UTF-8, sorted keys, 2-space indent, trailing newline
  (stable diffs, byte-identical round trips).
- No other files are meaningful. Unknown files (anything not matching the two paths
  above) are preserved, never interpreted. A ticket file that fails to decode fails the
  whole snapshot; repair it with an ordinary git commit.

## Ticket schema

```json
{
  "id": "tkt-7f3a",
  "title": "Expire reset tokens",
  "body": "Markdown text …",
  "kind": "task",
  "project": "91c6469b14fef602e0bb5ab9957b09937623a0da",
  "priority": 2,
  "blocked_by": ["tkt-91c2"],
  "tags": ["auth"],
  "claim": {"agent": "coder-7", "claim_id": "c9f2e1d07b3a4e58a6f0c2b9e4d1a873", "lease_until": 1791000000, "claimed_at": 1790995000},
  "stage": "development",
  "done_by": null,
  "last_claim_id": null,
  "created": 1790990000,
  "updated": 1790995000,
  "version": 3
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | string | `tkt-` + lowercase hex (`^tkt-[0-9a-f]+$`), unique, never reused |
| `title` | string | required, non-empty, no control characters |
| `body` | string | may be empty |
| `kind` | `"story" \| "task" \| "bug"` | |
| `project` | string \| null | project identity; null = any project |
| `priority` | int \| null | lower = more urgent; null sorts last |
| `blocked_by` | list[string] | ticket ids (same pattern as `id`) that must be `done` before claiming |
| `tags` | list[string] | free-form |
| `claim` | object \| null | present ⇒ held (possibly expired): `agent`, `claim_id` (exactly 32 lowercase hex characters), `lease_until`, `claimed_at` (unix seconds; renew keeps it) |
| `stage` | `"development" \| "review" \| "qa" \| "done" \| "cancelled"` | lifecycle position; `done`/`cancelled` are terminal (final once set) |
| `done_by` | string \| null | the claim id that completed the ticket; set only when `stage` is `done` |
| `last_claim_id` | string \| null | the most recent claim id that ended other than by `done` (released, reaped, taken over, cancelled); fenced, it cannot claim again |
| `created`, `updated` | int | unix seconds (from the injected clock) |
| `version` | int | content version for optimistic concurrency: 1 when added, incremented only by `update`; an update must name it (`STALE` otherwise) |

Unknown keys are preserved **at top level** and round-tripped unchanged; there is no
`extra` object on disk (`Ticket.extra` is only their in-memory holder).

**Not stored:** status and history (derived). Claim age is derived from `claim.claimed_at`.

## Commit messages

Every op is one commit. The subject line is human-readable and always one line;
trailers are machine-readable:

```text
claim tkt-7f3a: Expire reset tokens

tkt-protocol: 1
tkt-op: claim
tkt-time: 1790995000
tkt-id: tkt-7f3a
tkt-agent: coder-7
tkt-claim: c9f2e1d07b3a4e58a6f0c2b9e4d1a873
```

| Trailer | Required | Values |
|---|---|---|
| `tkt-protocol` | yes | integer protocol version |
| `tkt-op` | yes | `init`, `add`, `update`, `claim`, `claim-next`, `renew`, `release`, `done`, `cancel`, `reap` |
| `tkt-time` | yes | unix seconds from the writer's injected clock; informational across writers |
| `tkt-id` | yes (except `init`, `reap`) | ticket id; `reap` lists one `tkt-id` per released ticket |
| `tkt-agent` | when an agent acted | agent id (no control characters) |
| `tkt-claim` | for claim-scoped ops | claim id |
| `tkt-stage` | when a `release` hands off | the ticket's new stage |
| `tkt-reason` | optional | free text, no control characters (cancel/release reasons) |

A commit without tkt trailers is foreign and ignored by history. A tkt commit missing
a required trailer, or with an unknown future protocol version, is a `StoreError`.

Commit author/committer are the identity of the writing process (whatever runs `tkt`);
the acting agent is recorded in `tkt-agent`.
