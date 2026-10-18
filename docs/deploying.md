# Deploying

How to run a tkt store for a set of agents: the store repository, the clones, the agents'
identities and what the remote must do. The security model behind these rules is in
[`design.md`](design.md) §8 and ADR 0005.

Keep the store in its own repository; `tkt` uses only the `tkt-store` branch. Requires
git 2.29 or later.

## One clone per process

Give every process that runs `tkt` its own clone of the store repository, and never let
two processes use the same clone, for example by mounting one clone into several
containers. Each clone keeps a cache of what it has already read in
`.git/tkt-store/cache/`; deleting it is always safe (the next command reads the store in
full once). When a git command fails, tkt's error says only what kind of failure it
was; git's own message is in `.git/tkt-store/git-errors.log`. It may quote the server,
and the remote's URL as git printed it, credentials included if the URL holds them, so
read it yourself rather than passing it to an agent. Partial clones
(`git clone --filter`) are refused: make a full clone.

## Agents use only `tkt`, never git, on the store

`tkt` validates what it writes (and, from 0.2.0, everything it reads), never checks out
files (so no checkout hooks, filters or symlinks are ever involved), and writes only by
compare-and-swap; from 0.2.0 it also refuses to act as another agent's holder. Plain git
does none of that: an agent running it can forge tickets and history that other agents
then trust. Make each clone without a checkout (`git clone --no-checkout`; from 0.2.0,
`tkt clone`), and give agents only the `tkt` command for the store.

## One git identity per agent

From 0.2.0, `tkt` records who did each operation as the commit author, the identity git
itself uses (`user.name` and `user.email`), and refuses to write without one. Give each
agent its own, for example a name such as `coder-7` and a GitHub noreply address: the
store's history is readable by everyone with access to the repository, and GitHub can
refuse pushes that would expose a private address.

## The remote

The remote's repository is shared by all clones, so it needs the same care. A remote
given as a file path (a bare repository) is only safe when every clone is on the same
machine as that repository, with the same filesystem. If clones live in VMs or sandboxes
(Docker Desktop, Docker Sandboxes) or on other machines, don't mount the remote's
directory into them: git's locking may not hold across that boundary, and two agents
could both get the same claim. A path remote is also a security risk: every agent can
write the repository's files, so a compromised agent can plant a hook or change its
config, and that hook then runs inside every other agent that pushes. Use a path remote
only for agents that fully trust each other; otherwise serve it over the network (a
hosting service, SSH, or `git daemon`), so that only its own machine writes to it.

**Any git server works as the remote:** a hosting service such as GitHub, a bare
repository over SSH or `git daemon`, or, when every clone is on the same machine as the
repository, a bare repository's path. Every `tkt` write is one fetch and one push. The
server must:

- **accept direct pushes to `tkt-store`:** no pull-request, status-check or
  signed-commit requirement on that branch (store commits are unsigned);
- **refuse force pushes and deletion of `tkt-store`,** however your server does that,
  e.g. a ruleset on GitHub, or `receive.denyNonFastForwards` and `receive.denyDeletes`
  on a plain bare repository. `tkt` itself never does either; this protects the history
  from other writers.

`git daemon` is for trusted local agents only (e.g. agents in containers or VMs on one
host). It runs no code from the agents, but it has no authentication: anything that can
reach its port can push anything with plain git, forged tickets included. Bind it to
loopback, and use SSH if you need authentication:

```sh
git daemon --reuseaddr --base-path=/srv/git --export-all \
  --enable=receive-pack --listen=127.0.0.1 --port=9418
```

Agents then clone `git://<host>/tkt.git`; from a Docker Sandbox the host is
`host.docker.internal`, once the port is allowed (`sbx policy allow network
localhost:9418`).

## Check the protection

Once the store exists (`tkt init`), check the remote. The script tries a
non-fast-forward push and a deletion of the store branch, reports whether each was
refused, and restores the branch if either was accepted:

```sh
uv run python scripts/check_remote.py --repo /work/tasks --remote origin
```
