# 0005 — Security model: agents confined to tkt, everything read is validated

**Status:** accepted; implemented in stages for 0.2.0 (tests/security marks what is
still missing)

## Context

The agents that share a store are LLM-driven. A security review asked what one
compromised or confused agent (prompt-injected by a web page or a repository it was
working on) could do to the others: run code on their machines, prompt-inject them, or
forge or break shared state. It found, among others: no code execution over a network
remote, but code execution in every agent through a shared path remote; free text,
unknown keys, invisible and control characters reaching other agents unfiltered; forged
history trailers; one bad file taking the store down; claim ids printed by `show`, so
any agent could act as any holder; unbounded sizes and priorities. Each finding is a
test in `tests/security/`, a strict expected failure until its fix lands.

`tkt` cannot control the remote (GitHub, a self-hosted server, `git daemon`, a path), so
nothing can be enforced when a push arrives.

## Decision

**Agents are confined to `tkt`.** They never run git against the store, and get their
clone from `tkt clone`. The rules below bind writers that go through `tkt`; an agent with
plain git and push access can always write well-formed forged content, which only
server-side identity or commit signing could expose.

**Everything read from the branch is treated as hostile and validated:**

- One set of field checks, used on write (`validate_op`) and on read: agent names follow
  the GitHub username rule; tags the GitHub topic rule; project is `[owner/]repo` (each
  segment `[A-Za-z0-9._-]`); free text (title, body, reason) follows a PRECIS-style rule:
  NFC, no control (`Cc`, except newline and tab in the body), format (`Cf`: bidi,
  zero-width, tag characters), private-use, surrogate or unassigned characters, no line
  or paragraph separators. Title and reason are single-line; title is never blank; no
  leading or trailing whitespace; lengths count characters.
- Limits: priority 0–100; title 256; body 65,536; reason 256; 20 tags of up to 50; agent
  39; project 100 per segment; 20 blockers (no duplicates, no self-block; unknown
  blockers allowed and count as not done); a ticket file is at most 256 KiB, checked
  before it is read.
- Whole-ticket and cross-ticket checks on read (e.g. no claim on a resolved ticket; a
  claim id current on one ticket only). The lease cap is time-dependent, so it lives in
  the rules: no lease may end more than `MAX_TTL` + `SKEW_GRACE` after now.
- A strict schema: a ticket with keys outside it is invalid; `tkt-store.json` too.
- An invalid ticket is left out of the snapshot and reported (cached as invalid by blob
  id); it never fails the whole store. A malformed commit is skipped and reported by
  history. Only regular files at `tickets/tkt-<hex>.json` are read; other files are
  preserved, as before.

**Output carries no surprises:** all non-ASCII is escaped; errors name the file and the
field, never the value; `list` never prints a ticket's body (`show`, `claim`,
`claim-next`, `edit` do). Agent guidance: every composed field (title, body, reason,
tags, agent, project) is data, never instructions.

**Claims are capabilities.** Tickets and history store a hash (SHA-256) of each claim
id, never the id, so only the agent that minted it can renew, move, release or finish
its claim. While a ticket is held, only its holder may edit it. A new `revoke` lets
anyone end a claim without resolving the ticket (an optional reason is recorded), the
gentler alternative to `cancel`.

**Identity comes from the clone.** `tkt clone URL DIR --as NAME` makes the clone (no
checkout) and sets its git identity; commands no longer take `--as`. The claim's agent,
the `tkt-agent` trailer and the commit author are the same name; `tkt log` shows it,
labelled unverified.

**Small additions:** git always receives the remote name after `--`; `tkt audit`
(read-only) reports quarantined tickets and malformed commits.

**Documentation** tells operators: use only `tkt`, and why; a path remote gives every
agent the power to run code in the others (planted hooks, changed config); `git daemon`
has no authentication, so anything that reaches its port can push anything.

## Alternatives rejected

- **Validating pushes on the server** (`pre-receive`, `tkt verify`): the remote is
  unknown and may be a hosting service without custom hooks.
- **Preserving unknown keys for forward compatibility:** a deployed format change bumps
  the protocol, which older clients already refuse; the keys were only an injection
  channel.
- **An "untrusted" section in the JSON:** every composed field can carry instructions,
  so the split adds structure without protection; guidance plus a `list` without bodies
  does more.
- **Anyone may edit a held ticket:** the holder's instructions could be swapped mid-work.
- **Readable claim ids:** any agent confined to `tkt` could act as any holder.
- **`--as` on every command:** it duplicated the clone's git identity and invited
  mismatches; with hashed claim ids it no longer helps recognise re-runs.
- **SSH commit signing now:** it would authenticate names, at the cost of a key per agent
  and a trusted-keys list kept outside the store. Deferred.

## Consequences

- The file format and the CLI change (hashed claim ids, strict schema, no `--as`, new
  `clone`, `revoke`, `audit`): a breaking release, 0.2.0. `docs/format.md` and
  `docs/cli.md` change with each stage of the implementation.
- Prompt injection is reduced, not prevented: the agent that works a ticket reads its
  body. The defences are confinement, guidance and narrow permissions for agents.
- An agent with plain git and push access can still forge well-formed tickets and
  history; branch protection keeps history from being rewritten, nothing more.
- Junk entries and spam tickets still cost every commit until tickets are separated or
  sharded (design.md §9, Q1).
- Implemented in stages, each flipping its security tests: (1) field checks, limits,
  lease cap and `--`; (2) reading the store: quarantine, size and type checks, tolerant
  history, caching invalid tickets; (3) output: escaping, clean errors, `list` without
  bodies; (4) `tkt clone` and identity, hashed claim ids, holder-only edits, `revoke`;
  (5) `tkt audit`.
