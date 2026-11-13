"""SiteConfig schema, validation and the projection.json converter, against fictional projection.json files shaped like dedicated sites."""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from papyrus_content.projection.standard.config import standard_settings_from_mapping
from papyrus_content.site_config import ConversionError, from_site_config, to_site_config, validate_site_config
from procedures.newsroom.tests.standard_frontend_support import ProjectedSite

FIXTURES = Path(__file__).parent / "fixtures"
SITES = sorted(path.name.removesuffix(".projection.json") for path in FIXTURES.glob("*.projection.json"))


def load(site: str) -> dict:
    return json.loads((FIXTURES / f"{site}.projection.json").read_text(encoding="utf-8"))


def test_the_fixtures_are_the_sites_we_expect():
    assert SITES == ["harbor-ledger", "meridian-field-guide"]


@pytest.mark.parametrize("site", SITES)
def test_conversion_validates_and_round_trips(site):
    projection = load(site)
    config, rest = to_site_config(projection)
    assert validate_site_config(config) == []
    assert from_site_config(config, rest) == projection
    standard_settings_from_mapping(from_site_config(config, rest))


@pytest.mark.parametrize("site", SITES)
def test_conversion_does_not_change_its_input(site):
    projection = load(site)
    before = copy.deepcopy(projection)
    to_site_config(projection)
    assert projection == before


def test_a_sectioned_newsroom_lands_in_the_config():
    config, rest = to_site_config(load("harbor-ledger"))
    assert config["name"] == "Harbor Ledger"
    assert [s["slug"] for s in config["sections"]] == ["tides", "cargo", "piers", "field-dispatches"]
    assert config["homeTemplate"] == "sections"
    assert config["features"] == {"conversations": True, "videos": True}
    assert [link["href"] for link in config["nav"]] == ["/", "/cargo/", "/subscribe/", "https://port.example/"]
    assert rest["hooks"] == "hooks.py"
    assert "name" not in rest["site"]


def test_hooks_redirects_and_base_path_stay_with_the_dedicated_site():
    config, rest = to_site_config(load("meridian-field-guide"))
    assert set(config) <= {"schemaVersion", "name", "tagline", "purpose", "sections", "nav", "footer"}
    assert rest["urls"]["basePath"] == "guide"
    assert rest["redirects"]["exact"]["/old-glossary/"] == "/glossary/"
    assert rest["hooks"] == "hooks.py"
    assert [s["slug"] for s in config["sections"]] == ["basics", "kit", "glossary"]


def content_for(config: dict, work: Path) -> Path:
    """One article per section, so the home page and the section fronts have something to show."""
    root = work / "content"
    for index, section in enumerate(config.get("sections", [])):
        directory = root / section["name"]
        directory.mkdir(parents=True)
        (directory / "first.md").write_text(f"---\ntitle: First in {section['name']}\ndate: '2026-03-{10 + index:02d}'\n---\nBody.\n", encoding="utf-8")
    root.mkdir(exist_ok=True)
    (root / "index.md").write_text("---\ntitle: Home\n---\nWelcome.\n", encoding="utf-8")
    return root


def render(settings: dict, content: Path) -> dict[str, bytes]:
    # hooks and authored page files live in the site's repository, not in the settings; both sides of the comparison lose them
    settings = {key: value for key, value in settings.items() if key not in ("hooks", "pages")}
    settings.get("chrome", {}).pop("scripts", None)
    site = ProjectedSite(settings=settings, content=content)
    try:
        return site.tree
    finally:
        site.cleanup()


@pytest.mark.parametrize("site", SITES)
def test_the_round_tripped_site_renders_the_same_pages(site):
    projection = load(site)
    config, rest = to_site_config(projection)
    work = Path(tempfile.mkdtemp(prefix="site-config-"))
    try:
        content = content_for(config, work)
        original = render(projection, content)
        again = render(from_site_config(config, rest), content)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    assert any(name.endswith("index.html") for name in original)
    assert original == again


def test_a_shared_tenant_config_builds_a_projection():
    config = {"schemaVersion": 1, "name": "Example", "tagline": "Hi", "sections": [{"name": "News", "slug": "news"}],
              "nav": [{"label": "Home", "href": "/"}], "features": {"videos": True, "conversations": True}}
    assert validate_site_config(config) == []
    projection = from_site_config(config)
    standard_settings_from_mapping(projection)
    assert projection["embeds"] == {"providers": ["youtube"]}
    assert projection["homePage"]["threads"]["enabled"] is True


@pytest.mark.parametrize(
    "setting",
    ["hooks", "css", "chrome", "sizes", "spacing", "imageRatio", "borders", "urls", "basePath", "redirects", "imagePipeline", "cache", "plugins", "citations"],
)
def test_a_setting_outside_the_v1_surface_is_refused_by_name(setting):
    errors = validate_site_config({"schemaVersion": 1, "name": "Example", setting: "x"})
    assert len(errors) == 1 and errors[0].startswith(f"{setting}: refused on the shared tier")


def test_a_custom_css_file_in_a_section_is_refused_by_path():
    errors = validate_site_config({"schemaVersion": 1, "name": "Example", "sections": [{"name": "A", "slug": "a", "stylesheet": "x.css"}]})
    assert errors == ["sections[0].stylesheet: refused on the shared tier, custom CSS is not allowed; brand changes go through the brand pack"]


@pytest.mark.parametrize(
    "config, fragment",
    [
        ({"name": "x"}, "'schemaVersion' is required"),
        ({"schemaVersion": 2, "name": "x"}, "schemaVersion: must be 1"),
        ({"schemaVersion": 1, "name": ""}, "name: must not be empty"),
        ({"schemaVersion": 1, "name": "x", "analyticsId": "UA-1"}, "analyticsId"),
        ({"schemaVersion": 1, "name": "x", "homeTemplate": "magazine"}, "homeTemplate: must be one of"),
        ({"schemaVersion": 1, "name": "x", "nav": [{"label": "a", "href": "javascript:alert(1)"}]}, "nav[0].href"),
        ({"schemaVersion": 1, "name": "x", "features": {"findings": "yes"}}, "features.findings: must be a boolean"),
        ({"schemaVersion": 1, "name": "x", "sections": [{"name": "A", "slug": "a"}, {"name": "B", "slug": "a"}]}, "slug 'a' is used more than once"),
        ({"schemaVersion": 1, "name": "x", "colour": "red"}, "colour: is not a SiteConfig setting"),
    ],
)
def test_invalid_configs_are_refused_with_the_setting_named(config, fragment):
    assert any(fragment in error for error in validate_site_config(config))


def test_a_link_without_an_href_cannot_be_converted():
    with pytest.raises(ConversionError, match=r"nav.links\[0\]"):
        to_site_config({"site": {"name": "X"}, "nav": {"links": [{"label": "Group", "children": [{"label": "a", "href": "/a"}]}]}})
