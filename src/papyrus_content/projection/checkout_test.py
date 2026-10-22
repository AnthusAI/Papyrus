import subprocess
from pathlib import Path

import pytest

from papyrus_content.projection.checkout import warn_if_checkout_is_behind


def git(directory: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(directory), "-c", "user.name=t", "-c", "user.email=t@example.test", *arguments],
        check=True,
        capture_output=True,
    )


def commit(directory: Path, name: str) -> None:
    (directory / name).write_text(name)
    git(directory, "add", name)
    git(directory, "commit", "-m", name)


@pytest.fixture
def repositories(tmp_path):
    upstream = tmp_path / "upstream.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(upstream)], check=True, capture_output=True)
    site = tmp_path / "site"
    subprocess.run(["git", "clone", str(upstream), str(site)], check=True, capture_output=True)
    git(site, "checkout", "-B", "main")
    commit(site, "one")
    git(site, "push", "-u", "origin", "main")
    other = tmp_path / "other"
    subprocess.run(["git", "clone", str(upstream), str(other)], check=True, capture_output=True)
    return site, other


def test_warns_when_the_checkout_is_behind_its_upstream(repositories, capsys):
    site, other = repositories
    commit(other, "two")
    commit(other, "three")
    git(other, "push", "origin", "main")
    warn_if_checkout_is_behind(str(site))
    err = capsys.readouterr().err
    assert f"warning: --static-dir {site} is 2 commits behind origin/main;" in err
    assert "projection.json and templates come from this checkout" in err
    assert "fresh worktree of origin/main" in err


def test_says_commit_for_one(repositories, capsys):
    site, other = repositories
    commit(other, "two")
    git(other, "push", "origin", "main")
    warn_if_checkout_is_behind(str(site))
    assert "is 1 commit behind" in capsys.readouterr().err


def test_is_silent_when_the_checkout_is_current(repositories, capsys):
    site, _other = repositories
    warn_if_checkout_is_behind(str(site))
    assert capsys.readouterr().err == ""


def test_is_silent_outside_a_git_work_tree(tmp_path, capsys):
    warn_if_checkout_is_behind(str(tmp_path))
    assert capsys.readouterr().err == ""


def test_is_silent_without_an_upstream(tmp_path, capsys):
    lonely = tmp_path / "lonely"
    lonely.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(lonely)], check=True, capture_output=True)
    commit(lonely, "one")
    warn_if_checkout_is_behind(str(lonely))
    assert capsys.readouterr().err == ""


def test_warns_that_it_could_not_check_when_the_fetch_fails(repositories, capsys):
    site, _other = repositories
    git(site, "remote", "set-url", "origin", str(site.parent / "gone.git"))
    warn_if_checkout_is_behind(str(site))
    assert "could not check" in capsys.readouterr().err
