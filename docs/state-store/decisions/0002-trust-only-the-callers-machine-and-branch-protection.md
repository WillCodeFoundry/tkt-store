# 0002: Trust only the caller's machine and branch protection

**Status:** accepted

## Context

This is state-store's threat model. Writers on different machines share one store.
Anyone with push access to the remote can write anything to the branch, with plain git
or a buggy or compromised program.
Callers may be automated, and may pass an error from state-store on to an AI agent.
state-store does not control the remote: it may be a hosting service, a server over
SSH, or a bare repository.

The kinds of threat this leaves:

- **Code execution:** content from the branch or the remote gets git to run code on the
  caller's machine, for example through a hook, a checked-out file, or a crafted name
  read as a command-line option.
- **Corruption:** a broken or forged entry on the branch leads a caller to a wrong
  result.
- **Data loss:** history is rewritten or the branch deleted, or one commit silently
  overwrites another.
- **Injected text:** a stored value or name, or a message from the remote, reaches an
  AI agent through an error, carrying instructions.
- **Leaked credentials:** git's output quotes the remote's URL, credentials included.
- **Impersonation:** a writer commits under another writer's name.
- **Denial of service:** a writer keeps others from committing, or blocks reads.
- **Disclosure:** someone reads values they should not.

## Decision

- **The caller's machine is trusted fully** (the process, its clone, the git binary,
  git's configuration and credentials): anyone who can change these can already run
  code there.
- **The remote is trusted only to refuse force pushes and deletion of the branch**, and
  to be the same server for fetching and pushing.
- **Nothing else is trusted:** not the entries on the branch, whoever wrote them, nor
  anything the remote sends back.

Against code execution, corruption, data loss, injected text and leaked credentials,
state-store:

- never runs hooks, checks out files, uses a shell or lets the environment point git at
  another repository, and always puts remote names after `--`;
- checks everything it reads, and stops the operation that reads a bad entry
  ([0005](0005-fail-operations-that-read-corrupt-state.md));
- never rewrites or deletes the branch, and commits only by compare-and-swap
  ([0004](0004-use-immutable-snapshots-and-compare-and-swap-commits.md));
- puts only a category in its errors, never stored values or names, nor anything git or
  the remote printed; git's own output goes to a log in the clone, for an operator.

Impersonation, denial of service and disclosure are not defended.

## Alternatives rejected

- **Authenticating writers** (signed commits, or checks on the server): it needs a key
  per writer and a list of trusted keys, or control of the remote, which state-store
  does not have.
- **Trusting what other writers wrote:** one buggy or compromised writer could then
  give every caller wrong results.

## Consequences

- Someone with push access can commit anything that passes the checks, under any
  name: state-store checks what it reads, not who wrote it.
- A writer can keep other commits failing by committing constantly, or block
  operations with a bad entry, until an operator steps in.
- Anyone who can read the remote can read every value, so the store must not hold
  secrets.
- A deployment must protect the branch on the remote, have writers use only state-store
  on the branch, and keep credentials out of the remote's URL (in a credential helper
  instead), since the operator log can quote it.
- The tests cover each defence: forged entries, hooks, environment variables, error
  text and lost push outcomes.
