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
clone from `tkt clone`. Each agent has its own git identity, which does not change while
it runs. The rules below bind writers that go through `tkt`; an agent with plain git and
push access can always write well-formed forged content, which only server-side identity
or commit signing could expose.

**Everything read from the branch is treated as hostile and validated:**

- One set of field checks, used on write (`validate_op`) and on read:
  - `holder` (below): the GitHub username rule (letters, digits, single hyphens, no
    hyphen at either end, at most 39);
  - tags: the GitHub topic rule (lowercase letters, digits, hyphens; at most 20 tags of
    at most 50);
  - project: `[owner/]repo`, each segment `[A-Za-z0-9._-]` of at most 100;
  - free text (title, body, reason): a PRECIS-style rule. NFC; no control characters
    (`Cc`, except newline and tab in the body), format characters (`Cf`: bidi, zero-width,
    tag characters), private-use, surrogate or unassigned characters, line or paragraph
    separators. Title and reason are single-line, title is never blank; no leading or
    trailing whitespace anywhere. Title at most 256, reason 256, body 65,536;
  - priority 0–100; blockers at most 20, no duplicates, no self-block;
  - lengths count Unicode code points after NFC.
- Writes still refuse unknown blockers; on read, a blocker that is missing or set aside
  counts as not done.
- Whole-ticket and cross-ticket checks on read (e.g. no claim on a resolved ticket; a
  claim hash current on one ticket only: if two tickets carry it, both are set aside).
- A strict schema: a ticket with keys outside it is invalid; `tkt-store.json` too.
- A ticket file is at most 256 KiB. Reads check the size before reading; writes refuse an
  op whose encoded file would exceed it (`INVALID`), so `tkt` never writes what it would
  refuse to read.
- An invalid ticket is set aside and reported (cached as invalid, ADR 0006); it never
  fails the whole store. A partial view is safe: a set-aside blocker counts as not done,
  and the worst case is `claim-next` choosing a less urgent ticket. `add` of an id whose
  file is set aside is `DUPLICATE_ID`. A malformed commit is skipped and reported by
  history. Only regular files at `tickets/tkt-<hex>.json` are read; other files are
  preserved, as before.
- The lease cap is time-dependent, so it lives in the rules: a lease ending more than
  `MAX_TTL` + `SKEW_GRACE` after now is treated as takeable (and reads expired).

**Output carries no surprises:** all non-ASCII is escaped; errors never echo values read
from the store (they name the file and the field); `list` never prints a ticket's body
(`show`, `claim`, `claim-next`, `edit` do). Agent guidance: every composed field (title,
body, reason, tags, holder, project) is data, never instructions.

**Claims are capabilities.** Tickets and history (the `tkt-claim` trailer) store the
SHA-256 of each claim id (64 lowercase hex), never the id. Only the agent that minted it
can renew, move, release or finish its claim, and while a ticket is held only its holder
may edit it (`edit` takes the claim id; anyone else gets `NOT_HOLDER`). A re-run of a
claim is recognised by the hash alone. Callers always supply claim ids: the library
stops minting them, since a minted id could never be read back. `revoke` (new, anyone,
optional reason) ends a claim without resolving the ticket: `NOT_FOUND`; `TERMINAL` if
resolved; NoOp if not claimed; otherwise the hash joins `ended_claim_ids`, and the
holder's next `renew`, `move` or `done` is `NOT_HOLDER` (its `release` a NoOp), each
saying the claim was revoked. `cancel` remains for work that is no longer wanted.

**Identity comes from git, not from a flag.** No command takes an agent name (`--as` is
removed). `tkt` uses the author identity git would put on the commit (`git var
GIT_AUTHOR_IDENT`), run with `user.useConfigOnly=true` so git never invents one from the
OS account and host name, and refuses to write if none is configured. The commit author
records who did each op, and `tkt log` shows its name and email, unverified; the
`tkt-agent` trailer goes. A claim stores `holder`, the git name mapped to an identifier:
accents folded (NFKD, then combining marks dropped), each run of characters outside
`[A-Za-z0-9]` (hyphens included) replaced by one `-`, cut to 39, then hyphens trimmed
from both ends; refused if nothing is left (so a name in a non-Latin script needs an
ASCII `user.name`). `show` and `list` say who is working on what; `list --holder NAME`
maps its argument the same way and matches ignoring case, as GitHub does. A re-run of a
claim keeps its `holder`. `tkt clone URL DIR` makes the clone without a checkout and
prints the identity and the holder name; every write reports them. Documentation
recommends a GitHub noreply address per agent: the store's history is readable by
everyone with access, and GitHub can refuse pushes that expose a private address.

**Small additions:** git always receives the remote name after `--`; `tkt audit`
(read-only) reports set-aside tickets and malformed commits.

**Documentation** tells operators: use only `tkt`, and why; a path remote gives every
agent the power to run code in the others (planted hooks, changed config); `git daemon`
runs no agent code but has no authentication, so anything that reaches its port can push
anything.

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
- **An agent name declared per command (`--as`), or set apart from git:** it duplicated
  the commit author and invited mismatches; with hashed claim ids it no longer helps
  recognise re-runs. Accepting git names verbatim was rejected too: they may hold
  spaces and any text, so the stored `holder` is a mapped identifier.
- **Failing on a git name that is not an identifier:** mapping it is friendlier and
  loses nothing, since the commit keeps the exact name.
- **SSH commit signing:** it would authenticate names, at the cost of a key per agent and
  a trusted-keys list kept outside the store. Not planned.

## Consequences

- The file format and the CLI change: protocol 2 (hashed claim ids, `holder`, a strict
  schema), no `--as`, new `clone`, `revoke`, `audit`, `edit --claim-id`. 0.1.0 stores are
  not migrated: 0.2.0 refuses any store whose protocol is not 2 with a clear
  `StoreError`, rather than reading it (its tickets would all fail the strict schema).
  `docs/format.md` and `docs/cli.md` change with each stage.
- Two git names can map to the same `holder`; that affects only what the board shows,
  since claims are proven by hash.
- Prompt injection is reduced, not prevented: the agent that works a ticket reads its
  body. The defences are confinement, guidance and narrow permissions for agents.
- An agent with plain git and push access can still forge well-formed tickets and
  history, or get a genuine held ticket set aside by pushing a duplicate claim hash;
  branch protection keeps history from being rewritten, nothing more.
- Junk files and spam tickets still cost every op: every file under `tickets/` is listed
  and in every commit's tree, and spam open tickets are read each time (only resolved and
  invalid ones are cached, ADR 0006).
- Implemented in stages, each flipping its security tests: (1) field checks, limits,
  lease cap and `--`; (2) reading the store: set-aside tickets, size and type checks,
  tolerant history, the cache of resolved and invalid tickets (ADR 0006); (3) output:
  escaping, clean errors, `list` without bodies; (4) identity from git and `tkt clone`,
  hashed claim ids, `holder`, holder-only edits, `revoke`; (5) `tkt audit`.
