from __future__ import annotations

import json

from .actors import ACTOR_AI, Actor, ReviewMarks
from .monitor_import import MONITOR_IMPORT_RUN, is_record_mention, is_record_relation, plan_monitor_records
from .monitor_records import MonitorRecord
from .publish_run import NodeIndex, PublishPlan, new_node_row, plan_publish_run
from .loaders import links_and_relations

NOW = "2026-10-19T05:00:00Z"
URL = "https://huggingface.co/org/"


def record(name: str, *, author: str = "org", licence: str | None = "apache-2.0", task: str | None = "text-to-speech", bases=()) -> MonitorRecord:
    details = {"modelId": f"{author}/{name}", "author": author, "createdAt": "2026-10-14T08:00:00Z", "baseModels": [{"modelId": b, "relation": r} for b, r in bases]}
    details.update({key: value for key, value in (("license", licence), ("pipelineTag", task)) if value})
    return MonitorRecord(f"reference-{author}-{name}", f"lineage-{author}-{name}", "huggingface", f"https://huggingface.co/{author}/{name}", f"{author}/{name}", "2026-10-14T08:00:00Z", details)


def existing_node(kind: str, name: str, status: str = "accepted", **overrides) -> dict:
    row = new_node_row(kind, name, status, import_run_id="knowledge-front-matter", corpus_id="c", now=NOW, reason=ReviewMarks(accepted_by=Actor(ACTOR_AI, None, "2026-10-01")).encode())
    return {**row, **overrides}


def plan_for(records, nodes=(), rows=()):
    plan = PublishPlan()
    plan_monitor_records(records, NodeIndex(list(nodes)), list(rows), plan, corpus_id="knowledge-corpus-shipped", now=NOW)
    return plan


def created(plan: PublishPlan, model: str) -> list[dict]:
    return [entry["expected"] for entry in plan.records if entry["modelName"] == model]


def test_a_record_makes_an_entity_per_structured_field_accepted_by_the_hub_import_without_the_extractor():
    plan = plan_for([record("tuned")])
    nodes = {row["nodeKey"]: row for row in created(plan, "SemanticNode")}
    assert sorted(nodes) == ["licence--apache-2-0", "maker--org", "model--org-tuned", "task--text-to-speech"]
    assert {row["status"] for row in nodes.values()} == {"accepted"} and {row["importRunId"] for row in nodes.values()} == {MONITOR_IMPORT_RUN}
    assert '"name":"Hugging Face Hub import"' in nodes["maker--org"]["changeReason"]
    links = created(plan, "SemanticRelation")
    assert len(links) == 4 and all(is_record_mention(row) for row in links)
    metadata = json.loads(links[0]["metadata"])
    assert (metadata["confirmed"], metadata["linkSource"], metadata["provenance"]) == (True, "monitor", "from the Hugging Face Hub")
    assert {row["subjectKind"] for row in links} == {"reference"}


def test_an_entity_of_the_sites_own_items_is_reused_by_key_not_created_again():
    apache = existing_node("licence", "Apache-2.0")  # the site calls it "Apache-2.0"; the Hub says "apache-2.0"
    task = existing_node("task", "text-to-speech")
    plan = plan_for([record("tuned")], nodes=[apache, task])
    assert sorted(row["nodeKey"] for row in created(plan, "SemanticNode")) == ["maker--org", "model--org-tuned"]
    targets = {row["objectLineageId"] for row in created(plan, "SemanticRelation")}
    assert {apache["lineageId"], task["lineageId"]} <= targets


def test_a_rejected_entity_is_never_linked_and_a_generated_one_is_accepted_on_the_hubs_word():
    rejected = existing_node("maker", "org", status="rejected")
    generated = existing_node("task", "text-to-speech", status="generated")
    plan = plan_for([record("tuned")], nodes=[rejected, generated])
    assert plan.counts["recordLinksSkippedRejected"] == 1 and plan.counts["recordNodesAccepted"] == 1
    assert [patch["expected"]["id"] for patch in plan.patches] == [generated["id"]]
    assert rejected["lineageId"] not in {row["objectLineageId"] for row in created(plan, "SemanticRelation")}


def test_a_base_model_becomes_a_built_on_relation_with_subtype_evidence_and_provenance_when_both_ends_are_on_the_map():
    plan = plan_for([record("base"), record("tuned", bases=[("org/base", "finetune")]), record("quant", bases=[("org/tuned", "quantized")])])
    relations = [row for row in created(plan, "SemanticRelation") if row["predicate"] == "built_on"]
    assert plan.counts["recordRelations"] == 2
    by_subject = {row["subjectLineageId"]: row for row in relations}
    tuned = by_subject["semantic-node-model--org-tuned"]
    assert tuned["objectLineageId"] == "semantic-node-model--org-base"
    metadata = json.loads(tuned["metadata"])
    assert (metadata["confirmed"], metadata["subtype"], metadata["evidence"], metadata["provenance"]) == (True, "finetune", "https://huggingface.co/org/tuned", "from the Hugging Face Hub")
    assert json.loads(by_subject["semantic-node-model--org-quant"]["metadata"])["subtype"] == "quantized"
    assert all(is_record_relation(row) for row in relations)


def test_a_base_model_that_is_not_on_the_map_stays_in_the_record():
    plan = plan_for([record("tuned", bases=[("someone/else", "adapter")])])
    assert plan.counts["recordBaseModelsOffMap"] == 1
    assert not [row for row in created(plan, "SemanticRelation") if row["predicate"] == "built_on"]


def test_a_base_model_named_by_an_accepted_entity_of_the_site_is_on_the_map():
    known = existing_node("model", "meta/llama-base")
    plan = plan_for([record("tuned", bases=[("meta/llama-base", "finetune")])], nodes=[known])
    [relation] = [row for row in created(plan, "SemanticRelation") if row["predicate"] == "built_on"]
    assert relation["objectLineageId"] == known["lineageId"]


def test_a_second_run_plans_nothing_new_and_a_changed_record_supersedes_the_links_it_lost():
    records = [record("tuned"), record("base"), record("tuned2", bases=[("org/base", "merge")])]
    first = plan_for(records)
    written = [entry["expected"] for entry in first.records if entry["modelName"] == "SemanticNode"]
    rows = [entry["expected"] for entry in first.records if entry["modelName"] == "SemanticRelation"]
    again = plan_for(records, nodes=written, rows=rows)
    assert again.records == [] and again.patches == []
    changed = plan_for([record("tuned", licence=None), record("base"), record("tuned2", bases=[("org/base", "merge")])], nodes=written, rows=rows)
    assert changed.records == []
    [patch] = changed.patches
    assert patch["expected"]["relationState"] == "superseded" and patch["expected"]["id"] in {row["id"] for row in rows}


def test_the_plan_of_a_publish_run_includes_the_records_beside_the_front_matter_and_the_extractor():
    plan = plan_publish_run(
        items=[], node_rows=[], mention_rows=[], proposal_rows=[], run=None, corpus_id="knowledge-corpus-shipped", category_set_id=None, now=NOW,
        records=[record("tuned")], record_rows=[],
    )
    assert plan.counts["recordNodesCreated"] == 4 and plan.counts["recordLinks"] == 4


def test_the_snapshot_loader_reads_record_links_and_built_on_relations_as_data_not_as_item_mentions():
    plan = plan_for([record("base"), record("tuned", bases=[("org/base", "finetune")])])
    rows = [entry["expected"] for entry in plan.records if entry["modelName"] == "SemanticRelation"]
    links, relations = links_and_relations(rows)
    assert {link.source for link in links} == {"monitor"} and {link.item_key for link in links} == {"lineage-org-base", "lineage-org-tuned"}
    [relation] = relations
    assert (relation.predicate, relation.subtype, relation.evidence, relation.provenance, relation.confirmed) == (
        "built_on", "finetune", "https://huggingface.co/org/tuned", "from the Hugging Face Hub", True,
    )
