"""Images and media under ``urls.basePath``: where renditions and originals are written, and the URLs pages carry for them."""

from __future__ import annotations

import json
import re

import pytest

from papyrus_content.markus_renderer.images import ImageBuilder, ImagePipeline, ImageRequest
from papyrus_content.projection.standard.config import standard_settings_from_mapping
from papyrus_content.renditions import (
    DirectoryRenditionStore,
    PrefixedRenditionStore,
    RenditionCatalog,
    StoredRenditionImageBuilder,
    base_path_from_static_directory,
    make_renditions,
    meta_key,
    settings_from_mapping,
)
from procedures.newsroom.tests.based_images_support import CHART, CHART_DARK, FOLDER, IMAGE_SETTINGS, LONE, BasedImageSite, pages, settings, tree

EXPECTED = "/articles/assets/responsive/" + FOLDER


@pytest.fixture
def based():
    site = BasedImageSite("/articles")
    yield site
    site.release_function()
    site.cleanup()


@pytest.fixture
def unbased():
    site = BasedImageSite(None)
    yield site
    site.release_function()
    site.cleanup()


def image_urls(html: str) -> list[str]:
    urls: list[str] = []
    for tag in re.findall(r"<(?:img|source)\b[^>]*>", html):
        for value in re.findall(r'\b(?:src|srcset)="([^"]+)"', tag):
            urls.extend(re.findall(r"(\S+)\s+\d+w", value) or [value])
    return urls


# ------------------------------------------------------------------ the store and the builder


def test_a_prefixed_store_puts_gets_and_lists_under_its_prefix(tmp_path):
    inner = DirectoryRenditionStore(tmp_path)
    store = PrefixedRenditionStore(inner, "articles")
    store.put("assets/responsive/a-200.webp", b"x", cache_control="c")
    assert inner.get("articles/assets/responsive/a-200.webp") == b"x"
    assert store.get("assets/responsive/a-200.webp") == b"x"
    assert store.get("assets/responsive/missing.webp") is None
    assert store.keys("assets/responsive/") == ["assets/responsive/a-200.webp"]
    assert store.prefix == "articles/"


def test_an_empty_prefix_is_the_store_itself(tmp_path):
    inner = DirectoryRenditionStore(tmp_path)
    assert PrefixedRenditionStore(inner, "") is inner


def test_the_builder_prefixes_with_the_url_root_when_it_has_one_and_with_the_depth_otherwise(tmp_path):
    settings_ = settings_from_mapping(IMAGE_SETTINGS)
    store = DirectoryRenditionStore(tmp_path)
    from procedures.newsroom.tests.based_images_support import picture

    make_renditions(settings_, store, "a.png", picture((800, 400), 50))
    catalog = RenditionCatalog(store, settings_.pipeline)
    relative = StoredRenditionImageBuilder(settings_.pipeline, catalog).render(ImageRequest(src="a.png"), depth=2)
    rooted = StoredRenditionImageBuilder(settings_.pipeline, catalog, url_root="/articles/").render(ImageRequest(src="a.png"), depth=2)
    assert 'src="../../assets/responsive/a-800.png"' in relative
    assert rooted == relative.replace("../../assets/", "/articles/assets/")


def test_a_missing_description_names_the_key_under_the_base_path(tmp_path):
    pipeline = ImagePipeline(**{"formats": ("webp",), "widths": (200,)})
    catalog = RenditionCatalog(PrefixedRenditionStore(DirectoryRenditionStore(tmp_path), "articles"), pipeline)
    with pytest.raises(Exception, match=re.escape("articles/" + meta_key(pipeline, "a.png"))):
        catalog.record("a.png")


def test_the_base_path_is_read_from_the_static_directory(tmp_path):
    (tmp_path / "projection.json").write_text(json.dumps({"urls": {"basePath": "/articles/"}}), encoding="utf-8")
    assert base_path_from_static_directory(tmp_path) == "articles"
    (tmp_path / "projection.json").write_text("{}", encoding="utf-8")
    assert base_path_from_static_directory(tmp_path) == ""
    assert base_path_from_static_directory(None) == ""
    assert base_path_from_static_directory(tmp_path / "nowhere") == ""


# ------------------------------------------------------------------ the settings


def test_images_and_media_are_accepted_with_a_base_path():
    standard = standard_settings_from_mapping({"site": {"name": "Example"}, "urls": {"basePath": "/articles"}, "images": {}, "media": {"originals": True}})
    assert standard.base_path == "articles"


# ------------------------------------------------------------------ the local command


def test_the_local_command_writes_renditions_and_originals_under_the_base_path(based):
    based.project_locally()
    keys = tree(based.out)
    assert f"articles/assets/responsive/{FOLDER}/chart.meta.json" in keys
    assert f"articles/assets/responsive/{FOLDER}/chart.dark-400.webp" in keys
    assert keys[f"articles/{CHART}"] == based.pictures[CHART]
    assert not [key for key in keys if key.startswith("assets/")]


def test_every_image_url_of_the_page_is_under_the_base_path_and_a_file(based):
    based.project_locally()
    html = (based.out / "articles/hello/index.html").read_text(encoding="utf-8")
    urls = image_urls(html)
    assert len(urls) >= 12
    assert all(url.startswith(EXPECTED[: len("/articles/assets/responsive/")]) for url in urls), urls
    assert [url for url in urls if not (based.out / url.lstrip("/")).is_file()] == []


def test_the_dark_pair_sits_under_the_base_path_with_its_rules(based):
    based.project_locally()
    html = (based.out / "articles/hello/index.html").read_text(encoding="utf-8")
    light = re.search(r'<div class="papyrus-image-light">(.*?)</div>', html, re.S).group(1)
    dark = re.search(r'<div class="papyrus-image-dark">(.*?)</div>', html, re.S).group(1)
    assert all(url.startswith(EXPECTED + "/chart-") for url in image_urls(light))
    assert all(url.startswith(EXPECTED + "/chart.dark-") for url in image_urls(dark))
    assert ".papyrus-image-dark{display:none}" in html and ":root.dark:not([data-theme=light]) .papyrus-image-dark" in html


def test_the_head_carries_absolute_urls_with_the_origin_and_the_base_path(based):
    based.project_locally()
    html = (based.out / "articles/hello/index.html").read_text(encoding="utf-8")
    image = f"https://example.com{EXPECTED}/chart-800.png"
    assert f'<meta property="og:image" content="{image}">' in html
    assert f'<meta name="twitter:image" content="{image}">' in html
    assert f'"image":"{image}"' in html
    assert "example.com/../" not in html


def test_the_markdown_twin_keeps_the_story_paths_as_written(based):
    based.project_locally()
    twin = (based.out / "articles/hello/index.md").read_text(encoding="utf-8")
    assert f'src="{CHART}"' in twin and f'srcDark="{CHART_DARK}"' in twin and f'src="{LONE}"' in twin and f"]({FOLDER}/photo.png)" in twin
    assert "/articles/assets" not in twin


def test_a_second_local_run_is_identical(based):
    based.project_locally()
    first = tree(based.out)
    based.project_locally()
    assert tree(based.out) == first


def test_a_local_run_without_images_settings_writes_no_renditions(tmp_path):
    site = BasedImageSite("/articles")
    try:
        raw = settings("/articles")
        del raw["images"], raw["media"]
        site.write_settings(raw)
        (site.content / "hello.md").write_text("---\ntitle: Hello\n---\n\nNo pictures.\n", encoding="utf-8")
        site.project_locally()
        assert not [key for key in tree(site.out) if "assets" in key.split("/")[:2]]
    finally:
        site.cleanup()


# ------------------------------------------------------------------ the cloud path


def test_the_renditions_function_writes_under_the_base_path(based):
    based.configure_function()
    result = based.upload(f"media/{CHART}")
    assert result["results"][0]["action"] == "rendered"
    keys = tree(based.site_store)
    assert f"articles/assets/responsive/{FOLDER}/chart.meta.json" in keys
    assert keys[f"articles/{CHART}"] == based.pictures[CHART]
    assert [key for key in keys if not key.startswith("articles/")] == []


def test_a_back_fill_skips_what_exists_under_the_base_path(based):
    based.configure_function()
    based.upload_all()
    event = {"bucket": "media", "key": f"media/{CHART}", "skipExisting": True}
    assert based.handler.handler(event, None)["results"][0]["action"] == "skipped-existing"


def test_the_cloud_render_equals_the_local_render(based):
    based.configure_function()
    based.upload_all()
    based.render_from_store()
    assert based.error is None, based.error
    based.project_locally()
    assert pages(based.cloud_out) == pages(based.out)


def test_renditions_at_the_bucket_root_are_not_used_by_a_based_site(based, unbased):
    unbased.configure_function()
    unbased.upload_all()
    unbased.release_function()
    based.site_store = unbased.site_store
    based.render_from_store()
    assert f"articles/assets/responsive/{FOLDER}/" in str(based.error)
    assert "papyrus ops content renditions --source" in str(based.error)


def test_reconcile_keeps_renditions_and_originals(based):
    from papyrus_content.projection.directory_source import DirectoryContentSource
    from papyrus_content.projection.engine import ProjectionContext, reconcile
    from papyrus_content.projection.standard.projector import StandardMarkusProjector
    from papyrus_content.projection.writers import LocalDirectoryWriter

    based.project_locally()
    before = tree(based.out)
    projector = StandardMarkusProjector.from_static_directory(based.static, renditions=DirectoryRenditionStore(based.out), environ={"PAPYRUS_SITE_PUBLIC_URL": ""})
    report = reconcile(ProjectionContext(source=DirectoryContentSource(based.content), projector=projector, writer=LocalDirectoryWriter(based.out), keep_state=False))
    assert not report.orphan_pages
    assert set(before) <= set(tree(based.out))
    assert not projector.owns_page_key(f"articles/{CHART}")
    assert not projector.owns_page_key(f"articles/assets/responsive/{FOLDER}/chart.meta.json")


# ------------------------------------------------------------------ no base path: unchanged


EXPECTED_ROOT = "features_backend/fixtures/based-images/root-expected"


def test_a_site_without_a_base_path_renders_the_recorded_pages(unbased):
    from papyrus_content.env import PAPYRUS_ROOT

    unbased.configure_function()
    unbased.upload_all()
    unbased.render_from_store()
    assert unbased.error is None, unbased.error
    root = PAPYRUS_ROOT / EXPECTED_ROOT
    recorded = {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}
    rendered = pages(unbased.cloud_out)
    assert rendered == recorded
    keys = tree(unbased.site_store)
    assert f"assets/responsive/{FOLDER}/chart.meta.json" in keys and keys[CHART] == unbased.pictures[CHART]


def test_a_site_without_a_base_path_keeps_relative_image_urls(unbased):
    unbased.configure_function()
    unbased.upload_all()
    unbased.render_from_store()
    html = (unbased.cloud_out / "hello/index.html").read_text(encoding="utf-8")
    assert f'src="../assets/responsive/{FOLDER}/chart-800.png"' in html
