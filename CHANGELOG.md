# Changelog

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
