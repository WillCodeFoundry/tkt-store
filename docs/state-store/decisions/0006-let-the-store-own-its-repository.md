# 0006: Let the store own its repository

**Status:** proposed

## Context

The git store needs very little from a local repository: a place to fetch one branch
into its private ref, to write new objects, and to push from. It never uses a working
tree, the index, local branches, other refs or other branches of the remote.

A clone that a user makes holds much more than that, and can be set up in ways the
store must refuse or advise against: shallow or partial, bare, with a separate push
URL or several URLs, or with a checkout. Each needs a requirement in the README, and
most a check when the store is opened ([design](../design.md#7-opening-a-store)).

## Decision

The store creates and owns the repository it works in.

- **Interface:** `GitStateStore(path, *, url, branch)`. `url` is the remote's URL (not
  a remote name), `branch` the branch on it.
- **Running git:** every command runs as `git --git-dir=<path>`, not `git -C <path>`:
  git refuses `-C` into a bare repository when the user's configuration sets
  `safe.bareRepository=explicit`.
- **Creating:** when `path` does not exist, the store creates a bare repository in a new
  temporary directory next to it, sets `remote.origin.url` to `url` (and no fetch
  refspec, so a fetch writes only the private ref) and `state-store.branch` to
  `branch`, then renames the directory to `path`. A crash leaves at most a temporary
  directory, never a half-made repository at `path`. Creating ends with the same checks
  as reopening.
- **Reopening:** an existing `path` must be a repository the store created: bare, its
  git directory is `path` itself, `state-store.branch` is `branch`, and
  `remote.origin.url` has exactly one value, `url`, with no `remote.origin.pushurl`.
  `git remote get-url -- origin` must equal `git remote get-url --push -- origin`, so
  the user's URL rewriting (`insteadOf`, `pushInsteadOf`) cannot send fetches and pushes
  to different places. Anything else is refused, as an error that replaces `NotAClone`
  and says the repository is not usable as this store.
- **Unchanged:** fetching only the branch into the private ref, committing and pushing
  as now; credentials still come from the user's git configuration (credential helpers,
  ssh keys, configuration injected by CI), and the URL must not hold them.

## Alternatives rejected

- **A clone that the user makes:** it carries every branch of the remote and settings
  the store must check for, and its working tree is never used.
- **A non-bare repository created by the store:** its working tree would never be used.

## Consequences

- These requirements and checks go: a full, non-bare clone, given as its top-level
  directory, preferably without a checkout; not shallow, not partial; a configured
  remote name. The checks that stay are those above under *Reopening*.
- The repository holds only the store's branch.
- These requirements stay: one process at a time per repository, nobody runs git in it
  by hand while writers are active, no credentials in the URL, and the branch name
  rules.
- The minimum git version is set again from the options the store then relies on
  (`rev-parse --is-shallow-repository`, which sets it now, is no longer needed).
- To implement it, change every mention of a clone, of `GitStateStore`'s arguments and
  of `NotAClone` in the README, the design, the code and the tests (including the test
  fixture that makes clones), and add tests for creating, reopening, and refusing a
  repository made for another URL or branch, or changed by hand.
