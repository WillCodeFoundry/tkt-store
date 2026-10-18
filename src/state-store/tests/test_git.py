"""What only `GitStateStore` has: the layout on the branch, cloning and opening, checks
on what is read, hooks, errors and push outcomes (state-store design)."""

from __future__ import annotations

import shutil
import traceback
from collections.abc import Callable
from pathlib import Path

import pytest

from state_store import (
    MAX_VALUE_SIZE,
    CommitRefused,
    CompareAndSwapFailed,
    CorruptState,
    GitStateStore,
    NoIdentity,
    NoSuchBranch,
    PushElsewhere,
    RemoteFailed,
    StateSnapshot,
    StoreError,
    UnknownOutcome,
    UnusableRepository,
)
from state_store.runner import LOG_NAME
from state_store_testkit import (
    BRANCH,
    DIRECTORY,
    EMPTY_TREE,
    EXECUTABLE,
    REGULAR,
    SUBMODULE,
    SYMLINK,
    CloneStore,
    NewPath,
    blob,
    create_branch,
    publish,
    run_git,
    tree,
)

pytestmark = [
    pytest.mark.git,
    pytest.mark.xfail(raises=NotImplementedError, strict=True, reason="skeleton"),
]

FETCH_REFSPEC = f"+refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}"


def set_user_config(*args: str) -> None:
    """Change the user's (the test's isolated) global git configuration."""
    run_git(Path.home(), "config", "--global", *args)


def remote_tip(bare_remote: Path) -> str:
    return run_git(bare_remote, "rev-parse", f"refs/heads/{BRANCH}").strip()


def seed_remote(bare_remote: Path) -> None:
    publish(bare_remote, tree(bare_remote, [(REGULAR, blob(bare_remote, b"1"), "a")]))


def shown(error: BaseException) -> str:
    """Everything a printed traceback of `error` shows, chained exceptions included."""
    return "".join(traceback.format_exception(error))


# --- Layout on the branch (§2) ------------------------------------------------------------


def test_values_are_regular_blobs_and_namespaces_are_trees(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    store = clone_store()
    store.commit(store.snapshot().with_value("t/a", b"1").with_value("top", b"2"), "seed")
    listing = run_git(bare_remote, "ls-tree", "-r", "-t", f"refs/heads/{BRANCH}").splitlines()
    assert [line.split()[0] + " " + line.split("\t")[1] for line in listing] == [
        "040000 t",
        "100644 t/a",
        "100644 top",
    ]


def test_a_new_store_is_the_branchs_first_commit(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    assert clone_store().snapshot().revision == remote_tip(bare_remote)


def test_an_emptied_store_is_a_commit_of_the_empty_tree(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    store = clone_store()
    seeded = store.commit(store.snapshot().with_value("a", b""), "seed")
    store.commit(seeded.without("a"), "empty")
    assert run_git(bare_remote, "rev-parse", f"refs/heads/{BRANCH}^{{tree}}").strip() == EMPTY_TREE


def test_the_commit_has_the_message_and_gits_identity(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    store = clone_store()
    store.commit(store.snapshot().with_value("a", b""), "first line\n\nmore")
    log = run_git(bare_remote, "log", "-1", "--format=%an%n%ae%n%B", f"refs/heads/{BRANCH}")
    name = run_git(Path.home(), "config", "--global", "user.name").strip()
    email = run_git(Path.home(), "config", "--global", "user.email").strip()
    assert log.startswith(f"{name}\n{email}\nfirst line\n\nmore")


def test_the_clone_holds_only_the_tracking_ref_and_no_checkout(
    clone_store: CloneStore, new_path: NewPath
) -> None:
    path = new_path()
    store = clone_store(path)
    snap = store.commit(store.snapshot().with_value("t/a", b"1"), "seed")
    store.commit(snap.with_value("t/b", b"2"), "more")
    GitStateStore(path).snapshot()
    assert sorted(p.name for p in path.iterdir()) == [".git"]
    assert run_git(path, "for-each-ref", "--format=%(refname)").split() == [
        f"refs/remotes/origin/{BRANCH}"
    ]


def test_without_an_identity_nothing_is_committed(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    set_user_config("--remove-section", "user")
    store = clone_store()
    snap = store.snapshot()
    with pytest.raises(NoIdentity):
        store.commit(snap.with_value("a", b""), "no author")
    assert remote_tip(bare_remote) == snap.revision


# --- Cloning (§7) -------------------------------------------------------------------------


def test_cloning_makes_a_clone_of_only_the_branch(
    clone_store: CloneStore, new_path: NewPath, bare_remote: Path
) -> None:
    create_branch(bare_remote, "other")
    run_git(bare_remote, "tag", "-a", "v1", "-m", "a tag", f"refs/heads/{BRANCH}")
    path = new_path()
    clone_store(path)
    assert run_git(path, "rev-parse", "--is-bare-repository").strip() == "false"
    assert run_git(path, "config", "--get-all", "state-store.branch").splitlines() == [BRANCH]
    assert sorted(run_git(path, "config", "--get-regexp", r"^remote\.origin\.").splitlines()) == [
        f"remote.origin.fetch {FETCH_REFSPEC}",
        "remote.origin.tagopt --no-tags",
        f"remote.origin.url {bare_remote}",
    ]
    assert run_git(path, "for-each-ref", "--format=%(refname)").split() == [
        f"refs/remotes/origin/{BRANCH}"
    ]


def test_cloning_leaves_nothing_next_to_the_path(
    clone_store: CloneStore, new_path: NewPath
) -> None:
    """No temporary directory is left behind (whether one was used does not show here)."""
    path = new_path()
    clone_store(path)
    assert list(path.parent.iterdir()) == [path]


def test_cloning_uses_none_of_the_users_template(
    clone_store: CloneStore, new_path: NewPath, tmp_path: Path
) -> None:
    """git copies a template's files, `config` included, into a new repository."""
    template = tmp_path / "template"
    (template / "hooks").mkdir(parents=True)
    (template / "hooks" / "pre-push").write_text("#!/bin/sh\n")
    (template / "config").write_text('[remote "origin"]\n\tpushurl = /elsewhere.git\n')
    set_user_config("init.templateDir", str(template))
    path = new_path()
    clone_store(path).snapshot()
    assert not (path / ".git" / "hooks" / "pre-push").exists()
    assert "pushurl" not in run_git(path, "config", "--list", "--local")


def test_the_clone_takes_the_remotes_object_format_not_the_users_default(
    clone_store: CloneStore, new_path: NewPath, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user's default for new repositories is SHA-256, the remote is SHA-1."""
    set_user_config("init.defaultObjectFormat", "sha256")
    monkeypatch.setenv("GIT_DEFAULT_HASH", "sha256")
    path = new_path()
    store = clone_store(path)
    store.commit(store.snapshot().with_value("a", b"1"), "one")
    monkeypatch.delenv("GIT_DEFAULT_HASH")
    assert run_git(path, "rev-parse", "--show-object-format").strip() == "sha1"
    assert clone_store().snapshot().get("a") == b"1"


def test_a_sha256_remote_is_served(clone_store: CloneStore, tmp_path: Path) -> None:
    remote = tmp_path / "remote-sha256.git"
    run_git(tmp_path, "init", "--bare", "--quiet", "--object-format=sha256", str(remote))
    create_branch(remote, BRANCH)
    store = clone_store(url=str(remote))
    seeded = store.commit(store.snapshot().with_value("t/a", b"1"), "one")
    store.commit(seeded.without("t/a"), "emptied")
    assert clone_store(url=str(remote)).snapshot().keys() == []
    assert (
        run_git(remote, "rev-parse", f"refs/heads/{BRANCH}^{{tree}}").strip()
        == run_git(remote, "hash-object", "-t", "tree", "/dev/null").strip()
    )


def test_the_users_default_remote_name_is_not_used(
    clone_store: CloneStore, new_path: NewPath
) -> None:
    set_user_config("clone.defaultRemoteName", "upstream")
    path = new_path()
    store = clone_store(path)
    store.commit(store.snapshot().with_value("a", b"1"), "one")
    assert GitStateStore(path).snapshot().get("a") == b"1"


def test_an_enclosing_repository_is_never_read(
    clone_store: CloneStore, new_path: NewPath, bare_remote: Path
) -> None:
    """The clone is made inside another repository whose configuration maps `alias:` to
    a remote without the branch. `git clone` never reads it; the `ls-remote` run in the
    temporary directory after the clone fails would, and find no branch."""
    path = new_path()
    empty = path.parent.parent / "empty.git"
    run_git(path.parent.parent, "init", "--bare", "--quiet", str(empty))
    run_git(path.parent, "init", "--quiet")
    run_git(path.parent, "config", f"url.{empty}.insteadOf", "alias:")
    with pytest.raises(RemoteFailed):  # not NoSuchBranch: `alias:` names nothing here
        clone_store(path, url="alias:")


def test_a_relative_path_is_made_absolute(
    clone_store: CloneStore, new_path: NewPath, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = new_path()
    monkeypatch.chdir(path.parent)
    store = clone_store(Path(path.name))
    monkeypatch.chdir(tmp_path)
    store.commit(store.snapshot().with_value("a", b"1"), "from elsewhere")
    monkeypatch.chdir(path.parent)
    reopened = GitStateStore(Path(path.name))
    monkeypatch.chdir(tmp_path)
    assert reopened.snapshot().get("a") == b"1"


def test_a_tag_with_the_branchs_name_is_not_the_branch(
    clone_store: CloneStore, new_path: NewPath, bare_remote: Path
) -> None:
    """`git clone --branch` also accepts a tag, and then makes no tracking ref."""
    run_git(bare_remote, "tag", "-a", "v1", "-m", "a tag", f"refs/heads/{BRANCH}")
    path = new_path()
    with pytest.raises(NoSuchBranch):
        clone_store(path, branch="v1")
    assert list(path.parent.iterdir()) == []


def test_a_clone_that_fails_opening_stays_at_its_path(
    clone_store: CloneStore, new_path: NewPath
) -> None:
    """Cloning ends by opening; the user's configuration adds a setting to `origin`."""
    set_user_config("remote.origin.receivepack", "git-receive-pack")
    path = new_path()
    with pytest.raises(UnusableRepository):
        clone_store(path)
    assert (path / ".git").is_dir()
    with pytest.raises(UnusableRepository):
        GitStateStore(path)


def test_a_relative_path_to_the_remote_is_made_absolute(
    clone_store: CloneStore, new_path: NewPath, bare_remote: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = new_path()
    monkeypatch.chdir(bare_remote.parent)
    store = clone_store(path, url=Path(bare_remote.name))
    monkeypatch.chdir(path.parent)
    store.commit(store.snapshot().with_value("a", b"1"), "one")
    assert run_git(path, "config", "remote.origin.url").strip() == str(bare_remote)
    assert clone_store().snapshot().get("a") == b"1"


def test_cloning_a_branch_the_remote_does_not_have_is_no_such_branch(
    clone_store: CloneStore, new_path: NewPath
) -> None:
    path = new_path()
    with pytest.raises(NoSuchBranch):
        clone_store(path, branch="missing")
    assert list(path.parent.iterdir()) == []


def test_a_ref_merely_ending_like_the_branch_is_not_the_branch(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    """`ls-remote` matches on the end of a ref name (state-store design §3): only the
    exact ref counts."""
    root = tree(bare_remote, [(REGULAR, blob(bare_remote, b"decoy"), "a")])
    decoy = run_git(bare_remote, "commit-tree", root, "-m", "decoy").strip()
    run_git(bare_remote, "update-ref", "refs/foo/refs/heads/missing", decoy)
    with pytest.raises(NoSuchBranch):
        clone_store(branch="missing")


def test_a_failed_clone_leaves_nothing(
    clone_store: CloneStore, new_path: NewPath, tmp_path: Path
) -> None:
    path = new_path()
    with pytest.raises(RemoteFailed) as caught:
        clone_store(path, url=str(tmp_path / "missing.git"))
    assert "missing.git" not in shown(caught.value)
    assert list(path.parent.iterdir()) == []


def test_an_unreachable_remote_is_a_remote_failure(clone_store: CloneStore) -> None:
    with pytest.raises(RemoteFailed):
        clone_store(url="git://127.0.0.1:9/nothing.git")


Occupy = Callable[[Path, CloneStore], None]
"""Puts something at a path: `(path, clone_store)`."""


def an_empty_directory(path: Path, clone_store: CloneStore) -> None:
    path.mkdir()


def a_file(path: Path, clone_store: CloneStore) -> None:
    path.write_text("")


def a_broken_symlink(path: Path, clone_store: CloneStore) -> None:
    path.symlink_to(path.with_name("nowhere"))


def a_stores_clone(path: Path, clone_store: CloneStore) -> None:
    clone_store(path)


@pytest.mark.parametrize("occupy", [an_empty_directory, a_file, a_broken_symlink, a_stores_clone])
def test_cloning_to_a_path_that_exists_is_refused(
    clone_store: CloneStore, new_path: NewPath, occupy: Occupy
) -> None:
    path = new_path()
    occupy(path, clone_store)
    before = sorted(path.parent.iterdir())
    with pytest.raises(UnusableRepository):
        clone_store(path)
    assert sorted(path.parent.iterdir()) == before


def test_cloning_where_the_parent_is_missing_is_refused(
    clone_store: CloneStore, tmp_path: Path
) -> None:
    with pytest.raises(UnusableRepository):
        clone_store(tmp_path / "missing" / "store")
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize(
    "branch", ["", "refs/heads/x", "@", "HEAD", "x@{1}", "a..b", "-x", "a b", "x.lock"]
)
def test_invalid_branch_names_are_refused_before_anything_is_made(
    clone_store: CloneStore, new_path: NewPath, branch: str
) -> None:
    path = new_path()
    with pytest.raises(ValueError):
        clone_store(path, branch=branch)
    assert list(path.parent.iterdir()) == []


def test_an_empty_url_is_refused_before_anything_is_made(
    clone_store: CloneStore, new_path: NewPath
) -> None:
    path = new_path()
    with pytest.raises(ValueError):
        clone_store(path, url="")
    assert list(path.parent.iterdir()) == []


# --- Opening (§7) -------------------------------------------------------------------------


def test_a_clone_is_opened_again(clone_store: CloneStore, new_path: NewPath) -> None:
    path = new_path()
    store = clone_store(path)
    store.commit(store.snapshot().with_value("a", b"1"), "one")
    reopened = GitStateStore(path)
    assert reopened.snapshot().get("a") == b"1"
    reopened.commit(reopened.snapshot().with_value("a", b"2"), "two")
    assert clone_store().snapshot().get("a") == b"2"


def test_opening_never_contacts_the_remote(
    clone_store: CloneStore, new_path: NewPath, bare_remote: Path
) -> None:
    path = new_path()
    clone_store(path)
    bare_remote.rename(bare_remote.with_name("moved.git"))
    store = GitStateStore(path)
    with pytest.raises(RemoteFailed):
        store.snapshot()


def test_a_clone_reached_through_a_symlink_is_opened(
    clone_store: CloneStore, new_path: NewPath, tmp_path: Path
) -> None:
    path = new_path()
    clone_store(path)
    link = tmp_path / "link-to-store"
    link.symlink_to(path)
    store = GitStateStore(link)
    store.commit(store.snapshot().with_value("a", b"1"), "through a link")
    assert clone_store().snapshot().get("a") == b"1"


MakePath = Callable[[Path, Path, CloneStore], Path]
"""Makes something that is not a store's clone, from a new path:
`(path, bare_remote, clone_store)`; the path to open."""


def nothing(path: Path, bare_remote: Path, clone_store: CloneStore) -> Path:
    return path


def an_empty_directory_to_open(path: Path, bare_remote: Path, clone_store: CloneStore) -> Path:
    path.mkdir()
    return path


def a_file_to_open(path: Path, bare_remote: Path, clone_store: CloneStore) -> Path:
    path.write_text("")
    return path


def a_clone_made_with_plain_git(path: Path, bare_remote: Path, clone_store: CloneStore) -> Path:
    """The same clone the store makes, but the store did not make it."""
    run_git(
        path.parent,
        "clone",
        "--quiet",
        "--no-checkout",
        "--single-branch",
        f"--branch={BRANCH}",
        "--no-tags",
        str(bare_remote),
        path.name,
    )
    return path


def a_bare_repository_configured_like_a_clone(
    path: Path, bare_remote: Path, clone_store: CloneStore
) -> Path:
    """Everything a store's clone has, but bare: only that tells."""
    run_git(path.parent, "init", "--bare", "--quiet", path.name)
    for key, value in (
        ("remote.origin.url", str(bare_remote)),
        ("remote.origin.fetch", FETCH_REFSPEC),
        ("remote.origin.tagopt", "--no-tags"),
        ("state-store.branch", BRANCH),
    ):
        run_git(path, "config", key, value)
    run_git(path, "fetch", "--quiet", "origin")
    return path


def a_directory_inside_a_stores_clone(
    path: Path, bare_remote: Path, clone_store: CloneStore
) -> Path:
    clone_store(path)
    (path / "inner").mkdir()
    return path / "inner"


def the_git_directory_of_a_stores_clone(
    path: Path, bare_remote: Path, clone_store: CloneStore
) -> Path:
    clone_store(path)
    return path / ".git"


@pytest.mark.parametrize(
    "make_path",
    [
        nothing,
        an_empty_directory_to_open,
        a_file_to_open,
        a_clone_made_with_plain_git,
        a_bare_repository_configured_like_a_clone,
        a_directory_inside_a_stores_clone,
        the_git_directory_of_a_stores_clone,
    ],
)
def test_opening_what_is_not_a_stores_clone_is_refused(
    clone_store: CloneStore, new_path: NewPath, bare_remote: Path, make_path: MakePath
) -> None:
    to_open = make_path(new_path(), bare_remote, clone_store)
    with pytest.raises(UnusableRepository):
        GitStateStore(to_open)


@pytest.mark.parametrize(
    "change",
    [
        ("--add", "remote.origin.url", "/elsewhere.git"),
        ("--unset", "remote.origin.url"),
        ("--add", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"),
        ("--unset", "remote.origin.fetch"),
        ("--unset", "remote.origin.tagopt"),
        ("remote.origin.receivepack", "git-receive-pack"),
        ("--add", "state-store.branch", "other"),
        ("--unset", "state-store.branch"),
        ("state-store.branch", "-x"),
        ("state-store.branch", "other"),
        ("core.bare", "true"),
    ],
    ids=[
        "two urls",
        "no url",
        "another fetch refspec",
        "no fetch refspec",
        "no tagopt",
        "another setting",
        "two branches",
        "no branch",
        "invalid branch",
        "branch without its refspec",
        "bare",
    ],
)
def test_a_clone_changed_by_hand_is_refused(
    clone_store: CloneStore, new_path: NewPath, change: tuple[str, ...]
) -> None:
    path = new_path()
    clone_store(path)
    run_git(path, "config", *change)
    with pytest.raises(UnusableRepository):
        GitStateStore(path)


@pytest.mark.parametrize(
    "setting",
    [
        ("remote.origin.url", "/elsewhere.git"),
        ("remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"),
    ],
    ids=["another url", "another fetch refspec"],
)
def test_user_configuration_that_changes_the_remote_is_refused(
    clone_store: CloneStore, new_path: NewPath, setting: tuple[str, str]
) -> None:
    """The checks read every configuration file git reads, not only the clone's."""
    path = new_path()
    clone_store(path)
    set_user_config(*setting)
    with pytest.raises(UnusableRepository):
        GitStateStore(path)


def test_pushing_the_same_repository_by_another_url_is_accepted(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    """Like fetching over HTTPS and pushing over SSH: the URLs differ, the repository
    is the same, and the next snapshot finds the commit."""
    set_user_config(f"url.{bare_remote.as_uri()}.pushInsteadOf", str(bare_remote))
    store = clone_store()
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    assert store.snapshot().revision == snap.revision
    assert clone_store().snapshot().get("a") == b"1"


def test_a_push_url_for_the_same_repository_is_accepted(
    clone_store: CloneStore, new_path: NewPath, bare_remote: Path
) -> None:
    path = new_path()
    clone_store(path)
    run_git(path, "config", "remote.origin.pushurl", bare_remote.as_uri())
    store = GitStateStore(path)
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    assert store.snapshot().revision == snap.revision


def test_two_push_urls_are_refused(clone_store: CloneStore, new_path: NewPath) -> None:
    """git would push to both and report each; one comes from the user's configuration."""
    path = new_path()
    clone_store(path)
    run_git(path, "config", "remote.origin.pushurl", "/one.git")
    set_user_config("remote.origin.pushurl", "/two.git")
    with pytest.raises(UnusableRepository):
        GitStateStore(path)


def test_a_push_url_to_another_repository_shows_at_the_next_snapshot(
    clone_store: CloneStore, new_path: NewPath, bare_remote: Path, tmp_path: Path
) -> None:
    path = new_path()
    clone_store(path)
    elsewhere = tmp_path / "elsewhere.git"
    shutil.copytree(bare_remote, elsewhere)
    run_git(path, "config", "remote.origin.pushurl", str(elsewhere))
    store = GitStateStore(path)
    store.commit(store.snapshot().with_value("a", b"1"), "lands elsewhere")
    with pytest.raises(PushElsewhere):
        store.snapshot()


def test_a_push_to_another_repository_shows_at_the_next_snapshot(
    clone_store: CloneStore, bare_remote: Path, tmp_path: Path
) -> None:
    """Pushes are rewritten to a copy of the remote: the compare-and-swap passes there,
    and only the next snapshot, read from the real remote, can tell."""
    store = clone_store()
    elsewhere = tmp_path / "elsewhere.git"
    shutil.copytree(bare_remote, elsewhere)
    set_user_config(f"url.{elsewhere}.pushInsteadOf", str(bare_remote))
    first = store.snapshot()
    store.commit(first.with_value("a", b"1"), "lands elsewhere")
    assert remote_tip(bare_remote) == first.revision
    with pytest.raises(PushElsewhere):
        store.snapshot()


def test_a_push_to_a_repository_elsewhere_in_history_shows_at_the_next_snapshot(
    clone_store: CloneStore, bare_remote: Path, tmp_path: Path
) -> None:
    """Pushes are rewritten to a copy taken before the branch moved: every lease there
    fails its compare-and-swap, and the next snapshot finds the branch has not moved."""
    elsewhere = tmp_path / "elsewhere.git"
    shutil.copytree(bare_remote, elsewhere)
    seed_remote(bare_remote)
    set_user_config(f"url.{elsewhere}.pushInsteadOf", str(bare_remote))
    store = clone_store()
    with pytest.raises(CompareAndSwapFailed):
        store.commit(store.snapshot().with_value("a", b"2"), "refused elsewhere")
    with pytest.raises(PushElsewhere):
        store.snapshot()


def test_a_lease_refused_by_a_real_race_passes_the_check(clone_store: CloneStore) -> None:
    store, other = clone_store(), clone_store()
    stale = store.snapshot()
    other.commit(other.snapshot().with_value("b", b"2"), "first")
    with pytest.raises(CompareAndSwapFailed):
        store.commit(stale.with_value("a", b"1"), "second")
    assert store.snapshot().keys() == ["b"]


def test_commits_built_on_by_others_pass_the_check(clone_store: CloneStore) -> None:
    store, other = clone_store(), clone_store()
    store.commit(store.snapshot().with_value("a", b"1"), "one")
    other.commit(other.snapshot().with_value("b", b"2"), "on top")
    assert store.snapshot().keys() == ["a", "b"]


def test_a_url_rewritten_the_same_both_ways_is_accepted(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    set_user_config(f"url.{bare_remote}.insteadOf", "alias:")
    store = clone_store(url="alias:")
    store.commit(store.snapshot().with_value("a", b"1"), "through an alias")
    assert clone_store().snapshot().get("a") == b"1"


# --- Checks on what is read (§1, §4) ------------------------------------------------------


def forge_bad_namespace(remote: Path, bad: tuple[str, str, str]) -> None:
    """Publish `bad/ok` (a valid value), `bad` + the entry `bad`, and `good/a`."""
    ok = (REGULAR, blob(remote, b"ok"), "ok")
    good = tree(remote, [(REGULAR, blob(remote, b"a"), "a")])
    publish(
        remote,
        tree(remote, [(DIRECTORY, tree(remote, [ok, bad]), "bad"), (DIRECTORY, good, "good")]),
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


def corrupt_snapshot(
    clone_store: CloneStore, bare_remote: Path, kind: str
) -> tuple[GitStateStore, StateSnapshot]:
    mode, content, name = BAD_ENTRIES[kind]
    oid = content if isinstance(content, str) else blob(bare_remote, content)
    forge_bad_namespace(bare_remote, (mode, oid, name))
    store = clone_store()
    return store, store.snapshot()


def assert_corrupt(caught: pytest.ExceptionInfo[StoreError]) -> None:
    assert isinstance(caught.value, CorruptState)


@pytest.mark.parametrize("kind", BAD_KINDS)
def test_listing_a_namespace_with_a_bad_entry_fails(
    clone_store: CloneStore, bare_remote: Path, kind: str
) -> None:
    _, snap = corrupt_snapshot(clone_store, bare_remote, kind)
    with pytest.raises(StoreError) as caught:
        snap.keys("bad")
    assert_corrupt(caught)


@pytest.mark.parametrize(
    "kind", ["symlink", "executable", "submodule", "oversized", "duplicate", "empty namespace"]
)
def test_reading_a_bad_entry_fails(clone_store: CloneStore, bare_remote: Path, kind: str) -> None:
    _, snap = corrupt_snapshot(clone_store, bare_remote, kind)
    with pytest.raises(StoreError) as caught:
        snap.get(f"bad/{BAD_ENTRIES[kind][2]}")
    assert_corrupt(caught)


@pytest.mark.parametrize("kind", BAD_KINDS)
def test_reads_that_do_not_touch_the_bad_entry_succeed(
    clone_store: CloneStore, bare_remote: Path, kind: str
) -> None:
    _, snap = corrupt_snapshot(clone_store, bare_remote, kind)
    assert snap.get("good/a") == b"a"
    assert snap.keys("good") == ["good/a"]
    if kind != "duplicate":
        assert snap.get("bad/ok") == b"ok"


@pytest.mark.parametrize("kind", BAD_KINDS)
def test_a_commit_never_rebuilds_a_namespace_with_a_bad_entry(
    clone_store: CloneStore, bare_remote: Path, kind: str
) -> None:
    store, snap = corrupt_snapshot(clone_store, bare_remote, kind)
    next_to_it = snap.with_value("bad/new", b"")  # its path holds no bad entry
    with pytest.raises(StoreError) as caught:
        store.commit(next_to_it, "next to a bad entry")
    assert_corrupt(caught)
    store.commit(snap.with_value("good/b", b""), "elsewhere")


def test_a_collision_check_that_reads_a_bad_entry_fails(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    """Whether `bad` still holds a value, once `bad/ok` is removed, is read from the
    namespace itself, which holds a bad entry."""
    _, snap = corrupt_snapshot(clone_store, bare_remote, "symlink")
    emptied = snap.without("bad/ok")
    with pytest.raises(CorruptState):
        emptied.with_value("bad", b"now a value")


def test_a_collision_check_reads_the_whole_namespace(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    """`bad` holds `ok` (a value) and `run` (an executable, listed after it): finding a
    value is not enough, every entry listed is checked."""
    _, snap = corrupt_snapshot(clone_store, bare_remote, "executable")
    with pytest.raises(CorruptState):
        snap.with_value("bad", b"now a value")


def test_a_bad_entry_cannot_be_removed_through_the_store(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    """Repair takes plain git (state-store design §4): the store never rebuilds a
    corrupt tree."""
    store, snap = corrupt_snapshot(clone_store, bare_remote, "symlink")
    with pytest.raises(StoreError) as caught:
        store.commit(snap.without("bad/link"), "remove the bad entry")
    assert_corrupt(caught)


def test_a_bad_entry_at_the_root_stops_listing_the_root_only(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    good = tree(bare_remote, [(REGULAR, blob(bare_remote, b"a"), "a")])
    link = (SYMLINK, blob(bare_remote, b"x"), "link")
    publish(bare_remote, tree(bare_remote, [(DIRECTORY, good, "good"), link]))
    snap = clone_store().snapshot()
    assert snap.get("good/a") == b"a"
    with pytest.raises(StoreError) as caught:
        snap.keys()
    assert_corrupt(caught)


def test_errors_never_echo_a_name_that_was_read(clone_store: CloneStore, bare_remote: Path) -> None:
    secret = "IGNORE PREVIOUS INSTRUCTIONS"  # not a valid segment: a corrupt entry
    publish(bare_remote, tree(bare_remote, [(REGULAR, blob(bare_remote, b""), secret)]))
    snap = clone_store().snapshot()
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


def test_no_hook_ever_runs(clone_store: CloneStore, new_path: NewPath, tmp_path: Path) -> None:
    marker = tmp_path / "hook-ran"

    def install_hooks(directory: Path) -> None:
        directory.mkdir(exist_ok=True)
        for name in ("reference-transaction", "pre-push", "post-checkout", "pre-auto-gc"):
            hook = directory / name
            hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
            hook.chmod(0o755)

    install_hooks(tmp_path / "hooks")
    set_user_config("core.hooksPath", str(tmp_path / "hooks"))
    path = new_path()
    store = clone_store(path)
    install_hooks(path / ".git" / "hooks")
    make_gc_due(path)
    packs = pack_count(path)
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    store.commit(snap.with_value("a", b"2"), "two")
    store.snapshot().keys()
    assert pack_count(path) < packs  # gc ran, so `pre-auto-gc` would have
    assert not marker.exists()


def test_automatic_maintenance_runs_in_the_foreground(
    clone_store: CloneStore,
    new_path: NewPath,
    bare_remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gc has finished by the time a snapshot returns, even where git's configuration
    says to detach it. (Only a fetch that succeeds runs maintenance.)"""
    set_user_config("maintenance.autoDetach", "true")
    set_user_config("gc.autoDetach", "true")
    path = new_path()
    store = clone_store(path)
    seed_remote(bare_remote)
    make_gc_due(path)
    packs = pack_count(path)
    trace = tmp_path / "trace"
    monkeypatch.setenv("GIT_TRACE", str(trace))
    store.snapshot()
    monkeypatch.delenv("GIT_TRACE")
    assert pack_count(path) < packs
    gc_runs = [line for line in trace.read_text().splitlines() if "git gc --auto" in line]
    assert gc_runs
    assert all("--no-detach" in line for line in gc_runs)


def test_tags_are_never_pushed(
    clone_store: CloneStore, new_path: NewPath, bare_remote: Path
) -> None:
    set_user_config("push.followTags", "true")
    path = new_path()
    store = clone_store(path)
    first = store.commit(store.snapshot().with_value("a", b"1"), "one")
    run_git(path, "tag", "-a", "v1", "-m", "a tag", first.revision)
    store.commit(first.with_value("a", b"2"), "two")
    assert run_git(bare_remote, "tag").strip() == ""


def test_inherited_variables_never_redirect_git(
    clone_store: CloneStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoy = tmp_path / "decoy.git"
    run_git(tmp_path, "init", "--bare", "--quiet", str(decoy))
    monkeypatch.setenv("GIT_DIR", str(decoy))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "decoy-index"))
    store = clone_store()
    store.commit(store.snapshot().with_value("a", b"1"), "one")
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_INDEX_FILE")
    assert clone_store().snapshot().get("a") == b"1"
    assert run_git(decoy, "for-each-ref").strip() == ""
    assert "state-store" not in run_git(decoy, "config", "--list", "--local")


def test_replace_objects_never_stand_in_for_what_the_branch_holds(
    clone_store: CloneStore, new_path: NewPath
) -> None:
    writer = clone_store()
    writer.commit(writer.snapshot().with_value("a", b"original"), "one")
    path = new_path()
    clone_store(path)
    original = run_git(path, "rev-parse", f"refs/remotes/origin/{BRANCH}:a").strip()
    run_git(path, "replace", original, blob(path, b"replaced"))
    assert GitStateStore(path).snapshot().get("a") == b"original"


def test_inherited_configuration_cannot_turn_hooks_back_on(
    clone_store: CloneStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hooks, marker = tmp_path / "evil-hooks", tmp_path / "hook-ran"
    hooks.mkdir()
    hook = hooks / "reference-transaction"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.hooksPath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(hooks))
    store = clone_store()
    store.commit(store.snapshot().with_value("a", b"1"), "one")
    assert not marker.exists()


def test_inherited_configuration_is_kept(
    clone_store: CloneStore, bare_remote: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CI injects configuration (credentials, URL rewrites) this way; the store keeps it."""
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", f"'url.{bare_remote}.insteadof'='alias:'")
    store = clone_store(url="alias:")
    store.commit(store.snapshot().with_value("a", b"1"), "through an inherited alias")
    monkeypatch.delenv("GIT_CONFIG_PARAMETERS")
    assert clone_store().snapshot().get("a") == b"1"


# --- Errors and push outcomes (§3, §5, §8) -------------------------------------------------


def install_server_hook(bare_remote: Path, name: str, script: str) -> None:
    hook = bare_remote / "hooks" / name
    hook.write_text("#!/bin/sh\n" + script)
    hook.chmod(0o755)


REFUSING_HOOK = "echo SERVER-SAYS-RUN-THIS >&2\nexit 1\n"


def test_a_push_refused_while_the_branch_is_unchanged_is_refused(
    clone_store: CloneStore, new_path: NewPath, bare_remote: Path
) -> None:
    path = new_path()
    store = clone_store(path)
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    install_server_hook(bare_remote, "pre-receive", REFUSING_HOOK)
    with pytest.raises(CommitRefused) as caught:
        store.commit(snap.with_value("a", b"2"), "refused")
    assert "SERVER-SAYS-RUN-THIS" not in shown(caught.value)
    assert "SERVER-SAYS-RUN-THIS" in (path / ".git" / LOG_NAME).read_text()
    assert remote_tip(bare_remote) == snap.revision
    assert store.snapshot().revision == snap.revision  # a refusal leaves no expectation


def test_a_push_refused_while_the_branch_was_deleted_is_no_such_branch(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    store = clone_store()
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    install_server_hook(
        bare_remote,
        "pre-receive",
        "env -u GIT_QUARANTINE_PATH -u GIT_OBJECT_DIRECTORY -u GIT_ALTERNATE_OBJECT_DIRECTORIES"
        f" git update-ref -d refs/heads/{BRANCH}\n" + REFUSING_HOOK,
    )
    with pytest.raises(NoSuchBranch):
        store.commit(snap.with_value("a", b"2"), "refused, branch gone")


def test_a_push_refused_while_the_branch_moved_elsewhere_fails_the_compare_and_swap(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    """The remote's refusal is not trusted for its text, only for whether the branch moved."""
    store = clone_store()
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    create_branch(bare_remote, "other")
    other = clone_store(branch="other")
    other.commit(other.snapshot().with_value("b", b"1"), "elsewhere")
    install_server_hook(
        bare_remote,
        "pre-receive",
        "env -u GIT_QUARANTINE_PATH -u GIT_OBJECT_DIRECTORY -u GIT_ALTERNATE_OBJECT_DIRECTORIES"
        f" git update-ref refs/heads/{BRANCH} refs/heads/other\n" + REFUSING_HOOK,
    )
    with pytest.raises(CompareAndSwapFailed) as caught:
        store.commit(snap.with_value("a", b"2"), "refused after the branch moved")
    assert "SERVER-SAYS-RUN-THIS" not in shown(caught.value)
    assert store.snapshot().revision == remote_tip(bare_remote)  # it did move: no alarm


def test_a_push_refused_while_the_branch_moved_and_cannot_be_fetched_is_unknown(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    """The branch moved elsewhere, and the fetch that would show whether our commit is
    in its history fails (the server can no longer send packs; `ls-remote` still works)."""
    store = clone_store()
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    create_branch(bare_remote, "other")
    other = clone_store(branch="other")
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
    clone_store: CloneStore, bare_remote: Path
) -> None:
    """An `update` hook runs once the objects are in the repository: it can apply the
    update and still report a refusal. Only where the branch is decides."""
    store = clone_store()
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    install_server_hook(bare_remote, "update", 'git update-ref "$1" "$3"\n' + REFUSING_HOOK)
    landed = store.commit(snap.with_value("a", b"2"), "applied, then refused")
    assert landed.revision == remote_tip(bare_remote)
    assert clone_store().snapshot().get("a") == b"2"


def test_a_push_refused_after_it_landed_and_was_built_on_is_a_success(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    """The hook applies our commit, commits on top of it, then refuses: the branch is
    elsewhere, but our commit is in its history."""
    store = clone_store()
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    install_server_hook(
        bare_remote,
        "update",
        'top=$(git -c user.name=s -c user.email=s@x commit-tree "$3^{tree}" -p "$3" -m on-top)'
        ' || exit 1\ngit update-ref "$1" "$top"\n' + REFUSING_HOOK,
    )
    landed = store.commit(snap.with_value("a", b"2"), "applied, built on, then refused")
    tip = remote_tip(bare_remote)
    assert landed.revision == run_git(bare_remote, "rev-parse", f"{tip}^").strip()


def test_a_refused_push_whose_branch_cannot_be_read_has_an_unknown_outcome(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    """A refused push may still have landed, so if the branch cannot be read afterwards,
    the outcome is unknown."""
    store = clone_store()
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    # refuse, and leave the remote unreadable for the `ls-remote` that follows
    install_server_hook(
        bare_remote, "pre-receive", "git config core.repositoryformatversion 99\nexit 1\n"
    )
    with pytest.raises(UnknownOutcome):
        store.commit(snap.with_value("a", b"2"), "refused, then unreadable")


def test_a_push_whose_status_is_lost_has_an_unknown_outcome(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    """The remote applies the update, then dies before reporting it (verified with git
    2.53: the client sees `the remote end hung up`, exit 128, no status line)."""
    store = clone_store()
    snap = store.commit(store.snapshot().with_value("a", b"1"), "one")
    install_server_hook(
        bare_remote,
        "reference-transaction",
        'if [ "$1" = committed ]; then kill -9 "$PPID"; fi\n',
    )
    with pytest.raises(UnknownOutcome):
        store.commit(snap.with_value("a", b"2"), "two")
    (bare_remote / "hooks" / "reference-transaction").unlink()
    assert store.snapshot().get("a") == b"2"
    assert clone_store().snapshot().get("a") == b"2"


def test_a_push_without_a_status_has_an_unknown_outcome(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    """Even when nothing was sent: the next snapshot reports what is wrong."""
    store = clone_store()
    first = store.snapshot()
    moved = bare_remote.rename(bare_remote.with_name("moved.git"))
    with pytest.raises(UnknownOutcome):
        store.commit(first.with_value("a", b"1"), "to nowhere")
    with pytest.raises(RemoteFailed):
        store.snapshot()
    moved.rename(bare_remote)
    assert store.snapshot().revision == first.revision  # an unknown outcome expects nothing


def test_a_branch_deleted_from_the_remote_is_no_such_branch(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    """Against the preconditions, but reported, not taken for an empty store."""
    store = clone_store()
    tip = remote_tip(bare_remote)
    run_git(bare_remote, "update-ref", "-d", f"refs/heads/{BRANCH}")
    run_git(bare_remote, "update-ref", f"refs/foo/refs/heads/{BRANCH}", tip)  # not the branch
    with pytest.raises(NoSuchBranch):
        store.snapshot()


def test_a_branch_written_by_someone_else_is_read(
    clone_store: CloneStore, bare_remote: Path
) -> None:
    seed_remote(bare_remote)
    snap = clone_store().snapshot()
    assert snap.revision == remote_tip(bare_remote)
    assert snap.get("a") == b"1"
