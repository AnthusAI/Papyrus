"""Home page groups (PPY-f24696): listings that filter by type and section, make one group per section, fall back to another type, and never repeat a Story on a page;
References that filter by picture and carry an explainer card; and the counts a layout needs to fill its rows."""

from __future__ import annotations

import re
from datetime import date
from types import SimpleNamespace

import pytest

from papyrus_content.home_page.settings import home_page_settings_from_mapping
from papyrus_content.projection.standard import home_page_blocks, includes
from papyrus_content.projection.standard.config import standard_settings_from_mapping
from papyrus_content.projection.standard.page_ledger import PageLedger
from procedures.newsroom.tests.standard_frontend_content_support import DirectorySite, cms_site, item, settings

BAND = '::band{size="bare"}\n'
SECTIONS = {"sections": {name: {"listingPage": False} for name in ("privacy", "law", "science")}}


def story_items():
    return [
        item("a1", section="privacy", date="2026-02-05", type="article"),
        item("p1", section="privacy", date="2026-02-04", type="post"),
        item("p2", section="privacy", date="2026-02-03", type="post"),
        item("p3", section="law", date="2026-02-06", type="post"),
        item("p4", section="law", date="2026-02-02", type="post"),
        item("a2", section="science", date="2026-02-01", type="article"),
        item("p5", section="science", date="2026-02-07", type="post"),
    ]


def page(name: str) -> dict:
    return {"id": name, "path": name, "title": name.title(), "source": f"{name}.md"}


def project(lines: dict[str, str]):
    files = {f"{name}.md": f"---\ntitle: {name}\n---\n{BAND}{line}\n" for name, line in lines.items()}
    return cms_site(settings(urls=SECTIONS, storyTypes={"default": "post", "types": ["post", "article"]}, listings={"types": ["article", "post"]}, pages=[page(name) for name in files_names(lines)]), story_items(), files)


def files_names(lines):
    return [name for name in lines]


def slugs(markup: str) -> list[str]:
    return re.findall(r'href="/(?:privacy|law|science)/([^/".]+)\.html"', markup)


def groups_of(markup: str) -> list[tuple[str, int, list[str]]]:
    found = re.findall(r'<section class="[^"]*papyrus-group[^"]*" data-section="([^"]+)" data-label="[^"]*" data-index="\d+" data-count="(\d+)">(.*?)</section>', markup, re.S)
    return [(name, int(count), slugs(body)) for name, count, body in found]


GROUP = '::include{kind="listing" type="article" fallback="post" sections="3" per="2,1" unique="true"}'


@pytest.fixture(scope="module")
def site():
    built = project({
        "groups": GROUP,
        "after": f'{GROUP}\n\n::include{{kind="listing" type="post" count="10" unique="true" layout="bare"}}',
        "repeat": f'{GROUP}\n\n::include{{kind="listing" type="post" count="10" layout="bare"}}',
        "short": '::include{kind="listing" type="article" section="law" fallback="post" layout="bare"}',
        "own": '::include{kind="listing" type="article" section="privacy" fallback="post" layout="bare"}',
        "section": '::include{kind="listing" section="science" layout="bare"}',
        "counted": '::include{kind="listing" type="post" count="3" tag="ul" class="rail" counts="true" layout="bare"}',
        "grid": '::include{kind="listing" type="post" count="2" counts="true"}',
        "plain": '::include{kind="listing" type="post" count="2" tag="ul" layout="bare"}',
        "heading": '::include{kind="listing" type="post" sections="2" per="1" heading="true" more="More in {section}"}',
        "twin": f"{GROUP}",
    })
    yield built
    built.cleanup()


def test_one_group_per_section_has_the_best_of_each_with_a_count_and_a_lead(site):
    found = groups_of(site.text("groups/index.html"))
    # Law has no article, so it shows its posts; the groups are ordered by their best Story: law (p3), privacy (a1), science (a2). Per is 2, then 1.
    assert found == [("law", 2, ["p3", "p4"]), ("privacy", 1, ["a1"]), ("science", 1, ["a2"])]
    assert all("papyrus-has-lead" in markup for markup in re.findall(r'<section class="([^"]*)" data-section', site.text("groups/index.html")))


def test_a_later_unique_listing_does_not_repeat_what_a_group_placed(site):
    shown = groups_of(site.text("after/index.html"))
    used = {slug for _name, _count, found in shown for slug in found}
    rest = slugs(site.text("after/index.html").split("</section>")[-1])
    assert used == {"p3", "p4", "a1", "a2"}
    assert rest == ["p5", "p1", "p2"]


def test_a_listing_that_is_not_unique_repeats_as_before(site):
    rest = slugs(site.text("repeat/index.html").split("</section>")[-1])
    assert rest == ["p5", "p3", "p1", "p2", "p4"]


def test_fallback_shows_posts_only_for_a_section_with_no_articles(site):
    assert slugs(site.text("short/index.html")) == ["p3", "p4"]
    assert slugs(site.text("own/index.html")) == ["a1"]


def test_section_is_a_short_form_of_sections(site):
    assert slugs(site.text("section/index.html")) == ["p5", "a2"]


def test_a_counted_wrapper_carries_the_count_and_the_lead_class(site):
    assert re.search(r'<ul class="rail papyrus-has-lead" data-count="3">', site.text("counted/index.html"))
    assert re.search(r'<div class="markus-card-grid papyrus-has-lead" data-count="2">', site.text("grid/index.html"))


def test_a_list_without_counts_is_marked_up_exactly_as_before(site):
    markup = site.text("plain/index.html")
    assert "<ul>" in markup and "data-count" not in markup.split("<main")[1] and "papyrus-has-lead" not in markup.split("<main")[1]


def test_a_group_header_names_the_section(site):
    assert '<h2 class="papyrus-group-title">' in site.text("heading/index.html")


def test_the_twin_lists_the_same_stories_as_the_page(site):
    assert slugs(site.text("twin/index.html")) == ["p3", "p4", "a1", "a2"]


# ------------------------------------------------------------------ the cheap, pure parts

def entry(slug, topic, kind, day, lineage=None):
    return SimpleNamespace(
        fingerprint=lambda full=False: [slug],
        summary=SimpleNamespace(lineage_id=lineage or slug), item_id=slug, slug=slug, topic=topic, type=kind, tags=(), draft=False, listed=True, date=day, updated=day,
    )


STANDARD = standard_settings_from_mapping({"site": {"name": "Example"}})


def test_stars_decide_the_order_inside_the_window_and_the_groups_follow_the_best_story():
    entries = [entry("a", "x", "post", "2026-02-05"), entry("b", "x", "post", "2026-02-04"), entry("c", "y", "post", "2026-02-03")]
    stars = {"c": 5}   # the older Story in section y has the stars: its section comes first
    groups = includes.listing_groups({"kind": "listing", "sections": "2", "per": "2", "bucket": "week"}, entries, STANDARD, stars, date(2026, 2, 6))
    assert [group.topic for group in groups] == ["y", "x"]
    assert [[e.slug for e in group.entries] for group in groups] == [["c"], ["a", "b"]]


def test_a_section_with_nothing_left_is_skipped_and_empty_selections_are_empty():
    entries = [entry("a", "x", "post", "2026-02-05")]
    ledger = PageLedger()
    attributes = {"kind": "listing", "sections": "3", "per": "1", "unique": "true"}
    assert [group.topic for group in includes.listing_groups(attributes, entries, STANDARD, None, None, ledger)] == ["x"]
    assert includes.listing_groups(attributes, entries, STANDARD, None, None, ledger) == []
    assert includes.listing_entries({"kind": "listing", "type": "article", "fallback": "guide"}, entries, STANDARD) == []


def test_the_digest_of_a_page_follows_the_ledger():
    entries = [entry("a", "x", "post", "2026-02-05"), entry("b", "x", "post", "2026-02-04")]
    one = {"kind": "listing", "count": "1", "unique": "true"}
    inputs = includes.include_inputs([one, one], entries, STANDARD)
    assert [len(found) for _attributes, found in inputs] == [1, 1] and inputs[0][1] != inputs[1][1]


@pytest.mark.parametrize(
    "attributes, message",
    [
        ({"sections": "2", "count": "3"}, "takes per"),
        ({"sections": "2", "section": "x"}, "does not take section|not both"),
        ({"per": "2"}, "go with sections"),
        ({"heading": "true"}, "go with sections"),
        ({"fallback": "post"}, "fallback goes with type"),
        ({"type": "article", "types": "post"}, "type or types"),
        ({"type": "article", "unique": "yes"}, "unique must be"),
        ({"sections": "2", "per": "0"}, "per must be"),
        ({"sections": "0"}, "at least 1"),
    ],
)
def test_bad_group_options_are_refused(attributes, message):
    with pytest.raises(ValueError, match=message):
        includes.check({"kind": "listing", **attributes}, STANDARD, "page.md")


# ------------------------------------------------------------------ References

HOME = home_page_settings_from_mapping({})
AS_OF = date(2026, 10, 29)


def record(key, status="accepted", **fields):
    return {"key": key, "status": status, "title": f"Title {key}", "url": f"https://example.org/{key}", "host": "example.org", "arrivedAt": "2026-10-28T00:00:00Z", **fields}


def snapshot(*records):
    return {"references": list(records)}


def drawn(attributes, document):
    return home_page_blocks.render({"kind": "references", **attributes}, document, PageLedger(), HOME, as_of=AS_OF)


def keys(markup):
    return re.findall(r'href="https://example.org/([^"]+)"', markup)


def test_image_none_keeps_text_only_references_and_any_keeps_pictured_ones():
    document = snapshot(record("pic", image="/a.png", confidence=0.9), record("text", confidence=0.8), record("pic2", image="https://x.test/b.png", confidence=0.7))
    assert keys(drawn({"select": "confident", "image": "none"}, document)) == ["text"]
    assert keys(drawn({"select": "confident", "image": "any"}, document)) == ["pic", "pic2"]
    assert keys(drawn({"select": "confident"}, document)) == ["pic", "text", "pic2"]


def test_videos_come_in_quality_order_stars_then_prediction():
    document = snapshot(
        record("low", medium="video", confidence=0.4, rank=4), record("starred", medium="video", confidence=0.1, rank=1), record("sure", medium="video", confidence=0.95, rank=2),
        record("paper", confidence=0.99, rank=3),
    )
    assert keys(drawn({"select": "confident", "medium": "video"}, document)) == ["starred", "sure", "low"]


def test_just_found_is_in_quality_order_not_arrival_order():
    document = snapshot(
        record("new", "recommended", confidence=0.5, arrivedAt="2026-10-28T09:00:00Z"), record("best", "recommended", confidence=0.9, arrivedAt="2026-10-01T09:00:00Z"),
        record("unscored", "recommended", arrivedAt="2026-10-28T10:00:00Z"),
    )
    assert keys(drawn({"select": "recommended"}, document)) == ["best", "new", "unscored"]


def test_the_explainer_is_the_first_card_in_the_grid_and_is_not_counted():
    document = snapshot(record("a", confidence=0.9), record("b", confidence=0.8), record("c", confidence=0.7))
    markup = drawn({"select": "confident", "count": "2", "counts": "true", "explainer": "How It Works", "explainerKicker": "About <this> grid", "explainerBody": "Monitors & Cyclotrons."}, document)
    grid = markup.split('<ul class="home-page-grid')[1]
    assert grid.index('class="home-page-explainer"') < grid.index("home-page-tile")
    assert "<h3 class=\"home-page-title\">How It Works</h3>" in markup and "About &lt;this&gt; grid" in markup and "Monitors &amp; Cyclotrons." in markup
    assert keys(markup) == ["a", "b"]
    assert markup.count('data-count="2"') == 2 and "home-page-has-lead" in markup


def test_an_empty_selection_draws_no_explainer():
    assert drawn({"select": "confident", "explainer": "How It Works"}, snapshot()) == ""
    assert drawn({"select": "confident", "explainer": "How It Works", "empty": "None."}, snapshot()) == '<p class="home-page-empty">None.</p>'


def test_a_references_include_without_the_new_options_is_unchanged():
    markup = drawn({"select": "confident"}, snapshot(record("a")))
    assert "data-count" not in markup and "explainer" not in markup and "has-lead" not in markup


@pytest.mark.parametrize(
    "attributes, message",
    [
        ({"image": "some"}, "image must be one of"),
        ({"counts": "yes"}, "counts must be"),
        ({"explainerBody": "x"}, "go with explainer"),
        ({"paged": "true", "explainer": "x"}, "cannot be paged"),
    ],
)
def test_bad_reference_options_are_refused(attributes, message):
    with pytest.raises(ValueError, match=message):
        home_page_blocks.check({"kind": "references", "select": "recent", **attributes}, "page.md")


def test_a_directory_site_refuses_a_group_include_with_a_bad_option():
    site = DirectorySite(settings(pages=[page("p")]), [item("x", section="posts")], {"p.md": f'{BAND}::include{{kind="listing" sections="2" count="1"}}\n'})
    try:
        with pytest.raises(ValueError, match="takes per"):
            site.project_all()
    finally:
        site.cleanup()
