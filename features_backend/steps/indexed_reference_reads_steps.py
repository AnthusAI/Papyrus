"""Steps for features_backend/indexed-reference-reads.feature. In memory; the client counts whole-table listings."""
from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.records import prepare_versioned_knowledge_records  # noqa: E402
from papyrus_content.reference_reads import targeted_scope  # noqa: E402
from papyrus_content.reference_reads_testing import list_by_index_from_records  # noqa: E402


class CountingClient:
    tenant_id = None

    def __init__(self, count: int):
        self.listed: list[str] = []
        self.tables = {
            "Reference": [{"id": f"r{n}", "lineageId": f"r{n}", "versionState": "current", "versionNumber": 1, "corpusId": "c", "contentHash": f"h{n}"}
                          for n in range(count)],
            "ReferenceAttachment": [{"id": f"a{n}", "referenceLineageId": f"r{n}", "role": "source"} for n in range(count)],
            "SemanticRelation": [{"id": f"s{n}", "subjectStateKey": f"reference#r{n}#current", "subjectLineageId": f"r{n}", "relationState": "current"}
                                 for n in range(count)],
        }

    def list_records(self, model):
        self.listed.append(model)
        return list(self.tables[model])

    def list_by_index(self, index_name, key_value, *, limit=100, sort_eq=None):
        return list_by_index_from_records(lambda model: self.tables[model], index_name, key_value, sort_eq)

    def get_record(self, model, record_id):
        return next((row for row in self.tables[model] if row["id"] == record_id), None)


@given("a publication with {references:d} References and {relations:d} relations")
def publication(context, references, relations):
    context.client = CountingClient(references)


@when("a new version of one Reference is prepared for writing")
def prepare(context):
    changed = {"id": "r7-import", "lineageId": "r7", "versionState": "current", "versionNumber": 1, "corpusId": "c", "contentHash": "different"}
    context.prepared = prepare_versioned_knowledge_records(context.client, [{"modelName": "Reference", "expected": changed}])


@then("no whole table was listed")
def none_listed(context):
    assert context.client.listed == [], context.client.listed


@then("the previous version is superseded")
def superseded(context):
    ids = {change["expected"]["id"]: change["expected"] for change in context.prepared["postChanges"]}
    assert ids["r7"]["versionState"] == "superseded", ids


@when("the targeted scope of one named Reference is built")
def scope(context):
    context.scope = targeted_scope(context.client, reference_ids=["r7"])


@then("the scope holds that Reference and its attachments")
def scope_rows(context):
    assert [row["id"] for row in context.scope["references"]] == ["r7"]
    assert [row["id"] for row in context.scope["attachments"]] == ["a7"]


@when("the citation lookup is not used")
def not_used(context):
    pass


@when("the citation lookup is used")
def used(context):
    assert len(context.scope["all_references"]) == len(context.client.tables["Reference"])


@then("the Reference table was listed once")
def listed_once(context):
    assert context.client.listed == ["Reference"], context.client.listed
