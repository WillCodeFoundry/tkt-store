# 0006: Let the store make its own clone

**Status:** accepted

## Context

The git store needs very little from a local repository: a place to fetch one branch
into, to write new objects, and to push from. It never uses a working tree, the index,
local branches, tags or other branches of the remote.

A clone that a user makes holds much more than that, and can be set up in ways the
store must refuse or advise against: shallow or partial, bare, with several URLs,
with a checkout, or with every branch of the remote. Each needs a
requirement in the README, and most a check when the store is opened
([design](../design.md#7-cloning-and-opening)).

## Decision

The store makes the clone it works in, and opens only clones it made.

- **Cloning:** `GitStateStore.clone(path, *, url, branch)` clones the branch `branch`
  of the remote at `url` (a URL string, or a path, made absolute) to `path`, which
  must not exist, and returns the store opened on it. It is the only operation that
  makes a clone. The clone is not bare, has no
  checkout, and holds only that branch and no tags (`git clone --no-checkout
  --single-branch --branch <branch> --no-tags`); the store records the branch in it.
  It is made in a temporary directory next to `path` and renamed to `path` when
  complete.
- **The branch must exist:** cloning a branch the remote does not have fails with
  `NoSuchBranch`. Whoever sets up the remote creates the branch first, with one commit
  of the empty tree.
- **Every state has a revision:** since the branch exists before any store uses it,
  `revision` is always a commit id, never `None`. `MemoryStateStore` starts at an
  empty state with a revision of its own.
- **Opening:** `GitStateStore(path)` opens a clone that `clone` made, without
  contacting the remote. The URL and branch are read from the clone. A path that is not
  such a clone, or a clone whose configuration no longer passes the checks made when
  opening, is refused with `UnusableRepository`.
- **Credentials** come from the user's git configuration (credential helpers, ssh
  keys, configuration injected by CI), and the URL must not hold them.

## Alternatives rejected

- **A clone that the user makes:** it can carry every branch of the remote and
  settings the store must check for, and its working tree is never used.
- **An empty repository made with `git init`, set up to fetch the branch:** `git init`
  cannot learn the remote's object format (SHA-1 or SHA-256), so the store would have
  to fix one and refuse remotes with the other.
- **A bare clone:** `git clone --bare` puts the branch on a local branch and writes no
  fetch refspec, so the store would set up where fetches go itself; and git refuses
  `git -C <path>` into a bare repository when the user's configuration sets
  `safe.bareRepository=explicit`, so every command would have to name the git
  directory instead.
- **Creating the branch with the first commit:** a clone cannot select a branch that
  does not exist yet, so the store would have to clone something else and remove it,
  and keep a separate state for a store never committed to.
- **Cloning when opening:** opening would need the remote, and any open could make a
  clone; a separate call keeps opening local and makes cloning explicit.

## Consequences

- How a clone is made is no longer the user's concern: there are no requirements on
  shallow, partial or bare clones, checkouts or remote names, and opening checks only
  what the store wrote.
- Opening needs no network; cloning does, and so can fail with `RemoteFailed`.
- The branch is created on the remote, by whoever sets it up, before the first clone.
- The store has no state without a revision, and a branch missing from the remote is
  `NoSuchBranch` wherever the store finds it missing.
- A clone is still used by one process at a time, nobody runs git in it by hand while
  writers are active, the URL holds no credentials, and the branch name rules apply.
- The minimum git version follows from the options cloning needs.
