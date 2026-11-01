"""References with no extracted text still get their reference_summary vector (src/papyrus_knowledge_query/vector_index.py). Fakes only; no AWS or OpenAI."""
from __future__ import annotations

import json
from unittest import mock

from papyrus_knowledge_query import vector_index
from papyrus_knowledge_query.services import KnowledgeQueryServices

LONG_BODY = "The extracted article body talks about retrieval and ranking at some length. " * 12


class FakeGraph:
    def __init__(self, attachments):
        self.attachments = attachments

    def graphql(self, query, variables):
        return {"listModelAttachmentsByOwnerRoleAndSortKey": {"items": [], "nextToken": None}}

    def list_reference_attachments(self, reference):
        return self.attachments.get(reference["lineageId"], [])


class FakeCorpus:
    def read_text(self, path):
        return LONG_BODY


class FakeIndex:
    def __init__(self):
        self.stored = {}
        self.written = []

    def list_vectors(self, arn):
        return [{"key": key, "metadata": metadata} for key, metadata in self.stored.items()]

    def put(self, arn, candidates):
        for candidate in candidates:
            self.written.append(candidate)
            self.stored[candidate["key"]] = candidate["metadata"]
        return len(candidates)


def reference(name, title):
    return {"id": f"id-{name}", "lineageId": f"lin-{name}", "corpusId": "c", "title": title, "sourceUri": f"https://example.org/{name}", "curationStatus": "accepted", "versionState": "current"}


def curation(text):
    return {"role": "curation", "metadata": json.dumps({"summary": {"text": text, "model": "m", "promptVersion": "v1"}})}


def preview(description):
    return {"role": "preview", "metadata": json.dumps({"description": description, "imageUrl": "https://example.org/i.png"})}


SOURCE = {"role": "source", "sourceUri": "https://example.org/x"}
CURATION_TEXT = "A study of how small retrieval models rank news items for readers, with the failure cases it found."
DESCRIPTION = "A long description of the article that the publisher put in its page metadata for link previews."


def sync(references, attachments, index, force=False):
    services = KnowledgeQueryServices(graph=FakeGraph(attachments), corpus_text=FakeCorpus())
    with mock.patch.dict("os.environ", {"PAPYRUS_S3_VECTOR_INDEX_ARN": "arn:fake"}), \
            mock.patch.object(vector_index, "_list_references", return_value=references), \
            mock.patch.object(vector_index, "_list_note_messages", return_value=[]), \
            mock.patch.object(vector_index, "_prepare_note_messages", return_value=[]), \
            mock.patch.object(vector_index, "_list_index_vectors", side_effect=index.list_vectors), \
            mock.patch.object(vector_index, "_embed_and_put_vectors", side_effect=index.put):
        return vector_index.index_reference_passages(
            services, vector_index.VectorIndexOptions(action="sync", include_ontology_vectors=False, include_concept_cards=False, force=force)
        )


def test_curation_summary_gets_one_summary_vector_and_no_passages():
    ref = reference("a", "Ranking news")
    index = FakeIndex()
    stats = sync([ref], {"lin-a": [SOURCE, preview(DESCRIPTION), curation(CURATION_TEXT)]}, index)
    assert len(index.written) == 1
    vector = index.written[0]
    assert vector["key"] == vector_index.reference_summary_vector_key("lin-a")
    assert vector["metadata"]["vectorKind"] == "reference_summary"
    assert vector["metadata"]["summarySource"] == "curation"
    assert CURATION_TEXT in vector["text"] and DESCRIPTION not in vector["text"]
    assert stats["summarySourceCounts"] == {"curation": 1}
    assert stats["referencesSkippedNoText"] == 0 and stats["passageVectorsPrepared"] == 0


def test_title_and_preview_description_is_indexed_but_a_bare_title_is_not():
    with_description, bare, same_as_title = reference("b", "Ranking news"), reference("c", "Only a title"), reference("d", "Same words")
    attachments = {"lin-b": [SOURCE, preview(DESCRIPTION)], "lin-c": [SOURCE], "lin-d": [SOURCE, preview("Same words")]}
    index = FakeIndex()
    stats = sync([with_description, bare, same_as_title], attachments, index)
    assert [vector["metadata"]["summarySource"] for vector in index.written] == ["preview"]
    assert index.written[0]["text"].startswith("Ranking news")
    assert stats["summarySourceCounts"] == {"preview": 1}
    assert stats["referencesSkippedNoText"] == 2


def test_reference_with_extracted_text_is_unchanged():
    ref = reference("e", "Ranking news")
    index = FakeIndex()
    stats = sync([ref], {"lin-e": [{"role": "extracted_text", "storagePath": "s/e.txt"}, curation(CURATION_TEXT)]}, index)
    kinds = sorted(vector["metadata"]["vectorKind"] for vector in index.written)
    assert kinds[0] == "reference_passage" and kinds.count("reference_summary") == 1
    assert all("summarySource" not in vector["metadata"] for vector in index.written)
    assert stats["summarySourceCounts"] == {} and stats["referencesWithExtractedText"] == 1


def test_unchanged_summary_is_skipped_on_the_second_sync_and_a_changed_one_is_rewritten():
    ref = reference("f", "Ranking news")
    attachments = {"lin-f": [SOURCE, curation(CURATION_TEXT)]}
    index = FakeIndex()
    sync([ref], attachments, index)
    index.written.clear()
    stats = sync([ref], attachments, index)
    assert index.written == [] and stats["vectorsSkippedExisting"] == 1
    attachments["lin-f"] = [SOURCE, curation(CURATION_TEXT + " It also covers the cost.")]
    sync([ref], attachments, index)
    assert len(index.written) == 1
