"""Surfable site (features_backend/surfable-site.feature): thin steps over the helpers of the unit tests."""

from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.site_relations import SiteRelations, read_site_relations  # noqa: E402
from procedures.newsroom.tests import test_surfable_site as t  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402
from procedures.newsroom.tests.standard_frontend_content_support import item  # noqa: E402

ICON = 'data-icon="external-link"'


@given("a Story that cites two sources and a published Story based on the first")
def two_sources(context) -> None:
    context.items = [item("reader", section="posts", body=t.BODY, citations=t.CITATIONS), t.story("based")]
    context.relations = SiteRelations(based_on={"example.org/outside": t.ids("based")})


@given("a Story that cites a source and two published Stories based on it")
def two_based(context) -> None:
    context.items = [item("reader", section="posts", body=t.BODY, citations=t.CITATIONS), t.story("newest"), t.story("older")]
    context.relations = SiteRelations(based_on={"example.org/outside": t.ids("newest", "older")})


@given("a Story that cites a source it is itself based on")
def itself(context) -> None:
    context.items = [item("reader", section="posts", body=t.BODY, citations=t.CITATIONS)]
    context.relations = SiteRelations(based_on={"example.org/outside": t.ids("reader")})


@when("the site renders the citing Story")
def render(context) -> None:
    context.site = t.project(context.items, context.relations)
    context.add_cleanup(context.site.cleanup)
    context.page = context.site.text("reader/index.html")


@then("the first source links to the other Story and carries no icon")
def first_internal(context) -> None:
    assert '<a href="/based/">' in context.page and "/outside" not in context.page and context.page.count(ICON) == 1


@then("the second source links out in a new tab with the external-link icon")
def second_external(context) -> None:
    assert '<a class="citation-external" href="https://example.net/elsewhere" target="_blank" rel="noopener noreferrer">' in context.page


@then("the first source links to the newest of the two")
def newest(context) -> None:
    assert '<a href="/newest/">' in context.page and "/older/" not in context.page


@then("the source links out in a new tab with the external-link icon")
def source_external(context) -> None:
    assert 'href="https://www.example.org/outside/?utm_source=x#top" target="_blank" rel="noopener noreferrer"' in context.page and context.page.count(ICON) == 2


# -- the read

@given("Stories that cite, consult or are based on References, one of them not accepted")
@given("Stories related to concepts, one rejected, one without a public page")
@given("Stories with relations")
def seeded(context) -> None:
    context.client = t.seeded()
    context.stories = [("item-1", "L1", "2026-11-01"), ("item-2", "L2", "2026-11-02"), ("item-3", "L3", "2026-11-03")]


@given("two Stories related to each other by one relation and a third pointing at an unpublished Story")
def related(context) -> None:
    context.client = FakeAuthoringClient({"SemanticRelation": [t.story_link("L1", "L2"), t.story_link("L3", "L9")]})
    context.stories = [("a", "L1", None), ("b", "L2", None), ("c", "L3", None)]


@when("the relations of the published Stories are read")
def read(context) -> None:
    context.found = read_site_relations(context.client, context.stories, ["alpha", "spam"])


@then("only the accepted Reference's address is linked, to the Story based on it")
def accepted_only(context) -> None:
    assert dict(context.found.based_on) == {"example.org/outside": ("item-1",)}


@then("each Story keeps only its accepted concepts that have a public page")
def concepts_kept(context) -> None:
    assert dict(context.found.concepts) == {"item-1": ("alpha",)}


@then("a page lists them most used first and then by name")
def ordered(context) -> None:
    t.test_a_story_page_gets_the_public_concept_pages_its_relations_reach_most_used_first()


@then("each of the two is related to the other and the third is related to none")
def related_both(context) -> None:
    assert dict(context.found.related) == {"a": ("b",), "b": ("a",)}


@then("no table is listed and only the subject and object indexes are queried")
def index_only(context) -> None:
    assert "list" not in {call[0] for call in context.client.calls}
    assert {call[1] for call in context.client.calls if call[0] == "list_by_index"} <= {"semanticRelationsBySubjectState", "semanticRelationsByObjectState"}
