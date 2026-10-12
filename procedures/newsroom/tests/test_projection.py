from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from papyrus_content import cli
from papyrus_content.markus_renderer import CitationRendering, build_markus_site
from papyrus_content.markus_renderer import build as markus_build
from papyrus_content.markus_renderer.content_markup import prepare_page
from papyrus_content.markus_renderer.convert import convert_fragment, convert_text_in_process
from papyrus_content.markus_renderer.shell import SiteChrome
from papyrus_content.projection.projector import (
    MarkusSiteProjector,
    normalized_redirect_source,
    settings_from_mapping,
    static_version,
)
from papyrus_content.projection.runtime import context_from_environment, projection_configured, public_item_url
from papyrus_content.projection.stored import parse_front_matter, projection_metadata
from papyrus_content.projection.writers import (
    KeyValueStoreRedirects,
    cache_control_for,
    content_type_for,
    invalidation_paths_for,
)
from papyrus_content.publishing import ItemFields, publish_item, save_item
from procedures.newsroom.tests.fake_client import FakeAuthoringClient
from procedures.newsroom.tests.projection_fixtures import (
    FIXTURE_ROOT,
    FIXTURE_SECTIONS,
    copy_fixture_content,
    full_build,
    markdown_files,
    publish_content_tree,
    static_directory_for,
    tree_digests,
)

PRE_REFACTOR_DIGESTS = json.loads((FIXTURE_ROOT / "pre-refactor-build-digests.json").read_text(encoding="utf-8"))


class StoredProjectionMetadataTests(unittest.TestCase):
    def test_front_matter_is_parsed_to_json_safe_values(self) -> None:
        parsed = parse_front_matter("title: Hello\ndate: 2026-09-06\ntags:\n  - a\n  - b\n")
        self.assertEqual(parsed, {"title": "Hello", "date": date(2026, 9, 6).isoformat(), "tags": ["a", "b"]})
        json.dumps(parsed)

    def test_page_title_follows_the_build_title_rule(self) -> None:
        self.assertEqual(projection_metadata('title: "Quoted: title"\n')["pageTitle"], "Quoted: title")
        self.assertIsNone(projection_metadata("deck: only a deck\n")["pageTitle"])
        self.assertIsNone(projection_metadata(None)["pageTitle"])

    def test_publishing_stores_the_projection_metadata_on_the_published_item(self) -> None:
        client = FakeAuthoringClient()
        fields = ItemFields("article", "hello", "articles", "title: Hello\nauthors:\n  - Ada\n", "Body.\n", [], id="item-articles-hello")
        save_item(client, fields, actor="test")
        publish_item(client, "item-articles-hello", actor="test")
        published = client.get_record("PublishedItem", "published-item-articles-hello")
        stored = json.loads(published["metadata"])["projection"]
        self.assertEqual(stored, {"frontMatter": {"title": "Hello", "authors": ["Ada"]}, "pageTitle": "Hello"})


class WriterTests(unittest.TestCase):
    def test_invalidation_covers_directory_forms_of_index_pages(self) -> None:
        self.assertEqual(
            invalidation_paths_for(["index.html", "articles/a/index.html", "articles/b.html"]),
            ["/index.html", "/", "/articles/a/index.html", "/articles/a/", "/articles/b.html"],
        )

    def test_many_paths_stay_exact_paths_and_never_become_a_wildcard(self) -> None:
        paths = invalidation_paths_for([f"p/{number}.html" for number in range(1200)])
        self.assertEqual(len(paths), 1200)
        self.assertFalse(any("*" in path for path in paths))

    def test_content_types_and_cache_control(self) -> None:
        self.assertEqual(content_type_for("a/b.html"), "text/html; charset=utf-8")
        self.assertEqual(content_type_for("css/site.css"), "text/css; charset=utf-8")
        self.assertEqual(content_type_for("assets/x.json"), "application/json")
        self.assertEqual(content_type_for("assets/x.svg"), "image/svg+xml")
        self.assertEqual(cache_control_for("a.html"), "public, max-age=0, s-maxage=300, stale-while-revalidate=60")
        self.assertEqual(cache_control_for("a.html", 60), "public, max-age=0, s-maxage=60, stale-while-revalidate=60")

    def test_only_renditions_and_content_hashed_files_are_immutable(self) -> None:
        immutable = "public, max-age=31536000, immutable"
        self.assertEqual(cache_control_for("assets/responsive/cover/photo-640.avif"), immutable)
        self.assertEqual(cache_control_for("_next/static/chunks/app.js"), immutable)
        self.assertEqual(cache_control_for("css/site.3fa9c01b.css"), immutable)
        for mutable in ("css/site.css", "sitemap-0.xml", "robots.txt", "feed.json", "assets/responsive/cover/photo.meta.json"):
            self.assertIn("s-maxage=300", cache_control_for(mutable), mutable)

    def test_redirect_sources_always_start_with_a_slash(self) -> None:
        self.assertEqual(normalized_redirect_source("old/page"), "/old/page")
        self.assertEqual(normalized_redirect_source("/old/page"), "/old/page")

    def test_key_value_store_updates_in_batches_with_a_fresh_etag(self) -> None:
        class FakeKeyValueStore:
            def __init__(self) -> None:
                self.updates: list[dict] = []

            def describe_key_value_store(self, **_arguments) -> dict:
                return {"ETag": f"etag-{len(self.updates)}"}

            def update_keys(self, **arguments) -> None:
                self.updates.append(arguments)

        client = FakeKeyValueStore()
        store = KeyValueStoreRedirects("arn:aws:cloudfront::1:key-value-store/x", client)
        store.put_all({f"/old/{number}": f"/new/{number}" for number in range(60)})
        self.assertEqual([len(update["Puts"]) for update in client.updates], [50, 10])
        self.assertEqual([update["IfMatch"] for update in client.updates], ["etag-0", "etag-1"])
        store.delete_all(["/old/1"])
        self.assertEqual(client.updates[-1]["Deletes"], [{"Key": "/old/1"}])


class ProjectorSettingsTests(unittest.TestCase):
    def test_unknown_settings_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            settings_from_mapping({"themes": "x"})
        with self.assertRaises(ValueError):
            settings_from_mapping({"chrome": {"site_title": "x"}})

    def test_chrome_settings_build_a_site_chrome(self) -> None:
        settings = settings_from_mapping(
            {"theme": None, "sections": ["notes"], "citations": True, "chrome": {"site_name": "Fixture Co", "scripts": ["assets/site.js"]}}
        )
        self.assertIsNone(settings.theme)
        self.assertEqual(settings.sections, ("notes",))
        self.assertEqual(settings.chrome, SiteChrome(site_name="Fixture Co", scripts=("assets/site.js",)))

    def test_projector_reads_settings_and_static_files_from_a_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            content_root = copy_fixture_content(work)
            static_directory = static_directory_for(content_root, work)
            (static_directory / "projection.json").write_text(json.dumps({"sections": ["notes"], "citations": True}), encoding="utf-8")
            projector = MarkusSiteProjector.from_static_directory(static_directory)
            self.assertEqual(sorted(projector.static_files()), ["assets/data/x.json", "assets/site.js", "css/markus-vendor.css", "css/site-theme.css"])
            self.assertEqual(len(projector.version), 12)

    def test_static_version_equals_the_full_build_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            content_root = copy_fixture_content(work)
            full_build(content_root, work / "built")
            projector = MarkusSiteProjector.from_static_directory(static_directory_for(content_root, work))
            self.assertEqual(static_version(projector.static_files()), markus_build._css_version(work / "built" / "css", work / "built" / "assets"))


class InProcessConversionTests(unittest.TestCase):
    def test_in_process_conversion_matches_the_cli_for_every_fixture_page(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            for theme in (None, "hackerman"):
                for path in markdown_files(FIXTURE_ROOT / "content"):
                    with self.subTest(page=path.name, theme=theme):
                        lowered = prepare_page(path.read_text(encoding="utf-8"), images=None, citations=CitationRendering()).markdown
                        staged = Path(temporary) / path.name
                        staged.write_text(lowered, encoding="utf-8")
                        self.assertEqual(convert_text_in_process(lowered, theme=theme), convert_fragment(staged, theme=theme))


class FullBuildIsUnchangedTests(unittest.TestCase):
    def build_digests(self, variant: str) -> dict[str, str]:
        site_css = FIXTURE_ROOT / "css" / "site-theme.css"
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            out = work / "out"
            content = copy_fixture_content(work)
            if variant == "fixture-default-citations":
                build_markus_site(content_dir=content, out_dir=out, site_css=site_css, citations=CitationRendering())
            elif variant == "fixture-notes-section-no-theme":
                build_markus_site(content_dir=content, out_dir=out, site_css=site_css, sections=FIXTURE_SECTIONS, citations=CitationRendering(), theme=None)
            elif variant == "fixture-no-index-md":
                (content / "index.md").unlink()
                build_markus_site(content_dir=content, out_dir=out, site_css=site_css, sections=FIXTURE_SECTIONS, citations=CitationRendering())
            elif variant == "custom-chrome-no-vendor-css":
                build_markus_site(
                    content_dir=content,
                    out_dir=out,
                    site_css=site_css,
                    chrome=SiteChrome(site_name="Fixture Co", tagline="a tagline"),
                    vendor_css=False,
                    sections=FIXTURE_SECTIONS,
                    citations=CitationRendering(),
                )
            else:
                repository = FIXTURE_ROOT.parents[2]
                build_markus_site(content_dir=repository / "web" / "content", out_dir=out)
            return tree_digests(out)

    def test_full_build_output_is_byte_identical_to_the_output_before_the_projection_refactor(self) -> None:
        for variant, expected in PRE_REFACTOR_DIGESTS.items():
            with self.subTest(variant=variant):
                self.assertEqual(self.build_digests(variant), expected)


class ProjectCommandTests(unittest.TestCase):
    def test_project_all_to_a_directory_equals_the_full_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            content_root = copy_fixture_content(work)
            static_directory = static_directory_for(content_root, work)
            (static_directory / "projection.json").write_text(json.dumps({"sections": ["notes"], "citations": True}), encoding="utf-8")
            client = FakeAuthoringClient()
            publish_content_tree(client, content_root)
            with mock.patch("papyrus_content.project_commands.create_authoring_client", return_value=(client, {})):
                cli.dispatch("content", "project", ["--all", "--out", str(work / "projected"), "--static-dir", str(static_directory)])
            full_build(content_root, work / "expected")
            self.assertEqual(tree_digests(work / "projected"), tree_digests(work / "expected"))

    def test_exactly_one_mode_is_required(self) -> None:
        with self.assertRaises(ValueError):
            cli.dispatch("content", "project", [])
        with self.assertRaises(ValueError):
            cli.dispatch("content", "project", ["--all", "--listings"])


class RuntimeConfigurationTests(unittest.TestCase):
    def test_publication_is_configured_only_for_s3_projection(self) -> None:
        self.assertTrue(projection_configured({"PAPYRUS_PUBLICATION_KIND": "s3-projection"}))
        self.assertFalse(projection_configured({}))
        self.assertFalse(projection_configured({"PAPYRUS_PUBLICATION_KIND": "amplify-static"}))

    def test_a_context_needs_a_bucket(self) -> None:
        with self.assertRaises(ValueError):
            context_from_environment(FakeAuthoringClient(), {"PAPYRUS_PUBLICATION_KIND": "s3-projection"})

    def test_public_item_url(self) -> None:
        environment = {"PAPYRUS_SITE_PUBLIC_URL": "https://site.example/"}
        self.assertEqual(public_item_url(environment, ["articles/a.html"]), "https://site.example/articles/a.html")
        self.assertEqual(public_item_url(environment, ["index.html"]), "https://site.example/")
        self.assertIsNone(public_item_url({}, ["a.html"]))
        self.assertIsNone(public_item_url(environment, []))


if __name__ == "__main__":
    unittest.main()
