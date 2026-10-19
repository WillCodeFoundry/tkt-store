# 0003: Trust only the caller's machine and the remote's handling of pushes

**Status:** accepted

## Context

This is state-store's threat model. Writers on different machines share one store, kept
on a branch of a git remote
([0002](0002-store-keys-as-paths-in-the-tree-of-one-git-branch.md)). Anyone with push
access to the remote can write anything to the branch, with plain git or a buggy or
compromised program. state-store does not control the remote.

The kinds of threat this leaves:

- **Code execution:** content from the branch or the remote gets git to run code on the
  caller's machine, for example through a hook.
- **Corruption:** a broken or forged entry on the branch leads a caller to a wrong
  result.
- **Data loss:** history is rewritten, or one commit silently overwrites another.
- **Injected text:** a stored value reaches whatever reads an error.
- **Leaked credentials:** credentials in the remote's URL end up in output.
- **Impersonation, denial of service, disclosure:** a writer commits under another's
  name, keeps others from committing, or reads values it should not.

## Decision

- **The caller's machine is trusted fully:** the process, its clone, the git binary,
  git's configuration and credentials. Anyone who can change these can already run
  code there.
- **The remote is trusted only to apply pushes and report their outcome truthfully,**
  and to refuse force pushes and deletion of the branch.
- **Nothing else is trusted:** not the entries on the branch, whoever wrote them, nor
  any text the remote sends back.

So state-store runs git with hooks off and never through a shell
([design](../design.md#running-git)), checks everything it reads
([0005](0005-fail-operations-that-read-corrupt-state.md)), commits only by
compare-and-swap and never rewrites the branch
([0004](0004-use-immutable-snapshots-and-compare-and-swap-commits.md)), keeps values out
of its error messages, and requires credentials to stay out of the URL
([README](../README.md#git-store)). Impersonation, denial of service and disclosure are
not defended.

## Alternatives rejected

- **Authenticating writers** (signed commits, or checks on the server): it needs a key
  per writer and a list of trusted keys, or control of the remote, which state-store
  does not have.
- **Trusting what other writers wrote:** one buggy or compromised writer could then
  give every caller wrong results.

## Consequences

- Someone with push access can commit anything that passes the checks, under any
  name: state-store checks what it reads, not who wrote it.
- A writer can keep other commits failing by committing constantly, until an operator
  steps in.
- Anyone who can read the remote can read every value, so the store must not hold
  secrets.
