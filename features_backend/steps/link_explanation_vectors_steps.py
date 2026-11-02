"""features_backend/link-explanation-vectors.feature. Fakes only; the unit tests in procedures/newsroom/tests/test_link_explanation_vectors.py share them."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import test_link_explanation_vectors as unit  # noqa: E402
from test_pending_reference_vectors import FakeIndex, reference  # noqa: E402


def start(context, relations, nodes=(), references=None, deny_delete=False):
    context.index = FakeIndex(deny_delete=deny_delete)
    context.graph = unit.Graph(relations, nodes)
    context.references = references or unit.two_accepted()


def run_sync(context):
    context.stats = unit.sync(context.graph, context.references, context.index)


@given('the accepted References "{first}" and "{second}" linked by an editor who explained why')
def step_linked(context, first, second):
    context.names = (first, second)
    start(context, [unit.link("ab", first, second)], references=[reference(first, "accepted"), reference(second, "accepted")])


@given('the accepted References "{first}" and "{second}" linked by an editor who explained why in an index where deleting is not allowed')
def step_linked_no_delete(context, first, second):
    context.names = (first, second)
    start(context, [unit.link("ab", first, second)], references=[reference(first, "accepted"), reference(second, "accepted")], deny_delete=True)


@given('the accepted Reference "{first}" tagged with the concept "{name}" by an editor who explained why')
def step_tagged(context, first, name):
    tag = unit.link("ac", first, "node-1", kind="reference.concept", object_kind="semanticNode")
    start(context, [tag], nodes=[{**unit.NODE, "displayName": name}], references=[reference(first, "accepted")])


@given("links with no note, suggested links, rejected links and a link to a Reference that is still pending")
def step_unqualified(context):
    rows = [
        unit.link("n1", "a", "b", note=""),
        unit.link("n2", "a", "b", state="suggested", decision=None, provenance="suggested"),
        unit.link("n3", "a", "b", state="rejected", decision="rejected"),
        unit.link("n4", "a", "c"),
    ]
    start(context, rows, references=[reference("a", "accepted"), reference("b", "accepted"), reference("c", "pending")])


@given("the explanation index has been synced")
def step_synced(context):
    run_sync(context)


@when("the explanation index is synced")
@when("the explanation index is synced again")
def step_sync(context):
    run_sync(context)


@when("the editor rewrites the explanation and the explanation index is synced")
def step_rewrite(context):
    context.graph.relations = [unit.link("ab", *context.names, note="Corrected: they disagree on what counts as a failure.")]
    run_sync(context)


@when("the link is rejected and the explanation index is synced")
def step_reject(context):
    context.graph.relations = [unit.link("ab", *context.names, state="rejected", decision="rejected")]
    run_sync(context)


@then('there is one explanation vector that names "{first}", "{second}" and the explanation')
def step_one_vector(context, first, second):
    [stored] = unit.explanation_vectors(context.index).values()
    text = stored["metadata"]["text"]
    assert f"Title {first}" in text or first in text, text
    assert f"Title {second}" in text or second in text, text
    assert unit.NOTE in text, text


@then("it records both lineage ids, the link's id, its predicate and who decided")
def step_metadata(context):
    [stored] = unit.explanation_vectors(context.index).values()
    metadata = stored["metadata"]
    assert (metadata["subjectLineageId"], metadata["objectLineageId"]) == (f"lin-{context.names[0]}", f"lin-{context.names[1]}"), metadata
    assert (metadata["relationId"], metadata["predicate"], metadata["decidedBy"]) == ("rel-ab", "related_to", "an editor"), metadata


@then("there are no explanation vectors")
def step_none(context):
    assert unit.explanation_vectors(context.index) == {}, context.index.stored


@then("nothing is embedded")
def step_nothing_embedded(context):
    assert context.stats["vectorsWritten"] == 0 and context.stats["linkExplanationsSkippedUnchanged"] == 1, context.stats


@then("the explanation vector holds the new text")
def step_new_text(context):
    [stored] = unit.explanation_vectors(context.index).values()
    assert "Corrected" in stored["metadata"]["text"], stored


@then("the explanation vector is marked withdrawn")
def step_withdrawn(context):
    [stored] = unit.explanation_vectors(context.index).values()
    context.withdrawn = stored["metadata"]
    assert context.withdrawn["curationStatus"] == "withdrawn", context.withdrawn


@then("a search that the index answers with it returns nothing")
def step_search_nothing(context):
    assert unit.query({}, [context.withdrawn]) == []


# --- the query engine and the audience ---------------------------------------------------------------------------------------------------------


@given("an index that answers a question with an editor's explanation of a link")
def step_answers(context):
    context.unit = unit


@when("the newsroom asks the internal knowledge query")
def step_ask_internal(context):
    context.result = unit.ask()


@when("a request for a public reader asks the knowledge query")
def step_ask_public(context):
    context.result = unit.ask({"audience": "public"})


@then("the result has an explanation attributed to the editor, with the text and a link to each Reference")
def step_result(context):
    [found] = context.result["structured"]["linkExplanations"]
    assert found["attribution"].startswith("Editor's explanation") and found["explanation"] == unit.NOTE, found
    assert [end["objectUri"] for end in found["ends"]] == ["papyrus://reference/lin-a", "papyrus://reference/lin-b"], found["ends"]


@then("the context text carries the explanation under the editor's attribution")
def step_context(context):
    text = context.result["context"]["text"]
    assert "Editor's explanation" in text and unit.NOTE in text, text


@then("the result holds no explanation and its text does not contain the explanation")
def step_public_result(context):
    assert context.result["structured"]["linkExplanations"] == []
    assert unit.NOTE not in json.dumps(context.result)


@then("the search filter excludes explanation vectors for the public request")
def step_filter(context):
    provider = unit.S3VectorsProvider(vector_index_arn="arn:test:index")
    assert {"vectorKind": {"$ne": "link_explanation"}} in provider._metadata_filter({"audience": "public"})["$and"]


@then("the search drops an explanation vector the index returns for the public request anyway")
def step_post_filter(context):
    assert unit.query({"audience": "public"}, [unit.EXPLANATION_METADATA]) == []


@given("the vector kinds that suggestions and context packs ask the index for")
def step_kinds(context):
    from papyrus_content import reference_suggestions
    from papyrus_content.ideas import context_packs

    context.kinds = {*reference_suggestions.CONCEPT_VECTOR_KINDS, reference_suggestions.REFERENCE_SUMMARY_VECTOR_KIND, context_packs.REFERENCE_SUMMARY_VECTOR_KIND}


@then("explanation vectors are not among them")
def step_not_among(context):
    assert "link_explanation" not in context.kinds, context.kinds
