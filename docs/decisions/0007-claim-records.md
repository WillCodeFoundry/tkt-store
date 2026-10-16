# 0007 — Claims are records of their own, held in file names

**Status:** accepted; implemented for 0.2.0 (protocol 2) in stage 2a, with the read-side
validation of ADR 0005

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
- `<claimed_at>`, `<lease_until>`, `<ended_at>`: unix seconds, decimal, 1 to 12 digits,
  no leading zero.
- `<ended_by>`: `released`, `done`, `cancelled`, `reaped`, `taken-over` or `revoked`.

None of the parts can hold a `.`, so a name splits unambiguously. A name is at most 141
characters, within every filesystem's 255.

**A claim file is valid** when its mode is `100644`, its blob is the empty blob (its id,
computed once per repository, is in the listing, so nothing is read) and its name
matches that pattern. Anything else under `claims/` is an unknown file: preserved,
never interpreted, and no part of its name is used, not even a hash. Renaming a genuine
claim file to garbage therefore has the effect of deleting it, which a forger with push
access can do in any design.

**The ticket** loses `claim` and `ended_claim_ids`. Its `updated` and
`content_version` change only with content, workflow or resolution; claim activity no
longer shows in the ticket.

**Ops.** Each op is still one commit, and a change of claim state is a rename (one
entry removed and one added, in the same tree). tkt never writes a name it would set
aside: `ended_at` is at least `claimed_at`, and a renewed `lease_until` at least
`claimed_at`, even when the writer's clock is behind the claimer's.

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
- a re-run of `done` is a NoOp when the ticket is resolved `done` and the claim's file
  says `done` (replacing "the last of `ended_claim_ids`"). If that file was deleted by
  hand, the re-run is `NOT_HOLDER` ("completed by another claim"): wrong but safe. A
  revoked claim's refusals say so from its name;
- `claim-next` looks the claim's hash up first, so a re-run always finds its own claim,
  whatever state its ticket is in; `claim` names its ticket, so it answers `NOT_FOUND` or
  `TERMINAL` for that ticket first, then looks the hash up.

**Reading.** The snapshot lists `tickets/` and `claims/` and reads only ticket files;
claim state comes from the listing alone. The checks run in this order, the same for
every reader, and a claim they set aside still fences its hash:

1. **Each file:** not a valid claim file (mode, empty blob, name) → an unknown file,
   ignored; a valid name whose times are out of order (`claimed_at` after
   `lease_until` or `ended_at`, which tkt never writes) → the claim is set aside.
2. **Each hash,** over the files that passed step 1 (files set aside there still
   fence): in more than one folder → every file with it is set aside; ended more than
   once → every file with it is set aside (the claim is over, so its ticket is not
   held); an `open` and an ended file in one folder → the ended one wins, only the `open`
   is set aside.
3. **Each folder,** counting only claims still valid, in this order: no ticket file →
   its claims are set aside (and `add` of that id is refused); a resolved ticket →
   every valid `open` is set aside, the resolution wins; more than one valid `open` →
   all of them are set aside.

A ticket is **held by a set-aside claim** when it is left with no valid open claim after
an `open` file of its folder was set aside in step 1, in step 2 for being in more than
one folder, or in step 3 for being one of several. (A forged file beside a valid open
claim is set aside and fences, but the valid claim stands.) Then it cannot be claimed
(`claim-next` passes over it), is left out by `reap`, and every op on it but `cancel` is
refused `SET_ASIDE`; `cancel` always resolves it, so no ticket is locked for good. When
the claim is proven over (an ended file wins, or the ticket is resolved), the ticket is
not held. `show` reports a held ticket as held by a set-aside claim. Claims on a set-
aside ticket keep fencing and can't be acted on. A lease beyond the cap (stage 1) is a
rule, not a verdict: it reads expired and is takeable.

**`SET_ASIDE`** is a new refusal. It never echoes a value; it names the check that
failed and says an operator must repair the store. In order, after `validate_op`'s
`INVALID` and `NOT_INITIALISED`:

1. the op names a set-aside ticket, as its ticket or as a blocker (only `add` and
   `edit` name blockers, and an `edit` checks the blockers of the ticket it would
   write, existing ones included; to every other op a set-aside blocker is simply not
   done, so a `claim` of the ticket it blocks is `BLOCKED`), or `add` names an id
   whose ticket is set aside or whose claims folder exists without a ticket:
   `SET_ASIDE` (for `add`, instead of `DUPLICATE_ID`; the library treats it like
   `DUPLICATE_ID` when it mints a fresh id);
2. any op but `cancel` on a ticket held by a set-aside claim: `SET_ASIDE` (this covers a
   fresh `claim`, holder ops with any hash, a held `edit` and `revoke`);
3. `claim` or `claim-next` with a hash that has no valid file but a set-aside one, or
   whose file lies on a set-aside ticket: `SET_ASIDE`, never a new claim;
4. a holder op (`renew`, `move`, `release`, `done`) with a hash that has no valid file
   but a set-aside one: `SET_ASIDE`;
5. otherwise the rules of design.md §5, which see only valid claims and valid tickets:
   a landed re-run of `release`, `move` or `done` still converges from the names, and
   a hash with a valid ended file follows that file even if a set-aside `open` shares
   it.

**File sizes.** A ticket file no longer grows with claims, so stage 1's budgets go:
every op may write a ticket file of up to 256 KiB, and `FULL` is removed.

**History** keeps its trailers; `tkt-claim` carries the claim's hash from stage 2a, as
the file names do. `tkt log` still tells every op in order, with any reason given.

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

- Part of protocol 2: `docs/format.md` describes the layout when stage 2a lands.
  Stage 4's claim-id hashing moves into stage 2a, and with it the library stops minting
  claim ids and `show` can no longer print one.
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
  `claims/` tree, which has an entry per ticket that was ever claimed. Measured in stage
  2a at 20,000 tickets with 3 claims each (60,000 names): listing `claims/` about
  170 ms, parsing the names about 260 ms, assembling the snapshot about 250 ms, and
  rebuilding one folder and the `claims/` tree about 30 ms, all per op. That is more
  than the ~60 ms first estimated, and about doubles the uncached cost of an op at that
  size. Stage 2b's cache (ADR 0006) therefore also keeps parsed claim folders by their
  tree id, so an op lists `claims/` without recursing (about 20 ms) and re-reads only the
  folders that changed.
- An operator repairing a ticket finds all of its occupancy in `claims/<id>/`, readable
  through `tkt show`.
