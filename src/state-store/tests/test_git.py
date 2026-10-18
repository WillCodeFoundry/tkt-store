"""What only `GitStateStore` has: the layout on the branch, opening a clone, checks on
what is read, hooks, errors and push outcomes (state-store design)."""

from __future__ import annotations

import traceback
from pathlib import Path

import pytest

from state_store import (
    MAX_VALUE_SIZE,
    Category,
    GitStateStore,
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
        f"refs/state-store/origin/{BRANCH}"
    ]


def test_without_an_identity_nothing_is_committed(make_clone: MakeClone) -> None:
    store = open_store(make_clone(identity=False))
    with pytest.raises(StoreError) as caught:
        store.commit(store.snapshot().with_value("a", b""), "no author")
    assert caught.value.category is Category.NO_IDENTITY


# --- Opening a store (§7) ---------------------------------------------------------------


def seed_remote(make_clone: MakeClone) -> None:
    clone = make_clone()
    publish(clone, tree(clone, [(REGULAR, blob(clone, b"1"), "a")]))


@pytest.mark.parametrize("name", ["", "missing"], ids=["not a repository", "no such path"])
def test_a_path_that_is_not_a_repository_is_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(StoreError) as caught:
        open_store(tmp_path / name)
    assert caught.value.category is Category.NOT_A_CLONE


def test_a_subdirectory_of_a_clone_is_refused(make_clone: MakeClone) -> None:
    inner = make_clone() / "inner"
    inner.mkdir()
    with pytest.raises(StoreError) as caught:
        open_store(inner)
    assert caught.value.category is Category.NOT_A_CLONE


def test_a_shallow_clone_is_refused(make_clone: MakeClone, bare_remote: Path) -> None:
    seed_remote(make_clone)
    clone = make_clone("--depth=1", f"--branch={BRANCH}", url=bare_remote.as_uri())
    with pytest.raises(StoreError) as caught:
        open_store(clone)
    assert caught.value.category is Category.NOT_A_CLONE


def test_a_partial_clone_is_refused(make_clone: MakeClone, bare_remote: Path) -> None:
    seed_remote(make_clone)
    run_git(bare_remote, "config", "uploadpack.allowFilter", "true")
    clone = make_clone("--filter=blob:none", url=bare_remote.as_uri())
    with pytest.raises(StoreError) as caught:
        open_store(clone)
    assert caught.value.category is Category.NOT_A_CLONE


def test_a_promisor_on_any_remote_is_refused(make_clone: MakeClone, bare_remote: Path) -> None:
    clone = make_clone()
    run_git(clone, "remote", "add", "other", str(bare_remote))
    run_git(clone, "config", "remote.other.promisor", "true")
    with pytest.raises(StoreError) as caught:
        open_store(clone)
    assert caught.value.category is Category.NOT_A_CLONE


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
    with pytest.raises(StoreError) as caught:
        open_store(clone)
    assert caught.value.category is Category.NOT_A_CLONE


def test_a_remote_that_is_not_configured_is_refused(make_clone: MakeClone) -> None:
    with pytest.raises(StoreError) as caught:
        open_store(make_clone(), remote="upstream")
    assert caught.value.category is Category.NOT_A_CLONE


@pytest.mark.parametrize(
    "branch", ["", "refs/heads/x", "@", "HEAD", "x@{1}", "a..b", "-x", "a b", "x.lock"]
)
def test_invalid_branch_names_are_refused(make_clone: MakeClone, branch: str) -> None:
    with pytest.raises(ValueError):
        open_store(make_clone(), branch=branch)


@pytest.mark.parametrize("remote", ["", "-origin", "a/b", "a b", "http://x"])
def test_invalid_remote_names_are_refused(make_clone: MakeClone, remote: str) -> None:
    with pytest.raises(ValueError):
        open_store(make_clone(), remote=remote)


def test_a_bare_repository_is_refused(bare_remote: Path) -> None:
    with pytest.raises(StoreError) as caught:
        open_store(bare_remote)
    assert caught.value.category is Category.NOT_A_CLONE


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
    assert caught.value.category is Category.CORRUPT


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
def test_a_commit_never_carries_a_bad_entry_forward(make_clone: MakeClone, kind: str) -> None:
    store, snap = corrupt_snapshot(make_clone, kind)
    with pytest.raises(StoreError) as caught:
        store.commit(snap.with_value("bad/new", b""), "next to a bad entry")
    assert_corrupt(caught)
    store.commit(snap.with_value("good/b", b""), "elsewhere")


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
    store = open_store(clone)
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    store.commit(snap.with_value("a", b"2"), "two")
    store.snapshot().keys()
    assert not marker.exists()


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
    with pytest.raises(StoreError) as caught:
        store.commit(store.snapshot().with_value("a", b""), "refused")
    assert caught.value.category is Category.REFUSED
    assert "SERVER-SAYS-RUN-THIS" not in shown(caught.value)
    assert "SERVER-SAYS-RUN-THIS" in (clone / ".git" / LOG_NAME).read_text()


def test_a_push_refused_while_the_branch_is_unchanged_is_refused(
    make_clone: MakeClone, bare_remote: Path
) -> None:
    store = open_store(make_clone())
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    install_server_hook(bare_remote, "pre-receive", REFUSING_HOOK)
    with pytest.raises(StoreError) as caught:
        store.commit(snap.with_value("a", b"2"), "refused")
    assert caught.value.category is Category.REFUSED
    assert "SERVER-SAYS-RUN-THIS" not in shown(caught.value)


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


def test_a_missing_remote_repository_is_not_found(make_clone: MakeClone, tmp_path: Path) -> None:
    clone = make_clone()
    run_git(clone, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    with pytest.raises(StoreError) as caught:
        open_store(clone).snapshot()
    assert caught.value.category is Category.NOT_FOUND
    assert "missing.git" not in shown(caught.value)


def test_a_push_that_sends_nothing_is_a_store_error_not_an_unknown_outcome(
    make_clone: MakeClone, tmp_path: Path
) -> None:
    clone = make_clone()
    store = open_store(clone)
    snap = store.snapshot().with_value("a", b"1")
    run_git(clone, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    with pytest.raises(StoreError) as caught:
        store.commit(snap, "to nowhere")
    assert caught.value.category is Category.NOT_FOUND


def test_an_unreachable_remote_is_unreachable(make_clone: MakeClone) -> None:
    clone = make_clone()
    run_git(clone, "remote", "set-url", "origin", "git://127.0.0.1:9/nothing.git")
    with pytest.raises(StoreError) as caught:
        open_store(clone).snapshot()
    assert caught.value.category is Category.UNREACHABLE


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
