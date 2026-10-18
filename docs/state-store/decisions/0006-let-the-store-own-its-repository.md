# 0006: Let the store own its repository

**Status:** proposed

## Context

The git store needs very little from a local repository: a place to fetch one branch
into its private ref, to write new objects, and to push from. It never uses a working
tree, the index, local branches, other refs or other branches of the remote.

A clone that a user makes holds much more than that, and can be set up in ways that
break the store: shallow or partial, bare or not, with a separate push URL, several
URLs, or a checkout. Each of these needs a requirement in the README and a check when
the store is opened ([design](../design.md#7-opening-a-store)).

## Decision

The store creates and owns the repository it works in.

- **Interface:** `GitStateStore(path, *, url, branch)`. `url` is the remote's URL (not
  a remote name), `branch` the branch on it.
- **Creating:** when `path` does not exist, or is an empty directory, the store creates
  a bare repository there, adds one remote with `url`, and records `branch` in the
  repository's configuration, so that it can tell later which store the repository
  belongs to.
- **Reopening:** an existing `path` must be a repository the store created: bare, its
  git directory is `path` itself, it records the same `branch`, and its one remote has
  exactly the one URL `url`, the same for fetching and pushing once the user's git
  configuration has rewritten it (`insteadOf`, `pushInsteadOf`). Anything else is
  refused, as an error that replaces `NotAClone` and says the repository is not usable
  as this store.
- **Unchanged:** fetching only the branch into the private ref, committing and pushing
  as now; credentials still come from the user's git configuration (credential helpers,
  ssh keys, configuration injected by CI), and the URL must not hold them.

## Alternatives rejected

- **A clone that the user makes:** it carries every branch of the remote and settings
  the store must check for, and its working tree is never used.
- **A non-bare repository created by the store:** its working tree would never be used.

## Consequences

- These requirements and checks go: a full, non-bare clone, made without a checkout,
  given as its top-level directory; not shallow, not partial; a configured remote name.
  The checks that stay are those above under *Reopening*.
- The repository holds only the store's branch.
- These requirements stay: one process at a time per repository, nobody runs git in it
  by hand while writers are active, no credentials in the URL, and the branch name
  rules.
- The minimum git version is set again from the options the store then relies on
  (`rev-parse --is-shallow-repository`, which sets it now, is no longer needed).
- To implement it: rewrite the README's *Example*, *Store objects* and *Git store*
  sections and design §7 for the new interface and checks; rename `NotAClone` in the
  README, `errors.py` and its exports; say "repository" instead of "clone" in
  [0003](0003-trust-only-the-callers-machine-and-the-remotes-handling-of-pushes.md);
  and change the tests to open stores on new paths from the test remote's URL, with
  tests for creating, reopening, and refusing a repository made for another URL or
  branch, or changed by hand.
