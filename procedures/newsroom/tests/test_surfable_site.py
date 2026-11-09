"""Surfable site (PPY-6bd9810f): a cited source links to our own Story when one is based on it, and a Story page carries its concept links."""

from __future__ import annotations

import json

from papyrus_content.projection.directory_source import DirectoryContentSource
from papyrus_content.projection.engine import ProjectionContext, project_all
from papyrus_content.projection.site_relations import SiteRelations, concept_slug, read_site_relations
from papyrus_content.projection.standard.projector import StandardMarkusProjector
from papyrus_content.projection.writers import LocalDirectoryWriter
from procedures.newsroom.tests.fake_client import FakeAuthoringClient
from procedures.newsroom.tests.standard_frontend_content_support import DirectorySite, item, settings

CITATIONS = {
    "cited": {"type": "webpage", "title": "Cited Page", "URL": "https://www.example.org/outside/?utm_source=x#top"},
    "gone": {"type": "webpage", "title": "Elsewhere Page", "URL": "https://example.net/elsewhere"},
}
BODY = "As shown [@cited] and [@gone].\n\n::citations\n"


class RelatedSource(DirectoryContentSource):
    """Files carry no relations; this source hands the projection a fixed set."""

    relations = SiteRelations()

    def site_relations(self, summaries):
        return self.relations


def project(items, relations: SiteRelations) -> DirectorySite:
    created = DirectorySite(settings(urls={"style": "directory"}, citations={"externalIcon": True}), items)
    source = RelatedSource(created.content)
    source.relations = relations
    projector = StandardMarkusProjector.from_static_directory(created.static, environ=created.environ)
    report = project_all(ProjectionContext(source=source, projector=projector, writer=LocalDirectoryWriter(created.out)))
    assert report.ok, report.errors
    return created


def story(slug: str, **front):
    return item(slug, section="posts", body=BODY if slug == "reader" else None, **front)


def ids(*slugs: str) -> tuple[str, ...]:
    return tuple(f"file:posts/{slug}.md" for slug in slugs)


def test_a_cited_source_links_to_our_story_based_on_it_and_not_out():
    created = project([item("reader", section="posts", body=BODY, citations=CITATIONS), story("based")], SiteRelations(based_on={"example.org/outside": ids("based")}))
    try:
        page = created.text("reader/index.html")
        assert '<a href="/based/">' in page and "Cited Page" in page
        assert "/outside" not in page   # no outside address, and no icon on the entry that stays here
        assert page.count('data-icon="external-link"') == 1   # only the other source goes out
        assert '<a class="citation-external" href="https://example.net/elsewhere" target="_blank" rel="noopener noreferrer">' in page
    finally:
        created.cleanup()


def test_the_newest_story_wins_and_a_story_never_links_to_itself():
    items = [item("reader", section="posts", body=BODY, citations=CITATIONS), story("newest"), story("older")]
    created = project(items, SiteRelations(based_on={"example.org/outside": ids("newest", "older")}))
    try:
        assert '<a href="/newest/">' in created.text("reader/index.html")
    finally:
        created.cleanup()
    own = project(items, SiteRelations(based_on={"example.org/outside": ids("reader", "older")}))
    try:
        assert '<a href="/older/">' in own.text("reader/index.html")
    finally:
        own.cleanup()
    alone = project(items[:1], SiteRelations(based_on={"example.org/outside": ids("reader")}))
    try:
        page = alone.text("reader/index.html")
        assert 'href="https://www.example.org/outside/?utm_source=x#top"' in page and page.count('data-icon="external-link"') == 2
    finally:
        alone.cleanup()


def test_a_source_nobody_is_based_on_links_out_in_a_new_tab_with_the_icon():
    created = project([item("reader", section="posts", body=BODY, citations=CITATIONS)], SiteRelations())
    try:
        page = created.text("reader/index.html")
        assert page.count('target="_blank" rel="noopener noreferrer"') == 2 and page.count('data-icon="external-link"') == 2
    finally:
        created.cleanup()


def concept_page(slug: str, title: str):
    return item(slug, section="wiki", type="wiki_page", title=title, entityKey=slug)


def test_a_story_page_gets_the_public_concept_pages_its_relations_reach_most_used_first():
    items = [item("one", section="posts"), item("two", section="posts"), concept_page("alpha", "Alpha"), concept_page("beta", "Beta")]
    relations = SiteRelations(concepts={"file:posts/one.md": ("beta", "alpha", "hidden"), "file:posts/two.md": ("beta",)})
    created = DirectorySite(settings(urls={"style": "directory"}), items)
    source = RelatedSource(created.content)
    source.relations = relations
    projector = StandardMarkusProjector.from_static_directory(created.static, environ=created.environ)
    site = source.site_index()
    site = type(site)(items=site.items, load_item=site.load_item, relations=relations)
    try:
        by_path = {summary.output_path: summary for summary in site.items}
        links = projector._concept_links(site, by_path["posts/one.md"])
        assert [(link["slug"], link["href"], link["stories"]) for link in links] == [("beta", "/beta/", 2), ("alpha", "/alpha/", 1)]   # "hidden" has no page
        assert projector._concept_links(site, by_path["wiki/alpha.md"]) == ()
    finally:
        created.cleanup()


def test_a_change_in_the_relations_changes_the_shared_inputs_so_item_pages_are_rendered_again():
    created = DirectorySite(settings(urls={"style": "directory"}), [item("one", section="posts")])
    source = RelatedSource(created.content)
    projector = StandardMarkusProjector.from_static_directory(created.static, environ=created.environ)
    try:
        before = projector.shared_inputs(source.site_index())
        source.relations = SiteRelations(based_on={"example.org/outside": ids("one")})
        assert projector.shared_inputs(source.site_index()) != before
    finally:
        created.cleanup()


# ------------------------------------------------------------------ the read

def relation(story: str, predicate: str, kind: str, lineage: str, object_id: str, **extra) -> dict:
    return {
        "id": f"{story}-{object_id}", "relationState": "current", "predicate": predicate, "subjectKind": "item", "subjectLineageId": story,
        "subjectStateKey": f"item#{story}#current", "objectKind": kind, "objectId": object_id, "objectLineageId": lineage, **extra,
    }


def seeded() -> FakeAuthoringClient:
    based = json.dumps({"role": "based_on"})
    return FakeAuthoringClient({
        "SemanticRelation": [
            relation("L1", "uses_evidence", "reference", "R1", "ref-1", metadata=based),
            relation("L2", "uses_evidence", "reference", "R2", "ref-2", metadata=based),
            relation("L3", "uses_evidence", "reference", "R1", "ref-1", metadata=json.dumps({"role": "cited"})),
            relation("L1", "mentions", "semanticNode", "semantic-node-editor_concept--alpha", "node-alpha"),
            relation("L1", "related_to", "semanticNode", "semantic-node-editor_concept--spam", "node-spam"),
            relation("L1", "mentions", "semanticNode", "semantic-node-editor_concept--nopage", "node-nopage"),
            relation("L1", "related_to", "reference", "R9", "ref-9"),
        ],
        "Reference": [
            {"id": "ref-1", "curationStatus": "accepted", "sourceUri": "https://www.example.org/outside/?utm_medium=y"},
            {"id": "ref-2", "curationStatus": "rejected", "sourceUri": "https://example.net/rejected"},
        ],
        "SemanticNode": [{"id": "node-alpha", "status": "accepted"}, {"id": "node-spam", "status": "rejected"}, {"id": "node-nopage", "status": "accepted"}],
    })


def test_the_read_maps_accepted_references_to_the_stories_based_on_them_and_keeps_concepts_with_a_page():
    stories = [("item-1", "L1", "2026-11-01"), ("item-2", "L2", "2026-11-02"), ("item-3", "L3", "2026-11-03")]
    found = read_site_relations(seeded(), stories, ["alpha", "spam"])
    assert dict(found.based_on) == {"example.org/outside": ("item-1",)}   # L3 only cites it, ref-2 is not accepted
    assert dict(found.concepts) == {"item-1": ("alpha",)}                 # spam is rejected, nopage has no page, a related_to between References is not a concept


def test_the_read_uses_indexes_only_and_batches_nothing_it_does_not_need():
    client = seeded()
    read_site_relations(client, [("item-1", "L1", None), ("item-2", "L2", None)], ["alpha"])
    kinds = {call[0] for call in client.calls}
    assert "list" not in kinds   # no whole-table list
    assert {call[1] for call in client.calls if call[0] == "list_by_index"} == {"semanticRelationsBySubjectState", "semanticRelationsByObjectState"}


def test_the_newest_published_story_comes_first():
    client = FakeAuthoringClient({
        "SemanticRelation": [relation(lineage, "uses_evidence", "reference", "R1", "ref-1", metadata=json.dumps({"role": "based_on"})) for lineage in ("L1", "L2")],
        "Reference": [{"id": "ref-1", "curationStatus": "accepted", "sourceUri": "https://example.org/a"}],
    })
    found = read_site_relations(client, [("old", "L1", "2026-01-01"), ("new", "L2", "2026-02-01")], [])
    assert found.based_on["example.org/a"] == ("new", "old")


def test_a_concept_slug_is_what_follows_the_double_dash():
    assert concept_slug("semantic-node-editor_concept--machine-learning") == "machine-learning"
    assert concept_slug("editor_concept--a--b") == "a--b"
    assert concept_slug("something-else") is None


# ------------------------------------------------------------------ related Stories

def story_link(subject: str, other: str) -> dict:
    return relation(subject, "see_also", "item", other, f"item-{other}", subjectKind="item", objectStateKey=f"item#{other}#current")


def test_related_stories_are_read_in_both_directions_and_only_when_published():
    client = FakeAuthoringClient({"SemanticRelation": [story_link("L1", "L2"), story_link("L3", "L1"), story_link("L1", "L9"), story_link("L1", "L1")]})
    found = read_site_relations(client, [("a", "L1", None), ("b", "L2", None), ("c", "L3", None)], [])
    assert dict(found.related) == {"a": ("b", "c"), "b": ("a",), "c": ("a",)}   # L9 is not published; a Story is not related to itself


def test_a_page_lists_its_related_published_stories_with_their_type_and_never_itself():
    items = [item("one", section="posts"), item("two", section="posts", image="/two.png", type="article"), item("three", section="posts")]
    relations = SiteRelations(related={"file:posts/one.md": ("file:posts/two.md", "file:posts/one.md", "file:posts/gone.md", "file:posts/three.md")})
    created = DirectorySite(settings(urls={"style": "directory"}), items)
    source = RelatedSource(created.content)
    source.relations = relations
    projector = StandardMarkusProjector.from_static_directory(created.static, environ=created.environ)
    site = source.site_index()
    site = type(site)(items=site.items, load_item=site.load_item, relations=relations)
    try:
        one = next(summary for summary in site.items if summary.slug == "one")
        links = projector._related_stories(site, one)
        assert sorted(link["title"] for link in links) == ["THREE", "TWO"]
        assert all(link["url"] and link["itemId"] != one.item_id for link in links)
    finally:
        created.cleanup()


def test_a_client_with_no_relation_index_gives_no_relations_and_no_error():
    from papyrus_content.projection.url_compare import SnapshotClient

    found = read_site_relations(SnapshotClient([{"id": "p1", "sourceItemId": "i1"}]), [("i1", "L1", None)], ["alpha"])
    assert not found.based_on and not found.concepts and not found.related
    assert not read_site_relations(object(), [("i1", "L1", None)], ["alpha"]).related


def test_outside_links_are_the_original_markup_unless_the_site_opts_in_to_the_icon():
    created = DirectorySite(settings(urls={"style": "directory"}), [item("reader", section="posts", body=BODY, citations=CITATIONS)])
    try:
        assert created.project_all().ok
        page = created.text("reader/index.html")
        assert '<a href="https://example.net/elsewhere" target="_blank" rel="noopener noreferrer">' in page
        assert "citation-external" not in page and 'data-icon="external-link"' not in page
    finally:
        created.cleanup()
