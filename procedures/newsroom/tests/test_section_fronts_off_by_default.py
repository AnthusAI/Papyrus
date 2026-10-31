"""A site that does not set the section-fronts settings projects exactly the bytes it projected before they existed.

``off-by-default-digests.json`` holds the SHA-256 of every file projected from each existing standard-site fixture, recorded from the
code on ``origin/develop`` before section fronts were added. The test projects the same fixtures with the current code and compares.
"""

from __future__ import annotations

import json

import pytest

from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite, fixture_settings

MANIFEST = FIXTURES / "off-by-default-digests.json"
FIXTURE_NAMES = ("flat", "sectioned", "authors", "showcase", "home-page")


def project_fixture(name: str, settings: dict | None = None) -> ProjectedSite:
    directory = FIXTURES / name
    if name != "home-page":
        return ProjectedSite(name, settings=settings)
    pages = {f"pages/{path.name}": path.read_bytes() for path in sorted((directory / "pages").glob("*.md"))}
    snapshot = (directory / "_data" / "home-page" / "references.json").read_bytes()
    return ProjectedSite(settings=settings or fixture_settings(name), content=directory / "content", extra_files=pages, seed={"_data/home-page/references.json": snapshot})


def digests_of(name: str, settings: dict | None = None) -> dict[str, str]:
    site = project_fixture(name, settings)
    try:
        return {key.replace("@", "-at-"): digest for key, digest in site.digests().items()}
    finally:
        site.cleanup()


def all_digests() -> dict[str, dict[str, str]]:
    return {name: digests_of(name) for name in FIXTURE_NAMES}


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_an_existing_fixture_projects_byte_identical_output(name):
    recorded = json.loads(MANIFEST.read_text(encoding="utf-8"))[name]
    assert digests_of(name) == recorded
