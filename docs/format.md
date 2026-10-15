# On-branch format — tkt-protocol 1

Pre-1.0, while no store is deployed, format changes keep protocol 1 when documented
here (AGENTS.md). Protocol 1 includes `phase`/`resolution` (which replaced `stage`),
`ended_claim_ids`, `claim.claimed_at`, `content_version` and `tkt-store.json`.

## Branch layout

Default ref: `refs/heads/tkt-store`, i.e. the branch `tkt-store`. It is an ordinary branch,
so it is visible on the git host; branch protection (refuse force-push and deletion)
must target it.

```text
tkt-store.json
tickets/
  tkt-7f3a91c2.json
  tkt-91c20b4e.json
```

- `tkt-store.json` records the format version and the store's mode,
  `{"mode": "remote", "protocol": 1}` (`mode` is `remote` or `local`, fixed for the
  store's life; opening it in the other mode is refused). `init` writes it into
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
  "id": "tkt-7f3a91c2",
  "title": "Expire reset tokens",
  "body": "Markdown text …",
  "kind": "task",
  "project": "91c6469b14fef602e0bb5ab9957b09937623a0da",
  "priority": 2,
  "blocked_by": ["tkt-91c20b4e"],
  "tags": ["auth"],
  "claim": {"agent": "coder-7", "claim_id": "c9f2e1d07b3a4e58a6f0c2b9e4d1a873", "lease_until": 1791000000, "claimed_at": 1790995000},
  "phase": "implementation",
  "resolution": null,
  "ended_claim_ids": ["8a21c4f09e3b4d7fb6c5a1e2d3f40b9c"],
  "created": 1790990000,
  "updated": 1790995000,
  "content_version": 3
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | string | `tkt-` + lowercase hex (`^tkt-[0-9a-f]+$`), unique, never reused |
| `title` | string | required, non-empty, no control characters |
| `body` | string | may be empty |
| `kind` | `"story" \| "task" \| "bug"` | |
| `project` | string \| null | opaque project identity (never interpreted); null = no project; a `--project` filter matches that exact value only |
| `priority` | int \| null | lower = more urgent; null sorts last |
| `blocked_by` | list[string] | ticket ids (same pattern as `id`) that must be `done` before claiming |
| `tags` | list[string] | free-form |
| `claim` | object \| null | present ⇒ held (possibly expired): `agent`, `claim_id` (exactly 32 lowercase hex characters), `lease_until`, `claimed_at` (unix seconds; renew keeps it) |
| `phase` | `"triage" \| "specification" \| "implementation" \| "cleanup" \| "architecture" \| "hardening" \| "qa" \| "review" \| "release"` | workflow position (which role the ticket waits for); moved only by the holder's `move` |
| `resolution` | `"done" \| "cancelled"` \| null | null while open; set once by `done`/`cancel`; non-null means terminal (final) |
| `ended_claim_ids` | list[string] | every claim id that has ended on this ticket, oldest first, however it ended (released, reaped, taken over, cancelled, done); never truncated; an id here can never claim again; when `resolution` is `done`, the last entry completed the ticket |
| `created`, `updated` | int | unix seconds (from the injected clock); `updated` is set by every op that writes the ticket |
| `content_version` | int | optimistic concurrency for content: 1 when added, incremented only by `edit`; an edit must name it (`STALE` otherwise) |

Unknown keys are preserved **at top level** and round-tripped unchanged; there is no
`extra` object on disk (`Ticket.extra` is only their in-memory holder).

**Not stored:** status and history (derived). Claim age is derived from `claim.claimed_at`.

## Commit messages

Every op is one commit. The subject line is human-readable and always one line;
trailers are machine-readable:

```text
claim tkt-7f3a91c2: Expire reset tokens

tkt-protocol: 1
tkt-op: claim
tkt-time: 1790995000
tkt-id: tkt-7f3a91c2
tkt-agent: coder-7
tkt-claim: c9f2e1d07b3a4e58a6f0c2b9e4d1a873
```

| Trailer | Required | Values |
|---|---|---|
| `tkt-protocol` | yes | integer protocol version |
| `tkt-op` | yes | `init`, `add`, `edit`, `claim`, `claim-next`, `renew`, `move`, `release`, `done`, `cancel`, `reap` |
| `tkt-time` | yes | unix seconds from the writer's injected clock; informational across writers |
| `tkt-id` | yes (except `init`) | ticket id; `reap` lists one `tkt-id` per released ticket |
| `tkt-agent` | when an agent acted | agent id (no control characters) |
| `tkt-claim` | for claim-scoped ops | claim id |
| `tkt-phase` | on `move` | the ticket's new phase |
| `tkt-reason` | optional | free text, no control characters (cancel/release reasons) |

A commit without tkt trailers is foreign and ignored by history. A tkt commit missing
a required trailer, or with an unknown future protocol version, is a `StoreError`.

Commit author/committer are the identity of the writing process (whatever runs `tkt`);
the acting agent is recorded in `tkt-agent`.
