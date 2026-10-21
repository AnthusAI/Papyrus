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
