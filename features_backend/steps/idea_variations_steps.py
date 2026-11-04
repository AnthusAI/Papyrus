"""An idea run offers variations of each idea (features_backend/idea-variations.feature). The backend, the pages and the model are the fakes of the other idea
features (idea_more_than_summary_steps.py); the steps here add Stories, concepts and the writer of the other versions."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from ideas_fixtures import NOW  # noqa: E402
from papyrus_content import story_variations  # noqa: E402
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient  # noqa: E402
from papyrus_content.ideas import monitor_stories, variations  # noqa: E402
from papyrus_content.ideas.pack_stories import CostMeter  # noqa: E402
from test_idea_more_than_summary import ADDS, RESTATES, Model, sentence, story  # noqa: E402
from test_monitor_stories import PAGE_TEXT  # noqa: E402

from idea_more_than_summary_steps import client_of, held, knowledge_of, last, row_of, run_ideas  # noqa: E402

QUOTATIONS = "A tool that checks quotations"
STORY = "How archives keep quotations honest"
CONCEPT_LINEAGE = "concept-source-audits"
IDEA_HEADLINE = "Foo checks claims against sources"

#: The other versions, one per kind of option. Each rests on its own handle and shares a content word with what it cites.
VERSIONS = {
    "R1": {
        "point": "Quotation checking covers what claim checking alone leaves open.",
        "headline": ("Quotation checking covers what claim checking alone leaves open", "I1"),
        "dek": ("A tool that checks quotations against archives covers a gap that claim checking leaves open.", "R1"),
        "body": [("Foo is an open tool that checks claims against their sources.", "I1"), ("A tool that checks quotations against archives covers the quotations that claim checking leaves unchecked.", "R1", "I1")],
    },
    "S1": {
        "point": "Archives are where the quotations Foo cannot check have to be settled.",
        "headline": ("Archives settle the quotations that Foo cannot check", "I1"),
        "dek": ("A story on how archives keep quotations honest shows where claim checking has to hand over.", "S1"),
        "body": [("Foo is an open tool that checks claims against their sources.", "I1"), ("The story on how archives keep quotations honest shows the quotations that claim checking cannot settle.", "S1", "I1")],
    },
    "C1": {
        "point": "Source audits are the longer-running work that Foo's claim checking feeds.",
        "headline": ("Foo feeds the longer work of source audits", "I1"),
        "dek": ("Source audits trace where a claim came from, work that Foo's claim checking starts.", "C1"),
        "body": [("Foo is an open tool that checks claims against their sources.", "I1"), ("Source audits trace where a claim came from, which is what each claim check begins.", "C1", "I1")],
    },
}


def answer_of(anchor: str, *, point: str | None = None, headline: str | None = None, cites_anchor: bool = True) -> dict:
    made = VERSIONS[anchor]
    dek = made["dek"] if cites_anchor else (made["dek"][0], "I1")
    body = made["body"] if cites_anchor else [(text, "I1") for text, *_ in made["body"]]
    return {
        "anchor": anchor, "point": made["point"] if point is None else point,
        "headline": sentence(*((headline, "I1") if headline else made["headline"])), "dek": sentence(*dek), "section": "Tools",
        "paragraphs": [{"sentences": [sentence(*entry) for entry in body]}],
    }


def versions_of(context) -> list[dict]:
    if not hasattr(context, "written"):
        context.written = []
    return context.written


def write_versions(context, answer: dict) -> None:
    versions_of(context).append(answer)
    held(context).model.variations = {"variations": versions_of(context)}


def backend(context):
    """The run's fake backend, taught the reads variations make: concepts, Stories and their versions."""
    client = client_of(context)
    if not hasattr(client, "variation_world"):
        world = SimpleNamespace(nodes=[], subject_relations={}, stories={}, incoming={}, failing=False)
        client.variation_world = world
        records, by_index, objects, subjects, create = client.list_records, client.list_by_index, client.list_semantic_relations_by_object_state, client.list_semantic_relations_by_subject_state, client.create_record

        client.list_records = lambda model: list(world.nodes) if model == "SemanticNode" else records(model)
        client.list_by_index = lambda index, key: list(world.stories.get(key, [])) if index == "itemsByLineageAndVersion" else by_index(index, key)
        client.list_semantic_relations_by_object_state = lambda key: [*objects(key), *world.incoming.get(key, [])]
        client.list_semantic_relations_by_subject_state = lambda key: [*subjects(key), *world.subject_relations.get(key.split("#")[1], [])]

        def refusing(model, payload):
            if model == "StoryVariation" and world.failing:
                raise RuntimeError("Not Authorized to access createStoryVariation on type Mutation")
            return create(model, payload)

        client.create_record = refusing
    return client.variation_world


def the_story(title: str, stage: str) -> dict:
    lineage = "item-" + title.lower().replace(" ", "-")
    return {"id": lineage + "-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current", "versionCreatedAt": "2026-10-01T00:00:00Z", "type": "article", "stage": stage,
            "headline": title, "title": title, "deck": "Quotations and the archives that settle them."}


def rest_on(context, title: str, reference_title: str, stage: str) -> None:
    world = backend(context)
    story = the_story(title, stage)
    world.stories[story["lineageId"]] = [story]
    lineage = row_of(context, reference_title)["lineageId"]
    world.incoming.setdefault(f"reference#{lineage}#current", []).append({
        "predicate": "uses_evidence", "relationState": "current", "subjectKind": "item", "subjectLineageId": story["lineageId"], "objectKind": "reference", "objectLineageId": lineage,
        "metadata": json.dumps({"role": "based_on"}),
    })


# --- the world -------------------------------------------------------------------------------------------------------------------


@given('the Story "{title}" rests on "{reference}"')
def step_story(context, title, reference):
    rest_on(context, title, reference, "draft")


@given('the idea "{title}" rests on "{reference}"')
def step_idea_only(context, title, reference):
    rest_on(context, title, reference, "idea")


@given('an editor tagged "{reference}" with the concept "{hashtag}" described as "{description}"')
def step_concept(context, reference, hashtag, description):
    world = backend(context)
    name = hashtag.lstrip("#")
    world.nodes.append({
        "id": "node-1", "lineageId": CONCEPT_LINEAGE, "versionState": "current", "status": "accepted", "nodeKey": f"concept--{name}", "displayName": name.replace("-", " "),
        "nodeKind": "concept", "description": description,
    })
    world.subject_relations.setdefault(row_of(context, reference)["lineageId"], []).append({
        "predicate": "related_to", "relationState": "current", "objectKind": "semanticNode", "objectLineageId": CONCEPT_LINEAGE,
        "metadata": json.dumps({"provenance": "human", "decision": "accepted", "decidedBy": "editor-a"}),
    })


@given("the model writes a version for the related Reference")
def step_version_reference(context):
    write_versions(context, answer_of("R1"))


@given("the model writes a version for the other Story")
def step_version_story(context):
    write_versions(context, answer_of("S1"))


@given("the model writes a version for the concept")
def step_version_concept(context):
    write_versions(context, answer_of("C1"))


@given("the model has no point for the concept")
def step_no_point(context):
    write_versions(context, answer_of("C1", point=""))


@given("the model writes a version for the related Reference that cites only the source")
def step_cites_source(context):
    write_versions(context, answer_of("R1", cites_anchor=False))


@given("the model writes a version for the related Reference that repeats the idea's headline")
def step_repeats(context):
    write_versions(context, answer_of("R1", headline=IDEA_HEADLINE))


@given("the point check answers that the version for the related Reference restates its source")
def step_version_restates(context):
    held(context).model.verdict = lambda given: RESTATES if given["headline"] == VERSIONS["R1"]["headline"][0] else ADDS


class Varied(Model):
    """Writes a story of its own for the Reference about quotations, so that two ideas in one run are not duplicates."""

    def __call__(self, url, headers, payload):
        if not payload["instructions"].startswith(("You are a sceptical editor", "You write other versions")):
            quotations = "quotations" in json.loads(payload["input"])["source"]["title"]
            self.answer = story(
                point="Foo traces each quotation to the archive it came from, which is the quotation checking that sourcing needs.", headline=("Foo traces quotations to archives", "I1"),
                dek=("Foo traces quotations to their archives, the quotation checking that sourcing coverage needs.", "E1"), body=[
                    ("Foo is an open tool that traces quotations to archives.", "I1"), ("Foo does the quotation checking that sourcing coverage needs.", "I1", "E1")]) if quotations else story()
        return super().__call__(url, headers, payload)


@given("the model writes a different story for each Reference")
def step_varied(context):
    state = held(context)
    state.model = Varied(state.model.answer, state.model.verdict, state.model.variations)


@given("the backend refuses to create variations")
def step_refuses(context):
    backend(context).failing = True


# --- the run ---------------------------------------------------------------------------------------------------------------------


@when('the run drafts ideas for "{title}" only with only enough budget for the idea')
def step_small_budget(context, title):
    held(context).only = title
    run_ideas(context, maximum_cost_usd=0.0028)


@given('the run drafts ideas for "{title}" only')
def step_given_run(context, title):
    held(context).only = title
    run_ideas(context)


@when("the variations of that idea are offered again")
def step_again(context):
    run = last(context)
    [idea] = run["drafts"]
    again = {"runId": run["runId"], "modelCalls": [], "pointChecks": []}
    state = held(context)
    item = next(item for item in monitor_stories.collect_monitored_items(client_of(context), site="example-site", now=NOW)[0] if item.lineage_id == row_of(context, state.only)["lineageId"])
    knowledge = knowledge_of(context)
    connections = knowledge.connections_for(item)
    view = monitor_stories.source_view(item, PAGE_TEXT, None)
    once = variations.Pass(client_of(context), state.model, "gpt-6-luna", CostMeter(), again, 1.0)
    draft = {"headline": {"text": idea["title"]}, "dek": {"text": idea["angle"]}, "citedHandles": ["I1", "E1"], "paragraphs": []}
    context.again = once.offer(
        story_lineage_id=idea["itemLineageId"], item=item, view=view, connections=connections, knowledge=knowledge, raw={"point": "Anything."}, draft=draft, record=idea,
        verdict=ADDS, context={"sections": [{"title": "Tools"}]},
    )


# --- what the run offered --------------------------------------------------------------------------------------------------------


def story_of(context) -> str:
    return last(context)["drafts"][0]["itemLineageId"]


def offered(context) -> list[dict]:
    return story_variations.variations_of(client_of(context), story_of(context))


@then("the run files {count:d} ideas")
def step_files_many(context, count):
    assert len(client_of(context).filed) == count and len(last(context)["drafts"]) == count, (last(context)["invalid"], last(context)["skipped"])


@then("the idea has {count:d} variation")
@then("the idea has {count:d} variations")
def step_count(context, count):
    assert len(offered(context)) == count, [(row["variationNumber"], row["headline"]) for row in offered(context)]


@then("offered variation {number:d} is the idea as filed")
def step_first(context, number):
    row, filed = offered(context)[number - 1], client_of(context).filed[0]
    assert row["headline"] == filed["title"] and row["deck"] == filed["summary"] and row["bodyMarkus"] == filed["body"] and row["origin"] == "generated" and row["status"] == "offered", row
    assert row["point"] == "Foo is built to check each claim against its source, which is the work claim checking in sourcing needs.", row["point"]


@then('offered variation {number:d} connects to the Reference "{title}" itself')
def step_source(context, number, title):
    [connection] = offered(context)[number - 1]["connections"]
    assert connection["kind"] == "reference" and connection["id"] == row_of(context, title)["lineageId"] and connection["title"] == title and connection["how"], connection


@then("offered variation {number:d} records that the point check found it adds something")
def step_verdict(context, number):
    verdict = offered(context)[number - 1]["pointCheck"]
    assert verdict["verdict"] == "adds" and verdict["claim"], verdict


@then('offered variation {number:d} has the point "{point}"')
def step_point(context, number, point):
    assert offered(context)[number - 1]["point"] == point


@then('offered variation {number:d} connects to the "{kind}" "{title}"')
def step_connects(context, number, kind, title):
    connections = offered(context)[number - 1]["connections"]
    assert connections[0]["kind"] == kind and connections[0]["title"] == title and connections[0]["id"] and connections[0]["how"], connections


@then('the variations connect, in order, to a "{first}", a "{second}", a "{third}" and a "{fourth}"')
def step_order(context, first, second, third, fourth):
    assert [row["connections"][0]["kind"] for row in offered(context)] == [first, second, third, fourth], [row["connections"] for row in offered(context)]
    assert [row["variationNumber"] for row in offered(context)] == [1, 2, 3, 4]


def asked_for_versions(context) -> list[dict]:
    return held(context).model.variation_writing


@then("no model was asked to write other versions")
def step_none_asked(context):
    assert asked_for_versions(context) == [], asked_for_versions(context)


@then("the writer was asked once for all three other versions")
def step_asked_once_all(context):
    [request] = asked_for_versions(context)
    assert [option["anchor"] for option in json.loads(request["input"])["options"]] == ["R1", "S1", "C1"]


@then("the writer was asked once for the other versions")
def step_asked_once(context):
    assert len(asked_for_versions(context)) == 1


def shown_option(context, kind: str, title: str) -> None:
    [request] = asked_for_versions(context)
    given = json.loads(request["input"])
    options = [option for option in given["options"] if option["kind"] == kind]
    assert [option["title"] for option in options] == [title], given["options"]
    assert given["the_idea_as_filed"]["point"] and given["the_idea_as_filed"]["headline"] == IDEA_HEADLINE
    known = {entry["handle"]: entry for entry in given["what_the_newsroom_knows"]}
    assert options[0]["anchor"] in known, known


@then("the model was shown the related Reference as an option")
def step_shown_reference(context):
    shown_option(context, "reference", QUOTATIONS)


@then("the model was shown the other Story as an option")
def step_shown_story(context):
    shown_option(context, "story", STORY)


@then("the model was shown no Story as an option")
def step_no_story(context):
    [request] = asked_for_versions(context)
    assert [option for option in json.loads(request["input"])["options"] if option["kind"] == "story"] == []


@then("the model was shown the concept as an option")
def step_shown_concept(context):
    shown_option(context, "concept", "#source-audits")


def dropped(context) -> dict[str, dict]:
    [entry] = last(context)["variations"]
    return {row["anchor"]: row for row in entry["dropped"]}


@then('the run record says nothing was offered for "{anchor}" because the writer offered no point')
def step_no_point_recorded(context, anchor):
    assert dropped(context)[anchor]["reason"] == "no_point_offered", dropped(context)


@then('the run record says nothing was offered for "{anchor}" because the point check failed with "{reason}"')
def step_point_failed(context, anchor, reason):
    row = dropped(context)[anchor]
    assert row["reason"] == "point_check_failed" and reason in row["failures"], row


@then('the run record says nothing was offered for "{anchor}" because the citation check failed')
def step_citation_failed(context, anchor):
    assert dropped(context)[anchor]["reason"] in ("anchor_not_cited", "citation_check_failed"), dropped(context)


@then('the run record says nothing was offered for "{anchor}" because it repeats another variation')
def step_repeats_recorded(context, anchor):
    assert dropped(context)[anchor]["reason"] == "repeats_another_variation", dropped(context)


@then("the run record shows {count:d} model calls for variations at a cost")
def step_cost(context, count):
    run = last(context)
    assert run["variationCost"]["calls"] == count and run["variationCost"]["costUsd"] > 0, run["variationCost"]
    [entry] = run["variations"]
    assert 0 < entry["costUsd"] <= run["variationCost"]["costUsd"] + 1e-9 and run["variationsOffered"] == 2, run["variations"]


@then("the run's total counts the {count:d} model calls: the idea, its check, the other versions and their check")
def step_total(context, count):
    run = last(context)
    assert run["usage"]["calls"] == count and len(run["modelCalls"]) == count, run["usage"]
    assert run["usage"]["costUsd"] > run["variationCost"]["costUsd"] > 0


@then("the run record says the other versions were held back by the cost limit")
def step_held_back(context):
    [entry] = last(context)["variations"]
    assert entry["skipped"] == "cost" and "estimated" in entry["stoppedForCost"], entry
    assert last(context)["variationCost"]["calls"] == 0


@then("no variation was written")
def step_none_written(context):
    assert client_of(context).variations == {}, client_of(context).variations


@then("the run record lists {count:d} variations that would have been offered")
def step_would(context, count):
    [entry] = last(context)["variations"]
    assert len(entry["offered"]) == count and all(row["dryRun"] for row in entry["offered"]), entry


@then("the run record has {count:d} variation errors and says the offering was turned off")
def step_errors(context, count):
    run = last(context)
    assert len(run["variationErrors"]) == count and "Not Authorized" in run["variationsDisabled"], run.get("variationErrors")
    assert all(entry.get("skipped") or entry["dropped"] for entry in run["variations"]), run["variations"]


# --- a backend whose records carry a tenant -------------------------------------------------------------------------------------


@given('a backend for the tenant "{tenant}"')
def step_tenant_backend(context, tenant):
    rows: dict[str, dict] = {}
    client = PapyrusGraphQLAuthoringClient(endpoint="https://example.invalid/graphql", header_factory=lambda body: {}, tenant_id=tenant)

    def respond(query, variables=None):
        variables = variables or {}
        if "createStoryVariation" in query:
            rows[variables["input"]["id"]] = dict(variables["input"])
            return {"createStoryVariation": variables["input"]}
        if "listStoryVariationsByStoryAndNumber" in query:
            return {"listStoryVariationsByStoryAndNumber": {"items": [row for row in rows.values() if row["storyLineageId"] == variables["storyLineageId"]], "nextToken": None}}
        raise AssertionError(f"unexpected request: {query[:60]}")

    client.graphql = respond
    context.tenant, context.tenant_client, context.tenant_rows = tenant, client, rows


@when("a run offers {count:d} variations of a Story to that backend")
def step_tenant_offer(context, count):
    connection = [{"kind": "reference", "id": "reference-1", "title": "A Reference", "how": "The item this idea is about"}]
    for number in range(1, count + 1):
        story_variations.offer_variation(context.tenant_client, "item-story-1", point=f"Point {number}", headline=f"Headline {number}", connections=connection, run_id="run-1", model="gpt-6-luna", created_by="AI")


@then("the backend holds {count:d} variations of the Story without a tenant column")
def step_tenant_rows(context, count):
    assert len(context.tenant_rows) == count and all("tenantId" not in row for row in context.tenant_rows.values()), context.tenant_rows


@then("an authoring client of that tenant reads both back in order")
def step_tenant_read(context):
    assert context.tenant_client.tenant_id == context.tenant
    assert [row["headline"] for row in story_variations.variations_of(context.tenant_client, "item-story-1")] == ["Headline 1", "Headline 2"]
