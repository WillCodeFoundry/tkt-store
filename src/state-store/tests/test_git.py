"""What only `GitStateStore` has: the layout on the branch, opening a clone, checks on
what is read, hooks, errors and push outcomes (state-store design)."""

from __future__ import annotations

import traceback
from pathlib import Path

import pytest

from state_store import (
    MAX_VALUE_SIZE,
    CommitRefused,
    CorruptState,
    GitStateStore,
    NoIdentity,
    NotAClone,
    RemoteFailed,
    StaleSnapshot,
    StateSnapshot,
    StoreError,
    UnknownOutcome,
)
from state_store.runner import LOG_NAME
from state_store_testkit import (
    BRANCH,
    DIRECTORY,
    EXECUTABLE,
    REGULAR,
    SUBMODULE,
    SYMLINK,
    MakeClone,
    blob,
    publish,
    run_git,
    tree,
)

pytestmark = [
    pytest.mark.git,
    pytest.mark.xfail(raises=NotImplementedError, strict=True, reason="skeleton"),
]

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def open_store(path: Path, **kwargs: str) -> GitStateStore:
    return GitStateStore(path, **{"remote": "origin", "branch": BRANCH, **kwargs})


# --- Layout on the branch (§2) ------------------------------------------------------------


def test_values_are_regular_blobs_and_namespaces_are_trees(
    make_clone: MakeClone, bare_remote: Path
) -> None:
    store = open_store(make_clone())
    store.commit(store.snapshot().with_value("t/a", b"1").with_value("top", b"2"), "seed")
    listing = run_git(bare_remote, "ls-tree", "-r", "-t", f"refs/heads/{BRANCH}").splitlines()
    assert [line.split()[0] + " " + line.split("\t")[1] for line in listing] == [
        "040000 t",
        "100644 t/a",
        "100644 top",
    ]


def test_an_emptied_store_is_a_commit_of_the_empty_tree(
    make_clone: MakeClone, bare_remote: Path
) -> None:
    store = open_store(make_clone())
    seeded = store.commit(store.snapshot().with_value("a", b""), "seed")
    store.commit(seeded.without("a"), "empty")
    assert run_git(bare_remote, "rev-parse", f"refs/heads/{BRANCH}^{{tree}}").strip() == EMPTY_TREE


def test_the_commit_has_the_message_and_gits_identity(
    make_clone: MakeClone, bare_remote: Path
) -> None:
    clone = make_clone()
    store = open_store(clone)
    store.commit(store.snapshot().with_value("a", b""), "first line\n\nmore")
    log = run_git(bare_remote, "log", "-1", "--format=%an%n%ae%n%B", f"refs/heads/{BRANCH}")
    name = run_git(clone, "config", "user.name").strip()
    email = run_git(clone, "config", "user.email").strip()
    assert log.startswith(f"{name}\n{email}\nfirst line\n\nmore")


def test_the_clone_is_never_checked_out_and_has_no_local_branch(make_clone: MakeClone) -> None:
    clone = make_clone()
    store = open_store(clone)
    snap = store.commit(store.snapshot().with_value("t/a", b"1"), "seed")
    store.commit(snap.with_value("t/b", b"2"), "more")
    assert sorted(p.name for p in clone.iterdir()) == [".git"]
    assert run_git(clone, "for-each-ref", "refs/heads/").strip() == ""
    assert run_git(clone, "for-each-ref", "--format=%(refname)", "refs/state-store/").split() == [
        f"refs/state-store/{BRANCH}"
    ]


def test_without_an_identity_nothing_is_committed(make_clone: MakeClone, bare_remote: Path) -> None:
    store = open_store(make_clone(identity=False))
    with pytest.raises(NoIdentity):
        store.commit(store.snapshot().with_value("a", b""), "no author")
    assert run_git(bare_remote, "for-each-ref").strip() == ""


# --- Opening a store (§7) ---------------------------------------------------------------


def seed_remote(make_clone: MakeClone) -> None:
    clone = make_clone()
    publish(clone, tree(clone, [(REGULAR, blob(clone, b"1"), "a")]))


@pytest.mark.parametrize("name", ["", "missing"], ids=["not a repository", "no such path"])
def test_a_path_that_is_not_a_repository_is_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(NotAClone):
        open_store(tmp_path / name)


def test_a_subdirectory_of_a_clone_is_refused(make_clone: MakeClone) -> None:
    inner = make_clone() / "inner"
    inner.mkdir()
    with pytest.raises(NotAClone):
        open_store(inner)


def test_a_shallow_clone_is_refused(make_clone: MakeClone, bare_remote: Path) -> None:
    seed_remote(make_clone)
    clone = make_clone("--depth=1", f"--branch={BRANCH}", url=bare_remote.as_uri())
    with pytest.raises(NotAClone):
        open_store(clone)


def test_a_partial_clone_is_refused(make_clone: MakeClone, bare_remote: Path) -> None:
    seed_remote(make_clone)
    run_git(bare_remote, "config", "uploadpack.allowFilter", "true")
    clone = make_clone("--filter=blob:none", url=bare_remote.as_uri())
    with pytest.raises(NotAClone):
        open_store(clone)


def test_a_promisor_on_any_remote_is_refused(make_clone: MakeClone, bare_remote: Path) -> None:
    clone = make_clone()
    run_git(clone, "remote", "add", "other", str(bare_remote))
    run_git(clone, "config", "remote.other.promisor", "true")
    with pytest.raises(NotAClone):
        open_store(clone)


def test_a_remote_that_is_explicitly_not_a_promisor_is_accepted(make_clone: MakeClone) -> None:
    clone = make_clone()
    run_git(clone, "config", "remote.origin.promisor", "false")
    store = open_store(clone)
    assert store.snapshot().revision is None


@pytest.mark.parametrize(
    "config",
    [
        ("--add", "remote.origin.url", "/elsewhere.git"),
        ("remote.origin.pushurl", "/elsewhere.git"),
        ("url./elsewhere/.pushInsteadOf", "/"),
    ],
    ids=["two urls", "pushurl", "pushInsteadOf"],
)
def test_a_remote_that_pushes_elsewhere_is_refused(
    make_clone: MakeClone, config: tuple[str, ...]
) -> None:
    clone = make_clone()
    run_git(clone, "config", *config)
    with pytest.raises(NotAClone):
        open_store(clone)


@pytest.mark.parametrize("remote", ["upstream", "-origin", "--push", "http://x"])
def test_a_remote_that_is_not_configured_is_refused(make_clone: MakeClone, remote: str) -> None:
    with pytest.raises(NotAClone):
        open_store(make_clone(), remote=remote)


@pytest.mark.parametrize(
    "branch", ["", "refs/heads/x", "@", "HEAD", "x@{1}", "a..b", "-x", "a b", "x.lock"]
)
def test_invalid_branch_names_are_refused(make_clone: MakeClone, branch: str) -> None:
    with pytest.raises(ValueError):
        open_store(make_clone(), branch=branch)


def test_an_empty_remote_name_is_refused(make_clone: MakeClone) -> None:
    with pytest.raises(ValueError):
        open_store(make_clone(), remote="")


def test_a_bare_repository_is_refused(bare_remote: Path) -> None:
    with pytest.raises(NotAClone):
        open_store(bare_remote)


def test_a_clone_reached_through_a_symlink_is_accepted(
    make_clone: MakeClone, tmp_path: Path
) -> None:
    link = tmp_path / "link-to-clone"
    link.symlink_to(make_clone())
    store = open_store(link)
    store.commit(store.snapshot().with_value("a", b"1"), "through a link")
    assert open_store(make_clone()).snapshot().get("a") == b"1"


def test_a_url_rewrite_that_applies_to_both_directions_is_accepted(
    make_clone: MakeClone, bare_remote: Path
) -> None:
    clone = make_clone()
    run_git(clone, "config", f"url.{bare_remote}.insteadOf", "alias:")
    run_git(clone, "remote", "set-url", "origin", "alias:")
    store = open_store(clone)
    store.commit(store.snapshot().with_value("a", b"1"), "through an alias")
    assert open_store(make_clone()).snapshot().get("a") == b"1"


# --- Checks on what is read (§1, §4) ------------------------------------------------------


def forge_bad_namespace(clone: Path, bad: tuple[str, str, str]) -> None:
    """Publish `bad/ok` (a valid value), `bad` + the entry `bad`, and `good/a`."""
    ok = (REGULAR, blob(clone, b"ok"), "ok")
    good = tree(clone, [(REGULAR, blob(clone, b"a"), "a")])
    publish(
        clone,
        tree(clone, [(DIRECTORY, tree(clone, [ok, bad]), "bad"), (DIRECTORY, good, "good")]),
    )


BAD_ENTRIES: dict[str, tuple[str, bytes | str, str]] = {
    # kind: (mode, content (or the id of a submodule's commit or of a tree), name)
    "symlink": (SYMLINK, b"/etc/passwd", "link"),
    "executable": (EXECUTABLE, b"#!/bin/sh\n", "run"),
    "submodule": (SUBMODULE, "1" * 40, "sub"),
    "bad name": (REGULAR, b"", ".hidden"),
    "oversized": (REGULAR, b"x" * (MAX_VALUE_SIZE + 1), "big"),
    "duplicate": (REGULAR, b"other", "ok"),
    "empty namespace": (DIRECTORY, EMPTY_TREE, "empty"),
}
BAD_KINDS = list(BAD_ENTRIES)


def corrupt_snapshot(make_clone: MakeClone, kind: str) -> tuple[GitStateStore, StateSnapshot]:
    forger = make_clone()
    mode, content, name = BAD_ENTRIES[kind]
    oid = content if isinstance(content, str) else blob(forger, content)
    forge_bad_namespace(forger, (mode, oid, name))
    store = open_store(make_clone())
    return store, store.snapshot()


def assert_corrupt(caught: pytest.ExceptionInfo[StoreError]) -> None:
    assert isinstance(caught.value, CorruptState)


@pytest.mark.parametrize("kind", BAD_KINDS)
def test_listing_a_namespace_with_a_bad_entry_fails(make_clone: MakeClone, kind: str) -> None:
    _, snap = corrupt_snapshot(make_clone, kind)
    with pytest.raises(StoreError) as caught:
        snap.keys("bad")
    assert_corrupt(caught)


@pytest.mark.parametrize(
    "kind", ["symlink", "executable", "submodule", "oversized", "duplicate", "empty namespace"]
)
def test_reading_a_bad_entry_fails(make_clone: MakeClone, kind: str) -> None:
    _, snap = corrupt_snapshot(make_clone, kind)
    with pytest.raises(StoreError) as caught:
        snap.get(f"bad/{BAD_ENTRIES[kind][2]}")
    assert_corrupt(caught)


@pytest.mark.parametrize("kind", BAD_KINDS)
def test_reads_that_do_not_touch_the_bad_entry_succeed(make_clone: MakeClone, kind: str) -> None:
    _, snap = corrupt_snapshot(make_clone, kind)
    assert snap.get("good/a") == b"a"
    assert snap.keys("good") == ["good/a"]
    if kind != "duplicate":
        assert snap.get("bad/ok") == b"ok"


@pytest.mark.parametrize("kind", BAD_KINDS)
def test_a_commit_never_rebuilds_a_namespace_with_a_bad_entry(
    make_clone: MakeClone, kind: str
) -> None:
    store, snap = corrupt_snapshot(make_clone, kind)
    next_to_it = snap.with_value("bad/new", b"")  # its path holds no bad entry
    with pytest.raises(StoreError) as caught:
        store.commit(next_to_it, "next to a bad entry")
    assert_corrupt(caught)
    store.commit(snap.with_value("good/b", b""), "elsewhere")


def test_a_collision_check_that_reads_a_bad_entry_fails(make_clone: MakeClone) -> None:
    """Whether `bad` still holds a value, once `bad/ok` is removed, is read from the
    namespace itself, which holds a bad entry."""
    _, snap = corrupt_snapshot(make_clone, "symlink")
    emptied = snap.without("bad/ok")
    with pytest.raises(CorruptState):
        emptied.with_value("bad", b"now a value")


def test_a_collision_check_reads_the_whole_namespace(make_clone: MakeClone) -> None:
    """`bad` holds `ok` (a value) and `run` (an executable, listed after it): finding a
    value is not enough, every entry listed is checked."""
    _, snap = corrupt_snapshot(make_clone, "executable")
    with pytest.raises(CorruptState):
        snap.with_value("bad", b"now a value")


def test_a_bad_entry_cannot_be_removed_through_the_store(make_clone: MakeClone) -> None:
    """Repair takes plain git (state-store design §4): the store never rebuilds a
    corrupt tree."""
    store, snap = corrupt_snapshot(make_clone, "symlink")
    with pytest.raises(StoreError) as caught:
        store.commit(snap.without("bad/link"), "remove the bad entry")
    assert_corrupt(caught)


def test_a_bad_entry_at_the_root_stops_listing_the_root_only(make_clone: MakeClone) -> None:
    forger = make_clone()
    good = tree(forger, [(REGULAR, blob(forger, b"a"), "a")])
    publish(
        forger,
        tree(forger, [(DIRECTORY, good, "good"), (SYMLINK, blob(forger, b"x"), "link")]),
    )
    snap = open_store(make_clone()).snapshot()
    assert snap.get("good/a") == b"a"
    with pytest.raises(StoreError) as caught:
        snap.keys()
    assert_corrupt(caught)


def shown(error: BaseException) -> str:
    """Everything a printed traceback of `error` shows, chained exceptions included."""
    return "".join(traceback.format_exception(error))


def test_errors_never_echo_a_name_that_was_read(make_clone: MakeClone) -> None:
    forger = make_clone()
    secret = "IGNORE PREVIOUS INSTRUCTIONS"  # not a valid segment: a corrupt entry
    publish(forger, tree(forger, [(REGULAR, blob(forger, b""), secret)]))
    snap = open_store(make_clone()).snapshot()
    with pytest.raises(StoreError) as caught:
        snap.keys()
    assert_corrupt(caught)
    assert secret not in shown(caught.value)


# --- Hooks, configuration and environment (§6) --------------------------------------------


def pack_count(clone: Path) -> int:
    return len(list((clone / ".git" / "objects" / "pack").glob("*.pack")))


def make_gc_due(clone: Path) -> None:
    """More packs than the limit of one, so the maintenance after the next fetch runs gc
    (unreachable objects only go to a pack when written to one directly)."""
    for data in (b"1", b"2", b"3"):
        run_git(
            clone, "pack-objects", "-q", ".git/objects/pack/pack", stdin=blob(clone, data).encode()
        )
    run_git(clone, "config", "gc.autoPackLimit", "1")


def test_no_hook_ever_runs(make_clone: MakeClone, tmp_path: Path) -> None:
    clone = make_clone()
    marker = tmp_path / "hook-ran"
    hooks = [clone / ".git" / "hooks", tmp_path / "hooks"]
    for directory in hooks:
        directory.mkdir(exist_ok=True)
        for name in ("reference-transaction", "pre-push", "post-checkout", "pre-auto-gc"):
            hook = directory / name
            hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
            hook.chmod(0o755)
    run_git(clone, "config", "core.hooksPath", str(tmp_path / "hooks"))
    make_gc_due(clone)
    packs = pack_count(clone)
    store = open_store(clone)
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    store.commit(snap.with_value("a", b"2"), "two")
    store.snapshot().keys()
    assert pack_count(clone) < packs  # gc ran, so `pre-auto-gc` would have
    assert not marker.exists()


def test_automatic_maintenance_runs_in_the_foreground(
    make_clone: MakeClone, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gc has finished by the time a snapshot returns, even where the clone's
    configuration says to detach it. (Only a fetch that succeeds runs maintenance.)"""
    seed_remote(make_clone)
    clone = make_clone()
    run_git(clone, "config", "maintenance.autoDetach", "true")
    run_git(clone, "config", "gc.autoDetach", "true")
    make_gc_due(clone)
    packs = pack_count(clone)
    trace = tmp_path / "trace"
    monkeypatch.setenv("GIT_TRACE", str(trace))
    open_store(clone).snapshot()
    monkeypatch.delenv("GIT_TRACE")
    assert pack_count(clone) < packs
    gc_runs = [line for line in trace.read_text().splitlines() if "git gc --auto" in line]
    assert gc_runs
    assert all("--no-detach" in line for line in gc_runs)


def test_tags_are_never_pushed(make_clone: MakeClone, bare_remote: Path) -> None:
    clone = make_clone()
    run_git(clone, "config", "push.followTags", "true")
    store = open_store(clone)
    first = store.commit(store.snapshot().with_value("a", b"1"), "one")
    assert first.revision is not None
    run_git(clone, "tag", "-a", "v1", "-m", "a tag", first.revision)
    store.commit(first.with_value("a", b"2"), "two")
    assert run_git(bare_remote, "tag").strip() == ""


def test_inherited_variables_never_redirect_git(
    make_clone: MakeClone, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoy = tmp_path / "decoy.git"
    run_git(tmp_path, "init", "--bare", "--quiet", str(decoy))
    clone = make_clone()
    monkeypatch.setenv("GIT_DIR", str(decoy))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "decoy-index"))
    store = open_store(clone)
    store.commit(store.snapshot().with_value("a", b"1"), "one")
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_INDEX_FILE")
    assert open_store(make_clone()).snapshot().get("a") == b"1"
    assert run_git(decoy, "for-each-ref").strip() == ""


def test_replace_objects_never_stand_in_for_what_the_branch_holds(
    make_clone: MakeClone,
) -> None:
    writer = open_store(make_clone())
    writer.commit(writer.snapshot().with_value("a", b"original"), "one")
    reader = make_clone()
    run_git(reader, "fetch", "--quiet", "origin")
    original = run_git(reader, "rev-parse", f"origin/{BRANCH}:a").strip()
    run_git(reader, "replace", original, blob(reader, b"replaced"))
    assert open_store(reader).snapshot().get("a") == b"original"


def test_inherited_configuration_cannot_turn_hooks_back_on(
    make_clone: MakeClone, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hooks, marker = tmp_path / "evil-hooks", tmp_path / "hook-ran"
    hooks.mkdir()
    hook = hooks / "reference-transaction"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    clone = make_clone()
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.hooksPath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(hooks))
    store = open_store(clone)
    store.commit(store.snapshot().with_value("a", b"1"), "one")
    assert not marker.exists()


def test_inherited_configuration_is_kept(
    make_clone: MakeClone, bare_remote: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CI injects configuration (credentials, URL rewrites) this way; the store keeps it."""
    clone = make_clone()
    run_git(clone, "remote", "set-url", "origin", "alias:")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", f"'url.{bare_remote}.insteadof'='alias:'")
    store = open_store(clone)
    store.commit(store.snapshot().with_value("a", b"1"), "through an inherited alias")
    monkeypatch.delenv("GIT_CONFIG_PARAMETERS")
    assert open_store(make_clone()).snapshot().get("a") == b"1"


# --- Errors and push outcomes (§5, §8) -----------------------------------------------------


def install_server_hook(bare_remote: Path, name: str, script: str) -> None:
    hook = bare_remote / "hooks" / name
    hook.write_text("#!/bin/sh\n" + script)
    hook.chmod(0o755)


REFUSING_HOOK = "echo SERVER-SAYS-RUN-THIS >&2\nexit 1\n"


def test_a_refused_first_push_is_refused_without_the_servers_text(
    make_clone: MakeClone, bare_remote: Path
) -> None:
    clone = make_clone()
    store = open_store(clone)
    install_server_hook(bare_remote, "pre-receive", REFUSING_HOOK)
    with pytest.raises(CommitRefused) as caught:
        store.commit(store.snapshot().with_value("a", b""), "refused")
    assert "SERVER-SAYS-RUN-THIS" not in shown(caught.value)
    assert "SERVER-SAYS-RUN-THIS" in (clone / ".git" / LOG_NAME).read_text()
    assert run_git(bare_remote, "for-each-ref").strip() == ""


def test_a_push_refused_while_the_branch_is_unchanged_is_refused(
    make_clone: MakeClone, bare_remote: Path
) -> None:
    store = open_store(make_clone())
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    install_server_hook(bare_remote, "pre-receive", REFUSING_HOOK)
    with pytest.raises(CommitRefused) as caught:
        store.commit(snap.with_value("a", b"2"), "refused")
    assert "SERVER-SAYS-RUN-THIS" not in shown(caught.value)
    assert run_git(bare_remote, "rev-parse", f"refs/heads/{BRANCH}").strip() == snap.revision


def test_a_push_refused_while_the_branch_was_deleted_is_refused(
    make_clone: MakeClone, bare_remote: Path
) -> None:
    store = open_store(make_clone())
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    install_server_hook(
        bare_remote,
        "pre-receive",
        "env -u GIT_QUARANTINE_PATH -u GIT_OBJECT_DIRECTORY -u GIT_ALTERNATE_OBJECT_DIRECTORIES"
        f" git update-ref -d refs/heads/{BRANCH}\n" + REFUSING_HOOK,
    )
    with pytest.raises(CommitRefused):
        store.commit(snap.with_value("a", b"2"), "refused, branch gone")


def test_a_push_refused_while_the_branch_moved_elsewhere_is_stale(
    make_clone: MakeClone, bare_remote: Path
) -> None:
    """The remote's refusal is not trusted for its text, only for whether the branch moved."""
    store = open_store(make_clone())
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    other = open_store(make_clone(), branch="other")
    other.commit(other.snapshot().with_value("b", b"1"), "elsewhere")
    install_server_hook(
        bare_remote,
        "pre-receive",
        "env -u GIT_QUARANTINE_PATH -u GIT_OBJECT_DIRECTORY -u GIT_ALTERNATE_OBJECT_DIRECTORIES"
        f" git update-ref refs/heads/{BRANCH} refs/heads/other\n" + REFUSING_HOOK,
    )
    with pytest.raises(StaleSnapshot) as caught:
        store.commit(snap.with_value("a", b"2"), "refused after the branch moved")
    assert not isinstance(caught.value, UnknownOutcome)
    assert "SERVER-SAYS-RUN-THIS" not in shown(caught.value)


def test_a_push_refused_while_the_branch_moved_and_cannot_be_fetched_is_unknown(
    make_clone: MakeClone, bare_remote: Path
) -> None:
    """The branch moved elsewhere, and the fetch that would show whether our commit is
    in its history fails (the server can no longer send packs; `ls-remote` still works)."""
    store = open_store(make_clone())
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    other = open_store(make_clone(), branch="other")
    other.commit(other.snapshot().with_value("b", b"1"), "elsewhere")
    install_server_hook(
        bare_remote,
        "pre-receive",
        "env -u GIT_QUARANTINE_PATH -u GIT_OBJECT_DIRECTORY -u GIT_ALTERNATE_OBJECT_DIRECTORIES"
        f" git update-ref refs/heads/{BRANCH} refs/heads/other\n"
        "git config --global uploadpack.packObjectsHook false\n" + REFUSING_HOOK,
    )
    with pytest.raises(UnknownOutcome):
        store.commit(snap.with_value("a", b"2"), "refused, then unfetchable")


def test_a_push_refused_after_the_remote_applied_it_is_a_success(
    make_clone: MakeClone, bare_remote: Path
) -> None:
    """An `update` hook runs once the objects are in the repository: it can apply the
    update and still report a refusal. Only where the branch is decides."""
    store = open_store(make_clone())
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    install_server_hook(bare_remote, "update", 'git update-ref "$1" "$3"\n' + REFUSING_HOOK)
    landed = store.commit(snap.with_value("a", b"2"), "applied, then refused")
    assert landed.revision == run_git(bare_remote, "rev-parse", f"refs/heads/{BRANCH}").strip()
    assert open_store(make_clone()).snapshot().get("a") == b"2"


def test_a_push_refused_after_it_landed_and_was_built_on_is_a_success(
    make_clone: MakeClone, bare_remote: Path
) -> None:
    """The hook applies our commit, commits on top of it, then refuses: the branch is
    elsewhere, but our commit is in its history."""
    store = open_store(make_clone())
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    install_server_hook(
        bare_remote,
        "update",
        'top=$(git -c user.name=s -c user.email=s@x commit-tree "$3^{tree}" -p "$3" -m on-top)'
        ' || exit 1\ngit update-ref "$1" "$top"\n' + REFUSING_HOOK,
    )
    landed = store.commit(snap.with_value("a", b"2"), "applied, built on, then refused")
    tip = run_git(bare_remote, "rev-parse", f"refs/heads/{BRANCH}").strip()
    assert landed.revision == run_git(bare_remote, "rev-parse", f"{tip}^").strip()


def test_a_refused_push_whose_branch_cannot_be_read_has_an_unknown_outcome(
    make_clone: MakeClone, bare_remote: Path
) -> None:
    """A refused push may still have landed, so if the branch cannot be read afterwards,
    the outcome is unknown."""
    store = open_store(make_clone())
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    # refuse, and leave the remote unreadable for the `ls-remote` that follows
    install_server_hook(
        bare_remote, "pre-receive", "git config core.repositoryformatversion 99\nexit 1\n"
    )
    with pytest.raises(UnknownOutcome):
        store.commit(snap.with_value("a", b"2"), "refused, then unreadable")


def test_a_push_whose_status_is_lost_has_an_unknown_outcome(
    make_clone: MakeClone, bare_remote: Path
) -> None:
    """The remote applies the update, then dies before reporting it (verified with git
    2.53: the client sees `the remote end hung up`, exit 128, no status line)."""
    store = open_store(make_clone())
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    install_server_hook(
        bare_remote,
        "reference-transaction",
        'if [ "$1" = committed ]; then kill -9 "$PPID"; fi\n',
    )
    with pytest.raises(UnknownOutcome):
        store.commit(snap.with_value("a", b"2"), "two")
    (bare_remote / "hooks" / "reference-transaction").unlink()
    assert open_store(make_clone()).snapshot().get("a") == b"2"


def test_a_missing_remote_repository_is_a_remote_failure(
    make_clone: MakeClone, tmp_path: Path
) -> None:
    clone = make_clone()
    run_git(clone, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    with pytest.raises(RemoteFailed) as caught:
        open_store(clone).snapshot()
    assert "missing.git" not in shown(caught.value)


def test_a_push_without_a_status_has_an_unknown_outcome(
    make_clone: MakeClone, tmp_path: Path
) -> None:
    """Even when nothing was sent: the next snapshot reports what is wrong."""
    clone = make_clone()
    store = open_store(clone)
    snap = store.snapshot().with_value("a", b"1")
    run_git(clone, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    with pytest.raises(UnknownOutcome):
        store.commit(snap, "to nowhere")
    with pytest.raises(RemoteFailed):
        store.snapshot()


def test_an_unreachable_remote_is_a_remote_failure(make_clone: MakeClone) -> None:
    clone = make_clone()
    run_git(clone, "remote", "set-url", "origin", "git://127.0.0.1:9/nothing.git")
    with pytest.raises(RemoteFailed):
        open_store(clone).snapshot()


def test_a_branch_created_by_someone_else_is_read(make_clone: MakeClone) -> None:
    seed_remote(make_clone)
    snap = open_store(make_clone()).snapshot()
    assert snap.revision is not None
    assert snap.get("a") == b"1"


def test_a_ref_merely_ending_like_the_branch_is_not_the_branch(make_clone: MakeClone) -> None:
    """`ls-remote` matches on the end of a ref name (state-store design §3): only the
    exact ref counts."""
    forger = make_clone()
    root = tree(forger, [(REGULAR, blob(forger, b"decoy"), "a")])
    decoy = run_git(forger, "commit-tree", root, "-m", "decoy").strip()
    run_git(forger, "push", "--quiet", "origin", f"{decoy}:refs/foo/refs/heads/{BRANCH}")
    snap = open_store(make_clone()).snapshot()
    assert snap.revision is None
    assert snap.get("a") is None
