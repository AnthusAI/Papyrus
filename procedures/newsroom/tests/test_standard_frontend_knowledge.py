"""Knowledge components of the standard front end: chip, sparkline, trend chart, neighbourhood, score, blocks and wiki directives."""

from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest

from papyrus_content.projection.engine import ProjectionContext, project_all, project_listings
from papyrus_content.projection.directory_source import DirectoryContentSource
from papyrus_content.projection.standard import knowledge_blocks, knowledge_components as parts
from papyrus_content.projection.standard.knowledge import KnowledgeSource
from papyrus_content.projection.standard.knowledge_lookup import KnowledgeLookup
from papyrus_content.projection.standard.projector import ASSET_DIRECTORY, StandardMarkusProjector
from papyrus_content.projection.writers import LocalDirectoryWriter
from procedures.newsroom.tests import knowledge_fixtures as data
from procedures.newsroom.tests.standard_frontend_content_support import DirectorySite, item, settings
from procedures.newsroom.tests.standard_frontend_support import static_directory

BAND = '::band{size="bare"}\n'
KINDS = {"maker": "Maker", "tool": "Tool"}


def source_for(tmp_path: Path, **files) -> KnowledgeSource:
    source = KnowledgeSource()
    source.use_directory(data.write(tmp_path / "knowledge", **files))
    return source


def block(name: str, source: KnowledgeSource, **attributes) -> str:
    return knowledge_blocks.render_block({"kind": "block", "name": name, **attributes}, source, "test.md")


# ------------------------------------------------------------------ sparkline and trend

def test_cold_start_shows_no_sparkline_and_no_percent_and_says_new():
    markup = parts.trend({"weeksOfHistory": 3, "series8": [0, 0, 0, 0, 0, 1, 2, 3], "change": {"last4": 6, "prior4": 0, "percent": None}})
    assert "<svg" not in markup and "%" not in markup
    assert ">new<" in markup and 'data-state="new"' in markup


def test_four_to_seven_weeks_show_a_sparkline_without_a_percent():
    markup = parts.trend({"weeksOfHistory": 5, "series8": [0, 0, 0, 1, 2, 2, 3, 4], "change": {"last4": 11, "prior4": 1, "percent": None}})
    assert "<svg" in markup and "%" not in markup and 'data-state="building"' in markup
    assert len(re.search(r'points="([^"]+)"', markup).group(1).split()) == 5


def test_the_percent_is_the_snapshots_and_the_component_does_not_apply_a_history_rule_of_its_own():
    markup = parts.trend({"weeksOfHistory": 5, "series8": [0, 0, 0, 1, 2, 2, 3, 4], "change": {"last4": 11, "prior4": 6, "percent": 83}})
    assert "+83%" in markup


def test_full_history_shows_the_sparkline_and_the_percent_change_with_a_mark_and_a_sign():
    markup = parts.trend(data.ENTITIES[0])
    assert "<svg" in markup and "+200%" in markup and "▲" in markup
    assert len(re.search(r'points="([^"]+)"', markup).group(1).split()) == 8
    falling = parts.trend(data.ENTITIES[3])
    assert "▼" in falling and "−68%" in falling and "down" in falling


def test_a_full_history_without_a_percent_shows_only_the_sparkline():
    markup = parts.trend({"weeksOfHistory": 9, "series8": [3] * 8, "change": {"last4": 12, "prior4": 4, "percent": None}})
    assert "<svg" in markup and "%" not in markup


def test_the_sparkline_needs_no_script_and_is_hidden_from_screen_readers():
    markup = parts.trend(data.ENTITIES[0])
    assert 'aria-hidden="true"' in markup and "<script" not in markup and "<img" not in markup
    assert "+200%" in re.sub(r"<[^>]+>", "", markup)                       # the figure is text beside the drawing


def test_the_trend_chart_appears_only_after_twelve_weeks_of_history():
    series = data.ACME["series26"]
    assert parts.trend_chart(series, 11, data.AS_OF) == ""
    chart = parts.trend_chart(series, 12, data.AS_OF)
    assert chart.startswith("<figure") and "<script" not in chart
    assert chart.count("papyrus-knowledge-chart-bar") == 12 and "papyrus-knowledge-chart-average" in chart   # two series, only the weeks since the first link


def test_the_trend_chart_marks_the_annotated_week_and_says_so_in_text():
    chart = parts.trend_chart(data.ACME["series26"], 26, data.AS_OF, annotate="2026-09-24", annotate_label="Launch")
    assert "papyrus-knowledge-chart-marker" in chart and "Launch" in chart
    assert "Marked: Launch" in chart
    assert "papyrus-knowledge-chart-marker" not in parts.trend_chart(data.ACME["series26"], 26, data.AS_OF, annotate="2019-01-01", annotate_label="Old")


# ------------------------------------------------------------------ chip and readout

def test_a_proposed_entity_chip_is_dashed_and_says_proposed():
    chip = parts.entity_chip("Maker", "Acme", kind="maker", proposed=True)
    assert "papyrus-knowledge-chip--proposed" in chip and 'data-state="proposed"' in chip and "(proposed)" in chip
    css = (ASSET_DIRECTORY / "papyrus-knowledge.css").read_text(encoding="utf-8")
    assert re.search(r"\.papyrus-knowledge-chip--proposed\s*\{[^}]*border-style:\s*dashed", css)
    plain = parts.entity_chip("Maker", "Acme", kind="maker", href="/wiki/acme/")
    assert "proposed" not in plain and plain.startswith('<a ') and "Maker" in plain and "Acme" in plain


def test_a_chip_escapes_names_and_drops_unsafe_links():
    chip = parts.entity_chip("Maker", "<b>x</b>", href="javascript:alert(1)")
    assert "<b>" not in chip and "href" not in chip


def test_a_low_score_is_dimmed_and_keeps_its_text_value():
    low = parts.score_readout(0.2, 3, threshold=0.5)
    assert "papyrus-knowledge-score--dimmed" in low and ">0.20<" in low and "n=<span>3</span>" in low
    assert low.count("papyrus-knowledge-score-segment--filled") == 1
    high = parts.score_readout(0.9, 40, threshold=0.5)
    assert "dimmed" not in high and high.count("papyrus-knowledge-score-segment--filled") == 5 and high.count("<rect") == 5


# ------------------------------------------------------------------ neighbourhood

def test_the_neighbourhood_renders_one_column_per_relation_with_entries_by_weight(tmp_path):
    source = source_for(tmp_path)
    markup = block("knowledge-entity", source, key="acme-loom", part="neighbourhood")
    columns = markup.split("papyrus-knowledge-neighbourhood-column")[1:]
    assert len(columns) == 2
    assert "Built on" in columns[0] and "Made by" in columns[1]            # the heavier relation first
    assert [m for m in re.findall(r"chip-name\">([^<]+)<", columns[0])] == ["Gamma New", "Beta Spool"]
    assert [m for m in re.findall(r"chip-name\">([^<]+)<", columns[1])] == ["Zeta", "Delta Fade"]
    assert re.findall(r'papyrus-knowledge-weight">(\d+)<', columns[0]) == ["9", "5"] and "weightbar" in markup


def test_only_what_the_snapshot_lists_is_shown(tmp_path):
    source = source_for(tmp_path)
    assert block("knowledge-entity", source, key="gamma-new", part="neighbourhood") == ""
    assert block("knowledge-entity", source, key="gamma-new", part="related") == ""
    related = block("knowledge-entity", source, key="acme-loom", part="related")
    assert '<a href="/posts/loom-news/">Loom news</a>' in related and "2026-10-12" in related


def test_entity_trend_part_has_the_trend_and_the_chart_only_with_enough_history(tmp_path):
    source = source_for(tmp_path)
    full = block("knowledge-entity", source, key="acme-loom", part="trend", annotate="2026-09-24", annotateLabel="Launch")
    assert "+200%" in full and "<figure" in full and "Launch" in full
    young = block("knowledge-entity", source, key="gamma-new", part="trend")
    assert ">new<" in young and "<figure" not in young and "<svg" not in young


# ------------------------------------------------------------------ trending, clusters, the rest

def test_the_trending_list_keeps_the_snapshot_order_with_counts_and_leaves_out_new_entities(tmp_path):
    source = source_for(tmp_path)
    markup = block("knowledge-trending-list", source, limit="6")
    names = re.findall(r"chip-name\">([^<]+)<", markup)
    assert names == ["Acme Loom", "Delta Fade", "Beta Spool"] and "Gamma New" not in markup
    assert "24 items" in markup and "18 in the last 4 weeks" in markup
    assert block("knowledge-trending-list", source, limit="2").count("<li class=\"papyrus-knowledge-trending-item\"") == 2


def test_the_trending_list_filters_by_kind_on_the_server_and_without_a_script_by_anchors(tmp_path):
    source = source_for(tmp_path)
    only = block("knowledge-trending-list", source, entityKind="tool")
    assert re.findall(r"chip-name\">([^<]+)<", only) == ["Beta Spool"] and "kindfilter" not in only
    everything = block("knowledge-trending-list", source)
    assert "papyrus-knowledge-kindfilter" in everything and "<script" not in everything
    anchor = re.search(r'href="#(papyrus-knowledge-trending-[0-9a-f]+-tool)"', everything).group(1)
    assert f'id="{anchor}"' in everything and f'#{anchor}:target~ol>li:not([data-kind="tool"])' in everything
    assert block("knowledge-trending-list", source) == everything               # the same page renders the same bytes


def test_the_trending_strip_shows_chips_with_their_trend(tmp_path):
    markup = block("knowledge-trending-strip", source_for(tmp_path), limit="2")
    assert markup.count("papyrus-knowledge-trending-item") == 2 and "+200%" in markup and "Beta Spool" not in markup


def test_an_accepted_cluster_shows_its_name_count_terms_and_a_sparkline(tmp_path):
    markup = block("knowledge-clusters", source_for(tmp_path))
    assert "Wearable looms" in markup and "14 items" in markup and "loom, wearable, textile" in markup and "<svg" in markup
    assert "▲ Growing" in markup and '<a href="/topics/wearable-looms/">' in markup


def test_a_cluster_with_under_four_weeks_of_data_has_no_state_label_and_no_sparkline(tmp_path):
    markup = block("knowledge-clusters", source_for(tmp_path))
    fresh = markup.split("Fresh theme")[1].split("</li>")[0]
    assert "cluster-label" not in fresh and "<svg" not in fresh and "3 items" in fresh


def test_unaccepted_clusters_are_hidden_or_shown_as_unnamed_by_the_setting(tmp_path):
    hidden = block("knowledge-clusters", source_for(tmp_path))
    assert "secret" not in hidden and "Unnamed" not in hidden
    shown_data = copy.deepcopy(data.CLUSTERS)
    shown_data["unacceptedClusters"] = "unnamed"
    shown = block("knowledge-clusters", source_for(tmp_path / "again", clusters=shown_data), limit="5")
    assert "Unnamed theme" in shown and "6 items" in shown and "secret" not in shown


def test_the_concept_of_the_week_and_the_topic_count(tmp_path):
    source = source_for(tmp_path)
    week = block("knowledge-concept-of-the-week", source)
    assert "Acme Loom" in week and "A loom maker that doubled its output." in week and "36 items" in week
    assert block("knowledge-topic-count", source) == '<span class="papyrus-knowledge-count">7</span>'


def test_blocks_render_nothing_when_their_data_is_absent(tmp_path):
    empty = KnowledgeSource()
    empty.use_directory(tmp_path / "nothing")
    for name in ("knowledge-trending-strip", "knowledge-trending-list", "knowledge-clusters", "knowledge-concept-of-the-week", "knowledge-topic-count"):
        assert block(name, empty) == ""
    assert block("knowledge-entity", empty, key="acme-loom", part="trend") == ""
    unattached = KnowledgeSource()
    assert block("knowledge-topic-count", unattached) == ""


def test_a_score_block_shows_the_value_it_is_given():
    markup = block("knowledge-score", KnowledgeSource(), value="0.3", n="8", threshold="0.5", label="Confidence")
    assert "papyrus-knowledge-score--dimmed" in markup and ">0.30<" in markup and "Confidence" in markup


@pytest.mark.parametrize("attributes", [
    {"name": "knowledge-nothing"},
    {"name": "knowledge-trending-strip", "limit": "many"},
    {"name": "knowledge-trending-strip", "colour": "red"},
    {"name": "knowledge-entity", "part": "trend"},
    {"name": "knowledge-entity", "key": "acme-loom", "part": "graph"},
    {"name": "knowledge-score"},
])
def test_a_bad_knowledge_block_is_a_build_error(tmp_path, attributes):
    with pytest.raises(ValueError, match="test.md"):
        knowledge_blocks.render_block({"kind": "block", **attributes}, source_for(tmp_path), "test.md")


def test_an_unsupported_schema_version_is_an_error_not_a_guess(tmp_path):
    bad = {**data.INDEX, "schemaVersion": 2}
    with pytest.raises(ValueError, match="schemaVersion"):
        source_for(tmp_path, index=bad).index()


# ------------------------------------------------------------------ the projector

PAGE = "\n".join([
    BAND,
    "# Knowledge",
    '::include{kind="block" name="knowledge-topic-count"}',
    '::include{kind="block" name="knowledge-trending-strip" limit=5}',
    '::include{kind="block" name="knowledge-trending-list" limit=6 entityKind=""}',
    '::include{kind="block" name="knowledge-clusters" limit=3}',
    '::include{kind="block" name="knowledge-concept-of-the-week"}',
    '::include{kind="block" name="knowledge-entity" key="acme-loom" part="trend"}',
    '::include{kind="block" name="knowledge-entity" key="acme-loom" part="neighbourhood"}',
    '::include{kind="block" name="knowledge-entity" key="acme-loom" part="related"}',
    "",
])
BLOCK_NAMES = ("knowledge-topic-count", "knowledge-trending-strip", "knowledge-trending-list", "knowledge-clusters", "knowledge-concept-of-the-week", "knowledge-entity")


class KnowledgeSite(DirectorySite):
    """A directory site whose output directory already holds the snapshot, as after ``papyrus knowledge snapshot``."""

    def __init__(self, items, files, *, snapshot=True, base="", **extra):
        super().__init__(settings(pages=[{"id": "knowledge", "path": "knowledge", "title": "Knowledge", "source": "knowledge.md"}], **extra), items, files)
        if snapshot:
            data.write(self.out / base / "_data" / "knowledge")

    def context(self):
        projector = StandardMarkusProjector.from_static_directory(self.static, environ=self.environ)
        return ProjectionContext(source=DirectoryContentSource(self.content), projector=projector, writer=LocalDirectoryWriter(self.out), keep_state=False)


@pytest.fixture
def site():
    wiki = item("loom", section="wiki", body=f'{BAND}# Acme Loom\n\n::concept-count\n\n::concept-count{{kind="maker"}}\n\n::recent-concepts{{limit=2}}\n\n::concept-list{{kind="tool"}}\n\n'
               '::include{kind="block" name="knowledge-entity" key="acme-loom" part="trend"}\n')
    created = KnowledgeSite([wiki, item("loom-news", section="posts")], {"knowledge.md": PAGE})
    yield created
    created.cleanup()


def page_text(site, key="knowledge/index.html"):
    return site.text(key)


def test_a_page_uses_every_block_from_fixture_data(site):
    report = project_all(site.context())
    assert report.ok, report.errors
    page = page_text(site)
    for expected in ("papyrus-knowledge-count\">7<", "papyrus-knowledge-trending-strip", "papyrus-knowledge-trending-list", "papyrus-knowledge-clusters",
                     "papyrus-knowledge-cotw", "papyrus-knowledge-entity-trend", "papyrus-knowledge-neighbourhood", "papyrus-knowledge-related", "Wearable looms"):
        assert expected in page, expected
    assert "secret" not in page and "Gamma New</span>" in page                     # unaccepted cluster hidden; the new entity shows only as a neighbour
    assert "css/papyrus-knowledge.css" in page and "css/papyrus-knowledge.css" in site.keys()
    assert "<script" not in re.search(r"<main.*?</main>", page, re.S).group(0).replace('<script src', '')


def test_the_markdown_twin_keeps_the_knowledge_include_source(site):
    project_all(site.context())
    twin = site.text("knowledge/index.md")
    for name in BLOCK_NAMES:
        assert f'name="{name}"' in twin
    assert '::include{kind="block" name="knowledge-trending-strip" limit=5}' in twin
    assert "<svg" not in twin and "papyrus-knowledge" not in twin


def test_concept_directives_render_from_the_index_in_a_static_item_and_keep_their_source_in_the_twin(site):
    report = project_all(site.context())
    assert report.ok, report.errors
    page = site.text("loom.html")
    assert re.search(r'<span class="papyrus-knowledge-count">4</span>', page)                  # concept-count: the accepted entities of the index
    assert '<span class="papyrus-knowledge-count">3</span>' in page                            # concept-count{kind="maker"}
    recent = re.search(r'data-directive="recent-concepts">(.*?)</ul>', page, re.S).group(1)
    assert re.findall(r"chip-name\">([^<]+)<", recent) == ["Gamma New", "Beta Spool"]          # the most recently first linked, limit 2
    assert re.findall(r"chip-name\">([^<]+)<", re.search(r'data-directive="concept-list">(.*?)</ul>', page, re.S).group(1)) == ["Beta Spool"]
    assert "papyrus-dynamic" not in page and "papyrus-knowledge-entity-trend" in page          # an item may place a knowledge block after a band
    twin = site.text("loom.md")
    assert "::concept-count{kind=\"maker\"}" in twin and "::recent-concepts{limit=2}" in twin
    assert '::include{kind="block" name="knowledge-entity" key="acme-loom" part="trend"}' in twin


def test_without_a_snapshot_the_directives_keep_their_empty_placeholder_and_the_blocks_draw_nothing():
    wiki = item("loom", section="wiki", body="# Loom\n\n::concept-count\n\n::recent-concepts{limit=3}\n")
    created = KnowledgeSite([wiki], {"knowledge.md": PAGE}, snapshot=False)
    try:
        assert project_all(created.context()).ok
        assert page_text(created, "loom.html").count('class="papyrus-dynamic"') == 2
        page = page_text(created)
        assert "papyrus-knowledge-trending" not in page and "papyrus-knowledge-cluster" not in page and "<h1" in page
    finally:
        created.cleanup()


def test_a_local_knowledge_directory_replaces_the_store(site, tmp_path):
    other = copy.deepcopy(data.INDEX)
    other["topicCount"] = 99
    directory = data.write(tmp_path / "local", index=other)
    context = site.context()
    context.projector.use_knowledge_directory(directory)
    assert project_all(context).ok
    assert 'papyrus-knowledge-count">99<' in page_text(site)


def test_a_new_snapshot_changes_the_input_digest_of_the_pages_that_read_it_and_an_unchanged_one_does_not(site):
    context = site.context()
    assert project_all(context).ok
    before = context.projector.listing_inputs(context.source.site_index())
    assert context.projector.listing_inputs(context.source.site_index()) == before
    changed = copy.deepcopy(data.INDEX)
    changed["topicCount"] = 8
    data.write(site.out / "_data" / "knowledge", index=changed)
    after = context.projector.listing_inputs(context.source.site_index())
    assert after["knowledge/index.html"] != before["knowledge/index.html"]
    assert project_listings(context).ok and 'papyrus-knowledge-count">8<' in page_text(site)
    entity = copy.deepcopy(data.ACME)
    entity["relatedItems"] = []
    data.write(site.out / "_data" / "knowledge", index=changed, entities=(entity, data.NEW_ENTITY))
    assert context.projector.listing_inputs(context.source.site_index())["knowledge/index.html"] != after["knowledge/index.html"]


def test_the_default_stylesheet_is_a_static_file_and_the_theme_properties_are_documented():
    css = (ASSET_DIRECTORY / "papyrus-knowledge.css").read_text(encoding="utf-8")
    documented = (Path(__file__).resolve().parents[3] / "docs" / "knowledge-components.md").read_text(encoding="utf-8")
    for name in sorted(set(re.findall(r"var\((--papyrus-knowledge-[\w-]+)", css))):
        assert name in documented, name


def test_a_page_that_names_an_unknown_attribute_fails_the_build_with_the_file_name():
    created = KnowledgeSite([item("a")], {"knowledge.md": f'{BAND}::include{{kind="block" name="knowledge-trending-strip" colour="red"}}\n'})
    try:
        report = project_all(created.context())
        assert not report.ok or any("knowledge.md" in str(error) for error in report.errors)
    except ValueError as error:
        assert "knowledge.md" in str(error)
    finally:
        created.cleanup()


def test_the_projector_does_not_own_the_snapshot_files(site):
    projector = site.context().projector
    for key in ("_data/knowledge/index.json", "_data/knowledge/clusters.json", "_data/knowledge/entities/acme-loom.json"):
        assert not projector.owns_page_key(key)


# ------------------------------------------------------------------ who accepted and who edited

@pytest.mark.parametrize(
    ("actor", "verb", "text"),
    [
        ({"actor": "ai", "name": None, "on": "2026-10-01"}, "accepted", "Accepted by AI"),
        ({"actor": "ai", "name": "Research agent", "on": "2026-10-01"}, "accepted", "Accepted by AI"),
        ({"actor": "human", "name": "Ada", "on": "2026-10-12"}, "accepted", "Accepted by Ada"),
        ({"actor": "human", "name": None, "on": "2026-10-12"}, "accepted", "Accepted by an editor"),
        ({"actor": "ai", "name": None, "on": "2026-10-01"}, "description", "Edited by AI on 2026-10-01"),
        ({"actor": "human", "name": "Ada", "on": "2026-10-12"}, "description", "Reviewed by Ada on 2026-10-12"),
        ({"actor": "human", "name": None, "on": "2026-10-12"}, "description", "Reviewed by an editor on 2026-10-12"),
    ],
)
def test_attribution_text_names_the_ai_or_the_person(actor, verb, text):
    assert parts.attribution_text(actor, verb) == text
    assert text in parts.attribution(actor, verb) and f'data-actor="{actor["actor"]}"' in parts.attribution(actor, verb)


def test_no_actor_means_no_attribution():
    assert parts.attribution(None, "accepted") == "" and parts.attribution({"actor": "robot"}, "accepted") == ""
    assert parts.attribution_text({"actor": "ai", "name": "Research agent", "on": "2026-10-01"}, "accepted") == "Accepted by AI"


def test_clusters_say_who_accepted_them(tmp_path):
    markup = block("knowledge-clusters", source_for(tmp_path), limit="5")
    assert "Accepted by AI" in markup.split("Wearable looms")[1].split("</li>")[0]
    assert "Accepted by Ada" in markup.split("Fresh theme")[1].split("</li>")[0]


def test_the_concept_of_the_week_says_who_edited_its_description(tmp_path):
    assert "Edited by AI on 2026-10-01" in block("knowledge-concept-of-the-week", source_for(tmp_path))
    human = copy.deepcopy(data.INDEX)
    human["conceptOfTheWeek"]["editedBy"] = data.BY_ADA
    assert "Reviewed by Ada on 2026-10-12" in block("knowledge-concept-of-the-week", source_for(tmp_path / "human", index=human))


def test_the_provenance_part_shows_the_acceptance_and_the_description_edit(tmp_path):
    source = source_for(tmp_path)
    markup = block("knowledge-entity", source, key="acme-loom", part="provenance")
    assert "Accepted by AI" in markup and "Edited by AI on 2026-10-01" in markup
    assert block("knowledge-entity", source, key="gamma-new", part="provenance").count("papyrus-knowledge-attribution") == 1   # no description edit


# ------------------------------------------------------------------ a site under urls.basePath

def test_a_based_site_reads_the_snapshot_under_its_base_path_and_does_not_own_it():
    wiki = item("loom", section="wiki", body=f'{BAND}# Acme Loom\n\n::include{{kind="block" name="knowledge-topic-count"}}\n')
    created = KnowledgeSite([wiki], {"knowledge.md": PAGE}, base="posts", urls={"basePath": "/posts"})
    try:
        context = created.context()
        assert project_all(context).ok
        assert 'papyrus-knowledge-count">7<' in page_text(created, "posts/knowledge/index.html")
        assert not any(key.startswith("_data/") for key in created.keys())
        for key in ("posts/_data/knowledge/index.json", "posts/_data/knowledge/entities/acme-loom.json"):
            assert not context.projector.owns_page_key(key)
    finally:
        created.cleanup()


# ------------------------------------------------------------------ block options (PPY-ddbb84)

def test_clusters_show_at_most_terms_top_terms_and_default_to_five(tmp_path):
    source = source_for(tmp_path)
    assert "loom, wearable, textile" in block("knowledge-clusters", source)
    assert "loom, wearable<" in block("knowledge-clusters", source, terms="2") and "textile" not in block("knowledge-clusters", source, terms="2")
    assert "papyrus-knowledge-terms" not in block("knowledge-clusters", source, terms="0")
    many = copy.deepcopy(data.CLUSTERS)
    many["clusters"][0]["topTerms"] = ["a", "b", "c", "d", "e", "f", "g"]
    assert "a, b, c, d, e<" in block("knowledge-clusters", source_for(tmp_path / "many", clusters=many))


def test_the_trending_list_drops_its_kind_filter_with_filter_false(tmp_path):
    source = source_for(tmp_path)
    assert "kindfilter" in block("knowledge-trending-list", source, filter="true")
    plain = block("knowledge-trending-list", source, filter="false")
    assert "kindfilter" not in plain and "<style" not in plain and "Delta Fade" in plain and "Beta Spool" in plain


def test_the_topic_count_counts_beats_or_entities_and_can_be_a_labelled_link(tmp_path):
    source = source_for(tmp_path)
    assert block("knowledge-topic-count", source, count="beats") == '<span class="papyrus-knowledge-count">7</span>'
    assert block("knowledge-topic-count", source, count="entities") == '<span class="papyrus-knowledge-count">4</span>'
    assert block("knowledge-topic-count", source, href="/topics/", label="All {n} topics") == '<a class="papyrus-knowledge-count" href="/topics/">All 7 topics</a>'
    assert block("knowledge-topic-count", source, count="entities", href="/wiki/", label="{n} concepts") == '<a class="papyrus-knowledge-count" href="/wiki/">4 concepts</a>'
    assert block("knowledge-topic-count", source, href="/topics/") == '<a class="papyrus-knowledge-count" href="/topics/">7</a>'
    assert block("knowledge-topic-count", source, label="<b>{n}</b>") == '<span class="papyrus-knowledge-count">&lt;b&gt;7&lt;/b&gt;</span>'


def test_the_topic_count_link_shows_no_number_when_the_count_is_absent_or_zero(tmp_path):
    empty = KnowledgeSource()
    empty.use_directory(tmp_path / "nothing")
    assert block("knowledge-topic-count", empty, href="/topics/", label="All {n} topics") == ""
    without = {key: value for key, value in data.INDEX.items() if key != "topicCount"}
    assert block("knowledge-topic-count", source_for(tmp_path / "without", index=without), href="/topics/", label="All {n} topics") == ""
    zero = {**data.INDEX, "topicCount": 0}
    assert block("knowledge-topic-count", source_for(tmp_path / "zero", index=zero), href="/topics/", label="All {n} topics") == ""


def test_the_beat_trend_is_the_weekly_series_with_its_counts_as_text(tmp_path):
    markup = block("knowledge-beat", source_for(tmp_path), key="weaving", part="trend")
    assert "<svg" in markup and 'aria-hidden="true"' in markup and len(re.search(r'points="([^"]+)"', markup).group(1).split()) == 8
    assert "36 items in the last 8 weeks" in markup and "7 items in the latest week" in markup and "2, 3, 4, 4, 5, 5, 6, 7" in markup
    assert block("knowledge-beat", source_for(tmp_path), key="quiet", part="trend") == ""
    assert block("knowledge-beat", source_for(tmp_path), key="missing", part="trend") == ""


def test_the_beat_entities_are_its_top_accepted_entities_in_the_snapshots_order(tmp_path):
    source = source_for(tmp_path)
    markup = block("knowledge-beat", source, key="weaving", part="entities")
    assert re.findall(r"chip-name\">([^<]+)<", markup) == ["Acme Loom", "Beta Spool", "Delta Fade"]      # a key the index does not hold is skipped
    assert 'href="/wiki/acme-loom/"' in markup
    assert re.findall(r"chip-name\">([^<]+)<", block("knowledge-beat", source, key="weaving", part="entities", limit="1")) == ["Acme Loom"]
    assert block("knowledge-beat", source, key="quiet", part="entities") == ""


def test_the_beat_clusters_are_the_accepted_clusters_that_overlap_the_beat(tmp_path):
    source = source_for(tmp_path)
    markup = block("knowledge-beat", source, key="weaving", part="clusters")
    assert "Wearable looms" in markup and "Fresh theme" not in markup and "secret" not in markup        # c-3 is unaccepted: hidden
    assert "loom, wearable, textile" in markup
    assert block("knowledge-beat", source, key="quiet", part="clusters") == ""
    absent = KnowledgeSource()
    absent.use_directory(tmp_path / "nothing")
    assert block("knowledge-beat", absent, key="weaving", part="trend") == block("knowledge-beat", absent, key="weaving", part="clusters") == ""


@pytest.mark.parametrize("attributes", [
    {"name": "knowledge-beat", "part": "trend"},
    {"name": "knowledge-beat", "key": "weaving", "part": "graph"},
    {"name": "knowledge-beat", "key": "weaving"},
    {"name": "knowledge-trending-list", "filter": "maybe"},
    {"name": "knowledge-clusters", "terms": "some"},
    {"name": "knowledge-topic-count", "count": "everything"},
    {"name": "knowledge-topic-count", "href": "javascript:alert(1)"},
    {"name": "knowledge-topic-count", "colour": "red"},
])
def test_bad_option_values_are_build_errors(tmp_path, attributes):
    with pytest.raises(ValueError, match="test.md"):
        knowledge_blocks.render_block({"kind": "block", **attributes}, source_for(tmp_path), "test.md")


# ------------------------------------------------------------------ the hooks API

def lookup(tmp_path, **files):
    return KnowledgeLookup(source_for(tmp_path, **files))


def test_entity_for_finds_an_accepted_entity_by_name_or_alias_ignoring_case_and_spaces(tmp_path):
    found = lookup(tmp_path)
    expected = {"key": "acme-loom", "name": "Acme Loom", "kind": "maker", "href": "/wiki/acme-loom/", "state": "accepted"}
    assert found.entity_for("maker", "Acme Loom") == expected
    assert found.entity_for("Maker", "  acme   LOOM ") == expected                  # the kind label works too
    assert found.entity_for("maker", "loom co") == expected                          # an alias
    assert found.entity_for(None, "Acme") == expected and found.entity_for("", "Acme") == expected
    assert found.entity_for("tool", "Acme Loom") is None                            # wrong kind
    assert found.entity_for("maker", "Nobody") is None
    assert found.entity_for("maker", "Gamma New")["href"] is None                    # no page: no link


def test_entity_for_does_not_guess_between_kinds_and_is_empty_without_a_snapshot(tmp_path):
    shared = copy.deepcopy(data.INDEX)
    shared["entities"].append(data.entity("acme-tool", "tool", "Acme Loom", 12, [1] * 8, 4, 4, 0, href="/wiki/acme-tool/"))
    both = lookup(tmp_path, index=shared)
    assert both.entity_for(None, "acme loom") is None
    assert both.entity_for("tool", "acme loom")["key"] == "acme-tool"
    empty = KnowledgeSource()
    empty.use_directory(tmp_path / "nothing")
    assert KnowledgeLookup(empty).entity_for("maker", "Acme Loom") is None and KnowledgeLookup().entity_for("maker", "x") is None


def test_chip_html_is_the_standard_chip(tmp_path):
    found = lookup(tmp_path)
    chip = found.chip_html(found.entity_for("maker", "Acme"))
    assert chip == parts.entity_chip("Maker", "Acme Loom", kind="maker", href="/wiki/acme-loom/")
    assert 'class="papyrus-knowledge-chip"' in chip and 'href="/wiki/acme-loom/"' in chip
    assert found.chip_html(None) == ""
    assert found.chip_html(found.entity_for("maker", "Gamma New")).startswith("<span ")


HOOKS = '''
def item_decorator(html, summary, site):
    chip = site.knowledge.chip_html(site.knowledge.entity_for("maker", "acme"))
    return html + '<p class="decorated">' + chip + "</p>"
'''
PLAIN_HOOKS = '''
def item_decorator(html, summary):
    return html + '<p class="plain-decorated"></p>'
'''


def decorated_site(hooks: str, **kwargs):
    created = KnowledgeSite([item("loom-news", section="posts")], {"knowledge.md": PAGE, "hooks.py": hooks}, hooks="hooks.py", **kwargs)
    return created


def test_item_decorator_may_take_site_and_link_entities_from_the_snapshot():
    created = decorated_site(HOOKS)
    try:
        assert project_all(created.context()).ok
        page = created.text("loom-news.html")
        assert '<p class="decorated"><a class="papyrus-knowledge-chip" data-kind="maker" href="/wiki/acme-loom/">' in page
    finally:
        created.cleanup()


def test_item_decorator_without_site_is_called_as_before_and_without_a_snapshot_the_lookup_is_empty():
    created = decorated_site(PLAIN_HOOKS)
    try:
        assert project_all(created.context()).ok
        assert '<p class="plain-decorated"></p>' in created.text("loom-news.html")
    finally:
        created.cleanup()
    bare = decorated_site(HOOKS, snapshot=False)
    try:
        assert project_all(bare.context()).ok
        assert '<p class="decorated"></p>' in bare.text("loom-news.html")
    finally:
        bare.cleanup()


def test_a_changed_snapshot_renders_the_decorated_item_again():
    created = decorated_site(HOOKS)
    try:
        context = created.context()
        assert project_all(context).ok
        changed = copy.deepcopy(data.INDEX)
        changed["entities"][0]["href"] = "/wiki/moved/"
        data.write(created.out / "_data" / "knowledge", index=changed)
        assert project_all(context).ok
        assert 'href="/wiki/moved/"' in created.text("loom-news.html")
    finally:
        created.cleanup()


# ------------------------------------------------------------------ the wiki listing page size

def test_a_site_sets_the_wiki_listing_page_size_in_urls_sections():
    pages = [item(f"page-{number}", section="wiki", type="wiki_page") for number in range(5)]
    created = DirectorySite(settings(urls={"style": "directory", "sections": {"wiki": {"label": "Wiki", "pageSize": 2}}}, listings={"types": ["article", "wiki_page"], "pageSize": 10}), pages)
    try:
        assert created.project_all().ok
        keys = created.keys()
        assert "wiki/index.html" in keys and "wiki/page/2/index.html" in keys and "wiki/page/3/index.html" in keys and "wiki/page/4/index.html" not in keys
    finally:
        created.cleanup()
