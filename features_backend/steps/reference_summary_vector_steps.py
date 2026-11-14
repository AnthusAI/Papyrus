from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_knowledge_query import vector_index  # noqa: E402
from papyrus_knowledge_query.services import KnowledgeQueryServices  # noqa: E402

REFERENCE = {"id": "id-r", "lineageId": "lin-r", "corpusId": "c", "title": "Ranking news", "versionState": "current", "curationStatus": "accepted"}
ATTACHMENTS = [
    {"role": "source", "sourceUri": "https://example.org/r"},
    {"role": "curation", "metadata": json.dumps({"summary": {"text": "A study of how small retrieval models rank news items for readers, with the failure cases it found.", "model": "m"}})},
]


class FakeGraph:
    def graphql(self, query, variables):
        return {"listModelAttachmentsByOwnerRoleAndSortKey": {"items": [], "nextToken": None}}

    def list_reference_attachments(self, reference):
        return ATTACHMENTS


@given("an accepted Reference delivered by a monitor, with a curation summary and no extracted text")
def step_monitor_reference(context):
    context.references = [REFERENCE]


@when("the Reference summary vectors are synced")
def step_sync_references(context):
    context.index.written_last_run = []
    services = KnowledgeQueryServices(graph=FakeGraph(), corpus_text=object())
    with mock.patch.dict("os.environ", {"PAPYRUS_S3_VECTOR_INDEX_ARN": "arn:fake"}), \
            mock.patch.object(vector_index, "_list_references", return_value=context.references), \
            mock.patch.object(vector_index, "_list_note_messages", return_value=[]), \
            mock.patch.object(vector_index, "_prepare_note_messages", return_value=[]), \
            mock.patch.object(vector_index, "_list_index_vectors", side_effect=context.index.list_vectors), \
            mock.patch.object(vector_index, "_embed_and_put_vectors", side_effect=context.index.embed_and_put):
        context.stats = vector_index.index_reference_passages(
            services, vector_index.VectorIndexOptions(action="sync", include_ontology_vectors=False, include_concept_cards=False)
        )


@then('exactly 1 Reference summary vector is written, with the summary source "{source}" and no passage vectors')
def step_one_summary(context, source):
    assert len(context.index.written_last_run) == 1, context.index.written_last_run
    metadata = next(iter(context.index.stored.values()))
    assert metadata["vectorKind"] == "reference_summary" and metadata["summarySource"] == source, metadata
    assert context.stats["passageVectorsPrepared"] == 0, context.stats


@then("no Reference summary vector is written")
def step_no_summary(context):
    assert context.index.written_last_run == [], context.index.written_last_run
