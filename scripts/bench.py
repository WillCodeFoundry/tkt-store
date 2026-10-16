"""Benchmark a remote-backed store against a real remote (ADR 0001).

Not part of the test suite. It WRITES many tickets: point it at a dedicated, otherwise
empty test repository, never at a real store. It refuses to run against a store that
holds any ticket it did not create itself. Any remote works: a hosted one (GitHub), a
bare repository over SSH, or `git daemon`. Check the remote's protection separately,
with `scripts/check_remote.py`.

    uv run python scripts/bench.py --url git@github.com:ORG/REPO.git --workdir /tmp/bench

Stages:
- all (default): init, sequential latency, then contention.
- contention: only the contention stage, against an already initialised store.

Contention: K agents, each in its own clone, drain K * --per-agent fresh tickets with
claim-next then done, as fast as they can (no work between ops: the worst case).
Prints one JSON report on stdout; progress goes to stderr.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, ClassVar, ParamSpec, TypeVar

from tkt_store.application.service import TicketStore
from tkt_store.application.transaction import Committed, Refused
from tkt_store.domain.outcomes import RefusalCode
from tkt_store.domain.ticket import AgentId, TicketId
from tkt_store.infrastructure.backoff import JitteredBackoff
from tkt_store.infrastructure.clock import SystemClock, monotonic, sleep
from tkt_store.infrastructure.git.repo import GitStore
from tkt_store.infrastructure.git.runner import GitError, git_runner
from tkt_store.infrastructure.ids import RandomIds, jitter

TTL = 1800
T = TypeVar("T")
P = ParamSpec("P")


def log(*parts: object) -> None:
    print(*parts, file=sys.stderr, flush=True)


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=check
    )


class CountingRunner:
    """A real runner that counts git calls and pushes, and tallies every rejected push's
    porcelain status (shared across agents)."""

    lock: ClassVar[threading.Lock] = threading.Lock()
    rejections: ClassVar[Counter[str]] = Counter()

    def __init__(self, repo: Path) -> None:
        self._run = git_runner(repo)
        self.calls = 0
        self.pushes = 0

    def __call__(self, *args: str, stdin: bytes | None = None) -> bytes:
        self.calls += 1
        self.pushes += args[0] == "push"
        try:
            return self._run(*args, stdin=stdin)
        except GitError as error:
            if args[0] == "push":
                for line in error.stdout.decode().splitlines():
                    if line.startswith("!"):
                        with CountingRunner.lock:
                            CountingRunner.rejections[line.split("\t")[-1]] += 1
            raise


def clone(url: str, workdir: Path, name: str) -> Path:
    path = workdir / name
    if not path.exists():
        subprocess.run(["git", "clone", "-q", url, str(path)], check=True, capture_output=True)
    return path


def service(repo: Path) -> tuple[TicketStore, CountingRunner]:
    """The production wiring of open_store, with a counting runner."""
    runner = CountingRunner(repo)
    backoff = JitteredBackoff(sleep=sleep, jitter=jitter, monotonic=monotonic)
    store = GitStore(runner, remote="origin")
    return TicketStore(store, SystemClock(), RandomIds(), backoff=backoff), runner


def summary(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    if not ordered:
        return {"n": 0}
    return {
        "n": len(ordered),
        "median_s": round(statistics.median(ordered), 3),
        "p90_s": round(ordered[int(0.9 * (len(ordered) - 1))], 3),
        "max_s": round(ordered[-1], 3),
    }


def timed(fn: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> tuple[T, float]:
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    return result, time.perf_counter() - start


BENCH_TITLES = ("latency ", "contention ")
"""Every ticket this benchmark creates has a title starting with one of these."""


def refuse_real_stores(repo: Path) -> None:
    """Exit unless every ticket in the store was created by this benchmark."""
    tickets, _ = service(repo)
    foreign = [v.ticket.id for v in tickets.list() if not v.ticket.title.startswith(BENCH_TITLES)]
    if foreign:
        sys.exit(
            f"refusing to run: the store holds {len(foreign)} ticket(s) this benchmark did not "
            f"create (e.g. {foreign[0]}); point --url at a dedicated test repository"
        )


def latency(repo: Path, rounds: int) -> dict[str, Any]:
    """One clone, no contention: add, claim, renew, done and show, `rounds` times."""
    tickets, runner = service(repo)
    agent = AgentId("bench-seq")
    samples: dict[str, list[float]] = {k: [] for k in ("add", "claim", "renew", "done", "show")}
    for i in range(rounds):
        added, t = timed(tickets.add, f"latency {i}")
        assert isinstance(added, Committed), added
        samples["add"].append(t)
        ticket_id = added.tickets[0].id
        claim_id = RandomIds().claim_id()
        claimed, t = timed(tickets.claim, ticket_id, agent, TTL, claim_id=claim_id)
        assert isinstance(claimed, Committed), claimed
        samples["claim"].append(t)
        samples["renew"].append(timed(tickets.renew, ticket_id, claim_id, TTL)[1])
        done, t = timed(tickets.done, ticket_id, claim_id)
        assert isinstance(done, Committed), done
        samples["done"].append(t)
        samples["show"].append(timed(tickets.view, ticket_id)[1])
        log(f"  latency round {i + 1}/{rounds}")
    calls_per_op = runner.calls / (rounds * len(samples))
    return {op: summary(s) for op, s in samples.items()} | {
        "git_calls_per_op": round(calls_per_op, 1)
    }


def contention(clones: list[Path], per_agent: int) -> dict[str, Any]:
    k = len(clones)
    seeder, _ = service(clones[0])
    for i in range(k * per_agent):
        assert isinstance(seeder.add(f"contention k={k} #{i}"), Committed)
    log(f"  seeded {k * per_agent} tickets for k={k}")
    barrier = threading.Barrier(k)

    def agent(n: int) -> dict[str, Any]:
        tickets, runner = service(clones[n])
        name = AgentId(f"bench-{k}-{n}")
        ops: Counter[str] = Counter()
        errors: Counter[str] = Counter()
        durations: list[float] = []
        barrier.wait()
        while True:
            claim_id = RandomIds().claim_id()
            try:
                claimed, t = timed(tickets.claim_next, name, TTL, claim_id=claim_id)
            except Exception as error:  # record and keep draining
                errors[f"claim-next {type(error).__name__}: {str(error)[:160]}"] += 1
                continue
            if isinstance(claimed, Refused):
                if claimed.refusal.code is RefusalCode.NOTHING_CLAIMABLE:
                    break
                ops[f"claim-next refused {claimed.refusal.code.value}"] += 1
                continue
            durations.append(t)
            ops["claim-next"] += 1
            ticket_id: TicketId = claimed.tickets[0].id
            try:
                done, t = timed(tickets.done, ticket_id, claim_id)
            except Exception as error:
                errors[f"done {type(error).__name__}: {str(error)[:160]}"] += 1
                continue
            durations.append(t)
            ops["done" if isinstance(done, Committed) else f"done {type(done).__name__}"] += 1
        return {"ops": ops, "errors": errors, "durations": durations, "pushes": runner.pushes}

    start = time.perf_counter()
    with ThreadPoolExecutor(k) as pool:
        results = list(pool.map(agent, range(k)))
    wall = time.perf_counter() - start
    ops: Counter[str] = sum((r["ops"] for r in results), Counter())
    committed = ops["claim-next"] + ops["done"]
    pushes = sum(r["pushes"] for r in results)
    return {
        "agents": k,
        "tickets": k * per_agent,
        "wall_s": round(wall, 1),
        "committed_ops": committed,
        "ops_per_s": round(committed / wall, 2),
        "pushes": pushes,
        "lost_pushes": pushes - committed,
        "op_latency": summary([d for r in results for d in r["durations"]]),
        "ops": dict(ops),
        "errors": dict(sum((r["errors"] for r in results), Counter())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", required=True, help="a dedicated test repository")
    parser.add_argument("--workdir", required=True, type=Path, help="where the clones go")
    parser.add_argument("--stage", choices=["all", "contention"], default="all")
    parser.add_argument("--agents", type=int, nargs="+", default=[2, 5, 10])
    parser.add_argument("--per-agent", type=int, default=4, help="tickets per agent")
    parser.add_argument("--rounds", type=int, default=10, help="latency rounds")
    args = parser.parse_args()
    args.workdir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"git": git(args.workdir, "--version").stdout.strip()}
    first = clone(args.url, args.workdir, "clone-0")
    refuse_real_stores(first)
    if args.stage == "all":
        tickets, _ = service(first)
        outcome, t = timed(tickets.init)
        report["init"] = {"outcome": type(outcome).__name__, "s": round(t, 3)}
        report["latency"] = latency(first, args.rounds)
    clones = [clone(args.url, args.workdir, f"clone-{n}") for n in range(max(args.agents))]
    report["contention"] = []
    for k in args.agents:
        log(f"contention k={k}")
        report["contention"].append(contention(clones[:k], args.per_agent))
    report["rejections"] = dict(CountingRunner.rejections)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
