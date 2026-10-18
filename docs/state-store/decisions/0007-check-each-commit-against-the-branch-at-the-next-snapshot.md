# 0007: Check each commit against the branch at the next snapshot

**Status:** accepted

## Context

The store fetches and pushes through one remote, but git may use a different URL for
each: a push URL (`pushurl`), or the user's URL rewriting (`insteadOf`,
`pushInsteadOf`). Users set these up for good reasons, most often to fetch over HTTPS
and push over SSH, to the same repository.

The guarantees need fetches and pushes to reach the same repository. If pushes reach
another one, commits land where no snapshot reads them, or every compare-and-swap
fails against a branch that is not at the snapshot's revision, and callers start
again forever.

Two URLs cannot show whether they name the same repository: `https://host/a.git` and
`git@host:a.git` usually do, and an ssh `Host` alias can send either anywhere. What the
store can see is the branch: under the preconditions it only moves forward, so the
outcome of a commit is still visible on a later fetch.

## Decision

The store accepts push URLs and rewrites that differ from the fetch URL, and checks
each commit's outcome against the branch at the next snapshot of the same store
object:

- after a published commit, the branch's history must hold it;
- after a failed compare-and-swap, the branch must have moved from the revision the
  lease expected.

A check that fails raises `PushElsewhere`
([design](../design.md#3-taking-a-snapshot-and-reading)). Opening still refuses
several URLs or several push URLs, since git pushes to each and reports each.

## Alternatives rejected

- **Refusing any push URL that differs from the fetch URL:** it refuses the common,
  correct setup of fetching over HTTPS and pushing over SSH.
- **Comparing the hosts and paths of the two URLs:** text cannot show where a URL
  leads, so such a comparison both refuses correct setups and accepts wrong ones.
- **Checking with `ls-remote` right after every push:** it costs a round trip to the
  remote on every commit, where the next snapshot fetches anyway.
- **Ignoring the user's git configuration:** the same configuration holds the
  credentials and identity the store needs.

## Consequences

- Fetching and pushing the same repository by different URLs works.
- A wrong push URL is found at the next snapshot, at no cost on the network: at once
  for a caller that starts again after a failed compare-and-swap, and only after the
  fact for a commit that landed elsewhere.
- A commit is checked only if the same store object takes a snapshot after it: the
  last commit before a process exits is never checked.
