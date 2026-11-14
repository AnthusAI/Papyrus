"""Link suggestions, related concepts and concept search (features_backend/suggest-links.feature). A stand-in site and index; no network, login, model or AWS."""
from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.concept_search import search_concepts  # noqa: E402
from papyrus_content.link_suggestions import related_concepts, suggest_links  # noqa: E402
from test_concept_search import FakeIndex, with_extra_nodes  # noqa: E402
from test_link_suggestions import site  # noqa: E402


def _written(client) -> list:
    return [call for call in client.calls if call[0] in ("create", "update", "delete", "upsert")]


@given("a stand-in site with stories, References and concepts for link suggestions")
def _site(context):
    context.site = with_extra_nodes(site())
    context.index = FakeIndex()


@when('I ask for link suggestions for the story "{story}"')
def _suggest(context, story):
    context.suggestions = suggest_links(context.site, story)


@then('the first article is "{title}" with the shared concepts and a "papyrus stories link-story" command')
def _first_article(context, title):
    first = context.suggestions["candidates"]["articles"][0]
    assert first["title"] == title and first["shared"] and first["command"].startswith("papyrus stories link-story"), first


@then('the first related finding carries a "--reference" command')
def _first_reference(context):
    assert "--reference" in context.suggestions["candidates"]["references"][0]["command"]


@then("no row was written to the site")
def _nothing_written(context):
    assert _written(context.site) == []


@then("no candidate is the story itself, a story already linked by see also, a draft story, a Reference already used as evidence, or a Reference that is not accepted")
def _exclusions(context):
    everything = {item["id"] for kind in context.suggestions["candidates"].values() for item in kind}
    assert {"s0", "s3", "s5", "ref-3", "ref-4"}.isdisjoint(everything), everything


@then('the article "{title}" is found "{path}"')
def _path(context, title, path):
    item = next(item for item in context.suggestions["candidates"]["articles"] if item["title"] == title)
    assert item["path"] == path, item


@when('I ask for the concepts related to "{concept}"')
def _related(context, concept):
    context.related = related_concepts(context.site, concept)


@then('the first related concept is "{name}", confirmed, with the explanation an editor wrote')
def _first_related(context, name):
    first = context.related["related"][0]
    assert (first["name"], first["reason"]) == (name, "confirmed") and first["explanation"], first


@given('a concept index in which "Privacy" is far from the question but named exactly')
def _index(context):
    context.index = FakeIndex()


@when('I search the concepts for "{text}"')
def _search(context, text):
    context.search = search_concepts(context.site, context.index, text, limit=8)


@then('the first result is "{name}" as a name match')
def _first_name(context, name):
    first = context.search["results"][0]
    assert first["name"] == name and first["reason"].startswith("name match"), first


@then('the first result is "{name}" as a meaning match')
def _first_meaning(context, name):
    first = context.search["results"][0]
    assert first["name"] == name and first["reason"] == "meaning", first


@then('the popular concept "{name}" is shown with its counts but ranks lower')
def _popular(context, name):
    names = [entry["name"] for entry in context.search["results"]]
    popular = next(entry for entry in context.search["results"] if entry["name"] == name)
    assert names.index(name) > 0 and popular["stories"] > 5, popular


@given('a second accepted concept with the same name as "{name}"')
def _twin(context, name):
    assert any(node["displayName"] == name for node in context.site.tables["SemanticNode"].values())


@then("both are flagged as possible duplicates of each other")
def _duplicates(context):
    flagged = {entry["lineageId"] for entry in context.search["results"] if entry.get("duplicates")}
    assert flagged == {"voice", "voice2"}, flagged


@when("the index holds a vector for only two of the accepted concepts")
def _stale(context):
    context.search = search_concepts(context.site, FakeIndex(present=["voice", "privacy"]), "anything", limit=5)


@then("the search warns that the index is stale and prints the vector-index command")
def _warns(context):
    health = context.search["health"]
    assert health["status"] == "stale" and "knowledge-vector-index --action sync" in health["message"], health
