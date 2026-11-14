from __future__ import annotations

from papyrus_content.markus_renderer.images import ImagePipeline
from papyrus_content.projection.standard.card_images import hrefs_by_source, use_renditions
from papyrus_content.renditions import picture_href

SOURCE = "assets/story/cover.png"
LEGACY = {
    "kind": "legacy",
    "source": SOURCE,
    "renditions": [
        {"format": "webp", "width": 480, "href": "assets/responsive/assets/story/cover-480.webp"},
        {"format": "png", "width": 480, "href": "assets/responsive/assets/story/cover-480.png"},
        {"format": "png", "width": 1024, "href": "assets/responsive/assets/story/cover-1024.png"},
        {"format": "png", "width": 1366, "href": "assets/responsive/assets/story/cover-1366.png"},
    ],
}
PIPELINE = ImagePipeline()


def table() -> dict[str, str]:
    return hrefs_by_source([LEGACY], PIPELINE)


def test_a_legacy_record_shows_the_original_format_at_the_fallback_width():
    assert picture_href(LEGACY, SOURCE, PIPELINE) == "assets/responsive/assets/story/cover-1024.png"


def test_a_gatsby_record_shows_its_fallback_format_at_the_display_width():
    record = {"kind": "gatsby", "fallbackFormat": "jpeg", "displayWidth": 480, "renditions": [
        {"format": "jpeg", "width": 480, "href": "a-480.jpg"}, {"format": "jpeg", "width": 960, "href": "a-960.jpg"}, {"format": "webp", "width": 480, "href": "a-480.webp"}]}
    assert picture_href(record, "a.jpg", PIPELINE) == "a-480.jpg"


def test_a_passthrough_record_shows_its_own_file():
    assert picture_href({"kind": "passthrough", "href": "assets/responsive/a.svg"}, "a.svg", PIPELINE) == "assets/responsive/a.svg"


def test_an_img_at_the_stored_path_points_at_the_rendition():
    markup = f'<img class="c" src="/{SOURCE}" alt="" loading="lazy">'
    assert use_renditions(markup, table, "") == '<img class="c" src="/assets/responsive/assets/story/cover-1024.png" alt="" loading="lazy">'


def test_a_base_path_and_a_bare_address_get_the_site_root_address():
    assert 'src="/articles/assets/responsive/assets/story/cover-1024.png"' in use_renditions(f'<img src="{SOURCE}">', table, "articles/")


def test_an_address_that_climbs_keeps_its_climb():
    assert 'src="../../assets/responsive/assets/story/cover-1024.png"' in use_renditions(f'<img src="../../{SOURCE}">', table, "")


def test_other_tags_web_addresses_unknown_pictures_and_renditions_are_left_alone():
    markup = (
        f'<meta property="og:image" content="/{SOURCE}">'
        '<img src="https://example.com/assets/story/cover.png"><img src="/assets/other.png">'
        '<img src="/assets/responsive/assets/story/cover-480.png">'
    )
    assert use_renditions(markup, table, "") == markup


def test_the_site_store_is_read_only_when_a_page_has_an_img():
    def forbidden():
        raise AssertionError("read the store")

    assert use_renditions("<p>no pictures</p>", forbidden, "") == "<p>no pictures</p>"
