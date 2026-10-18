# 0002: Threat model: trust the caller's machine and the remote's branch protection

**Status:** accepted

## Context

Writers on different machines share one store, and anyone with push access to the
remote can write anything to the branch. Callers may be automated, and may pass an
error from state-store on to an AI agent. state-store does not control the remote: it
may be a hosting service, a server over SSH, or a bare repository.

## Decision

**What is trusted:**

- **The caller's machine** (the process, its clone, the git binary, git's configuration
  and credentials): fully. Anyone who can change these can already run code there.
- **The remote:** only to refuse force pushes and deletion of the branch, and to be the
  same server for fetching and pushing.
- **Everything else is untrusted:** every entry on the branch, whoever wrote it, and
  everything the remote sends back, including its messages.

**The threats, and how each is handled:**

| Threat | Handling |
|---|---|
| Code from the branch or the remote runs on the caller's machine | git hooks are always disabled, files are never checked out, no command goes through a shell, remote names always follow `--`, and environment variables that could point git at another repository are removed. |
| Corrupt or forged entries lead to wrong results | Everything read is checked, and a bad entry stops the operation that reads it ([0005](0005-corrupt-state-stops-the-operation-that-reads-it.md)). |
| Data is lost: history rewritten, the branch deleted, or one commit overwriting another | The remote refuses force pushes and deletion; state-store never does either, and every commit is a compare-and-swap ([0004](0004-snapshots-and-compare-and-swap-commits.md)). |
| Text from the branch or the remote reaches an AI agent through an error | Errors carry a category only, never stored values or names, nor anything git or the remote printed. git's own output goes to a log in the clone, for an operator. |
| Credentials leak through that log | The log can quote the remote's URL, so credentials belong in a credential helper, not the URL. |

**Accepted risks** (not defended):

- **Forged but valid entries:** someone with push access can commit anything that
  passes the checks. state-store checks what it reads, not who wrote it, and commit
  authors are not verified.
- **Denial of service:** a writer can keep other commits failing by committing
  constantly, or block operations with a bad entry, until an operator steps in.
- **Confidentiality:** anyone who can read the remote can read every value, so the
  store must not hold secrets.
- **A compromised caller machine.**

## Alternatives rejected

- **Authenticating writers** (signed commits, or checks on the server): it needs a key
  per writer and a list of trusted keys, or control of the remote, which state-store
  does not have.
- **Trusting what other writers wrote:** one buggy or compromised writer could then
  give every caller wrong results.

## Consequences

- The tests cover each handled threat: forged entries, hooks, environment variables,
  error text and lost push outcomes.
- A deployment must protect the branch on the remote, have writers use only state-store
  on the branch, and keep credentials out of the remote's URL.
