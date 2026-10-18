"""The contract every store keeps (state-store README, *Interface* and *Guarantees*), run against
`MemoryStateStore` and `GitStateStore` alike, so they never drift apart."""

from __future__ import annotations

import pytest

from state_store import (
    MAX_VALUE_SIZE,
    CompareAndSwapFailed,
    KeyCollision,
    StateSnapshot,
    StateStore,
)
from state_store_testkit import Writers

pytestmark = pytest.mark.xfail(raises=NotImplementedError, strict=True, reason="skeleton")


def seeded(writers: Writers, values: dict[str, bytes]) -> tuple[StateStore, StateSnapshot]:
    """A writer, and the store's state after one commit of `values`."""
    store = writers.new()
    snap = store.snapshot()
    for key, value in values.items():
        snap = snap.with_value(key, value)
    return store, store.commit(snap, "seed")


# --- A new store ----------------------------------------------------------------------


def test_a_new_store_is_empty_at_a_first_revision(writers: Writers) -> None:
    snap = writers.new().snapshot()
    assert isinstance(snap.revision, str)
    assert snap.changes == {}
    assert snap.get("a") is None
    assert snap.keys() == []
    assert snap.keys("inbox") == []


def test_the_first_commit_makes_a_new_revision(writers: Writers) -> None:
    store = writers.new()
    first = store.snapshot()
    committed = store.commit(first.with_value("a", b"1"), "first")
    assert committed.revision != first.revision
    assert committed.changes == {}
    assert committed.get("a") == b"1"


# --- Reading and deriving -------------------------------------------------------------


def test_a_derived_snapshot_reads_its_own_changes(writers: Writers) -> None:
    snap = writers.new().snapshot()
    derived = snap.with_value("inbox/i1", b"x")
    assert derived.get("inbox/i1") == b"x"
    assert derived.keys("inbox") == ["inbox/i1"]
    assert derived.changes == {"inbox/i1": b"x"}


def test_deriving_leaves_the_original_unchanged(writers: Writers) -> None:
    _, snap = seeded(writers, {"a": b"1"})
    derived = snap.with_value("a", b"2").without("a").with_value("b", b"3")
    assert snap.get("a") == b"1"
    assert snap.get("b") is None
    assert snap.changes == {}
    assert derived.get("a") is None
    assert derived.get("b") == b"3"


def test_derived_snapshots_keep_the_revision_they_come_from(writers: Writers) -> None:
    _, snap = seeded(writers, {"a": b"1"})
    assert snap.with_value("b", b"2").without("a").revision == snap.revision


def test_the_last_change_to_a_key_wins(writers: Writers) -> None:
    snap = writers.new().snapshot()
    derived = snap.with_value("a", b"1").with_value("a", b"2")
    assert derived.get("a") == b"2"
    assert derived.changes == {"a": b"2"}
    assert derived.without("a").changes == {"a": None}


def test_a_snapshot_is_immutable(writers: Writers) -> None:
    snap = writers.new().snapshot().with_value("a", b"1")
    with pytest.raises(AttributeError):
        snap.revision = "x"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        del snap._overlay
    with pytest.raises(TypeError):
        snap.changes["a"] = b"2"  # type: ignore[index]
    assert snap.get("a") == b"1"


def test_changes_are_as_given_even_when_they_change_nothing(writers: Writers) -> None:
    _, snap = seeded(writers, {"a": b"1"})
    assert snap.with_value("a", b"1").changes == {"a": b"1"}
    assert snap.without("missing").changes == {"missing": None}


def test_the_repr_shows_no_keys_or_values(writers: Writers) -> None:
    _, snap = seeded(writers, {"secret-key": b"secret-value"})
    shown = repr(snap.with_value("other-secret", b"other-value"))
    for hidden in ("secret-key", "secret-value", "other-secret", "other-value"):
        assert hidden not in shown


def test_keys_lists_full_keys_of_direct_values_sorted(writers: Writers) -> None:
    _, snap = seeded(
        writers,
        {"t/b": b"", "t/a": b"", "t/old/c": b"", "top": b"", "u/d": b""},
    )
    assert snap.keys("t") == ["t/a", "t/b"]
    assert snap.keys() == ["top"]
    assert snap.keys("t/old") == ["t/old/c"]


def test_keys_merges_the_changes(writers: Writers) -> None:
    _, snap = seeded(writers, {"t/a": b"", "t/b": b""})
    derived = snap.without("t/a").with_value("t/c", b"").with_value("t/sub/d", b"")
    assert derived.keys("t") == ["t/b", "t/c"]


def test_keys_of_a_missing_namespace_or_a_value_is_empty(writers: Writers) -> None:
    _, snap = seeded(writers, {"t/a": b""})
    assert snap.keys("nothing") == []
    assert snap.keys("t/a") == []
    assert snap.keys("t/a/below") == []


def test_get_of_a_namespace_or_through_a_value_is_none(writers: Writers) -> None:
    _, snap = seeded(writers, {"t/a": b"1"})
    assert snap.get("t") is None
    assert snap.get("t/a/below") is None


def test_values_are_bytes_as_given(writers: Writers) -> None:
    value = bytes(range(256)) * 4 + b"\x00\r\n"
    _, snap = seeded(writers, {"a": value, "empty": b""})
    assert snap.get("a") == value
    assert snap.get("empty") == b""


# --- Collisions -----------------------------------------------------------------------


def test_a_value_cannot_become_a_namespace(writers: Writers) -> None:
    _, snap = seeded(writers, {"t/a": b""})
    with pytest.raises(KeyCollision):
        snap.with_value("t/a/below", b"")


def test_a_namespace_cannot_become_a_value(writers: Writers) -> None:
    _, snap = seeded(writers, {"t/a": b""})
    with pytest.raises(KeyCollision):
        snap.with_value("t", b"")


def test_collisions_are_checked_against_the_changes_too(writers: Writers) -> None:
    snap = writers.new().snapshot().with_value("t/a", b"")
    with pytest.raises(KeyCollision):
        snap.with_value("t", b"")


def test_a_namespace_cannot_be_written_under_a_value_just_written(writers: Writers) -> None:
    snap = writers.new().snapshot().with_value("t", b"")
    with pytest.raises(KeyCollision):
        snap.with_value("t/a", b"")


def test_removing_the_last_value_frees_the_namespace(writers: Writers) -> None:
    _, snap = seeded(writers, {"t/a": b""})
    derived = snap.without("t/a").with_value("t", b"now a value")
    assert derived.get("t") == b"now a value"


def test_removing_the_last_nested_value_frees_every_enclosing_namespace(
    writers: Writers,
) -> None:
    _, snap = seeded(writers, {"t/x/y": b""})
    assert snap.without("t/x/y").with_value("t", b"now a value").get("t") == b"now a value"


def test_a_namespace_with_a_value_left_in_a_nested_namespace_is_not_free(
    writers: Writers,
) -> None:
    _, snap = seeded(writers, {"t/a": b"", "t/s/b": b""})
    with pytest.raises(KeyCollision):
        snap.without("t/a").with_value("t", b"")


def test_without_a_namespace_changes_nothing(writers: Writers) -> None:
    store, snap = seeded(writers, {"t/a": b"1"})
    derived = snap.without("t")
    assert derived.get("t/a") == b"1"
    assert store.commit(derived, "nothing").revision == snap.revision


# --- Committing -----------------------------------------------------------------------


def test_a_commit_is_seen_by_every_writer(writers: Writers) -> None:
    seeded(writers, {"t/a": b"1", "t/b": b"2"})
    snap = writers.new().snapshot()
    assert snap.get("t/a") == b"1"
    assert snap.keys("t") == ["t/a", "t/b"]


def test_a_commit_lands_all_its_changes_together(writers: Writers) -> None:
    store, snap = seeded(writers, {"open/x": b"x", "closed": b""})
    committed = store.commit(
        snap.without("open/x").with_value("archive/x", b"x").with_value("closed", b"c"),
        "move x",
    )
    for seen in (committed, writers.new().snapshot()):
        assert seen.get("open/x") is None
        assert seen.get("archive/x") == b"x"
        assert seen.get("closed") == b"c"


def test_commits_chain(writers: Writers) -> None:
    store, first = seeded(writers, {"a": b"1"})
    second = store.commit(first.with_value("a", b"2"), "second")
    third = store.commit(second.with_value("a", b"3"), "third")
    assert len({first.revision, second.revision, third.revision}) == 3
    assert writers.new().snapshot().get("a") == b"3"


def test_a_snapshot_that_changes_nothing_commits_nothing(writers: Writers) -> None:
    store, snap = seeded(writers, {"a": b"1"})
    for unchanged in (snap, snap.with_value("a", b"1"), snap.without("missing")):
        result = store.commit(unchanged, "nothing")
        assert result.revision == snap.revision
        assert result.changes == {}
    assert writers.new().snapshot().revision == snap.revision


def test_committing_nothing_is_not_a_freshness_check(writers: Writers) -> None:
    store, stale = seeded(writers, {"a": b"1"})
    other = writers.new()
    other.commit(other.snapshot().with_value("a", b"2"), "move on")
    assert store.commit(stale.with_value("a", b"1"), "nothing").revision == stale.revision


def test_a_new_store_with_nothing_to_commit_stays_new(writers: Writers) -> None:
    store = writers.new()
    first = store.snapshot()
    assert store.commit(first.without("a"), "nothing").revision == first.revision
    assert writers.new().snapshot().revision == first.revision


def test_emptying_the_store_is_a_commit(writers: Writers) -> None:
    store, snap = seeded(writers, {"a": b"1"})
    emptied = store.commit(snap.without("a"), "empty")
    assert emptied.revision != snap.revision
    assert emptied.keys() == []
    assert writers.new().snapshot().revision == emptied.revision


# --- Concurrency (guarantee 3) --------------------------------------------------------


def test_a_commit_on_a_stale_snapshot_is_refused(writers: Writers) -> None:
    seeded(writers, {"a": b"0"})
    first, second = writers.new(), writers.new()
    mine, theirs = first.snapshot(), second.snapshot()
    second.commit(theirs.with_value("a", b"theirs"), "theirs")
    with pytest.raises(CompareAndSwapFailed):
        first.commit(mine.with_value("a", b"mine"), "mine")
    assert writers.new().snapshot().get("a") == b"theirs"


def test_writes_to_different_keys_still_conflict(writers: Writers) -> None:
    seeded(writers, {"a": b"0", "b": b"0"})
    first, second = writers.new(), writers.new()
    mine, theirs = first.snapshot(), second.snapshot()
    second.commit(theirs.with_value("b", b"1"), "b")
    with pytest.raises(CompareAndSwapFailed):
        first.commit(mine.with_value("a", b"1"), "a")


def test_two_first_commits_conflict(writers: Writers) -> None:
    first, second = writers.new(), writers.new()
    mine, theirs = first.snapshot(), second.snapshot()
    second.commit(theirs.with_value("a", b"theirs"), "theirs")
    with pytest.raises(CompareAndSwapFailed):
        first.commit(mine.with_value("a", b"mine"), "mine")


def test_a_snapshot_whose_store_moved_on_is_stale_even_after_its_own_commit(
    writers: Writers,
) -> None:
    store, snap = seeded(writers, {"a": b"0"})
    store.commit(snap.with_value("a", b"1"), "first use")
    with pytest.raises(CompareAndSwapFailed):
        store.commit(snap.with_value("a", b"2"), "second use of the same snapshot")


def test_starting_again_from_a_new_snapshot_succeeds(writers: Writers) -> None:
    seeded(writers, {"a": b"0"})
    first, second = writers.new(), writers.new()
    mine = first.snapshot()
    second.commit(second.snapshot().with_value("a", b"theirs"), "theirs")
    with pytest.raises(CompareAndSwapFailed):
        first.commit(mine.with_value("b", b"mine"), "mine")
    again = first.snapshot()
    assert again.get("a") == b"theirs"
    committed = first.commit(again.with_value("b", b"mine"), "mine")
    assert committed.get("a") == b"theirs"
    assert committed.get("b") == b"mine"


def test_an_old_snapshot_keeps_reading_its_own_moment(writers: Writers) -> None:
    store, old = seeded(writers, {"t/a": b"old"})
    store.commit(store.snapshot().with_value("t/a", b"new").with_value("t/b", b""), "new")
    assert old.get("t/a") == b"old"
    assert old.keys("t") == ["t/a"]


# --- Caller bugs ------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["", "/a", "a/", ".git", "a/../b", "-a", "a b"])
def test_invalid_keys_are_refused_everywhere(writers: Writers, key: str) -> None:
    snap = writers.new().snapshot()
    with pytest.raises(ValueError):
        snap.get(key)
    with pytest.raises(ValueError):
        snap.with_value(key, b"")
    with pytest.raises(ValueError):
        snap.without(key)


@pytest.mark.parametrize("namespace", ["/", "t/", ".git"])
def test_invalid_namespaces_are_refused(writers: Writers, namespace: str) -> None:
    with pytest.raises(ValueError):
        writers.new().snapshot().keys(namespace)


def test_values_must_be_bytes(writers: Writers) -> None:
    snap = writers.new().snapshot()
    with pytest.raises(ValueError):
        snap.with_value("a", "text")  # type: ignore[arg-type]


def test_values_over_the_limit_are_refused(writers: Writers) -> None:
    snap = writers.new().snapshot()
    with pytest.raises(ValueError):
        snap.with_value("a", b"x" * (MAX_VALUE_SIZE + 1))


def test_a_value_of_exactly_the_limit_round_trips(writers: Writers) -> None:
    store = writers.new()
    big = b"x" * MAX_VALUE_SIZE
    store.commit(store.snapshot().with_value("big", big), "big")
    assert writers.new().snapshot().get("big") == big


def test_a_message_with_nul_is_refused(writers: Writers) -> None:
    store = writers.new()
    with pytest.raises(ValueError):
        store.commit(store.snapshot().with_value("a", b""), "a\x00b")


def test_a_message_with_nul_is_refused_even_when_nothing_changes(writers: Writers) -> None:
    store = writers.new()
    with pytest.raises(ValueError):
        store.commit(store.snapshot(), "a\x00b")


@pytest.mark.parametrize("message", ["", "one line", "subject\n\nbody\n", "ünïcödé ✓"])
def test_any_message_without_nul_is_accepted(writers: Writers, message: str) -> None:
    store = writers.new()
    assert store.commit(store.snapshot().with_value("a", b""), message).get("a") == b""


def test_a_snapshot_from_another_store_object_is_refused(writers: Writers) -> None:
    snap = writers.new().snapshot().with_value("a", b"")
    with pytest.raises(ValueError):
        writers.other_store().commit(snap, "wrong store")
