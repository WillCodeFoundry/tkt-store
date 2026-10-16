# 0007 — Claims are records of their own

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

## Decision

**Layout.** Occupancy moves out of the ticket file into one folder per ticket:

```text
tickets/<id>.json              content, workflow, resolution; no occupancy
claims/<id>/open.json          the ticket's open claim, if it has one
claims/<id>/<claim-hash>.json  one record per claim that has ended on the ticket
```

`<claim-hash>` is the claim id as stored: its SHA-256 from stage 4 (ADR 0005, 64 hex),
the claim id itself until then. The fixed `open.json` slot makes "at most one open
claim per ticket" structural: there is one path for it, even in a forged push.

**Records.** Canonical JSON with a strict schema and the field rules of ADR 0005, like
tickets:

- open: `ticket`, `claim_id`, `holder` (`agent` until stage 4), `claimed_at`,
  `lease_until`;
- ended: the same, plus `ended_at` and `ended_by`, one of `released`, `done`,
  `cancelled`, `reaped`, `taken-over`, `revoked`.

The ticket loses `claim` and `ended_claim_ids`. Its `updated` and `content_version`
change only with content, workflow or resolution; claim times are in the records.

**Ops.** Each op is still one commit. Ending a claim moves `open.json` to
`<claim-hash>.json` with its end recorded, in the same commit:

| Op | Writes |
|---|---|
| `claim`, `claim-next` | `open.json`; a takeover first ends the old claim as `taken-over` |
| `renew` | `open.json` (`lease_until`) |
| `release` | ends the claim as `released` |
| `done` | the ticket (`resolution`), and ends the claim as `done` |
| `cancel` | the ticket (`resolution`), and ends any open claim as `cancelled` |
| `reap` | ends each takeable claim as `reaped` |
| `revoke` (stage 4) | ends the claim as `revoked` |
| `add`, `edit`, `move` | the ticket only (`move` and, from stage 4, a held `edit` check `open.json`) |

**Rules.** Every outcome in design.md §5 stays; only where a rule looks changes. The
snapshot carries the tickets and, per ticket, its open claim and ended records:

- "this ticket's current claim" is its `open.json`;
- "an ended claim on this ticket" is an ended record in its folder;
- "an id recorded on any ticket" is a record with that hash in any folder: open on
  another ticket is `ALREADY_CLAIMED`, ended is `NOT_HOLDER`;
- a re-run of `done` is a NoOp when the claim's record says `ended_by: done`
  (replacing "the last of `ended_claim_ids`");
- `claim` and `claim-next` look the claim id up first, so a re-run always finds its own
  claim, whatever state its ticket is in.

**Reading.** Claim records are validated on their own, like ticket files (ADR 0005):
only regular files, a size cap of 4 KiB checked before reading, the strict schema, the
field rules, and their place: `ticket` names the folder, and an ended record's file
name is its `claim_id`. An invalid record is set aside by itself; the ticket stays
valid. Then:

- **File names fence.** The listing of `claims/` gives every recorded claim hash
  without reading a file, so fencing never uses the content of an invalid file: an
  ended record whose name is a well-formed claim hash fences that hash even if its
  content is set aside. A set-aside `open.json` fences nothing (its hash is in its
  content), but its ticket counts as held by an unknown claim: it cannot be claimed or
  reaped until an operator repairs it.
- **One hash, one record.** A hash found in more than one record (two folders, or an
  open claim and an ended record) has all of those records set aside; the hash stays
  fenced.
- **A claim on a set-aside or missing ticket** keeps fencing its hash and can't be acted
  on.

**`SET_ASIDE`** is a new refusal for any op that names a set-aside ticket (`add` of its
id included, instead of `DUPLICATE_ID`) or a claim that is set aside or whose ticket is
set aside. It says which check failed, never the value, and that an operator must
repair the file. So a holder whose ticket was set aside is told so, and is never given
a second ticket.

**File sizes.** A ticket file no longer grows with claims, so stage 1's budgets go:
every op may write a ticket file of up to 256 KiB, and `FULL` is removed.

**History** is unchanged: commits keep their trailers (`tkt-claim` and the rest), and
`tkt log` still tells every op in order.

## Alternatives rejected

- **Claims inside the ticket, as before:** the four problems above. Reading claim ids
  from a ticket that failed validation was rejected too: nothing read from an invalid
  file is used.
- **`claims/<claim-hash>.json`, one flat folder:** "one claim id, one ticket" would be
  structural instead, but "one open claim per ticket" would need a check across every
  record, and a ticket's claims would no longer be together for rules, history and
  repairs.
- **A folder per ticket without the `open.json` slot:** two open claims on one ticket
  could be pushed by hand and would need a check of their own.
- **Ordering ended records by name** (a sequence number): order comes from
  `claimed_at` and `ended_at`, and the one rule that used order now reads `ended_by`.
  The full order of ops is `tkt log`.

## Consequences

- Part of protocol 2: `docs/format.md` describes the new layout when stage 2a lands.
- The domain changes: `Ticket` loses its claim fields, claims become records with an
  end, and `Snapshot` carries them; the rules keep their outcomes.
- `show` and `list` join each ticket with its open claim, and `show` can list the
  ticket's ended claims.
- Stage 1's `FULL`, `CLAIM_FILE_MAX` and `CONTENT_FILE_MAX` are removed, and the
  cross-ticket duplicate-claim check of ADR 0005 is replaced by "one hash, one record".
- One file per claim ever made. Listing `claims/` costs little; every record is read,
  but ended records never change, so ADR 0006's cache keeps them like resolved tickets
  (stage 2b), and an op reads only the open claims and new records.
- An operator repairing a ticket finds all of its occupancy in `claims/<id>/`.
