# On-branch format — tkt-protocol 1

## Branch layout

Default ref: `refs/heads/tkt`.

```text
tickets/
  tkt-7f3a.json
  tkt-91c2.json
```

- One file per ticket; the id is both the filename stem and the `id` field.
- Files are canonical JSON: UTF-8, sorted keys, 2-space indent, trailing newline
  (stable diffs, byte-identical round trips).
- No other files are meaningful. Unknown files are preserved, never interpreted.

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
  "claim": {"agent": "coder-7", "claim_id": "c9f2e1…", "lease_until": 1791000000},
  "stage": "development",
  "created": 1790990000,
  "updated": 1790995000
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | string | `tkt-` + lowercase hex, unique, never reused |
| `title` | string | required, non-empty |
| `body` | string | may be empty |
| `kind` | `"story" \| "task" \| "bug"` | |
| `project` | string \| null | project identity; null = any project |
| `priority` | int \| null | lower = more urgent; null sorts last |
| `blocked_by` | list[string] | ticket ids that must be `done` before claiming |
| `tags` | list[string] | free-form |
| `claim` | object \| null | present ⇒ held (possibly expired) |
| `stage` | `"development" \| "review" \| "qa" \| "done" \| "cancelled"` | lifecycle position; `done`/`cancelled` are terminal (final once set) |
| `created`, `updated` | int | unix seconds (from the injected clock) |
| `extra` | object | optional; unknown keys preserved verbatim |

**Not stored:** status, claim age, history. All derived.

## Commit messages

Every op is one commit. Subject line is human-readable; trailers are machine-readable:

```text
claim tkt-7f3a: Expire reset tokens

tkt-protocol: 1
tkt-op: claim
tkt-id: tkt-7f3a
tkt-agent: coder-7
tkt-claim: c9f2e1…
```

| Trailer | Required | Values |
|---|---|---|
| `tkt-protocol` | yes | integer protocol version |
| `tkt-op` | yes | `init`, `add`, `update`, `claim`, `claim-next`, `renew`, `release`, `done`, `cancel`, `reap` |
| `tkt-id` | yes (except `init`, `reap`) | ticket id; `reap` lists one `tkt-id` per released ticket |
| `tkt-agent` | when an agent acted | agent id |
| `tkt-claim` | for claim-scoped ops | claim id |
| `tkt-stage` | when a `release` hands off | the ticket's new stage |
| `tkt-reason` | optional | free text (cancel/release reasons) |

Commit author/committer are the identity of the *writer process* (the coordinator),
not the agent; the agent is recorded in `tkt-agent`.
