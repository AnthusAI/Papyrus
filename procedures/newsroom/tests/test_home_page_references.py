"""The ``::include{kind="references"}`` component: ledger, source, selection, de-duplication, cards, twin line and reserved paths."""

from __future__ import annotations

import json

import pytest

from papyrus_content.home_page.settings import HomePageSettings, home_page_settings_from_mapping
from papyrus_content.projection.standard import blocks, home_page_blocks, home_page_components, includes
from papyrus_content.projection.standard.config import standard_settings_from_mapping
from papyrus_content.projection.standard.home_page import HomePageSource
from papyrus_content.projection.standard.page_ledger import PageLedger

SITE = {"site": {"name": "Example", "productionUrl": "https://example.org"}}


def record(key, status="accepted", **fields):
    return {"key": key, "status": status, "title": f"Title {key}", "url": f"https://example.org/{key}", "host": "example.org", **fields}


def document(*records):
    return {"generatedAt": "2026-10-31T12:00:00.000Z", "corpus": "c", "fields": [], "references": list(records)}


def keys_of(chosen):
    return [reference["key"] for reference in chosen]


def pick(documents, **attributes):
    return keys_of(home_page_blocks.select_references(documents, attributes, PageLedger()))


# ------------------------------------------------------------------ ledger

def test_the_first_claim_wins_and_a_second_claim_is_refused():
    ledger = PageLedger()
    assert ledger.claim("reference:a") is True
    assert ledger.claim("reference:a") is False
    assert ledger.claim("reference:b") is True
    assert ledger.seen == {"reference:a", "reference:b"}


def test_every_page_gets_its_own_ledger():
    assert PageLedger().seen is not PageLedger().seen


# ------------------------------------------------------------------ source

def test_a_source_with_no_store_and_no_directory_reads_nothing():
    source = HomePageSource()
    assert source.configured is False
    assert source.references() is None and source.digest() == ""


def test_a_source_reads_the_store_and_digests_the_bytes():
    body = json.dumps(document(record("a"))).encode()
    asked = []
    source = HomePageSource()
    source.attach_store(lambda key: asked.append(key) or body)
    assert source.configured is True
    assert source.references()["references"][0]["key"] == "a"
    assert source.references() is source.references()
    assert asked == ["_data/home-page/references.json"]
    assert len(source.digest()) == 16


def test_a_changed_file_changes_the_digest():
    first, second = HomePageSource(), HomePageSource()
    first.attach_store(lambda key: json.dumps(document(record("a"))).encode())
    second.attach_store(lambda key: json.dumps(document(record("b"))).encode())
    assert first.digest() != second.digest()


def test_a_directory_wins_over_the_store_in_either_call_order(tmp_path):
    (tmp_path / "references.json").write_text(json.dumps(document(record("from-directory"))), encoding="utf-8")
    for order in ("directory-first", "store-first"):
        source = HomePageSource()
        if order == "directory-first":
            source.use_directory(tmp_path)
            source.attach_store(lambda key: json.dumps(document(record("from-store"))).encode())
        else:
            source.attach_store(lambda key: json.dumps(document(record("from-store"))).encode())
            source.use_directory(tmp_path)
        assert source.references()["references"][0]["key"] == "from-directory"


def test_an_absent_file_reads_as_none_and_reset_reads_again():
    stored = {}
    source = HomePageSource()
    source.attach_store(lambda key: stored.get(key))
    assert source.references() is None
    stored["_data/home-page/references.json"] = json.dumps(document()).encode()
    assert source.references() is None
    source.reset()
    assert source.references() is not None


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"generatedAt": "x"}'])
def test_a_file_that_is_not_a_snapshot_is_an_error_naming_it(body):
    source = HomePageSource()
    source.attach_store(lambda key: body)
    with pytest.raises(ValueError, match="_data/home-page/references.json"):
        source.references()


# ------------------------------------------------------------------ attributes

@pytest.mark.parametrize(
    "attributes, message",
    [
        ({"kind": "references"}, "needs select"),
        ({"kind": "references", "select": "newest"}, "needs select"),
        ({"kind": "references", "select": "recent", "count": "many"}, "count must be a whole number"),
        ({"kind": "references", "select": "recent", "count": "-1"}, "count must be a whole number"),
        ({"kind": "references", "select": "recent", "card": "hero"}, "card must be one of tile, row"),
        ({"kind": "references", "select": "recent", "more": "javascript:alert(1)"}, "more must be"),
        ({"kind": "references", "select": "recent", "colour": "red"}, "unknown attributes: colour"),
    ],
)
def test_a_bad_references_include_is_an_error_naming_the_file(attributes, message):
    with pytest.raises(ValueError, match=f"pages/front.md: .*{message}"):
        home_page_blocks.check(attributes, "pages/front.md")


@pytest.mark.parametrize("select", home_page_blocks.SELECTIONS)
def test_every_selection_and_card_is_accepted(select):
    for card in ("tile", "row"):
        home_page_blocks.check({"kind": "references", "select": select, "card": card, "count": "3", "more": "/more/", "section": "Tools", "heading": "H", "empty": "None"}, "page.md")


def test_the_references_include_needs_homepage_in_projection_json():
    settings = standard_settings_from_mapping(SITE)
    with pytest.raises(ValueError, match=r"pages/front.md: ::include references: homePage is not configured in projection.json"):
        includes.check({"kind": "references", "select": "recent"}, settings, "pages/front.md")


def test_the_references_include_is_accepted_when_homepage_is_configured():
    settings = standard_settings_from_mapping({**SITE, "homePage": {}})
    assert includes.check({"kind": "references", "select": "recent"}, settings, "pages/front.md") == "references"


def test_the_page_digest_input_records_the_attributes_of_a_references_include():
    settings = standard_settings_from_mapping({**SITE, "homePage": {}})
    attributes = {"kind": "references", "select": "recent", "count": "3"}
    assert includes.include_inputs([attributes], [], settings) == [[attributes, "home-page:references"]]
    changed = includes.include_inputs([{**attributes, "count": "4"}], [], settings)
    assert changed != includes.include_inputs([attributes], [], settings)


def test_is_home_page_include_matches_only_references():
    assert home_page_blocks.is_home_page_include({"kind": "references"})
    assert not home_page_blocks.is_home_page_include({"kind": "listing"})


# ------------------------------------------------------------------ selection

@pytest.fixture
def snapshot():
    return document(
        record("old", acceptedAt="2026-10-01T00:00:00.000Z", arrivedAt="2026-09-01T00:00:00.000Z", confidence=0.9),
        record("new", acceptedAt="2026-10-05T00:00:00.000Z", arrivedAt="2026-09-02T00:00:00.000Z", confidence=0.6),
        record("tie-late", acceptedAt="2026-10-03T00:00:00.000Z", arrivedAt="2026-09-20T00:00:00.000Z", confidence=0.7),
        record("tie-early", acceptedAt="2026-10-03T00:00:00.000Z", arrivedAt="2026-09-10T00:00:00.000Z", confidence=0.7),
        record("no-confidence", acceptedAt="2026-10-02T00:00:00.000Z", arrivedAt="2026-09-05T00:00:00.000Z", confidence=None),
        record("rec-low", "recommended", arrivedAt="2026-10-02T00:00:00.000Z", confidence=0.55),
        record("rec-high", "recommended", arrivedAt="2026-10-01T00:00:00.000Z", confidence=0.95),
        record("rec-tie-b", "recommended", arrivedAt="2026-10-04T00:00:00.000Z", confidence=0.8),
        record("rec-tie-a", "recommended", arrivedAt="2026-10-04T00:00:00.000Z", confidence=0.8),
    )


def test_recent_orders_accepted_by_acceptance_then_arrival_then_key(snapshot):
    assert pick(snapshot, select="recent", count="10") == ["new", "tie-late", "tie-early", "no-confidence", "old"]


def test_confident_orders_accepted_by_confidence_with_a_missing_one_at_half(snapshot):
    assert pick(snapshot, select="confident", count="10") == ["old", "tie-late", "tie-early", "new", "no-confidence"]


def test_recommended_takes_only_the_not_yet_accepted_ordered_by_confidence_then_arrival_then_key(snapshot):
    assert pick(snapshot, select="recommended", count="10") == ["rec-high", "rec-tie-a", "rec-tie-b", "rec-low"]


def test_the_key_breaks_a_complete_tie():
    tied = document(*(record(key, acceptedAt="2026-10-01T00:00:00.000Z", arrivedAt="2026-09-01T00:00:00.000Z", confidence=0.5) for key in ("c", "a", "b")))
    assert pick(tied, select="recent") == ["a", "b", "c"]
    assert pick(tied, select="confident") == ["a", "b", "c"]


def test_an_empty_or_missing_snapshot_selects_nothing():
    for empty in (None, {}, document()):
        assert pick(empty, select="recent") == []


def test_a_record_without_a_key_is_never_placed():
    assert pick(document({"status": "accepted", "title": "No key"}), select="recent") == []


def test_count_limits_and_a_missing_count_uses_the_default(snapshot):
    assert len(pick(snapshot, select="recent", count="2")) == 2
    assert len(pick(snapshot, select="recent")) == 5
    chosen = home_page_blocks.select_references(snapshot, {"select": "recent"}, PageLedger(), default_count=2)
    assert len(chosen) == 2


def test_a_count_of_zero_places_nothing_and_claims_nothing(snapshot):
    ledger = PageLedger()
    assert home_page_blocks.select_references(snapshot, {"select": "recent", "count": "0"}, ledger) == []
    assert ledger.seen == set()


def test_the_default_count_comes_from_the_homepage_settings():
    settings = home_page_settings_from_mapping({"references": {"defaultCount": 4}})
    assert home_page_blocks.count_of({}, settings) == 4
    assert home_page_blocks.count_of({"count": "9"}, settings) == 9
    assert home_page_blocks.count_of({}, HomePageSettings()) == 6
    assert home_page_blocks.count_of({}, None) == 6


def test_section_keeps_references_whose_section_is_the_label_or_the_named_section():
    tagged = document(
        record("a", acceptedAt="2026-10-03T00:00:00.000Z", section="Tools"),
        record("b", acceptedAt="2026-10-02T00:00:00.000Z", section="Articles"),
        record("c", acceptedAt="2026-10-01T00:00:00.000Z"),
    )
    assert pick(tagged, select="recent", section="Tools") == ["a"]
    assert pick(tagged, select="recent", section="tools") == ["a"]
    labels = {"how-to": "Articles"}
    chosen = home_page_blocks.select_references(tagged, {"select": "recent", "section": "how-to"}, PageLedger(), section_labels=labels)
    assert keys_of(chosen) == ["b"]
    assert pick(tagged, select="recent", section="Nothing") == []


# ------------------------------------------------------------------ de-duplication

def test_three_components_on_one_page_never_repeat_a_reference_and_the_first_wins(snapshot):
    ledger = PageLedger()
    first = keys_of(home_page_blocks.select_references(snapshot, {"select": "recent", "count": "2"}, ledger))
    second = keys_of(home_page_blocks.select_references(snapshot, {"select": "confident", "count": "2"}, ledger))
    third = keys_of(home_page_blocks.select_references(snapshot, {"select": "recent", "count": "5"}, ledger))
    assert first == ["new", "tie-late"]
    assert second == ["old", "tie-early"]
    assert third == ["no-confidence"]
    assert len({*first, *second, *third}) == len(first + second + third)


def test_a_later_component_refills_to_its_count_after_skipping_what_is_taken(snapshot):
    ledger = PageLedger()
    home_page_blocks.select_references(snapshot, {"select": "recent", "count": "3"}, ledger)
    refilled = keys_of(home_page_blocks.select_references(snapshot, {"select": "confident", "count": "2"}, ledger))
    assert refilled == ["old", "no-confidence"]


def test_a_pool_that_runs_out_gives_fewer_than_count(snapshot):
    ledger = PageLedger()
    home_page_blocks.select_references(snapshot, {"select": "recommended", "count": "3"}, ledger)
    assert keys_of(home_page_blocks.select_references(snapshot, {"select": "recommended", "count": "3"}, ledger)) == ["rec-low"]
    assert home_page_blocks.select_references(snapshot, {"select": "recommended", "count": "3"}, ledger) == []


def test_a_section_filter_does_not_claim_what_it_leaves_out():
    tagged = document(record("a", acceptedAt="2026-10-02T00:00:00.000Z", section="Tools"), record("b", acceptedAt="2026-10-01T00:00:00.000Z", section="Articles"))
    ledger = PageLedger()
    home_page_blocks.select_references(tagged, {"select": "recent", "section": "Tools"}, ledger)
    assert keys_of(home_page_blocks.select_references(tagged, {"select": "recent"}, ledger)) == ["b"]


# ------------------------------------------------------------------ cards

@pytest.mark.parametrize("percent, filled", [(0, 0), (9, 0), (10, 1), (30, 2), (50, 3), (70, 4), (93, 5), (100, 5)])
def test_the_meter_fills_one_segment_per_fifth(percent, filled):
    markup = home_page_components.meter(percent)
    assert markup.count("home-page-meter-segment--filled") == filled
    assert markup.count("<rect") == 5


def test_confidence_is_a_labelled_number_with_the_gauge_icon():
    markup = home_page_components.confidence_markup({"confidence": 0.93})
    assert "93% confidence" in markup and 'data-icon="gauge"' in markup and markup.count("--filled") == 5
    assert home_page_components.confidence_markup({"confidence": None}) == ""
    assert home_page_components.confidence_markup({}) == ""
    assert "100% confidence" in home_page_components.confidence_markup({"confidence": 1.4})


def test_a_recommended_tile_says_so_in_words_and_with_the_sparkles_icon():
    markup = home_page_components.tile(record("a", "recommended", confidence=0.8, acceptedAt="2026-10-01T00:00:00.000Z", actor="human"))
    assert "<span>Recommended by Cyclotron, not yet accepted</span>" in markup and 'data-icon="sparkles"' in markup
    assert "Accepted" not in markup.replace("not yet accepted", "")


def test_an_accepted_tile_says_who_accepted_it_without_naming_anyone():
    editor = home_page_components.tile(record("a", actor="human", acceptedAt="2026-10-01T00:00:00.000Z"))
    machine = home_page_components.tile(record("a", actor="cyclotron"))
    unknown = home_page_components.tile(record("a"))
    assert "Accepted by an editor" in editor and "Accepted automatically" in machine
    assert "Accepted by" not in unknown and "Accepted automatically" not in unknown
    assert "sparkles" not in editor


def test_a_tile_shows_dates_host_section_and_an_image_with_empty_alt():
    markup = home_page_components.tile(record("a", sourceDate="2026-10-11", acceptedAt="2026-10-20T09:12:00.000Z", section="Tools", image="https://images.example.org/a.jpg"))
    assert '<time datetime="2026-10-11">11 Oct 2026</time>' in markup and '<time datetime="2026-10-20T09:12:00.000Z">20 Oct 2026</time>' in markup
    assert '<p class="home-page-eyebrow">example.org</p>' in markup and 'data-kind="section">Tools' in markup
    assert 'alt=""' in markup and 'rel="noopener"' in markup


def test_text_is_escaped_and_unsafe_addresses_are_dropped():
    markup = home_page_components.tile(record("a", title="<script>alert(1)</script>", url="javascript:alert(1)", image="javascript:alert(2)", host="<b>x</b>"))
    assert "<script>" not in markup and "<b>" not in markup and "javascript:" not in markup and "<img" not in markup
    assert "&lt;script&gt;" in markup


def test_a_row_is_one_line_of_host_title_and_date():
    markup = home_page_components.row(record("a", acceptedAt="2026-10-20T09:12:00.000Z"))
    assert markup.startswith('<div class="home-page-row"') and "example.org" in markup and "Title a" in markup and "20 Oct 2026" in markup
    assert "<h3" not in markup and "<img" not in markup


def test_a_row_shows_the_confidence_compactly_with_a_hidden_label_icon_and_meter():
    markup = home_page_components.row(record("a", acceptedAt="2026-10-20T09:12:00.000Z", confidence=0.92))
    assert '<span class="home-page-confidence-value">92%<span class="home-page-visually-hidden"> confidence</span></span>' in markup
    assert 'data-icon="gauge"' in markup and markup.count("--filled") == 5


def test_a_row_without_a_recorded_confidence_draws_none():
    assert "home-page-confidence" not in home_page_components.row(record("a", acceptedAt="2026-10-20T09:12:00.000Z", confidence=None))


def test_a_recommended_row_shows_the_label_and_the_confidence():
    markup = home_page_components.row(record("a", "recommended", confidence=0.8))
    assert "Recommended by Cyclotron, not yet accepted" in markup and "80%" in markup and 'data-icon="gauge"' in markup


@pytest.mark.parametrize("value", [None, "", "soon", "2026-13-40", "2026-02-30"])
def test_a_value_that_is_not_a_date_draws_no_time(value):
    assert home_page_components.time_markup(value) == ""


# ------------------------------------------------------------------ render

def render(snapshot, ledger=None, settings=None, **attributes):
    return home_page_blocks.render({"kind": "references", **attributes}, snapshot, ledger or PageLedger(), settings or HomePageSettings())


def test_render_wraps_cards_in_a_grid_with_heading_and_more_link(snapshot):
    markup = render(snapshot, select="recent", count="2", heading="Recently accepted", more="/references/")
    assert markup.startswith('<section class="home-page-references" data-select="recent" data-card="tile">')
    assert '<h2 class="home-page-heading">Recently accepted</h2>' in markup and '<a href="/references/">More</a>' in markup
    assert markup.count('class="home-page-tile"') == 2


def test_render_draws_rows_when_asked(snapshot):
    markup = render(snapshot, select="recent", count="2", card="row")
    assert markup.count('class="home-page-row"') == 2 and "home-page-tile" not in markup


def test_nothing_left_draws_the_empty_text_or_nothing():
    assert render(document(), select="recent", empty="Nothing yet.") == '<p class="home-page-empty">Nothing yet.</p>'
    assert render(document(), select="recent", heading="Heading", more="/m/") == ""
    assert render(None, select="recent") == ""
    assert render(None, select="recent", empty="<b>x</b>") == '<p class="home-page-empty">&lt;b&gt;x&lt;/b&gt;</p>'


def test_render_uses_the_configured_default_count(snapshot):
    settings = home_page_settings_from_mapping({"references": {"defaultCount": 1}})
    assert render(snapshot, settings=settings, select="recent").count('class="home-page-tile"') == 1


def test_render_passes_the_section_labels(snapshot):
    tagged = document(record("a", acceptedAt="2026-10-01T00:00:00.000Z", section="Articles"))
    markup = home_page_blocks.render({"select": "recent", "section": "how-to"}, tagged, PageLedger(), HomePageSettings(), {"how-to": "Articles"})
    assert "Title a" in markup


# ------------------------------------------------------------------ twin

TWIN_SOURCE = (
    '::band{size="bare"}\n'
    '::include{kind="references" select="recent" count="3"}\n'
    '::include{kind="threads" count="2"}\n'
    '::include{kind="listing" count="2"}\n'
    '::include{kind="block" name="knowledge-trending-strip"}\n'
    '::include{kind="form" id="contact"}\n'
)


def test_the_twin_keeps_references_and_threads_include_lines_and_drops_other_includes():
    twin = blocks.twin(TWIN_SOURCE, {}, "page.md")
    lines = twin.splitlines()
    assert '::include{kind="references" select="recent" count="3"}' in lines
    assert '::include{kind="threads" count="2"}' in lines
    assert '::include{kind="block" name="knowledge-trending-strip"}' in lines
    assert not any("kind=\"listing\"" in line or "kind=\"form\"" in line for line in lines)


# ------------------------------------------------------------------ reserved paths

@pytest.mark.parametrize("prefix", ["_data", "_plugins", "_papyrus", "_next", "api"])
def test_a_page_section_or_collection_path_equal_to_a_reserved_prefix_is_a_build_error(prefix):
    for raw, where in (
        ({"pages": [{"id": "p", "path": prefix, "title": "P"}]}, "pages.path"),
        ({"urls": {"sections": {"docs": {"base": prefix}}}}, "urls.sections.docs.base"),
        ({"collections": [{"id": "docs", "base": prefix}]}, "collections.docs.base"),
    ):
        with pytest.raises(ValueError, match=rf"{where} '{prefix}' is reserved.*newsroom"):
            standard_settings_from_mapping({**SITE, **raw})


def test_a_path_that_only_starts_with_a_reserved_prefix_is_allowed():
    settings = standard_settings_from_mapping({**SITE, "pages": [{"id": "p", "path": "api-notes", "title": "P"}, {"id": "q", "path": "docs/api", "title": "Q"}]})
    assert [page.path for page in settings.pages] == ["api-notes", "docs/api"]
