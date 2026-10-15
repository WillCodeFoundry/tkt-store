"""Jittered exponential backoff (infrastructure/backoff.py), with injected fakes."""

from __future__ import annotations

import pytest

from tkt_store.infrastructure.backoff import BACKOFF_CAP, JitteredBackoff
from tkt_store.infrastructure.ids import jitter


def backoff(fraction: float) -> tuple[JitteredBackoff, list[float]]:
    slept: list[float] = []
    return JitteredBackoff(sleep=slept.append, jitter=lambda: fraction, base=1.0, cap=8.0), slept


def test_window_doubles_from_base_up_to_cap() -> None:
    policy, _ = backoff(0.5)
    assert [policy.window(n) for n in range(1, 7)] == [1.0, 2.0, 4.0, 8.0, 8.0, 8.0]


@pytest.mark.parametrize(("fraction", "expected"), [(0.0, 0.0), (0.5, 2.0), (0.999, 3.996)])
def test_wait_sleeps_a_jittered_fraction_of_the_window(fraction: float, expected: float) -> None:
    policy, slept = backoff(fraction)
    policy.wait(3)
    assert slept == [pytest.approx(expected)]


def test_production_jitter_is_a_fraction_in_the_unit_interval() -> None:
    samples = [jitter() for _ in range(1000)]
    assert all(0.0 <= s < 1.0 for s in samples) and len(set(samples)) > 990


def test_default_cap_bounds_every_wait() -> None:
    slept: list[float] = []
    policy = JitteredBackoff(sleep=slept.append, jitter=lambda: 0.999999)
    for attempt in range(1, 20):
        policy.wait(attempt)
    assert max(slept) < BACKOFF_CAP
