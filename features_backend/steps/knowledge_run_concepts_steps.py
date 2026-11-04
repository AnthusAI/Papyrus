"""Automated runs never change an existing concept (features_backend/knowledge-run-concepts.feature)."""

from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus_content.analysis_graph import build_generated_graph_supersession_changes, build_graph_export_import_records  # noqa: E402
from papyrus_content.knowledge_snapshot.actors import ACTOR_AI, Actor, ReviewMarks  # noqa: E402
from papyrus_content.knowledge_snapshot.model import FrontMatterEntity, PublishedItem  # noqa: E402
from papyrus_content.knowledge_snapshot.monitor_import import plan_monitor_records  # noqa: E402
from papyrus_content.knowledge_snapshot.monitor_records import MonitorRecord  # noqa: E402
from papyrus_content.knowledge_snapshot.publish_run import FRONT_MATTER_IMPORT_RUN, NodeIndex, PublishPlan, new_node_row, plan_front_matter  # noqa: E402
from papyrus_content.ontology_enrichment import build_concept_authority_changes  # noqa: E402
from papyrus_content.semantic_node_writes import DERIVED_FIELDS  # noqa: E402

NOW = "2026-11-03T00:00:00Z"
PERSON_DESCRIPTION = "Written by a person."


def known_node(context, name, status, kind="concept", run="run"):
    row = new_node_row(kind, name, status, import_run_id=run, corpus_id="c", now=NOW, reason="seed")
    row["description"] = PERSON_DESCRIPTION
    context.concept_nodes = [*getattr(context, "concept_nodes", []), row]
    return row


def graph(*labels):
    return {
        "snapshot": {"snapshot_id": "s1", "extractor_id": "x"},
        "nodes": [{"node_id": f"n{i}", "node_type": "concept", "label": label} for i, label in enumerate(labels)],
        "edges": [],
    }


def run_import(context, label):
    return build_graph_export_import_records(
        graph(label), corpus_id="c", classifier_id=None, imported_at=NOW, reference_by_external_item_id={}, existing_nodes=getattr(context, "concept_nodes", [])
    )


def written_nodes(plan):
    return [record for record in plan["records"] if record["modelName"] == "SemanticNode"]


@given('the concept run knows an edited concept named "{name}" with the alias "{alias}"')
def step_edited(context, name, alias):
    row = known_node(context, name, "accepted")
    row["displayName"] = name
    row["aliases"] = [alias]
    context.edited_node = row


@given('the concept run knows a rejected concept named "{name}"')
def step_rejected(context, name):
    known_node(context, name, "rejected", kind="task" if name == "text-to-speech" else "concept")


@given('the concept run knows a generated concept named "{name}"')
def step_generated(context, name):
    known_node(context, name, "generated", kind="task" if name == "text-to-speech" else "concept")


@given("the concept run knows a concept the front matter path created without an acceptance mark")
def step_unmarked(context):
    known_node(context, "Voice Cloning", "accepted", run=FRONT_MATTER_IMPORT_RUN)


@when('the concept run imports a graph that names "{label}"')
def step_import(context, label):
    context.import_plan = run_import(context, label)


@when('the concept run imports a second graph that names "{label}"')
def step_import_second(context, label):
    context.second_plan = run_import(context, label)


@then("the concept run writes no concept")
def step_no_concept(context):
    plan = getattr(context, "import_plan", None)
    if plan is not None:
        assert written_nodes(plan) == []
    else:
        assert [r for r in context.publish_plan.records if r["modelName"] == "SemanticNode"] == []


@then("the concept run names the edited concept as the target of the association")
def step_target_edited(context):
    assert context.import_plan["semanticNodeCount"] == 1
    assert context.edited_node["description"] == PERSON_DESCRIPTION and context.edited_node["aliases"]


@then('the concept run creates exactly one concept, create-only, named "{name}"')
def step_creates(context, name):
    created = written_nodes(context.import_plan)
    assert len(created) == 1 and created[0]["createOnly"] is True and created[0]["expected"]["displayName"] == name


@then("the concept run names the created concept as the target of the association")
def step_target_created(context):
    assert context.import_plan["semanticNodeCount"] == 1


@then("the concept run writes no association")
def step_no_association(context):
    assert context.import_plan["semanticNodeCount"] == 0 and context.import_plan["skippedRejectedNodes"] == 1


@when("the concept run recomputes the authority numbers with a score of {score:f} and a relation count of {count:d}")
def step_recompute(context, score, count):
    node = context.edited_node
    state = {"models": {"SemanticNode": [node]}}
    ranked = [{"id": node["id"], "score": score, "authorityRank": 1, "acceptedReferenceMentions": 0, "distinctSourceKinds": 0, "relationCount": count}]
    context.authority_changes = build_concept_authority_changes(state, ranked, now=NOW)


@then("the concept run sends a partial update naming only the derived fields")
def step_partial(context):
    assert len(context.authority_changes) == 1
    assert set(context.authority_changes[0]["expected"]) <= DERIVED_FIELDS | {"id"}


@then("the edited concept still has its own name, description and aliases")
def step_still_edited(context):
    node = context.edited_node
    assert node["displayName"] == "Voice cloning (edited)" and node["description"] == PERSON_DESCRIPTION and node["aliases"] == ["Voice Cloning"]


@then("both imports plan the same concept id")
def step_same_id(context):
    assert written_nodes(context.import_plan)[0]["expected"]["id"] == written_nodes(context.second_plan)[0]["expected"]["id"]


class NoNodeReadClient:
    def list_knowledge_import_runs_by_corpus_kind_and_imported_at(self, key):
        return [{"id": "knowledge-import-c-graph-x-old"}]

    def list_semantic_nodes_by_import_run_and_node_key(self, run_id):
        raise AssertionError("an import never reads nodes to supersede them")

    def list_semantic_relations_by_import_run_and_imported_at(self, run_id):
        return []


@then("an import of a graph never supersedes the concepts of earlier imports")
def step_no_supersession(context):
    assert build_generated_graph_supersession_changes(NoNodeReadClient(), corpus_id="c", extractor_id="x", import_run_id="new", now=NOW) == []


@when('a published Story\'s front matter names the concept "{name}" of kind "{kind}"')
def step_front_matter(context, name, kind):
    item = PublishedItem(key="story", item_id="story-v1", title="t", url=None, published_at=None, entities=(FrontMatterEntity(kind, name),))
    context.publish_plan = PublishPlan()
    plan_front_matter(
        [item], NodeIndex(context.concept_nodes), [], context.publish_plan, corpus_id="c", now=NOW, accepted_by=Actor(ACTOR_AI, "Papyrus", NOW[:10])
    )


@when('a monitor record names the task "{name}"')
def step_monitor(context, name):
    details = {"modelId": "org/tuned", "author": "org", "createdAt": NOW, "pipelineTag": name}
    record = MonitorRecord("reference-tuned", "lineage-tuned", "huggingface", "https://huggingface.co/org/tuned", "org/tuned", NOW, details)
    context.publish_plan = PublishPlan()
    plan_monitor_records([record], NodeIndex(context.concept_nodes), [], context.publish_plan, corpus_id="c", now=NOW)


@then("the concept run accepts the concept and changes nothing else about it")
def step_accepts(context):
    patches = context.publish_plan.patches
    assert len(patches) == 1
    assert set(patches[0]["expected"]) == {"id", "status", "changeReason", "updatedAt"} and patches[0]["expected"]["status"] == "accepted"
    assert context.concept_nodes[0]["description"] == PERSON_DESCRIPTION


@then("the concept run writes no concept and sends no update")
def step_nothing(context):
    assert context.publish_plan.patches == []
    assert [r for r in context.publish_plan.records if r["modelName"] == "SemanticNode"] == []


@then("the concept run sends one update that only records the acceptance mark")
def step_mark(context):
    patches = context.publish_plan.patches
    assert len(patches) == 1 and set(patches[0]["expected"]) == {"id", "changeReason", "updatedAt"}


@then("the concept run sends no update to the concept")
def step_no_update(context):
    assert context.publish_plan.patches == []
