"""Concepts have a public page only when the page answer is yes (features_backend/knowledge-concept-page-answer.feature)."""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.knowledge_snapshot import commands  # noqa: E402
from papyrus_content.knowledge_snapshot.loaders import entity_node  # noqa: E402
from papyrus_content.knowledge_snapshot.model import ItemLink, KnowledgeData  # noqa: E402
from papyrus_content.knowledge_snapshot.publish_run import FRONT_MATTER_IMPORT_RUN  # noqa: E402
from papyrus_content.knowledge_snapshot.page_answer import PAGE_FIELD, decode_page_answer  # noqa: E402
from papyrus_content.knowledge_wiki.sync import entity_specs  # noqa: E402


def call(context, function, *flags):
    context.error = None
    captured = io.StringIO()
    try:
        with mock.patch.object(commands, "create_authoring_client", lambda *args, **kwargs: (context.client, {})), contextlib.redirect_stdout(captured):
            function(list(flags))
    except ValueError as error:
        context.error = str(error)
    context.output = captured.getvalue()


def node(context, name):
    return next(row for row in context.client.rows["SemanticNode"].values() if row["displayName"] == name)


def import_run(context, name, score, documents):
    page = {} if score is None else {"page_score": score, "page_answer": score >= 0.5, "page_documents": documents}
    entity = {"id": "e1", "kind": "task", "text": name, "state": "proposed", "entity_key": None, "span": None, "score": 0.9, **page}
    path = context.work / f"entities-{len(list(context.work.glob('entities-*.json')))}.json"
    path.write_text(json.dumps({"schema_version": 1, "items": [{"item_id": "item-alpha", "entities": [entity], "relations": []}]}))
    context.writes_before = len(context.client.writes)
    context.rows_before = {row["id"]: dict(row) for row in context.client.rows.get("SemanticNode", {}).values()}
    call(context, commands.knowledge_publish_run, "--entities", str(path), "--apply")
    assert context.error is None, context.error


@given('the extractor proposed "{name}" with page score {score:f} in {documents:d} documents and the run was imported')
@when('the extractor proposes "{name}" with page score {score:f} in {documents:d} documents and the run is imported')
def step_proposes(context, name, score, documents):
    import_run(context, name, score, documents)


@given('the extractor proposed "{name}" with no page answer and the run was imported')
def step_proposes_unanswered(context, name):
    import_run(context, name, None, None)


@given('an editor accepted the concept "{name}"')
def step_accepted(context, name):
    call(context, commands.knowledge_entities_accept, "--key", node(context, name)["nodeKey"], "--actor", "human", "--actor-name", "Ada")
    assert context.error is None, context.error


@given('an editor rejected the concept "{name}"')
def step_rejected(context, name):
    call(context, commands.knowledge_entities_reject, "--key", node(context, name)["nodeKey"], "--actor", "human", "--actor-name", "Ada")


def decide(context, name, choice):
    call(context, commands.knowledge_entities_page, "--key", node(context, name)["nodeKey"], "--set", choice, "--actor", "human", "--actor-name", "Ada")


@when('a person gives the concept "{name}" a page')
def step_gives(context, name):
    decide(context, name, "yes")
    assert context.error is None, context.error


@when('a person takes the page of the concept "{name}" away')
@given('a person took the page of the concept "{name}" away')
def step_takes(context, name):
    decide(context, name, "no")
    assert context.error is None, context.error


@when('a person hands the page decision of the concept "{name}" back to the machine')
def step_hands_back(context, name):
    decide(context, name, "machine")
    assert context.error is None, context.error


@when('a person tries to give the concept "{name}" a page')
def step_tries(context, name):
    decide(context, name, "yes")


@then('the command is refused saying the concept is rejected')
def step_refused(context):
    assert context.error and "rejected" in context.error, context.error


@then('the concept "{name}" has page score {score:f}, a page answer of {answer} and {documents:d} documents')
def step_answer(context, name, score, answer, documents):
    stored = decode_page_answer(node(context, name).get(PAGE_FIELD))
    assert stored is not None and (stored.score, stored.answer, stored.documents) == (score, answer == "yes", documents), stored


@then('the concept "{name}" has no page answer')
def step_no_answer(context, name):
    assert PAGE_FIELD not in node(context, name)


@then('the concept "{name}" is otherwise exactly as it was')
def step_otherwise(context, name):
    now, before = node(context, name), context.rows_before[node(context, name)["id"]]
    assert {k: v for k, v in now.items() if k not in (PAGE_FIELD, "updatedAt")} == {k: v for k, v in before.items() if k not in (PAGE_FIELD, "updatedAt")}


@then("the run wrote nothing")
def step_nothing(context):
    assert len(context.client.writes) == context.writes_before


def pages(context):
    # the published items' own front-matter entities (Acme) are accepted from the start and not what the scenarios are about
    rows = [row for row in context.client.rows.get("SemanticNode", {}).values() if row.get("status") == "accepted" and row.get("importRunId") != FRONT_MATTER_IMPORT_RUN]
    nodes = tuple(entity_node(row) for row in rows)
    links = tuple(ItemLink(item_key="lineage-alpha", node_lineage_id=entry.lineage_id, confirmed=True) for entry in nodes)
    return sorted(spec.front_matter["title"] for spec in entity_specs(KnowledgeData(nodes=nodes, links=links), {}))


@then('the wiki gives pages to "{name}" only')
def step_pages_only(context, name):
    assert pages(context) == [name], pages(context)


@then("the wiki gives pages to nobody")
def step_pages_nobody(context):
    assert pages(context) == [], pages(context)


@then('the concept "{name}" is accepted and still has its mention link')
def step_filed(context, name):
    row = node(context, name)
    links = [r for r in context.client.rows.get("SemanticRelation", {}).values() if r["objectLineageId"] == row["lineageId"] and r["predicate"] == "mentions"]
    assert row["status"] == "accepted" and links and all(json.loads(r["metadata"])["confirmed"] for r in links)


@when("the concepts are listed")
def step_list(context):
    call(context, commands.knowledge_entities_list)
    context.listed = [line.split("\t") for line in context.output.splitlines() if line.count("\t") > 3]


@then("the list is {names} in that order")
def step_order(context, names):
    wanted = [part.strip().strip('"') for part in names.split(",")]
    assert [row[3] for row in context.listed] == wanted, context.listed


@then('"{name}" shows {score} and {documents:d} documents, and "{other}" shows no answer')
def step_shows(context, name, score, documents, other):
    row = next(row for row in context.listed if row[3] == name)
    assert row[5:7] == [score, str(documents)], row
    assert next(row for row in context.listed if row[3] == other)[5:7] == ["-", "-"]
