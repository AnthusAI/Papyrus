"""A content directory projects exactly like the same files published through the CMS."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from papyrus_content.project_commands import content_project
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite, static_directory, fixture_settings


@pytest.mark.parametrize("name", ["flat", "sectioned"])
def test_a_content_directory_projects_like_the_cms(name, monkeypatch):
    cms = ProjectedSite(name)
    work = Path(tempfile.mkdtemp(prefix="directory-source-"))
    try:
        static = static_directory(work, fixture_settings(name))
        out = work / "dist"
        monkeypatch.setenv("PAPYRUS_SITE_PUBLIC_URL", "")
        content_project(["--all", "--from-dir", str(FIXTURES / name / "content"), "--static-dir", str(static), "--out", str(out)])
        tree = {path.relative_to(out).as_posix(): path.read_bytes() for path in sorted(out.rglob("*")) if path.is_file()}
        assert tree == cms.tree
    finally:
        cms.cleanup()
        shutil.rmtree(work, ignore_errors=True)


def test_from_dir_needs_out_and_all(tmp_path):
    with pytest.raises(ValueError, match="--all"):
        content_project(["--from-dir", str(tmp_path)])
    with pytest.raises(ValueError, match="--out"):
        content_project(["--all", "--from-dir", str(tmp_path)])


def test_nested_directories_become_nested_slugs(tmp_path):
    content = tmp_path / "content"
    (content / "guides" / "intro").mkdir(parents=True)
    (content / "guides" / "intro.md").write_text("---\ntitle: Intro\ntype: page\n---\n# Intro\n", encoding="utf-8")
    (content / "guides" / "intro" / "First Steps.md").write_text("---\ntitle: First\ntype: page\n---\n# First\n", encoding="utf-8")
    static = tmp_path / "web"
    static.mkdir()
    (static / "projection.json").write_text(
        '{"site": {"name": "T"}, "urls": {"style": "directory", "sections": {"guides": {"base": "guides", "listing": false, "feed": false}}}}',
        encoding="utf-8",
    )
    out = tmp_path / "dist"
    content_project(["--all", "--from-dir", str(content), "--static-dir", str(static), "--out", str(out)])
    assert (out / "guides" / "intro" / "index.html").is_file()
    assert (out / "guides" / "intro" / "first-steps" / "index.html").is_file()
    assert "<h1" in (out / "guides" / "intro" / "first-steps" / "index.html").read_text(encoding="utf-8")


def test_a_cms_path_keeps_its_file_stem_as_the_slug():
    from papyrus_content.projection.source import split_output_path

    assert split_output_path("guides/intro/first.md") == ("guides", "first")
    assert split_output_path("guides/intro/First Steps.md", nested=True) == ("guides", "intro/first-steps")
    assert split_output_path("about.md", nested=True) == (None, "about")
