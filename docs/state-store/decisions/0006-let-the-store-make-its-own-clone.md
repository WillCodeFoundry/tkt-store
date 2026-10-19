# 0006: Let the store make its own clone

**Status:** accepted

## Context

The git store needs very little from a local repository: a place to fetch one branch
into, to write new objects, and to push from. It never uses a working tree, the index,
local branches, tags or the remote's other branches.

A clone that a user makes holds much more than that, and can be set up in ways the
store would have to refuse or advise against: shallow or partial, bare, with a
checkout, or with every branch of the remote.

## Decision

- **Cloning:** `GitStateStore.clone(path, *, url, branch)` clones only `branch` of the
  remote at `url` to `path`, with no checkout and no tags, records the branch in the
  clone, and returns the store on it. It is the only way a clone is made.
- **The branch must exist:** whoever sets up the remote creates it first, with one
  commit. So every state of a store has a revision.
- **Opening:** `GitStateStore(path)` opens a clone that `clone` made, without
  contacting the remote.

## Alternatives rejected

- **A clone that the user makes:** it can carry settings and branches the store would
  have to check for.
- **An empty repository made with `git init` and set up to fetch the branch:** one
  `git clone` already writes the remote, the fetch refspec and the remote's object
  format.
- **Creating the branch with the first commit:** a clone cannot select a branch that
  does not exist yet, and the store would need a separate state for a store never
  committed to.
- **Cloning when opening:** opening would need the remote; a separate call keeps
  opening local and cloning explicit.

## Consequences

- Opening needs no network; cloning does.
- Before the first clone, someone creates the branch on the remote.
