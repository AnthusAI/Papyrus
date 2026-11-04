"""Images and citations are on for every site unless it turns them off, and save and publish read the same features (PPY-c69e7b)."""

from __future__ import annotations

import dataclasses
import json

import pytest

from papyrus_content.cli_body_features import site_features_from_response
from papyrus_content.markus_renderer.body_features import DEFAULT_FEATURES, BodyFeatures, current_body_features, install_body_features
from papyrus_content.markus_renderer.derive import derive_body
from papyrus_content.projection.projector import MarkusProjectorSettings, MarkusSiteProjector, read_static_files, settings_from_mapping
from papyrus_content.projection.runtime import site_body_features
from papyrus_content.renditions import DEFAULT_IMAGE_SETTINGS, DirectoryRenditionStore, make_renditions, settings_from_static_directory
from procedures.newsroom.tests.based_images_support import CHART, PICTURES, picture

FRONT = "title: Hello\ncitations:\n  smith:\n    type: book\n    title: A Book\n    author: [{family: Smith, given: Ann}]\n    issued: {date-parts: [[2020]]}\n"
PLAIN = "Just words.\n"
IMAGE = f'::image{{src="{CHART}" alt="A chart"}}\n'
CITE = "As shown [@smith].\n\n::citations\n"


@pytest.fixture
def store(tmp_path):
    directory = DirectoryRenditionStore(tmp_path / "site-store")
    make_renditions(DEFAULT_IMAGE_SETTINGS, directory, CHART, picture(PICTURES[CHART], 60))
    return directory


def projector(raw: dict, renditions=None) -> MarkusSiteProjector:
    return MarkusSiteProjector(settings_from_mapping(raw), read_static_files(None, None), renditions=renditions)


def save_verdict(site: MarkusSiteProjector, body: str) -> bool:
    return derive_body(FRONT, body, site.body_features()).ok


def publish_verdict(site: MarkusSiteProjector, body: str) -> bool:
    try:
        site._fragment(f"---\n{FRONT}---\n{body}", 1)
    except Exception:  # noqa: BLE001 - any failure to render is a page that does not go live
        return False
    return True


def test_images_and_citations_are_on_when_nothing_is_declared():
    settings = settings_from_mapping({})
    assert settings.images == DEFAULT_IMAGE_SETTINGS and settings.citations is True
    assert MarkusProjectorSettings().images == DEFAULT_IMAGE_SETTINGS and MarkusProjectorSettings().citations is True


@pytest.mark.parametrize("value", [True, None])
def test_true_and_null_mean_the_defaults(value):
    assert settings_from_mapping({"images": value, "citations": value}).images == DEFAULT_IMAGE_SETTINGS


def test_a_site_turns_each_off_by_itself():
    assert settings_from_mapping({"images": False}).images is None and settings_from_mapping({"images": False}).citations is True
    assert settings_from_mapping({"citations": False}).citations is False and settings_from_mapping({"citations": False}).images is not None


def test_a_declared_object_still_declares_the_pipeline_and_upgrades_plain_images():
    declared = settings_from_mapping({"images": {"widths": [200, 400], "formats": ["webp"]}}).images
    assert declared.pipeline.widths == (200, 400) and declared.pipeline.upgrade_plain_images is True
    assert DEFAULT_IMAGE_SETTINGS.pipeline.upgrade_plain_images is False   # the default leaves a page without ::image as it was


@pytest.mark.parametrize("raw", [{"images": "yes"}, {"images": 3}, {"citations": "no"}])
def test_a_value_that_is_neither_a_switch_nor_an_object_is_refused(raw):
    with pytest.raises(ValueError):
        settings_from_mapping(raw)


def test_the_rendition_function_reads_the_same_default(tmp_path):
    assert settings_from_static_directory(None) == DEFAULT_IMAGE_SETTINGS
    (tmp_path / "projection.json").write_text(json.dumps({"site": {"name": "x"}}), encoding="utf-8")
    assert settings_from_static_directory(tmp_path) == DEFAULT_IMAGE_SETTINGS
    (tmp_path / "projection.json").write_text(json.dumps({"images": False}), encoding="utf-8")
    assert settings_from_static_directory(tmp_path) is None


def test_a_default_site_renders_an_image_and_a_citation(store):
    site = projector({}, store)
    html = site._fragment(f"---\n{FRONT}---\n{IMAGE}\n{CITE}", 1)
    assert "<picture" in html and "assets/responsive/" in html and "A Book" in html


def test_a_page_without_images_or_citations_needs_no_media_store_and_renders_as_without_the_features():
    default, off = projector({}), projector({"images": False, "citations": False})
    text = "---\ntitle: Hello\n---\n\nSome **words** and ![a plain picture](https://example.com/a.png).\n"
    assert default._fragment(text, 1) == off._fragment(text, 1)


def test_a_site_with_no_media_store_refuses_an_image_at_save_and_at_publish():
    site = projector({})
    save = derive_body(FRONT, IMAGE, site.body_features())
    assert not save.ok and save.errors[0].code == "images-unavailable" and "media store" in save.errors[0].message
    assert not publish_verdict(site, IMAGE)
    assert save_verdict(site, PLAIN) and publish_verdict(site, PLAIN)


def test_a_site_that_turned_images_off_gets_the_error_at_save():
    site = projector({"images": False})
    save = derive_body(FRONT, IMAGE, site.body_features())
    assert not save.ok and save.errors[0].code == "markus-validation"
    assert "Unknown directive 'image'" in save.errors[0].message and "turned images off" in save.errors[0].message


def test_a_site_that_turned_citations_off_gets_the_error_at_save():
    save = derive_body(FRONT, CITE, projector({"citations": False}).body_features())
    assert not save.ok and "turned citations off" in save.errors[0].message


@pytest.mark.parametrize("raw", [{}, {"images": False}, {"citations": False}, {"images": False, "citations": False}, {"images": {"widths": [200]}}])
@pytest.mark.parametrize("with_store", [True, False])
@pytest.mark.parametrize("body", [PLAIN, IMAGE, CITE, IMAGE + "\n" + CITE, "::nope\n::\n", "Text [@missing].\n"])
def test_save_and_publish_give_the_same_verdict(raw, with_store, body, store):
    site = projector(raw, store if with_store else None)
    assert save_verdict(site, body) == publish_verdict(site, body)


def test_the_save_path_reads_the_installed_features():
    try:
        install_body_features(BodyFeatures(images=False))
        assert not derive_body(FRONT, IMAGE).ok and derive_body(FRONT, PLAIN).ok
        install_body_features(lambda: BodyFeatures(images=True, images_unavailable="no store"))
        assert derive_body(FRONT, IMAGE).errors[0].code == "images-unavailable"
    finally:
        install_body_features(None)
    assert current_body_features() == DEFAULT_FEATURES and derive_body(FRONT, IMAGE).ok


def test_a_site_that_does_not_project_validates_with_the_defaults():
    assert site_body_features({}) == DEFAULT_FEATURES


def test_the_function_answers_with_its_features_and_the_cli_reads_them():
    features = BodyFeatures(images=False, citations=True, images_unavailable=None)
    data = {"deriveMarkus": json.dumps({"ok": True, "features": features.to_dict()})}
    assert site_features_from_response(data) == features
    assert site_features_from_response({"deriveMarkus": json.dumps({"ok": True})}) == DEFAULT_FEATURES   # an older site does not say
    assert dataclasses.replace(features, images=True) != features


def test_only_the_post_deploy_render_goes_on_past_a_story_it_cannot_render(tmp_path):
    from papyrus_content.projection.deploy_render import deploy_render
    from papyrus_content.projection.directory_source import DirectoryContentSource
    from papyrus_content.projection.engine import ProjectionContext, project_all
    from papyrus_content.projection.standard.projector import StandardMarkusProjector
    from papyrus_content.projection.writers import LocalDirectoryWriter
    from procedures.newsroom.tests.standard_frontend_support import static_directory

    content = tmp_path / "content"
    content.mkdir()
    (content / "good.md").write_text("---\ntitle: Good\n---\n\nWords.\n", encoding="utf-8")
    (content / "bad.md").write_text(f"---\ntitle: Bad\n---\n\n{IMAGE}", encoding="utf-8")
    static = static_directory(tmp_path, {"site": {"name": "x"}, "images": False})

    def context() -> ProjectionContext:
        return ProjectionContext(
            source=DirectoryContentSource(content),
            projector=StandardMarkusProjector.from_static_directory(static, environ={"PAPYRUS_SITE_PUBLIC_URL": ""}),
            writer=LocalDirectoryWriter(tmp_path / "out"),
            keep_state=False,
        )

    with pytest.raises(Exception, match="Unknown directive 'image'"):
        project_all(context())                       # a command that renders everything still stops, naming the problem
    report = deploy_render(context())                # the deploy reports it and renders the rest
    assert report.ok and [failed["slug"] for failed in report.render.unrenderable] == ["bad"]
    assert any(path.name.startswith("good") for path in (tmp_path / "out").rglob("*.html")) and report.drift_count >= 1


def test_revalidation_on_the_signed_in_lane_uses_the_site_it_is_signed_in_to(monkeypatch):
    from papyrus_content import env, papyrus_config

    for name in ("PAPYRUS_BASE_URL", "PAPYRUS_PUBLIC_SITE_BASE_URL", "PAPYRUS_CONFIG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(papyrus_config, "load_papyrus_config", lambda *a, **k: None)
    monkeypatch.setattr(env, "site_host_in_use", lambda: "machines.example.com")
    assert papyrus_config.resolve_reader_revalidation_base_url() == "https://machines.example.com"
    monkeypatch.setattr(env, "site_host_in_use", lambda: None)
    with pytest.raises(ValueError, match="PAPYRUS_PUBLIC_SITE_BASE_URL"):
        papyrus_config.resolve_reader_revalidation_base_url()


def test_a_projecting_site_is_not_revalidated_as_a_pretext_reader(monkeypatch):
    from types import SimpleNamespace

    from papyrus_content import publish_commands

    class Client:
        def get_record(self, *args):
            return {"slug": "hello"}

    calls = []
    monkeypatch.setattr(publish_commands, "projection_enabled", lambda: False)
    monkeypatch.setattr(publish_commands, "projection_unknown", lambda: True)
    monkeypatch.setattr(publish_commands, "trigger_projection_as_user", lambda client, task: {"ok": True, "projectsPages": True})
    monkeypatch.setattr(publish_commands, "trigger_pretext_revalidation", lambda *a, **k: calls.append(a))
    monkeypatch.setattr("papyrus_content.user_auth_mode.user_auth_requested", lambda: True)
    result = SimpleNamespace(item_id="i", published_item_id="p", changed=True)
    triggers = publish_commands.run_site_triggers(Client(), {}, result)
    assert "revalidated" not in triggers and calls == []
    monkeypatch.setattr(publish_commands, "trigger_projection_as_user", lambda client, task: {"ok": True})
    publish_commands.run_site_triggers(Client(), {}, result)
    assert calls == [(["hello"], None)]   # a site that does not project is still revalidated


def broken_beside_good_fixture(tmp_path):
    """A site with a section, its introduction, two good Stories and a broken one; a first render holds the good versions of all four."""
    from papyrus_content.projection.directory_source import DirectoryContentSource
    from papyrus_content.projection.engine import ProjectionContext, project_all
    from papyrus_content.projection.standard.projector import StandardMarkusProjector
    from papyrus_content.projection.writers import LocalDirectoryWriter
    from procedures.newsroom.tests.standard_frontend_support import static_directory

    content = tmp_path / "content" / "notes"
    content.mkdir(parents=True)
    stories = {"index": "Welcome to the notes.", "one": "First good Story.", "two": "Second good Story.", "broken": "Fine for now."}
    for slug, body in stories.items():
        (content / f"{slug}.md").write_text(f"---\ntitle: {slug.title()}\ndate: '2026-10-01'\n---\n\n{body}\n", encoding="utf-8")
    settings = {
        "site": {"name": "Notes", "productionUrl": "https://example.com"},
        "urls": {"style": "directory", "sections": {"notes": {"base": "notes"}}},
        "images": False,
    }
    static = static_directory(tmp_path, settings)
    out = tmp_path / "out"

    def context() -> ProjectionContext:
        return ProjectionContext(
            source=DirectoryContentSource(tmp_path / "content"),
            projector=StandardMarkusProjector.from_static_directory(static, environ={"PAPYRUS_SITE_PUBLIC_URL": ""}),
            writer=LocalDirectoryWriter(out), keep_state=False,
        )

    assert project_all(context()).ok
    before = {path.relative_to(out).as_posix(): path.read_bytes() for path in out.rglob("*") if path.is_file()}
    for slug in ("index", "broken"):
        (content / f"{slug}.md").write_text(f"---\ntitle: {slug.title()}\ndate: '2026-10-01'\n---\n\n{IMAGE}", encoding="utf-8")
    return context, out, before


def test_a_broken_story_beside_good_ones_fails_no_step_of_the_deploy_render(tmp_path):
    from papyrus_content.projection.deploy_render import deploy_render

    context, out, before = broken_beside_good_fixture(tmp_path)
    report = deploy_render(context())
    assert report.ok, report.render.errors
    assert sorted(failed["slug"] for failed in report.render.unrenderable) == ["broken", "index"]   # the item page, and the introduction of the listing
    written = {path.relative_to(out).as_posix(): path.read_bytes() for path in out.rglob("*") if path.is_file()}
    # The pages of the broken Story stay as they were.
    kept = [key for key in before if key.startswith("notes/broken/")]
    assert kept and all(written[key] == before[key] for key in kept)
    # The listing, the feeds, the sitemap and llms.txt are written, name the good Stories, and the listing has lost only the introduction.
    listing = written["notes/index.html"].decode()
    assert "One" in listing and "Two" in listing and "Welcome to the notes" not in listing
    for key in ("feed.xml", "atom.xml", "sitemap.xml", "llms.txt", "llms-full.txt"):
        assert key in written, key
    assert b"First good Story" in written["llms-full.txt"] and b"notes/one" in written["feed.xml"]
    assert written["notes/one/index.html"] and written["notes/two/index.html"]


def test_a_command_that_renders_everything_still_stops_on_the_same_broken_listing_introduction(tmp_path):
    from papyrus_content.projection.engine import project_all

    context, _out, _before = broken_beside_good_fixture(tmp_path)
    with pytest.raises(Exception, match="Unknown directive 'image'"):
        project_all(context())
