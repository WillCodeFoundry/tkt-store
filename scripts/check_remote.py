"""Check that a store's remote protects the store branch (docs/design.md §7).

The remote must refuse a non-fast-forward push and a deletion of the store branch, or a
stray `git push --force` could rewrite or wipe the ticket history. This script tries
both against the real remote and reports whether each was refused:

    uv run python scripts/check_remote.py --repo /work/tasks --remote origin

`--repo` is a clone of the store repository with the remote configured; the store must
already be initialised (`tkt init`). Run it while no agent is working.

Safe to run against a real store. Each probe push carries a lease on the head it read,
so it can never replace a commit someone else pushed meanwhile. If the remote is not
protected and a probe is accepted, the branch is restored at once, again under a lease,
so only the probe's own change is undone. Exit codes: 0 both refused, 1 a probe was
accepted (protection missing; branch restored), 2 the check could not run or was
inconclusive (e.g. the branch moved while it ran).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from tkt_store.infrastructure.git.wire import DEFAULT_REF, STORE_META_PATH

PROBE_REF = "refs/tkt-store-check/head"
"""Where the remote head is fetched to, in the local clone only."""


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def push(repo: Path, remote: str, refspec: str, lease: str) -> tuple[bool, str]:
    """Push `refspec` with an explicit lease; (accepted, the remote's status or error)."""
    out = git(repo, "push", "--porcelain", f"--force-with-lease={lease}", "--", remote, refspec)
    status = [line.split("\t")[-1] for line in out.stdout.splitlines() if line[:1] in "!*+-="]
    detail = status[0] if status else (out.stderr.strip().splitlines() or ["?"])[-1]
    return out.returncode == 0, detail


def remote_head(repo: Path, remote: str, ref: str) -> str | None:
    out = git(repo, "ls-remote", "--", remote, ref)
    if out.returncode != 0:
        sys.exit(f"cannot reach {remote}: {out.stderr.strip()}")
    return out.stdout.split()[0] if out.stdout.strip() else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", required=True, type=Path, help="a clone of the store")
    parser.add_argument("--remote", required=True, help="the store's remote, e.g. origin")
    parser.add_argument("--ref", default=DEFAULT_REF)
    args = parser.parse_args()
    repo, remote, ref = args.repo, args.remote, args.ref

    head = remote_head(repo, remote, ref)
    if head is None:
        print(f"{remote} has no {ref}: initialise the store first (tkt init)")
        return 2
    if git(
        repo, "fetch", "--no-tags", "--no-write-fetch-head", remote, f"+{ref}:{PROBE_REF}"
    ).returncode:
        print(f"cannot fetch {ref} from {remote}")
        return 2
    try:
        if git(repo, "cat-file", "-e", f"{PROBE_REF}:{STORE_META_PATH}").returncode:
            print(f"{ref} on {remote} is not a tkt store (no {STORE_META_PATH}); not probing it")
            return 2
        empty_tree = git(repo, "mktree").stdout.strip()
        stray = git(repo, "-c", "user.name=tkt check", "-c", "user.email=check@tkt-store.invalid",
                    "commit-tree", empty_tree, "-m", "tkt-store protection check: never a store"
                    ).stdout.strip()  # fmt: skip
        checks = [
            ("refuses a non-fast-forward push", f"{stray}:{ref}", f"{ref}:{head}", stray),
            ("refuses deleting the branch", f":{ref}", f"{ref}:{head}", ""),
        ]
        failed = False
        for name, refspec, lease, probe in checks:
            accepted, detail = push(repo, remote, refspec, lease)
            if not accepted and "stale info" in detail:  # our lease failed: the branch moved
                print(f"????  {name}: {ref} moved during the check; re-run when no agent works")
                return 2
            if not accepted:
                print(f"PASS  {name}: {detail}")
                continue
            failed = True
            restored, how = push(repo, remote, f"{head}:{ref}", f"{ref}:{probe}")
            print(f"FAIL  {name}: the push was accepted ({detail})")
            print(f"      restored {ref} to {head}" if restored else f"      RESTORE FAILED: {how}")
            if not restored:
                print(f"      put it back by hand: git push --force {remote} {head}:{ref}")
                return 2
    finally:
        git(repo, "update-ref", "-d", PROBE_REF)
    if failed:
        print("protection is missing: see README, Deploying")
        return 1
    print("the remote protects the store branch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
