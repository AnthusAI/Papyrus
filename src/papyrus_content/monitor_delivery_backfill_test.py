from __future__ import annotations

import json

from .monitor_delivery_backfill import plan_reference_update, run_backfill


def relation(lineage: str, metadata: dict, imported: str = "2026-10-15T00:00:00Z") -> dict:
    return {"predicate": "ingestion_rationale", "relationState": "current", "objectLineageId": lineage, "importedAt": imported, "metadata": json.dumps(metadata)}


class Client:
    def __init__(self, references: list[dict], relations: list[dict]) -> None:
        self.references, self.relations, self.updates = references, relations, []

    def list_records(self, model):
        assert model == "Reference"
        return self.references

    def list_semantic_relations_by_object_state(self, state):
        lineage = state.split("#")[1]
        return [row for row in self.relations if row["objectLineageId"] == lineage]

    def update_record(self, model, row):
        assert model == "Reference"
        self.updates.append(row)


def test_the_newest_relation_gives_the_monitor_details_and_rule():
    reference = {"id": "r1", "lineageId": "l1"}
    update = plan_reference_update(reference, [
        relation("l1", {"monitorId": "huggingface", "details": {"likes": 5}}, "2026-10-15T00:00:00Z"),
        relation("l1", {"monitorId": "huggingface", "details": {"likes": 50}, "machineDecision": {"system": "direct", "rule": {"minLikes": 5}}}, "2026-10-17T00:00:00Z"),
    ])
    assert update["discoveredByMonitorId"] == "huggingface"
    assert json.loads(update["discoveryDetails"]) == {"likes": 50}
    assert json.loads(update["discoveryRule"]) == {"system": "direct", "rule": {"minLikes": 5}}


def test_a_reference_already_recorded_or_never_delivered_plans_nothing():
    assert plan_reference_update({"id": "r1", "lineageId": "l1", "discoveredByMonitorId": "hn"}, [relation("l1", {"monitorId": "other"})]) is None
    assert plan_reference_update({"id": "r2", "lineageId": "l2"}, []) is None


def test_a_dry_run_counts_and_writes_nothing_and_a_run_writes_only_the_new_fields():
    rows = [{"id": "r1", "lineageId": "l1", "versionState": "current"}, {"id": "r2", "lineageId": "l2", "discoveredByMonitorId": "hn"},
            {"id": "r3", "lineageId": "l3"}, {"id": "r0", "lineageId": "l1", "versionState": "superseded"}]
    relations = [relation("l1", {"monitorId": "hn", "details": {"a": 1}})]
    dry = Client(rows, relations)
    result = run_backfill(dry, apply=False)
    assert (result["scanned"], result["planned"], result["alreadyRecorded"], result["notDelivered"], result["written"]) == (3, 1, 1, 1, 0)
    assert result["dryRun"] is True and result["monitors"] == {"hn": 1} and dry.updates == []
    live = Client(rows, relations)
    assert run_backfill(live, apply=True)["written"] == 1
    assert live.updates == [{"id": "r1", "discoveredByMonitorId": "hn", "discoveryDetails": json.dumps({"a": 1})}]
