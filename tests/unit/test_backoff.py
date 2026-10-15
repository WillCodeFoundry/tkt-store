"""Jittered exponential backoff in slots (infrastructure/backoff.py), with injected
fakes: a fake monotonic clock, a fixed jitter and a recording sleep."""

from __future__ import annotations

import pytest

from tkt_store.infrastructure.backoff import BACKOFF_CAP, MIN_SLOT, JitteredBackoff
from tkt_store.infrastructure.ids import jitter


class Timeline:
    """A fake monotonic clock that sleeping advances."""

    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def backoff(fraction: float = 0.5, cap: float = 60.0) -> tuple[JitteredBackoff, Timeline]:
    time = Timeline()
    policy = JitteredBackoff(
        sleep=time.sleep, jitter=lambda: fraction, monotonic=time.monotonic, cap=cap
    )
    return policy, time


def lose(policy: JitteredBackoff, time: Timeline, attempt: int, took: float) -> None:
    """One attempt that took `took` seconds and lost the race."""
    wait_after_loss = policy.begin()
    time.now += took
    wait_after_loss(attempt)


def test_window_doubles_in_slots_up_to_the_cap() -> None:
    policy, _ = backoff(cap=30.0)
    assert [policy.window(n, slot=4.0) for n in range(1, 6)] == [4.0, 8.0, 16.0, 30.0, 30.0]


def test_the_slot_is_how_long_the_losing_attempt_took() -> None:
    policy, time = backoff(fraction=0.5)
    lose(policy, time, attempt=1, took=3.5)  # a GitHub-like attempt
    lose(policy, time, attempt=2, took=3.5)
    assert time.slept == [pytest.approx(1.75), pytest.approx(3.5)]


def test_fast_attempts_use_the_minimum_slot() -> None:
    policy, time = backoff(fraction=1.0)
    lose(policy, time, attempt=1, took=0.001)  # a local ref
    assert time.slept == [pytest.approx(MIN_SLOT)]


def test_concurrent_attempts_each_get_their_own_slot() -> None:
    """No state is shared between begin() calls: interleaved attempts (two threads on
    one instance) are each timed from their own start."""
    policy, time = backoff(fraction=1.0)
    first = policy.begin()
    time.now += 1.0
    second = policy.begin()
    time.now += 3.0
    second(1)  # its attempt took 3.0
    first(1)  # its attempt took 4.0 + the 3.0 slept since: 7.0
    assert time.slept == [pytest.approx(3.0), pytest.approx(7.0)]


def test_time_spent_sleeping_is_not_counted_as_attempt_time() -> None:
    """begin() at each attempt resets the slot: a long previous wait does not inflate it."""
    policy, time = backoff(fraction=1.0)
    lose(policy, time, attempt=1, took=2.0)  # sleeps 2.0
    lose(policy, time, attempt=2, took=2.0)  # slot is 2.0 again, not 4.0
    assert time.slept == [pytest.approx(2.0), pytest.approx(4.0)]


def test_default_cap_bounds_every_wait_and_is_reached() -> None:
    policy, time = backoff(fraction=0.999999, cap=BACKOFF_CAP)
    for attempt in range(1, 20):
        lose(policy, time, attempt, took=10.0)
    assert max(time.slept) < BACKOFF_CAP
    assert time.slept[-1] == pytest.approx(0.999999 * BACKOFF_CAP)


def test_production_jitter_is_a_fraction_in_the_unit_interval() -> None:
    samples = [jitter() for _ in range(1000)]
    assert all(0.0 <= s < 1.0 for s in samples) and len(set(samples)) > 990
