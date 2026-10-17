# Changelog

## Unreleased

- Lost races are recognised on any git server: after the server rejects a push, one
  `ls-remote` shows whether the branch moved (retry) or not (store error), instead of
  matching each server's wording. This also covers `git daemon` and receive-pack over
  SSH, whose lost races were store errors in 0.1.0.
- The store keeps itself packed (`git gc --auto` after each commit) and caches decoded
  tickets by blob id, so a long-lived store reads only tickets that changed (from
  0.2.0, resolved and invalid ones are also saved to a file per clone, ADR 0006).
- Every store has a remote: `--no-remote` is removed, and `tkt-store.json` records only
  the protocol version. For a single machine, use a bare repository on it as the remote.
- README: a *Deploying* section (one clone per process, what a remote must do).
- `scripts/check_remote.py` checks that a store's remote refuses a non-fast-forward push
  and a deletion of the store branch, restoring the branch if either is accepted.
- `scripts/bench_github.py` is now `scripts/bench.py`, for any remote; it refuses to run
  against a store holding tickets it did not create.
- ADR 0001 trimmed to the verdict, the binding constraint and the push budget.
- Security review: every finding is a strict expected-failure test in `tests/security/`
  (markers `security_bug` / `security_design`); test modules no longer import helpers
  from other test suites; pytest runs with `--strict-markers`.
- Security model decided (ADR 0005, `docs/design.md` §8), to be implemented for 0.2.0:
  agents confined to `tkt`; everything read validated and invalid tickets set aside;
  strict field rules and limits; escaped output; hashed claim ids; holder-only edits
  while held; `revoke`; identity from git (no `--as`); `tkt clone`; `tkt audit`.
- Store size decided (ADR 0006): from 0.2.0 each clone caches resolved and invalid
  tickets in a file in its git directory, so an op reads and checks only the others;
  tickets are neither moved nor sharded. Q3 (`claim-next` stays one op) and Q4 (integer
  seconds) decided.
- README: agents use only `tkt`, never git, on the store; the risks of path remotes
  (code execution in other agents) and `git daemon` (no authentication).
- 0.2.0 stage 1 (ADR 0005): tkt never writes an invalid ticket. `validate_op` checks
  every value an op writes and `decide` every ticket it would write, whole (`INVALID`;
  `domain/fields.py`, `docs/format.md`):
  - ids, tags and `--as` are lowercase slugs (ids 8 to 32, `tkt-` no longer required;
    tags at most 20 of 50; agents at most 39); `project` is a lowercase `[owner/]repo`;
  - title, body and reason refuse controls and a fixed list of invisible, reordering
    and hidden-data characters (never normalised; title and reason one line without
    outer whitespace), at most 256, 65,536 and 256 characters;
  - priority 0 to 100; at most 20 blockers and 20 tags without duplicates;
  - file budgets: `add`, and an `edit` that grows the file, up to 192 KiB; a claim up
    to 255 KiB (`FULL`, a new refusal, beyond); every other op up to 256 KiB;
    `claim-next` and `reap` skip tickets they cannot write.

  A lease ending more than `MAX_TTL` + `LEASE_CAP_MARGIN` (10 minutes) after now reads
  expired and may be taken over or reaped. git always gets `--` before the remote name.
- 0.2.0 stage 2a (ADR 0005, ADR 0007): **protocol 2**. Claims are empty files under
  `claims/<id>/` whose names hold their state (hash, open or how it ended, agent,
  times), renamed on renew and when they end; tickets lose `claim` and
  `ended_claim_ids`. Claim ids are stored and printed only as their SHA-256 hash, and
  the library no longer mints them. Everything read is checked: `tkt-store.json` must be
  exactly `{"protocol": 2}`; a ticket file must be a regular file of at most 256 KiB,
  decode strictly (unknown keys invalid) and follow the field rules; claim files are
  judged from their names alone, in a fixed order. A bad file is set aside, never
  fatal, and never echoed; an op naming one is refused `SET_ASIDE` (new). History skips
  malformed commits. Output: each ticket comes with its open claim
  (`{"ticket", "claim"}`), and `log` entries carry `claim_hash`. Stage 1's file budgets
  and `FULL` are gone.
- 0.2.0 stage 2b (ADR 0006): each clone keeps a cache in `.git/tkt-store/cache/` (256
  shard files) of what never changes again (valid resolved tickets, the verdicts on invalid ticket
  files, resolved tickets' claim file names), keyed by git object id, so an op reads and
  checks only what may have changed. `claims/` is listed without recursing and unknown
  folders are read in one batch. At 20,000 tickets a CLI op takes about 1.1 s instead
  of 2.4 s. The cache is JSON, written atomically, stamped with the versions and a hash
  of the rules it caches, and ignored when it cannot be trusted; deleting it is always
  safe.
- Claims to become records of their own in 0.2.0 (ADR 0007): empty files under
  `claims/<id>/` whose names hold the claim's whole state (hash, open or how it ended,
  holder, times), so fencing survives a ticket being set aside, nothing in a claim is
  ever parsed, and ticket files stop growing with claims. Claim-id hashing moves to
  stage 2a; stage 1's file budgets and `FULL` go; a new `SET_ASIDE` refusal names
  set-aside tickets and claims.

## 0.1.0 — milestone 1

The first working version: `tkt` runs end to end against a real git store, local-only
or backed by a shared remote, measured against a protected GitHub branch.

- **Domain:** claim timing, derived status, and every rule: holder-op fencing by claim
  id, full claim history (`ended_claim_ids`), re-run convergence for every op.
- **Transaction loop and `TicketStore`:** snapshot → decide → compare-and-swap commit,
  bounded retries with jittered exponential backoff counted in attempts.
- **Git store:** tickets as canonical JSON on the `tkt-store` branch, git plumbing only
  (no worktree, no index); pushes carry `--force-with-lease`; lost races are recognised
  in git's and GitHub's wording and retried; unknown files and non-UTF-8 names are
  preserved.
- **CLI:** one JSON value per store command, documented exit codes, error output that
  carries the op and its ids, `tkt mint` for caller-supplied ids.
- **Measured (ADR 0001):** ~4 s per write against GitHub, about 20 commits per minute
  per store; GitHub's guidance of 6 pushes per minute per repository is the binding
  limit, which fits about 10 agents on tasks of tens of minutes.
- **Tests:** one contract suite for every store, real-git race and crash tests,
  Hypothesis invariants, the README quickstart run as a test.
- Requires git 2.29 or later.

## 0.0.0 — skeleton

- Interfaces, data structures, design documents and ADRs for architecture review.
- Logic stubbed with `NotImplementedError`.
- Working module-boundary test (`tests/unit/test_architecture.py`).
