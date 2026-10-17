# On-branch format — tkt-protocol 2

Protocol 2 (0.2.0) is the format of ADR 0005 and ADR 0007: claims are files of their
own whose names hold their state, claim ids are stored only as their SHA-256 hash, and
everything read is checked; anything that fails a check is set aside, never fatal.
Protocol 1 stores are not read and not migrated. Pre-1.0, while no store is deployed,
format changes keep protocol 2 when documented here (AGENTS.md).

## Branch layout

Default ref: `refs/heads/tkt-store`, i.e. the branch `tkt-store`. It is an ordinary branch,
so it is visible on the git host; branch protection (refuse force-push and deletion)
must target it.

```text
tkt-store.json
tickets/
  tkt-7f3a91c2.json
  tkt-91c20b4e.json
claims/
  tkt-7f3a91c2/
    3f9c…a7e1.open.coder-7.1790995000.1790996800
    81d0…4c2b.released.coder-7.1790990500.1790994100
```

- `tkt-store.json` is exactly `{"protocol": 2}`. `init` writes it into the root commit;
  every snapshot checks it and fails (`StoreError`) if it is missing or anything else.
  The error never repeats what it read.
- One file per ticket, `tickets/<id>.json`: any file there whose name without `.json`
  follows the id rule (below) is a ticket file, and its `id` field must be that name.
- Claims are files under `claims/<id>/`, one folder per ticket (*Claims* below).
- `tickets` and `claims`, where present, must be folders: anything else refuses the whole
  store (`StoreError`), like a bad `tkt-store.json`.
- Ticket files are canonical JSON: UTF-8, sorted keys, 2-space indent, trailing newline
  (stable diffs, byte-identical round trips).
- No other files are meaningful. Unknown files (anything not matching these paths) are
  preserved, never interpreted.

**Reading.** Every file is treated as hostile. A ticket file is read only if it is a
regular file (mode `100644`) of at most 256 KiB, both known from the listing before
anything is read; it must then decode strictly (exactly the fields below, each of its
type), follow the field rules, and be named by its `id`. A file that fails any check is
**set aside**: left out of every decision, kept unchanged, its id still taken, and
recorded with the check that failed (never the value read). An operator repairs it with
an ordinary git commit. Nothing read from a set-aside file is used.

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
  "phase": "implementation",
  "resolution": null,
  "created": 1790990000,
  "updated": 1790995000,
  "content_version": 3
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | string | a slug of 8 to 32 (e.g. `tkt-7f3a91c2`, `fix-login-redirect`; minted ids are `tkt-` + 8 hex); unique, never reused |
| `title` | string | required, 1 to 256 characters, one line; free text (*Field rules*) |
| `body` | string | may be empty; at most 65,536 characters; free text that may hold newlines and tabs |
| `kind` | `"story" \| "task" \| "bug"` | |
| `project` | string \| null | `[owner/]repo`: an optional owner (a slug of 1 to 39) and `/`, then a repo of 1 to 100 lowercase letters, digits, `.`, `_` and `-`, starting and ending with a letter or digit (e.g. `willcodefoundry/tkt-store`, or a root-commit hash); never interpreted; null = no project; a `--project` filter matches that exact value only |
| `priority` | int \| null | 0 to 100, lower = more urgent; null sorts last |
| `blocked_by` | list[string] | at most 20 ticket ids (same pattern as `id`), no duplicates, never the ticket itself, each an existing valid ticket when written; they must be `done` before claiming (a missing or set-aside blocker counts as not done) |
| `tags` | list[string] | at most 20, no duplicates, each a slug of 1 to 50 (a valid GitHub topic) |
| `phase` | `"triage" \| "specification" \| "implementation" \| "cleanup" \| "architecture" \| "hardening" \| "qa" \| "review" \| "release"` | workflow position (which role the ticket waits for); moved only by the holder's `move` |
| `resolution` | `"done" \| "cancelled"` \| null | null while open; set once by `done`/`cancel`; non-null means terminal (final) |
| `created`, `updated` | int | unix seconds (from the injected clock); `updated` is never before `created`, and is set by every op that writes the ticket (add, edit, move, done, cancel; claim ops do not write it) |
| `content_version` | int | at least 1: 1 when added, incremented only by `edit`; an edit must name it (`STALE` otherwise) |

A key outside this table, or a missing one, makes the file invalid (set aside).

**Field rules.** tkt never writes a ticket that breaks the rules in the table: an op
whose values break them, or whose resulting ticket would, is refused `INVALID`. Every
ticket read is checked against the same rules.

- **Slugs.** Identifiers are lowercase slugs: letters `a-z` and digits in runs joined by
  single hyphens, never a hyphen at either end (`tkt-7f3a91c2`, `coder-7`, `auth`).
- **Free text** (`title`, `body`, `tkt-reason`): lengths count code points; nothing is
  normalised. Title and reason must not start or end with whitespace (the Unicode
  White_Space characters); a body may. Two variation selectors in a row are refused.
  These code points are refused:

  | Code points | What |
  |---|---|
  | U+0000–001F (a body may hold U+0009 tab and U+000A newline), U+007F–009F | controls; line ends are newlines only, so `\r\n` is refused |
  | U+D800–DFFF; U+FDD0–FDEF and U+xFFFE–xFFFF in every plane | surrogates, noncharacters (RFC 9839) |
  | U+E000–F8FF, U+F0000–10FFFF | private use |
  | U+00AD, U+034F, U+115F–1160, U+17B4–17B5, U+2800, U+3164, U+FFA0, U+16FE4, U+1D159 | invisible characters and fillers |
  | U+061C, U+200B–200F, U+2028–202E, U+2060–206F, U+FEFF | zero-width characters and joiners, bidi marks and controls, line and paragraph separators |
  | U+180B–180F, U+FE00–FE0D | variation selectors other than U+FE0E/FE0F (text and emoji presentation) |
  | U+FFF0–FFFB, U+13430–1343F, U+1BCA0–1BCA3, U+1D173–1D17A | format controls and specials |
  | U+E0000–E0FFF | tag characters and variation selectors supplement |

  Everything else, including emoji and characters not yet assigned, is allowed.
  Refusing the zero-width joiners (U+200C, U+200D) and tag characters rules out some
  Persian and Indic spellings, joined emoji such as family emoji, and subdivision flags.
- **File size.** A ticket file never exceeds 256 KiB: an op whose ticket file would is
  refused `INVALID`.

**Not stored:** status and history (derived). Claim age is derived from the open claim's
`claimed_at`.

## Claims

A claim is an **empty file** whose name is its whole state (ADR 0007). Nothing in a
claim file is ever read:

```text
claims/<id>/<hash>.open.<agent>.<claimed_at>.<lease_until>        the ticket's open claim
claims/<id>/<hash>.<ended_by>.<agent>.<claimed_at>.<ended_at>     each claim that ended on it
```

| Part | Value |
|---|---|
| `<id>` | the ticket's id |
| `<hash>` | the SHA-256 of the claim id, 64 lowercase hex. The claim id itself (32 lowercase hex, supplied by the caller) is never stored or printed: only the agent that minted it can act on its claim |
| `<ended_by>` | how the claim ended: `released`, `done`, `cancelled`, `reaped`, `taken-over`, `revoked` |
| `<agent>` | the acting agent: a slug of 1 to 39 |
| `<claimed_at>`, `<lease_until>`, `<ended_at>` | unix seconds, 1 to 12 digits, no leading zero |

No part can hold a `.`, so a name splits unambiguously; a name is at most 141
characters. Each op writes its claim changes in the same commit as the rest:

| Op | Claim files |
|---|---|
| `claim`, `claim-next` | adds the `open` file; a takeover first renames the old one to `taken-over` |
| `renew` | renames the `open` file with the new `lease_until` |
| `release` | renames the `open` file to `released` |
| `done` | renames the `open` file to `done` (and writes the ticket's resolution) |
| `cancel` | renames any `open` file to `cancelled` (and writes the ticket's resolution) |
| `reap` | renames each takeable `open` file to `reaped` |

`ended_at` is never before `claimed_at`, and a renewed `lease_until` never before
`claimed_at`, whatever the writer's clock. A `lease_until` more than `MAX_TTL` +
`LEASE_CAP_MARGIN` (2 h + 10 min) after now, which no honest writer sets, reads expired
and may be taken over or reaped. Ended claim files are kept for good: a claim hash that
appears anywhere can never claim again.

**Reading claims.** A file under `claims/` is a claim only if its mode is `100644`, its
blob is git's empty blob and its path matches the pattern above; anything else is an
unknown file, preserved, and no part of it is used (renaming a claim file to anything
else has the effect of deleting it). A `claims/<id>` that is not a folder, or a folder
holding a name with `/` (which git never writes, and no commit can rewrite), holds its
ticket by a set-aside claim, or sets the id aside when there is no ticket. A name with
`/` in the root, `tickets/` or `claims/` refuses the store. The claims
are then checked in this order, the same for every reader; a claim set aside still
fences its hash (it can never claim again):

1. **Each file:** `claimed_at` after `lease_until` or `ended_at` → the claim is set aside.
2. **Each hash:** in more than one folder → every file with it is set aside; ended more
   than once → all set aside; an `open` and an ended file in one folder → the ended one
   wins, only the `open` one is set aside.
3. **Each folder,** counting only the claims still valid: no ticket file → its claims are
   set aside, and so is the id (`add` of it is refused); a set-aside ticket → its claims
   fence but can't be acted on; a resolved ticket → every `open` claim is set aside (the
   resolution wins); more than one `open` claim → all of them are set aside.

A ticket that is left with no valid open claim after an `open` file of its folder was
set aside in step 1, in step 2 for being in more than one folder, or in step 3 for being
one of several, is **held by a set-aside claim**: it reads `claimed`, cannot be claimed
or reaped, and only `cancel` may act on it, so no ticket is locked for good.

## Commit messages

Every op is one commit. The subject line is human-readable and always one line;
trailers are machine-readable:

```text
claim tkt-7f3a91c2: Expire reset tokens

tkt-protocol: 2
tkt-op: claim
tkt-time: 1790995000
tkt-id: tkt-7f3a91c2
tkt-agent: coder-7
tkt-claim: 3f9c…a7e1
```

| Trailer | Required | Values |
|---|---|---|
| `tkt-protocol` | yes | `2` |
| `tkt-op` | yes | `init`, `add`, `edit`, `claim`, `claim-next`, `renew`, `move`, `release`, `done`, `cancel`, `reap` |
| `tkt-time` | yes | unix seconds from the writer's injected clock; informational across writers |
| `tkt-id` | yes (except `init`) | ticket id; `reap` lists one `tkt-id` per released ticket |
| `tkt-agent` | when an agent acted | agent id (a slug of 1 to 39) |
| `tkt-claim` | for claim-scoped ops | the claim's hash (64 lowercase hex), never the claim id |
| `tkt-phase` | on `move` | the ticket's new phase |
| `tkt-reason` | optional | free text, one line, at most 256 characters (cancel/release reasons) |

A commit without tkt trailers is foreign and ignored by history. A tkt commit whose
trailers break the format (another protocol, a missing or repeated required trailer, a
value that breaks its rule) is skipped by history, so one bad commit never breaks
`tkt log`.

Commit author/committer are the identity of the writing process (whatever runs `tkt`);
the acting agent is recorded in `tkt-agent`.
