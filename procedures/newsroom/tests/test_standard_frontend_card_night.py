"""Story cards show the Night picture when a figure has a Day and Night pair (PPY-7d34fa)."""

from __future__ import annotations

import re
from pathlib import Path

from papyrus_content.projection.standard import components
from papyrus_content.projection.standard.components import card_image
from procedures.newsroom.tests.standard_frontend_content_support import cms_site, item, settings

PAIR = {"image": "/media/fig.png", "imageDark": "/media/fig.dark.png"}
CSS = Path(components.__file__).parent / "assets" / "markus-components.css"
SOCIAL_IMAGE = re.compile(r"<meta[^>]*(?:og|twitter):image[^>]*>")


def projected(*items):
    return cms_site(settings(urls={"sections": {"posts": {"base": "posts"}}}), list(items))


def test_a_pair_renders_day_and_night_pictures_in_theme_spans():
    site = projected(item("a", date="2026-02-01", **PAIR))
    try:
        page = site.text("index.html")
        assert '<span class="markus-card-image-day"><img class="markus-card-image" src="/media/fig.png"' in page
        assert '<span class="markus-card-image-night"><img class="markus-card-image" src="/media/fig.dark.png"' in page
    finally:
        site.cleanup()


def test_a_card_without_a_night_picture_is_unchanged():
    site = projected(item("a", date="2026-02-01", image="/media/fig.png"))
    try:
        page = site.text("index.html")
        assert '<img class="markus-card-image" src="/media/fig.png" alt="" loading="lazy">' in page
        assert "markus-card-image-night" not in page and "markus-card-image-day" not in page
    finally:
        site.cleanup()


def test_a_night_picture_without_a_day_picture_is_ignored():
    site = projected(item("a", date="2026-02-01", imageDark="/media/fig.dark.png"))
    try:
        assert "fig.dark.png" not in site.text("index.html")
    finally:
        site.cleanup()


def test_social_images_and_generated_data_never_use_the_night_picture():
    site = projected(item("a", date="2026-02-01", **PAIR))
    try:
        tree = site.tree
        assert any(key.endswith(".html") for key in tree)
        for key, data in tree.items():
            text = data.decode("utf-8", "ignore")
            if key.endswith(".html"):
                assert "fig.dark.png" not in "".join(SOCIAL_IMAGE.findall(text)), key
            elif key.endswith((".xml", ".json")):
                assert "fig.dark.png" not in text, key
    finally:
        site.cleanup()


def test_the_night_source_is_escaped():
    class Entry:
        image = "/a.png"
        image_dark = '/b".png'

    assert 'src="/b&quot;.png"' in card_image(Entry())


def test_the_stylesheet_follows_system_and_hand_picked_themes():
    css = CSS.read_text(encoding="utf-8")
    assert ".markus-card-image-night { display: none; }" in css
    assert "@media (prefers-color-scheme: dark)" in css
    # The system setting applies unless a theme was picked by hand to Light.
    assert ":root:not([data-theme=light]):not(.light):not(.light-theme) .markus-card-image-night { display: contents; }" in css
    # A hand-picked Dark shows Night even when the system is Light.
    for selector in (":root[data-theme=dark]", ":root.dark", ":root.dark-theme"):
        assert f"{selector} .markus-card-image-night" in css and f"{selector} .markus-card-image-day" in css


BODY = """Intro.

::image{
  src="assets/story/reach-3.png" srcDark="assets/story/reach.dark-3.png"
  layout="full"
  alt="A figure"
}

More.
"""
RENDITION = "/assets/responsive/assets/story/reach-3-1024.png"


def test_a_card_that_shows_a_figure_with_a_pair_gets_its_night_rendition_from_the_body():
    from papyrus_content.projection.stored import night_image_for, projection_metadata

    assert night_image_for(RENDITION, BODY) == "/assets/responsive/assets/story/reach.dark-3-1024.png"
    assert night_image_for("assets/story/reach-3.png", BODY) == "assets/story/reach.dark-3.png"
    stored = projection_metadata(f"title: T\nimage: {RENDITION}\n", BODY)["frontMatter"]
    assert stored["imageDark"] == "/assets/responsive/assets/story/reach.dark-3-1024.png"


def test_no_night_picture_is_invented():
    from papyrus_content.projection.stored import night_image_for, projection_metadata

    assert night_image_for("/assets/responsive/assets/story/other-1024.png", BODY) is None
    assert night_image_for(RENDITION, BODY.replace('srcDark="assets/story/reach.dark-3.png"', "")) is None
    assert night_image_for("/assets/responsive/assets/story/reach-3-x.png", BODY) is None
    assert "imageDark" not in projection_metadata("title: T\n", BODY)["frontMatter"]
    assert projection_metadata("title: T\nimage: /x.png\n", BODY) == projection_metadata("title: T\nimage: /x.png\n")


def test_an_authors_own_night_picture_is_kept():
    from papyrus_content.projection.stored import projection_metadata

    stored = projection_metadata(f"image: {RENDITION}\nimageDark: /mine.png\n", BODY)["frontMatter"]
    assert stored["imageDark"] == "/mine.png"


def test_publishing_stores_the_pair_for_cards():
    import json

    from papyrus_content.publishing import project_item_to_published

    item = {"id": "i1", "slug": "s", "type": "article", "metadata": {"frontMatterYaml": f"image: {RENDITION}\n"}, "bodyMarkus": BODY}
    published, _ = project_item_to_published(item, [], published_at="2026-02-01T00:00:00Z", version_published_at="2026-02-01T00:00:00Z", version_published_by="behave", version_number=1)
    metadata = published["metadata"]
    metadata = json.loads(metadata) if isinstance(metadata, str) else metadata
    assert metadata["projection"]["frontMatter"]["imageDark"].endswith("reach.dark-3-1024.png")
