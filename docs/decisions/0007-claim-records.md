# 0007 — Claims are records of their own, held in file names

**Status:** accepted; to be implemented for 0.2.0 (protocol 2) in stage 2a, before the
read-side validation of ADR 0005 builds on it

## Context

A claim lives inside its ticket today: `claim` holds the open claim, and
`ended_claim_ids` every claim id that has ended on the ticket. Planning the read-side
validation of ADR 0005 showed four problems with that:

1. **Fencing depends on the ticket being valid.** An invalid ticket is set aside, and
   nothing read from an invalid file is ever used, so its claim ids vanish with it. If
   agent A holds ticket X with claim id C and X is set aside (a forged push suffices),
   A's re-run of `claim-next` with C finds no ticket holding C and takes a second
   ticket; ids that ended on X could claim again elsewhere. "One claim id names one
   claim on one ticket" breaks.
2. **The ticket file grows forever.** `ended_claim_ids` is never truncated, so stage 1
   needed three file budgets and a `FULL` refusal to keep content from crowding out
   claims.
3. **One claim id on one ticket is checked across every ticket** on every read.
4. **Every claim op rewrites the ticket**, so content and occupancy share one file and
   one validity: a bad claim field sets the whole ticket aside, and a bad title hides
   the claim.

A first draft moved claims into JSON records under `claims/<id>/`. Review showed that
any record with content brings the problem back one level down: a forged, unreadable
open record has a claim whose hash and lease are unknown, so it fences nothing, can't
be reaped or ended, and locks its ticket. Unix lock files point the other way: the
file's existence and name are the lock, and content is only ever a hint.

## Decision

**Layout.** Occupancy moves out of the ticket file into one folder per ticket, and a
claim's whole state is its file name. Claim files are empty; nothing in them is ever
read.

```text
tickets/<id>.json                                                  content, workflow, resolution
claims/<id>/<hash>.open.<holder>.<claimed_at>.<lease_until>        the open claim
claims/<id>/<hash>.<ended_by>.<holder>.<claimed_at>.<ended_at>     each ended claim
```

- `<hash>`: the SHA-256 of the claim id, 64 lowercase hex (ADR 0005). Hashing lands with
  claim records in stage 2a rather than stage 4, so names are final from the start.
- `<holder>`: a slug of at most 39 (the acting agent until stage 4 records `holder`).
- `<claimed_at>`, `<lease_until>`, `<ended_at>`: unix seconds, decimal, no leading zero.
- `<ended_by>`: `released`, `done`, `cancelled`, `reaped`, `taken-over` or `revoked`.

None of the parts can hold a `.`, so a name splits unambiguously. A name is about 150
characters, within every filesystem's 255.

**A claim file is valid** when it is an empty regular file (mode `100644`, size 0, both
known from the listing) whose name matches that pattern. Anything else under `claims/`
is an unknown file: preserved, never interpreted, and no part of its name is used, not
even a hash. Renaming a genuine claim file to garbage therefore has the effect of
deleting it, which a forger with push access can do in any design.

**The ticket** loses `claim` and `ended_claim_ids`. Its `updated` and
`content_version` change only with content, workflow or resolution; claim activity no
longer shows in the ticket.

**Ops.** Each op is still one commit, and a change of claim state is a rename (one
entry removed and one added, in the same tree):

| Op | Writes |
|---|---|
| `claim`, `claim-next` | adds the `open` file; a takeover first renames the old one to `taken-over` |
| `renew` | renames the `open` file with the new `lease_until` |
| `release` | renames the `open` file to `released` |
| `done` | the ticket (`resolution`), and renames the `open` file to `done` |
| `cancel` | the ticket (`resolution`), and renames any valid `open` file to `cancelled` |
| `reap` | renames each takeable `open` file to `reaped` |
| `revoke` (stage 4) | renames the `open` file to `revoked` |
| `add`, `edit`, `move` | the ticket only (`move`, and from stage 4 a held `edit`, check the `open` file) |

**Rules.** Every outcome in design.md §5 stays; only where a rule looks changes, and
it looks only at names:

- "this ticket's current claim" is its `open` file;
- "an ended claim on this ticket" is an ended file in its folder;
- "an id recorded on any ticket" is a valid file with that hash in any folder: open on
  another ticket is `ALREADY_CLAIMED`, ended is `NOT_HOLDER`;
- a re-run of `done` is a NoOp when the claim's file says `done` (replacing "the last
  of `ended_claim_ids`"); a revoked claim's refusals say so from its name;
- `claim` and `claim-next` look the claim's hash up first, so a re-run always finds its
  own claim, whatever state its ticket is in.

**Reading.** The snapshot lists `tickets/` and `claims/` and reads only ticket files;
claim state comes from the listing alone. On top of each name's own pattern, these
checks run on the listing, the same for every reader. A claim they set aside still
fences its hash:

| Forged state | Verdict |
|---|---|
| `claimed_at` after `lease_until`, or after `ended_at` | the claim is set aside |
| a lease beyond the cap (stage 1) | reads expired, takeable |
| two `open` files in one folder | both set aside; the ticket is held by a set-aside claim |
| an `open` and an ended file with the same hash | the ended one wins: only the `open` one is set aside |
| the same hash in two folders | every file with it is set aside |
| an `open` file on a resolved ticket | the resolution wins: the claim is set aside |
| a folder with no ticket file | its claims are set aside; `add` of that id is refused |

A ticket held by a set-aside claim cannot be claimed (`claim-next` passes over it) and
is left out by `reap`, but it is never locked for good: `cancel` still resolves it.
`show` reports it as held by a set-aside claim. Claims on a set-aside ticket keep
fencing and can't be acted on.

**`SET_ASIDE`** is a new refusal. It never echoes a value; it names the check that
failed and says an operator must repair the store. In order, after `validate_op`'s
`INVALID` and `NOT_INITIALISED`:

1. the op names a set-aside ticket, as its ticket or as a blocker, or `add` names an id
   whose ticket is set aside or whose claims folder exists without a ticket:
   `SET_ASIDE` (for `add`, instead of `DUPLICATE_ID`; the library treats it like
   `DUPLICATE_ID` when it mints a fresh id);
2. `claim` or `claim-next` with a hash whose file is set aside, or lies on a set-aside
   ticket: `SET_ASIDE`, never a new claim;
3. a holder op (`renew`, `move`, `release`, `done`) whose hash's file is set aside:
   `SET_ASIDE`;
4. otherwise the rules of design.md §5, which see only valid claims and valid tickets:
   a landed re-run of `release`, `move` or `done` still converges from the names.

**File sizes.** A ticket file no longer grows with claims, so stage 1's budgets go:
every op may write a ticket file of up to 256 KiB, and `FULL` is removed.

**History** is unchanged: commits keep their trailers (`tkt-claim` and the rest), and
`tkt log` still tells every op in order, with any reason given.

**What is not separated.** Only state that grows, that must outlive its ticket's
validity, or whose invariant a layout makes structural gets its own files; today that
is claims alone. Phase and resolution stay in the ticket: one value each, overwritten,
of no use while the ticket is set aside, and a split would add files and cross-file
checks with no gain in concurrency, since every op is a compare-and-swap on the whole
store.

## Alternatives rejected

- **Claims inside the ticket, as before:** the four problems above. Reading claim ids
  from a ticket that failed validation was rejected too: nothing read from an invalid
  file is used.
- **JSON claim records** (`claims/<id>/open.json` and `<hash>.json`, with the state in
  content): a forged, unreadable open record has an unknown hash and lease, so it
  fences nothing, can't be reaped or ended, and its holder can be given a second
  ticket. It also needs a schema, a size cap, a cache and content checks of its own.
- **State in names, the rest in content** (`<hash>.open.json` with the lease inside):
  better, but the same unreadable-lease case remains for the open claim.
- **Folders by state** (`claims/open/` and `claims/ended/`): reads less per op with
  content, but names-only claims are never read anyway.
- **One flat folder by hash, or one occupancy file per ticket:** one open claim per
  ticket would need content from every record; one file per ticket grows again and
  hides fencing behind one validity.
- **An append-only event file per claim transition:** every renewal adds a file, and
  `tkt log` already holds the full history.
- **A git ref per claim, or git notes:** they break the single-ref compare-and-swap that
  makes every op one atomic commit (ADR 0001).
- **Separating phase or resolution:** see *What is not separated*.

## Consequences

- Part of protocol 2: `docs/format.md` describes the layout when stage 2a lands, and
  stage 4's claim-id hashing moves into stage 2a.
- The domain changes: `Ticket` loses its claim fields; claims become values parsed from
  names, with an end; `Snapshot` carries them and the set-aside ones. The rules keep
  their outcomes.
- No JSON, size cap or cache for claims: the stage 2b cache covers ticket files only.
- `show` and `list` join each ticket with its open claim, and `show` can list its ended
  claims from their names.
- Stage 1's `FULL`, `CLAIM_FILE_MAX` and `CONTENT_FILE_MAX` are removed, and the
  cross-ticket duplicate-claim check of ADR 0005 becomes "one hash, one file".
- One empty file per claim ever made; they all share git's single empty blob. Each op
  lists them (names only) and each claim op rewrites its ticket's folder and the
  `claims/` tree, which has an entry per ticket that was ever claimed. At 20,000 tickets
  with about 3 claims each, that should roughly triple ADR 0006's listing and tree
  figures (about 20 and 40 ms); stage 2a measures it.
- An operator repairing a ticket finds all of its occupancy in `claims/<id>/`, readable
  through `tkt show`.
