"""The router's daily vector pass (src/papyrus_content/monitoring_vectors.py, features_backend/monitoring-vector-pass.feature) and the one related-items check per
Reference (src/papyrus_content/reference_suggest_once.py, features_backend/suggest-once.feature). The index, the embeddings, the S3 Vectors client, the queue and
the backends are fakes; nothing here reaches the network. The pass reads what changed, so these tests count the calls it makes."""
from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_monitoring_router as tr  # noqa: E402
import test_monitoring_stories as tms  # noqa: E402
from field_recorder import FieldRecorder  # noqa: E402
from fake_idea_store import FakeIdeaStore  # noqa: E402
from ideas_fixtures import NOW  # noqa: E402
from test_monitor_stories import StoryModel, pages, with_editors_reasons, world  # noqa: E402
from papyrus_content import monitoring_vectors as vectors  # noqa: E402
from papyrus_content import reference_suggest_once as once  # noqa: E402
from papyrus_content.monitoring_router import run_router, validate_router_config  # noqa: E402
from papyrus_content.monitoring_stories import run_publication, validate_monitor_stories  # noqa: E402
from papyrus_knowledge_query import vector_index  # noqa: E402
from papyrus_knowledge_query.services import KnowledgeQueryServices  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
ARN = "arn:aws:s3vectors:us-east-1:712236451410:bucket/site-vectors/index/site-index"
BUCKET = "site-storage-bucket"
POLICY = {"vectorIndexArn": ARN, "storageBucketName": BUCKET, "suggestions": {"enabled": True}}
PUBLICATION = {"publicationId": "example-site", "corpusId": "knowledge-corpus-example-site", "appsyncEndpoint": tr.ENDPOINT}
RUN_AT = NOW
BODY = "The extracted article body talks about retrieval and ranking at some length. " * 12
SUMMARY = "A study of how small retrieval models rank news items for readers, with the failure cases it found."


@pytest.fixture(autouse=True)
def iam_auth(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")


@pytest.fixture(autouse=True)
def runtime_has_s3vectors(monkeypatch):
    monkeypatch.setattr(vectors, "s3vectors_client_missing_reason", lambda region_name=None: None)


def stamp(minutes: int) -> str:
    """An ``updatedAt`` the given number of minutes after a fixed morning, in the form the index stores."""
    return (datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def row(number: int, minutes: int, status: str = "accepted", **more) -> dict:
    return {"id": f"ref-{number}", "lineageId": f"lineage-{number}", "corpusId": PUBLICATION["corpusId"], "title": f"Title {number}", "sourceUri": f"https://example.org/{number}",
            "versionState": "current", "curationStatus": status, "curationStatusKey": f"{PUBLICATION['corpusId']}#{status}", "updatedAt": stamp(minutes), **more}


class FeedClient:
    """The two ``updatedAt`` indexes of a publication's API: ``.references`` and ``.concepts`` are the rows by id; ``.calls`` counts every request."""

    def __init__(self, references=(), concepts=(), page_size=None):
        self.references = {r["id"]: dict(r) for r in references}
        self.concepts = {c["id"]: dict(c) for c in concepts}
        self.calls = []
        self.page_size = page_size

    def graphql(self, query, variables):
        field = "listReferencesByVersionStateAndUpdatedAt" if "listReferencesByVersionStateAndUpdatedAt" in query else "listSemanticNodesByVersionStateAndUpdatedAt"
        self.calls.append((field, dict(variables)))
        rows = list((self.references if field.startswith("listReferences") else self.concepts).values())
        bound = (variables.get("updatedAt") or {}).get("ge")
        rows = sorted((r for r in rows if r.get("versionState", "current") == "current" and (bound is None or r["updatedAt"] >= bound)), key=lambda r: (r["updatedAt"], r["id"]),
                      reverse=variables.get("sortDirection") == "DESC")
        start = int(variables.get("nextToken") or 0)
        size = min(variables.get("limit") or 1000, self.page_size or 1000)
        page = rows[start:start + size]
        return {field: {"items": page, "nextToken": str(start + size) if start + size < len(rows) else None}}

    def feed_calls(self):
        return len(self.calls)


class Watermark:
    def __init__(self, value=None):
        self.value, self.writes = value, []

    def read(self):
        return self.value

    def write(self, value):
        self.value = value
        self.writes.append(value)


def quiet_place(size: int) -> str:
    """The saved place of a site whose newest row is ``size`` minutes in: the rows of the last ten minutes are remembered by id, as a finished pass leaves them."""
    return saved_place(size, 0, seen={f"ref-{n}": stamp(n) for n in range(max(size - 10, 1), size + 1)})


def saved_place(since_minutes: int, nodes_minutes: int = 0, seen=None) -> str:
    return vectors.dump_state({"since": stamp(since_minutes), "seen": seen or {}, "nodesSince": stamp(nodes_minutes), "nodesSeen": {}})


class FakeAttachmentsGraph:
    """What ``index_changes`` reads about one changed Reference: its attachments, counted."""

    def __init__(self):
        self.attachment_reads = 0

    def graphql(self, query, variables):
        return {}

    def list_reference_attachments(self, reference):
        self.attachment_reads += 1
        return [{"role": "extracted_text", "storagePath": f"s/{reference['lineageId']}.txt"}, {"role": "curation", "metadata": json.dumps({"summary": {"text": SUMMARY}})}]


class FakeCorpus:
    def __init__(self):
        self.reads = 0

    def read_text(self, path):
        self.reads += 1
        return BODY


class FakeIndex:
    """The S3 Vectors index: vectors by key with their data and metadata, and a count of every call made to it."""

    def __init__(self):
        self.stored, self.calls, self.embedded, self.deleted = {}, [], [], []

    def count(self, name):
        return sum(1 for call in self.calls if call == name)

    def get_metadata(self, arn, keys):
        self.calls.append("get_metadata")
        return {key: dict(self.stored[key]["metadata"]) for key in keys if key in self.stored}

    def get(self, arn, keys):
        self.calls.append("get")
        return [{"key": key, "data": self.stored[key]["data"], "metadata": dict(self.stored[key]["metadata"])} for key in keys if key in self.stored]

    def query(self, arn, lineage, data):
        self.calls.append("query")
        return [{"key": key, "metadata": dict(v["metadata"])} for key, v in self.stored.items() if v["metadata"].get("referenceLineageId") == lineage]

    def embed_and_put(self, arn, candidates):
        self.calls.append("embed_and_put")
        for candidate in candidates:
            self.embedded.append(candidate["key"])
            self.stored[candidate["key"]] = {"data": {"float32": [1.0, 0.0]}, "metadata": dict(candidate["metadata"])}
        return len(candidates)

    def put(self, arn, vectors_):
        self.calls.append("put")
        for vector in vectors_:
            self.stored[vector["key"]] = {"data": vector["data"], "metadata": dict(vector["metadata"])}

    def delete(self, arn, keys):
        self.calls.append("delete")
        self.deleted.extend(keys)
        for key in keys:
            self.stored.pop(key, None)

    def list_vectors(self, arn):
        self.calls.append("list_vectors")
        return [{"key": key, "metadata": dict(v["metadata"])} for key, v in self.stored.items()]

    def patches(self):
        return (mock.patch.object(vector_index, "_get_vector_metadata", side_effect=self.get_metadata), mock.patch.object(vector_index, "_get_vectors", side_effect=self.get),
                mock.patch.object(vector_index, "_query_reference_vectors", side_effect=self.query), mock.patch.object(vector_index, "_embed_and_put_vectors", side_effect=self.embed_and_put),
                mock.patch.object(vector_index, "_put_vectors", side_effect=self.put), mock.patch.object(vector_index, "_delete_vectors", side_effect=self.delete),
                mock.patch.object(vector_index, "_list_index_vectors", side_effect=self.list_vectors))


class Site:
    """A fixture site: the feed, the index, the graph and the corpus text with a call counter on each, and a vector pass to run over them."""

    def __init__(self, references=(), concepts=(), place=None, page_size=None):
        self.feed = FeedClient(references, concepts, page_size)
        self.index, self.graph, self.corpus = FakeIndex(), FakeAttachmentsGraph(), FakeCorpus()
        self.watermark = Watermark(place)
        self.heard = []

    def run(self, *, key="sk-test", out_of_time=lambda: False, maximum_cost_usd=0.5, policy=None, hook=True, **fakes):
        from contextlib import ExitStack

        with ExitStack() as stack:
            for patch in self.index.patches():
                stack.enter_context(patch)
            return vectors.run_vector_pass(
                self.feed, PUBLICATION, {**POLICY, **(policy or {})}, now=RUN_AT, out_of_time=out_of_time, maximum_cost_usd=maximum_cost_usd, embedding_key=key,
                read_watermark=self.watermark.read, write_watermark=self.watermark.write,
                services_for=lambda publication, bucket: KnowledgeQueryServices(graph=self.graph, corpus_text=self.corpus),
                on_summary_written=(hook if callable(hook) else (lambda entries: self.heard.extend(entries))) if hook else None, **fakes)

    def graphql_calls(self):
        """Every AppSync request of the pass: the feed reads, plus the attachment reads of the rows it indexed."""
        return len(self.feed.calls) + self.graph.attachment_reads

    def vector_calls(self):
        return len(self.index.calls)

    def fill_index(self):
        """Index every current Reference, as an earlier pass would have, and forget the calls."""
        for r in self.feed.references.values():
            from papyrus_knowledge_query.vector_index import _prepare_reference_for_indexing

            prepared = _prepare_reference_for_indexing(KnowledgeQueryServices(graph=self.graph, corpus_text=self.corpus), r, vector_index.VectorIndexOptions(corpus_id=PUBLICATION["corpusId"]))
            for candidate in prepared["candidates"]:
                self.index.stored[candidate["key"]] = {"data": {"float32": [1.0, 0.0]}, "metadata": dict(candidate["metadata"])}
        self.index.calls.clear()
        self.graph.attachment_reads = 0
        self.corpus.reads = 0
        self.feed.calls.clear()


# --- the pass: what it reads -----------------------------------------------------------------------------------------------------------------


def test_a_site_with_nothing_new_makes_one_read_per_change_feed_and_nothing_else():
    site = Site([row(n, n) for n in range(1, 2001)], place=saved_place(2000, 0, seen={f"ref-{n}": stamp(n) for n in range(1990, 2001)}))
    site.fill_index()
    result = site.run()
    assert result["changeReads"] == 2 and result["changedReferences"] == 0 and result["changedConcepts"] == 0
    assert site.graphql_calls() == 2 and site.vector_calls() == 0 and site.corpus.reads == 0   # the two feeds, and not a single vector, attachment or text read
    assert site.watermark.writes == []   # a quiet day writes nothing either
    assert result["indexed"] == 0 and result["suggestionsQueued"] == 0 and result["stoppedBy"] is None


def test_the_calls_grow_with_what_changed_and_not_with_the_size_of_the_site():
    def changed(size):
        site = Site([row(n, n) for n in range(1, size + 1)], place=quiet_place(size))
        site.fill_index()
        for n in (3, 5, 7):   # a vote, a star and a retitle: three rows touched, none with new text
            site.feed.references[f"ref-{n}"]["updatedAt"] = stamp(size + n)
        result = site.run()
        return site, result

    small, small_result = changed(200)
    large, large_result = changed(5000)
    assert small_result["changedReferences"] == large_result["changedReferences"] == 3
    assert small.graphql_calls() == large.graphql_calls() == 2 + 3   # two feed reads and one attachment read for each changed row
    assert small.vector_calls() == large.vector_calls() and large.index.embedded == []   # a lookup of the three summaries and of their other vectors, and no embedding
    assert large.corpus.reads == 3
    assert large.index.count("list_vectors") == 0 and large.index.count("embed_and_put") == 0


def test_new_references_are_the_only_ones_embedded_and_each_summary_vector_is_announced_once():
    site = Site([row(n, n) for n in range(1, 101)], place=quiet_place(100))
    site.fill_index()
    for n in (101, 102):
        site.feed.references[f"ref-{n}"] = row(n, n)
    result = site.run()
    assert result["changedReferences"] == 2 and result["indexed"] >= 2
    assert sorted(entry["referenceLineageId"] for entry in site.heard) == ["lineage-101", "lineage-102"]
    assert all(entry["contentHash"] for entry in site.heard) and result["suggestionsQueued"] == 2
    assert site.index.embedded.count(vector_index.reference_summary_vector_key("lineage-101")) == 1
    again = site.run()
    assert again["changedReferences"] == 0 and len(site.heard) == 2   # nothing is announced twice


def test_a_vote_or_a_star_finds_the_vector_as_it_is_and_neither_embeds_nor_announces():
    site = Site([row(1, 1), row(2, 2)], place=quiet_place(2))
    site.fill_index()
    site.feed.references["ref-1"].update(updatedAt=stamp(10), starRating=5)
    result = site.run()
    assert result["changedReferences"] == 1 and site.index.embedded == [] and site.heard == [] and result["suggestionsQueued"] == 0


def test_accepting_a_pending_reference_rewrites_its_stored_status_without_embedding_and_without_a_new_check():
    site = Site([row(1, 1, "pending")], place=saved_place(1))
    site.fill_index()
    key = vector_index.reference_summary_vector_key("lineage-1")
    assert site.index.stored[key]["metadata"]["curationStatus"] == "pending"
    first_data = site.index.stored[key]["data"]
    site.feed.references["ref-1"].update(**row(1, 5, "accepted"))
    result = site.run()
    assert site.index.stored[key]["metadata"]["curationStatus"] == "accepted" and site.index.stored[key]["data"] == first_data
    assert any(v["metadata"].get("vectorKind") == "reference_passage" for v in site.index.stored.values())   # an accepted Reference gets its passages
    assert site.heard == [] and key not in site.index.embedded   # the summary vector was not stored again: the check was made when it first was
    assert result["changedReferences"] == 1


def test_rejecting_a_reference_deletes_its_vectors_by_a_filtered_query_and_not_by_listing_the_index():
    site = Site([row(1, 1), row(2, 2)], place=saved_place(2))
    site.fill_index()
    site.feed.references["ref-1"].update(**row(1, 5, "rejected"))
    site.run()
    assert not any(v["metadata"].get("referenceLineageId") == "lineage-1" for v in site.index.stored.values())
    assert any(v["metadata"].get("referenceLineageId") == "lineage-2" for v in site.index.stored.values())
    assert site.index.count("list_vectors") == 0 and site.index.count("query") == 1


def test_an_accepted_reference_sent_back_to_pending_keeps_its_summary_and_loses_its_passages():
    site = Site([row(1, 1)], place=saved_place(1))
    site.fill_index()
    site.feed.references["ref-1"].update(**row(1, 5, "pending"))
    site.run()
    kinds = sorted(v["metadata"]["vectorKind"] for v in site.index.stored.values())
    assert kinds == ["reference_summary"] and next(iter(site.index.stored.values()))["metadata"]["curationStatus"] == "pending"


def test_changed_text_stores_the_summary_vector_again_with_its_new_hash_and_announces_it():
    reference = row(1, 1, "pending")
    site = Site([reference], place=saved_place(1))
    graph = site.graph
    texts = {"value": "First summary of the piece, long enough to be a summary of the piece on its own."}

    def attachments(ref):
        graph.attachment_reads += 1
        return [{"role": "curation", "metadata": json.dumps({"summary": {"text": texts["value"]}})}]

    graph.list_reference_attachments = attachments   # no extracted text: the vector is made from the summary alone, which carries a content hash
    site.run()
    first = site.heard[0]["contentHash"]
    site.run()
    assert len(site.heard) == 1   # nothing changed: nothing stored, nothing announced
    texts["value"] = "A different summary of the piece, written later and also long enough to stand as a summary."
    site.feed.references["ref-1"]["updatedAt"] = stamp(9)
    site.run()
    assert len(site.heard) == 2 and site.heard[1]["contentHash"] != first and site.heard[1]["referenceLineageId"] == "lineage-1"


def test_a_row_written_a_little_late_with_an_earlier_clock_is_read_once_and_a_row_already_done_is_not_read_twice():
    site = Site([row(1, 100)], place=saved_place(100, 0, seen={"ref-1": stamp(100)}))
    site.fill_index()
    site.feed.references["ref-2"] = row(2, 95)   # inside the overlap, behind the saved place, not seen
    result = site.run()
    assert result["changedReferences"] == 1 and [e["referenceLineageId"] for e in site.heard] == ["lineage-2"]
    assert json.loads(site.watermark.value)["seen"].keys() == {"ref-1", "ref-2"}
    assert site.run()["changedReferences"] == 0


def test_the_pages_move_the_saved_place_and_a_run_the_time_stops_resumes_where_it_left_off(monkeypatch):
    monkeypatch.setattr(vectors, "PAGE_SIZE", 2)
    site = Site([row(n, n) for n in range(1, 8)], place=saved_place(0), page_size=2)
    clock = {"pages": 0}

    def out_of_time():
        return clock["pages"] >= 2

    original = vectors.read_changed_page

    def counting(*arguments):
        clock["pages"] += 1
        return original(*arguments)

    monkeypatch.setattr(vectors, "read_changed_page", counting)
    first = site.run(out_of_time=out_of_time)
    assert first["stoppedBy"] == "time" and json.loads(site.watermark.value)["since"] == stamp(2)   # the second page was cut off by the time, so the place stays behind it
    clock["pages"] = -99
    second = site.run()
    assert second["stoppedBy"] is None and json.loads(site.watermark.value)["since"] == stamp(7)
    assert sorted({e["referenceLineageId"] for e in site.heard}) == [f"lineage-{n}" for n in range(1, 8)]


def test_changed_concepts_are_the_only_cards_written_and_an_unchanged_card_costs_no_embedding():
    concept = {"id": "node-1", "lineageId": "node-1", "versionState": "current", "nodeKey": "topic:voice", "nodeKind": "topic", "displayName": "Voice cloning",
               "description": "Making a synthetic copy of a voice.", "aliases": [], "status": "accepted", "updatedAt": stamp(3)}
    site = Site(concepts=[concept], place=saved_place(0, 0))
    first = site.run()
    assert first["conceptCardsWritten"] == 1 and site.index.embedded == ["concept_card-node-1"]
    site.feed.concepts["node-1"]["updatedAt"] = stamp(40)
    second = site.run()
    assert second["changedConcepts"] == 1 and second["conceptCardsWritten"] == 0 and site.index.embedded == ["concept_card-node-1"]


# --- the pass: first run, bounds, reasons ---------------------------------------------------------------------------------------------------


def test_a_site_with_no_saved_place_is_indexed_once_by_the_full_sync_and_the_place_is_set_to_the_newest_change_read_before_it():
    site = Site([row(n, n) for n in range(1, 4)], concepts=[], place=None)
    seen = {}

    def full(services, options):
        seen.update(action=options.action, skip_indexed=options.skip_indexed, explanations=options.include_link_explanations, notes=options.include_notes, hook=options.on_summary_written)
        site.feed.references["ref-9"] = row(9, 50)   # changed while the sync ran: after the place, so the next pass reads it
        return {"vectorsWritten": 3, "conceptCardsToWrite": 0, "embeddingInputCharacters": 400_000}

    result = site.run(full_indexer=full)
    assert seen["action"] == "sync" and seen["skip_indexed"] and not seen["explanations"] and not seen["notes"] and seen["hook"] is not None
    state = json.loads(site.watermark.value)
    assert state["since"] == stamp(3) and state["v"] == 3 and result["bootstrapped"] and result["indexed"] == 3 and result["costUsd"] == pytest.approx(0.002)
    again = site.run()
    assert not again["bootstrapped"] and "lineage-9" in [e["referenceLineageId"] for e in site.heard]


@pytest.mark.parametrize("old", ["2026-10-30T10:00:00Z", '{"v": 2, "done": [], "accepted": {"high": null, "low": null}}', "not json {"])
def test_a_place_written_by_an_older_pass_is_not_trusted_and_the_site_is_indexed_again_once(old):
    site = Site([row(1, 1)], place=old)
    calls = []
    site.run(full_indexer=lambda services, options: calls.append(1) or {"vectorsWritten": 0, "conceptCardsToWrite": 0, "embeddingInputCharacters": 0})
    assert calls == [1] and json.loads(site.watermark.value)["v"] == 3


def test_a_full_sync_the_time_stopped_saves_no_place():
    site = Site([row(1, 1)], place=None)
    result = site.run(full_indexer=lambda services, options: {"vectorsWritten": 0, "conceptCardsToWrite": 0, "embeddingInputCharacters": 0, "stoppedBy": "time"})
    assert result["stoppedBy"] == "time" and site.watermark.writes == []


def test_without_an_index_arn_the_pass_does_nothing_and_says_why():
    site = Site([row(1, 1)], place=saved_place(0))
    result = site.run(policy={"vectorIndexArn": None})
    assert result["indexSkippedReason"] == "no vectorIndexArn in the publication's monitorStories" and site.feed.calls == []


def test_a_runtime_whose_boto3_has_no_s3vectors_client_skips_the_pass_and_says_so(monkeypatch):
    monkeypatch.setattr(vectors, "s3vectors_client_missing_reason", lambda region_name=None: "no usable s3vectors client")
    site = Site([row(1, 1)], place=saved_place(0))
    assert "s3vectors" in site.run()["indexSkippedReason"] and site.feed.calls == []


def test_without_the_openai_key_or_the_bucket_the_pass_reads_nothing_and_says_why():
    site = Site([row(1, 1)], place=saved_place(0))
    assert site.run(key=None)["indexSkippedReason"] == "openai_not_configured"
    assert "storageBucketName" in site.run(policy={"storageBucketName": None})["indexSkippedReason"] and site.feed.calls == []


def test_suggestions_can_be_turned_off_and_the_index_is_still_kept_current():
    site = Site([row(1, 1)], place=saved_place(0))
    result = site.run(policy={"suggestions": {"enabled": False}})
    assert result["indexed"] >= 1 and site.heard == [] and result["suggestionsQueued"] == 0 and "off" in result["suggestionsSkippedReason"]


def test_the_embedding_cost_stops_the_pass_and_keeps_the_place_before_the_unfinished_page():
    site = Site([row(1, 1)], place=saved_place(0))
    site.index.embed_and_put = lambda arn, candidates: (site.index.embedded.extend(c["key"] for c in candidates), len(candidates))[1]

    def indexer(services, options, references, nodes):
        stats = {"vectorsWritten": 1, "conceptCardsToWrite": 0, "embeddingInputCharacters": 400_000_000}
        stats["stoppedBy"] = options.stop_check(stats)
        return stats

    result = site.run(indexer=indexer)
    assert result["stoppedBy"] == "cost" and site.watermark.writes == []


def test_running_out_of_time_before_the_first_page_reads_nothing_and_keeps_the_place():
    site = Site([row(1, 1)], place=saved_place(0))
    result = site.run(out_of_time=lambda: True)
    assert result["stoppedBy"] == "time" and site.feed.calls == [] and site.watermark.writes == []


def test_a_failing_index_is_reported_and_never_raises():
    site = Site([row(1, 1)], place=saved_place(0))

    def failing(services, options, references, nodes):
        raise RuntimeError("index down")

    result = site.run(indexer=failing)
    assert "index sync failed (RuntimeError: index down)" in result["indexSkippedReason"] and site.watermark.writes == []


def test_a_queue_that_refuses_a_message_is_reported_and_the_vectors_stay_stored():
    site = Site([row(1, 1)], place=saved_place(0))

    def refusing(entries):
        raise RuntimeError("queue down")

    result = site.run(hook=refusing)
    assert result["suggestionsNotQueued"] >= 1 and "queue down" in result["suggestionsQueueError"] and result["indexed"] >= 1
    assert json.loads(site.watermark.value)["since"] == stamp(1)


def test_the_embedding_key_and_the_index_arn_are_in_the_environment_only_while_the_index_runs(monkeypatch):
    import os

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PAPYRUS_S3_VECTOR_INDEX_ARN", raising=False)
    seen = {}

    def indexer(services, options, references, nodes):
        seen.update(key=os.environ.get("OPENAI_API_KEY"), arn=os.environ.get("PAPYRUS_S3_VECTOR_INDEX_ARN"))
        return {"vectorsWritten": 0, "conceptCardsToWrite": 0, "embeddingInputCharacters": 0}

    Site([row(1, 1)], place=saved_place(0)).run(indexer=indexer)
    assert seen == {"key": "sk-test", "arn": ARN}
    assert "OPENAI_API_KEY" not in os.environ and "PAPYRUS_S3_VECTOR_INDEX_ARN" not in os.environ


def test_the_pass_has_no_suggestion_step_no_plan_and_no_backlog():
    for name in ("run_suggest_backlog", "plan_since", "OwedMemory", "_Suggesting", "references_since", "advance", "parse_watermark", "SUGGEST_WORKERS"):
        assert not hasattr(vectors, name), name
    from papyrus_content import monitoring_router as router_module

    assert "suggest-backlog" not in router_module.FAN_OUT_TASKS and not hasattr(router_module.Router, "suggest_backlog") and not hasattr(router_module.Router, "owed_memory")


# --- one check per Reference ---------------------------------------------------------------------------------------------------------------------


class Store:
    """The router's table as the check sees it: ``get_any`` / ``put_any`` / ``query_prefix`` over a dictionary, with a count of reads and writes."""

    def __init__(self):
        self.rows, self.reads, self.writes = {}, 0, 0

    def get_any(self, monitor_id, sk):
        self.reads += 1
        return self.rows.get(sk)

    def put_any(self, monitor_id, record):
        self.writes += 1
        self.rows[record["sk"]] = record

    def query_prefix(self, monitor_id, prefix):
        return [r for sk, r in self.rows.items() if sk.startswith(prefix)]


class Suggester:
    def __init__(self, skipped=False, fail=False):
        self.asked, self.skipped, self.fail = [], skipped, fail

    def __call__(self, client, provider, reference_id, **options):
        self.asked.append(reference_id)
        if self.fail:
            raise RuntimeError("s3vectors throttled")
        if self.skipped:
            return {"skipped": "no reference_summary vector is indexed for this Reference", "references": [], "concepts": []}
        return {"skipped": None, "references": [{"outcome": "created"}, {"outcome": "kept"}], "concepts": [{"outcome": "updated"}]}


def check(store, suggester, lineage="lineage-1", content_hash="h1", **message):
    return once.check_once(store, "hn", PUBLICATION, once.suggestion_message("hn", "example-site", lineage, content_hash, **message), client="client", provider="provider",
                           calibration=lambda: "calibration", suggester=suggester, now=RUN_AT)


def test_a_reference_is_checked_once_and_the_record_says_where():
    store, suggester = Store(), Suggester()
    assert check(store, suggester) == "checked"
    assert list(store.rows) == ["STATE#suggested#example-site#lineage-1"]
    record = store.rows["STATE#suggested#example-site#lineage-1"]
    assert record["contentHash"] == "h1" and record["written"] == 2 and record["pk"] == "MONITOR#hn"
    assert check(store, suggester) == "already" and suggester.asked == ["lineage-1"]   # a repeated message does not ask again


def test_the_same_text_is_never_checked_twice_and_changed_text_is_checked_again():
    store, suggester = Store(), Suggester()
    check(store, suggester)
    assert check(store, suggester, content_hash="h1") == "already"
    assert check(store, suggester, content_hash="h2") == "checked" and suggester.asked == ["lineage-1", "lineage-1"]
    assert store.rows["STATE#suggested#example-site#lineage-1"]["contentHash"] == "h2"


def test_a_failed_check_raises_so_the_queue_tries_again_and_records_nothing():
    store = Store()
    with pytest.raises(RuntimeError):
        check(store, Suggester(fail=True))
    with pytest.raises(RuntimeError, match="right after it was stored"):
        check(store, Suggester(skipped=True))
    assert store.rows == {}


def test_an_audit_message_for_a_reference_with_no_vector_is_not_a_failure_and_leaves_no_record():
    store = Store()
    assert check(store, Suggester(skipped=True), content_hash="", audit=True) == "noVector" and store.rows == {}


def record_for(body, message_id="m1"):
    return {"messageId": message_id, "eventSource": "aws:sqs", "body": json.dumps(body)}


def handle(store, records, suggester, lines=None):
    config = {"publications": [{**PUBLICATION, "monitorStories": POLICY}]}
    out = lines if lines is not None else []
    return once.handle_queue(store, {"Records": records}, config_for=lambda monitor: config, appsync=lambda endpoint, *tenant: "client", provider_for=lambda publication: "provider",
                             calibrations=once.Calibrations(lambda client: "calibration"), suggester=suggester, now=RUN_AT, emit=out.append)


def test_a_batch_reports_only_the_failed_messages_so_only_they_are_delivered_again():
    store, suggester, lines = Store(), Suggester(), []
    good = once.suggestion_message("hn", "example-site", "lineage-1", "h1")
    unknown = once.suggestion_message("hn", "nowhere", "lineage-2", "h1")
    response = handle(store, [record_for(good, "ok"), record_for(unknown, "bad"), {"messageId": "junk", "body": "not json"}], suggester, lines)
    assert response == {"batchItemFailures": [{"itemIdentifier": "bad"}, {"itemIdentifier": "junk"}]}
    parsed = [json.loads(line) for line in lines]
    assert [p["suggestOnce"] for p in parsed] == ["checked", "failed", "failed"] and "unknown publication" in parsed[1]["reason"]


def test_the_calibration_is_read_only_when_a_check_runs_and_kept_for_hours():
    reads, clock = [], {"now": 0.0}
    calibrations = once.Calibrations(lambda client: reads.append(client) or "calibration", clock=lambda: clock["now"])
    assert calibrations.get("e", "c") == "calibration" and calibrations.get("e", "c") == "calibration" and len(reads) == 1
    clock["now"] = once.CALIBRATION_SECONDS + 1
    calibrations.get("e", "c")
    assert len(reads) == 2
    store = Store()
    handle(store, [record_for(once.suggestion_message("hn", "example-site", "lineage-1", "h1"))], Suggester())
    reads_before = len(reads)
    handle(store, [record_for(once.suggestion_message("hn", "example-site", "lineage-1", "h1"))], Suggester())   # already checked: the record answers before the calibration is asked
    assert len(reads) == reads_before


class Sqs:
    def __init__(self, refuse=False):
        self.requests, self.refuse = [], refuse

    def send_message_batch(self, QueueUrl, Entries):
        self.requests.append((QueueUrl, Entries))
        return {"Failed": [{"Id": "0", "Code": "InternalError"}]} if self.refuse else {}


def test_messages_go_out_ten_to_a_request_and_a_refusal_is_an_error():
    sqs = Sqs()
    messages = [once.suggestion_message("hn", "example-site", f"lineage-{n}", "h") for n in range(25)]
    assert once.send_messages(sqs, "https://queue", messages) == 25 and [len(entries) for _, entries in sqs.requests] == [10, 10, 5]
    assert json.loads(sqs.requests[0][1][0]["MessageBody"])["referenceLineageId"] == "lineage-0"
    with pytest.raises(RuntimeError, match="refused"):
        once.send_messages(Sqs(refuse=True), "https://queue", messages[:1])


def test_the_hook_queues_one_message_per_stored_summary_vector():
    sqs = Sqs()
    once.queue_sender("hn", "example-site", sqs, "https://queue")([{"referenceLineageId": "lineage-1", "contentHash": "h1", "key": "k1"}, {"referenceLineageId": "", "contentHash": "h", "key": "k"}])
    bodies = [json.loads(e["MessageBody"]) for _, entries in sqs.requests for e in entries]
    assert [b["referenceLineageId"] for b in bodies] == ["lineage-1"] and bodies[0]["contentHash"] == "h1" and "audit" not in bodies[0]


class ListingClient:
    def __init__(self, accepted, pending=()):
        self.rows, self.asked = {"accepted": accepted, "pending": list(pending)}, []

    def list_by_index(self, index, key, *, limit=100):
        self.asked.append(key)
        return [{"lineageId": n, "id": f"id-{n}", "versionState": "current"} for n in self.rows[key.rsplit("#", 1)[1]]]


def test_the_by_hand_command_lists_only_references_with_no_record_and_writes_nothing_without_write():
    store = Store()
    check(store, Suggester(), lineage="lineage-1")
    client, sqs = ListingClient(["lineage-1", "lineage-2"], ["lineage-3"]), Sqs()
    dry = once.queue_unchecked(client, store, "hn", PUBLICATION, write=False, sqs=sqs, queue_url="https://queue")
    assert dry["unchecked"] == 2 and dry["queued"] == 0 and dry["write"] is False and sqs.requests == []
    assert "scanned" in dry and client.asked == [f"{PUBLICATION['corpusId']}#accepted", f"{PUBLICATION['corpusId']}#pending"]
    wet = once.queue_unchecked(client, store, "hn", PUBLICATION, write=True, sqs=sqs, queue_url="https://queue")
    bodies = [json.loads(e["MessageBody"]) for _, entries in sqs.requests for e in entries]
    assert wet["queued"] == 2 and sorted(b["referenceLineageId"] for b in bodies) == ["lineage-2", "lineage-3"] and all(b["audit"] for b in bodies)
    with pytest.raises(RuntimeError, match="SUGGEST_QUEUE_URL"):
        once.queue_unchecked(client, store, "hn", PUBLICATION, write=True)


# --- the settings ---------------------------------------------------------------------------------------------------------------------------


def test_the_vector_settings_default_to_suggestions_on_and_no_index_and_validate():
    normalized = validate_monitor_stories("p", None)
    assert normalized["suggestions"] == {"enabled": True} and normalized["vectorIndexArn"] is None and normalized["storageBucketName"] is None
    filled = validate_monitor_stories("p", {"vectorIndexArn": ARN, "storageBucketName": BUCKET, "suggestions": {"enabled": False}})
    assert filled["vectorIndexArn"] == ARN and filled["storageBucketName"] == BUCKET and filled["suggestions"] == {"enabled": False}
    assert validate_monitor_stories("p", filled) == filled
    for bad in ({"vectorIndexArn": "arn:aws:s3:::a-bucket"}, {"vectorIndexArn": 3}, {"storageBucketName": "Not A Bucket"}, {"suggestions": {"enabled": "yes"}},
                {"suggestions": {"limit": 3}}, {"suggestions": True}):
        with pytest.raises(ValueError):
            validate_monitor_stories("p", bad)


def seed_module():
    spec = importlib.util.spec_from_file_location("seed_router_config", ROOT / "infra/monitoring/seed_router_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def amplify_outputs(arn=ARN, bucket=BUCKET):
    return {"custom": {"knowledgeQuery": {"s3VectorIndexArn": arn}}, "storage": {"bucket_name": bucket}}


def test_seeding_reads_the_index_arn_and_the_bucket_from_each_sites_amplify_outputs():
    seed = seed_module()
    config = json.loads((ROOT / "docs/monitoring-router-config.example.json").read_text())
    config["publications"][0]["monitorStories"] = {"singleItem": False}
    filled = seed.fill_vector_settings(config, {"anth-us": amplify_outputs(), "threat-intelligence": amplify_outputs(ARN.replace("site-index", "other"), "other-bucket")})
    first, second, third = (entry["monitorStories"] for entry in filled["publications"])
    assert first == {"singleItem": False, "vectorIndexArn": ARN, "storageBucketName": BUCKET}   # what the entry already said is kept
    assert third["vectorIndexArn"].endswith("index/other") and third["storageBucketName"] == "other-bucket"
    assert second["vectorIndexArn"] != ARN   # p-apyr-us was not named: its entry is untouched
    publications = validate_router_config(filled)["publications"]
    assert publications[0]["monitorStories"]["vectorIndexArn"] == ARN
    assert config["publications"][0]["monitorStories"] == {"singleItem": False}   # the input is not changed


def test_seeding_refuses_outputs_without_an_index_or_a_bucket_and_publications_that_are_not_in_the_config():
    seed = seed_module()
    config = json.loads((ROOT / "docs/monitoring-router-config.example.json").read_text())
    with pytest.raises(ValueError, match="s3VectorIndexArn"):
        seed.fill_vector_settings(config, {"anth-us": {"custom": {}, "storage": {"bucket_name": BUCKET}}})
    with pytest.raises(ValueError, match="bucket_name"):
        seed.fill_vector_settings(config, {"anth-us": {"custom": {"knowledgeQuery": {"s3VectorIndexArn": ARN}}}})
    with pytest.raises(ValueError, match="not in the config"):
        seed.fill_vector_settings(config, {"nowhere": amplify_outputs()})


# --- the pass: order, watermark, bounds -----------------------------------------------------------------------------------------------------



# --- the router: what it hands the pass, the queue entry point --------------------------------------------------------------------------------


def drafter_recording(seen):
    def draft(client, publication, **options):
        seen.append(options)
        return {"publicationId": publication["publicationId"], "status": "complete", "drafted": 0, "stoppedBy": None, "indexed": 0, "conceptCardsWritten": 0,
                "suggestionsQueued": 0, "suggestionsSkippedReason": None, "costUsd": 0.0}

    return draft


def run_monitor_stories(store, **more):
    out = io.StringIO()
    with redirect_stdout(out):
        result = run_router(store, "hn", now=NOW.timestamp(), task="monitor-stories", appsync=lambda endpoint: object(), deliver=tr.Delivery(), story_transport=StoryModel(),
                            embedding_key="sk-test", **more)
    return result, out.getvalue()


def test_the_router_hands_the_pass_a_sender_for_the_suggestion_queue_and_no_owed_memory_or_plan():
    table, store = tms.router(settings={tms.PUBLICATION: {**tms.SINGLE_ITEM_ONLY, "vectorIndexArn": ARN, "storageBucketName": BUCKET}})
    seen, sqs = [], Sqs()
    run_monitor_stories(store, story_drafter=drafter_recording(seen), suggest_queue=(sqs, "https://queue"))
    assert "owed" not in seen[0] and callable(seen[0]["on_summary_written"])
    seen[0]["on_summary_written"]([{"referenceLineageId": "lineage-1", "contentHash": "h", "key": "k"}])
    body = json.loads(sqs.requests[0][1][0]["MessageBody"])
    assert body["monitorId"] == "hn" and body["publicationId"] == tms.PUBLICATION and body["referenceLineageId"] == "lineage-1"


def test_a_router_without_a_suggestion_queue_hands_the_pass_no_sender():
    table, store = tms.router(settings={tms.PUBLICATION: {**tms.SINGLE_ITEM_ONLY, "vectorIndexArn": ARN, "storageBucketName": BUCKET}})
    seen = []
    run_monitor_stories(store, story_drafter=drafter_recording(seen))
    assert seen[0]["on_summary_written"] is None


def test_the_router_has_no_suggest_backlog_task_a_stray_event_runs_the_ordinary_sweep_and_no_fan_out():
    table, store = tms.router()
    started = []
    result = run_router(store, "hn", task="suggest-backlog", fan_out=started.append, deliver=tr.Delivery(), appsync=lambda endpoint: object())
    assert started == [] and result.get("status") != "fanned-out"


def router_with(settings):
    return tms.router(settings={tms.PUBLICATION: settings})


def run_task(store, client, order, monkeypatch, *, key="sk-test", drafter_options=None):
    """Runs the daily monitor-stories task with a vector pass that records its place in the order of the steps and returns a canned count of what it did."""
    def fake_pass(client_, publication, policy, **options):
        order.append("index")
        return {**vectors.EMPTY_RESULT, "timings": {"passSeconds": 0.1}, "indexed": 3, "conceptCardsWritten": 1, "suggestionsQueued": 2, "costUsd": 0.002}

    monkeypatch.setattr("papyrus_content.monitoring_vectors.run_vector_pass", fake_pass)
    with_editors_reasons(client)   # a single item needs something the newsroom knows beyond its source
    endpoints = {tr.ENDPOINT.replace("abc123", "api0"): client}
    out = io.StringIO()
    from papyrus_content.ideas import monitor_stories

    real_drafting = monitor_stories.draft_monitor_stories
    monkeypatch.setattr(monitor_stories, "draft_monitor_stories", lambda **options: (order.append("drafting"), real_drafting(**options))[1])
    base = partial(run_publication, fetch=pages(*range(1, 60)), explorer=None)

    def draft(client_, publication, **options):
        return base(client_, publication, **{**options, **(drafter_options or {})})   # a test's own options win over what the router passes

    with redirect_stdout(out):
        result = run_router(store, "hn", now=NOW.timestamp(), task="monitor-stories", appsync=lambda endpoint: endpoints[endpoint], deliver=tr.Delivery(),
                            story_transport=StoryModel(), story_drafter=draft, embedding_key=key)
    line = next(json.loads(text) for text in out.getvalue().splitlines() if text.startswith('{"monitorStories"'))
    return result, line


@pytest.fixture
def idea_sink(monkeypatch):
    monkeypatch.setattr("papyrus_content.ideas.items.ItemStore", lambda client, **options: FakeIdeaStore(client, gate=options.get("gate")))
    from test_idea_items import FakeGate
    monkeypatch.setattr("papyrus_content.ideas.gate.HumanusGate.for_client", classmethod(lambda cls, client, **options: FakeGate()))


def test_a_router_run_indexes_then_drafts_and_the_log_line_names_each_count(idea_sink, monkeypatch):
    table, store = router_with({**tms.SINGLE_ITEM_ONLY, "vectorIndexArn": ARN, "storageBucketName": BUCKET})
    _, client = world(2)
    order = []
    result, line = run_task(store, client, order, monkeypatch)
    assert order == ["index", "drafting"]
    assert (line["indexed"], line["conceptCardsWritten"], line["suggestionsQueued"], line["suggestionsSkippedReason"]) == (3, 1, 2, None)
    assert line["drafted"] == 2 and line["costUsd"] >= 0.002 and result["monitorStories"][tms.PUBLICATION]["indexed"] == 3


def test_a_run_without_an_index_arn_still_drafts_and_logs_the_reason_suggestions_are_off(idea_sink):
    table, store = router_with(tms.SINGLE_ITEM_ONLY)
    _, client = world(2)
    result, lines = tms.run_task(store, {tms.PUBLICATION: client}, StoryModel())
    line = lines[tms.PUBLICATION]
    assert line["drafted"] == 2
    assert (line["indexed"], line["conceptCardsWritten"], line["suggestionsQueued"]) == (0, 0, 0)
    assert line["suggestionsSkippedReason"] == "no vectorIndexArn in the publication's monitorStories"
    assert table.get_item({"pk": "MONITOR#hn", "sk": vectors.watermark_sort_key(tms.PUBLICATION)}).get("Item") is None


def test_the_log_line_of_a_publication_that_was_skipped_or_disabled_carries_the_vector_fields_too(idea_sink):
    table, store = router_with({"enabled": False})
    _, client = world(1)
    _, lines = tms.run_task(store, {tms.PUBLICATION: client}, StoryModel())
    assert lines[tms.PUBLICATION]["status"] == "disabled" and lines[tms.PUBLICATION]["suggestionsSkippedReason"] is None and lines[tms.PUBLICATION]["indexed"] == 0


def test_the_router_holds_the_vector_pass_to_the_first_quarter_of_a_publications_time():
    table, store = router_with(dict(tms.SINGLE_ITEM_ONLY))
    _, client = world(1)
    remaining, seen = [400], {}

    def drafter(client_, publication, **options):
        seen.update(options)
        return {"publicationId": publication["publicationId"], "status": "complete", "stoppedBy": None, "drafted": 0}

    run_router(store, "hn", now=NOW.timestamp(), task="monitor-stories", appsync=lambda endpoint: client, deliver=tr.Delivery(), time_left=lambda: remaining[0],
               story_transport=StoryModel(), story_drafter=drafter)
    for left, expected in ((331, (False, False)), (329, (False, True)), (119, (True, True))):
        remaining[0] = left
        assert (seen["out_of_time"](), seen["vector_out_of_time"]()) == expected, left


def test_a_sqs_event_is_recognised_and_an_event_of_the_scheduler_is_not():
    from papyrus_content.monitoring_router import is_suggestion_queue_event

    assert is_suggestion_queue_event({"Records": [{"eventSource": "aws:sqs"}]})
    assert not is_suggestion_queue_event({"task": "monitor-stories"}) and not is_suggestion_queue_event({"Records": [{"eventSource": "aws:s3"}]}) and not is_suggestion_queue_event({})


def test_the_queue_entry_point_reads_the_routers_config_checks_the_reference_and_records_it():
    from papyrus_content import monitoring_router as router_module

    table, store = tms.router(settings={tms.PUBLICATION: {**tms.SINGLE_ITEM_ONLY, "vectorIndexArn": ARN, "storageBucketName": BUCKET}})
    suggester = Suggester()
    event = {"Records": [record_for(once.suggestion_message("hn", tms.PUBLICATION, "lineage-1", "h1"))]}
    out = io.StringIO()
    router_module.CALIBRATIONS = once.Calibrations(lambda client: "calibration")
    with redirect_stdout(out):
        response = router_module.handle_suggestion_queue(store, event, appsync=lambda endpoint, *tenant: "client", suggester=suggester, provider_for=lambda publication: "provider", now=RUN_AT)
    assert response == {"batchItemFailures": []} and suggester.asked == ["lineage-1"]
    assert json.loads(out.getvalue())["suggestOnce"] == "checked"
    stored = table.get_item({"pk": "MONITOR#hn", "sk": f"STATE#suggested#{tms.PUBLICATION}#lineage-1"})["Item"]
    assert stored["contentHash"] == "h1"


# --- IAM and the template ------------------------------------------------------------------------------------------------------------------


SITES = ("AnthUs", "Papyrus", "ThreatIntel", "DataParade", "Pilobolus", "Shipped", "Distinctive", "MachinesOnMachines")


def template_text():
    return (ROOT / "infra" / "monitoring" / "papyrus-monitoring.yaml").read_text()


def block_of(text, name):
    start = text.index(f"\n  {name}:\n")
    end = text.find("\n\n  ", start + 1)
    return text[start:end if end != -1 else len(text)]


def idea_policy_text():
    text = template_text()
    return text, block_of(text, "RouterIdeaPolicy")


def test_the_idea_policy_grants_the_s3_vectors_actions_on_the_eight_indexes_and_reads_the_eight_buckets_and_no_policy_was_added():
    text = template_text()
    policy = block_of(text, "RouterEnrichmentStoragePolicy")   # moved out of RouterIdeaPolicy, which hit IAM's policy-size limit
    assert "Sid: SiteVectorIndexes" not in block_of(text, "RouterIdeaPolicy")
    block = policy[policy.index("Sid: SiteVectorIndexes"):]
    for action in ("s3vectors:GetVectors", "s3vectors:QueryVectors", "s3vectors:PutVectors", "s3vectors:ListVectors"):
        assert action in block
    assert "s3vectors:DeleteVectors" not in block and "s3vectors:*" not in block
    for site in SITES:
        assert f"- !Ref {site}VectorIndexArn" in block, site
        assert f'arn:${{AWS::Partition}}:s3:::${{{site}StorageBucketName}}/*' in block, site
        for parameter, default in ((f"{site}VectorIndexArn", "unset-vector-index"), (f"{site}StorageBucketName", "unset-storage-bucket")):
            declared = text[text.index(f"\n  {parameter}:\n"):]
            assert default in declared[:declared.index("Description")], parameter   # the default names nothing, so an unfilled parameter grants nothing real
    assert "Resource: '*'" not in block and 's3:::*' not in block
    assert "Roles: [!Ref RouterRole]" in policy


def granted_fields(policy):
    return {(kind, name) for kind, name in re.findall(r"apis/\*/types/(Query|Mutation)/fields/(\w+)\"", policy)}


def test_every_graphql_field_the_pass_and_the_first_run_ask_for_is_granted_by_the_idea_policy():
    """Records the fields the pass asks a publication's API for (the change feeds, the attachments of a changed Reference, the one-time full sync), then checks the policy grants them."""
    asked = set()

    class Graph:
        def graphql(self, query, variables):
            asked.update(("Query", name) for name in re.findall(r"\b((?:list|get)[A-Z]\w+)\(", query))
            return {}

        def list_reference_attachments(self, reference):
            asked.add(("Query", "listReferenceAttachmentsByReferenceLineageAndSortKey"))
            return []

        def list_outgoing_relations_batch(self, objects):
            asked.add(("Query", "listSemanticRelationsBySubjectState"))
            return {}

    graph = Graph()
    feed = FeedClient([row(1, 1)], [])
    original = feed.graphql
    feed.graphql = lambda query, variables: (asked.update(("Query", name) for name in re.findall(r"\b((?:list|get)[A-Z]\w+)\(", query)), original(query, variables))[1]
    index = FakeIndex()
    from contextlib import ExitStack

    with ExitStack() as stack:
        for patch in index.patches():
            stack.enter_context(patch)
        stack.enter_context(mock.patch.object(vector_index, "_prepare_ontology_vectors", return_value=[]))
        for place in (None, saved_place(0)):   # the first run (the full sync), then a day of changes
            vectors.run_vector_pass(feed, PUBLICATION, POLICY, now=RUN_AT, out_of_time=lambda: False, maximum_cost_usd=1.0, embedding_key="sk-test",
                                    read_watermark=lambda place=place: place, write_watermark=lambda value: None,
                                    services_for=lambda publication, bucket: KnowledgeQueryServices(graph=graph, corpus_text=FakeCorpus()))
    granted = granted_fields(idea_policy_text()[1])
    assert {("Query", "listReferencesByVersionStateAndUpdatedAt"), ("Query", "listSemanticNodesByVersionStateAndUpdatedAt"), ("Query", "listReferences")} <= asked
    assert asked <= granted | {("Query", "getReference")}, sorted(asked - granted)


def test_every_graphql_field_a_suggestion_check_asks_for_is_granted_to_the_worker_and_the_worker_cannot_write_vectors():
    from papyrus_content.reference_suggestions import suggest_for
    from papyrus_content.suggestion_calibration import load_calibration
    from test_reference_suggestions import build

    inner, provider = build()
    original_get = inner.get_record
    inner.get_record = lambda model, record_id: {"id": "node-voice-v1", "lineageId": "node-voice", "versionNumber": 1} if model == "SemanticNode" else original_get(model, record_id)
    original_list = inner.list_by_index
    inner.list_by_index = lambda index, key, **kw: [] if index == "semanticRelationsByNewsroomFeedAndCreatedAt" else original_list(index, key, **kw)
    recorder = FieldRecorder(inner)
    for _ in range(2):   # the second pass finds the edge already written and updates it
        suggest_for(recorder, provider, "reference-a-v1", corpus_id="corpus-1", calibration=load_calibration(recorder), now="2026-11-01T12:00:00Z")
    recorded = set(recorder.fields)
    assert ("Mutation", "createSemanticRelation") in recorded
    text = template_text()
    worker = block_of(text, "SuggestWorkerRole")
    assert recorded <= granted_fields(worker), sorted(recorded - granted_fields(worker))
    assert "s3vectors:GetVectors" in worker and "s3vectors:QueryVectors" in worker
    assert "PutVectors" not in worker and "DeleteVectors" not in worker and "ListVectors" not in worker and "s3:GetObject" not in worker and "lambda:InvokeFunction" not in worker


def test_the_template_has_no_suggest_backlog_schedule_and_one_check_queue_with_a_bounded_retry_a_dead_letter_queue_and_an_alarm():
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_multi_constructor("!", lambda loader, suffix, node: {suffix: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else loader.construct_sequence(node)
                                                                   if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node)})
    resources = yaml.load(template_text(), Loader=Loader)["Resources"]
    assert not [name for name, resource in resources.items() if "SuggestBacklog" in name]
    inputs = [json.loads(r["Properties"]["Target"]["Input"]) for r in resources.values() if r["Type"] == "AWS::Scheduler::Schedule" and isinstance(r["Properties"]["Target"].get("Input"), str)
              and r["Properties"]["Target"]["Input"].startswith("{")]
    assert not [i for i in inputs if "suggest" in str(i.get("task"))]
    queue = resources["SuggestQueue"]["Properties"]
    assert queue["RedrivePolicy"]["maxReceiveCount"] == 3 and queue["RedrivePolicy"]["deadLetterTargetArn"] == {"GetAtt": "SuggestDeadLetterQueue.Arn"}
    assert queue["VisibilityTimeout"] >= 6 * resources["SuggestWorkerFunction"]["Properties"]["Timeout"]
    mapping = resources["SuggestEventSourceMapping"]["Properties"]
    assert mapping["FunctionResponseTypes"] == ["ReportBatchItemFailures"] and mapping["ScalingConfig"]["MaximumConcurrency"] == 2 and mapping["FunctionName"] == {"Ref": "SuggestWorkerFunction"}
    alarm = resources["SuggestDeadLetterAlarm"]["Properties"]
    assert alarm["MetricName"] == "ApproximateNumberOfMessagesVisible" and alarm["AlarmActions"] == [{"Ref": "AlarmTopic"}]
    assert resources["RouterFunction"]["Properties"]["Environment"]["Variables"]["SUGGEST_QUEUE_URL"] == {"Ref": "SuggestQueue"}
    router_inline = json.dumps(resources["RouterRole"]["Properties"]["Policies"])
    assert "sqs:SendMessage" in router_inline and "sqs:ReceiveMessage" not in router_inline   # the router sends; only the worker takes messages off


# --- packaging ---------------------------------------------------------------------------------------------------------------------------------




def load_build():
    spec = importlib.util.spec_from_file_location("monitoring_build", ROOT / "infra/monitoring/build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    return build


def test_the_router_zip_closure_carries_the_vector_pass_and_the_knowledge_query_package_and_they_import_with_the_standard_library_and_pyyaml(tmp_path):
    """The closure the zip holds (no wheels: those are fetched for the Lambda and need the network) imports in an isolated interpreter that has no boto3."""
    import shutil
    import subprocess

    import yaml

    build = load_build()
    modules = build.router_modules()
    needed = ["monitoring_vectors", "reference_suggest_once", "reference_suggestions", "suggestion_calibration", "reference_links", "knowledge_snapshot/keys", "knowledge_wiki/pages", "corpus_storage_paths"]
    assert set(needed) <= set(modules), sorted(set(needed) - set(modules))
    files = build.knowledge_query_files()
    assert set(files) == {f"papyrus_knowledge_query/{name}.py" for name in ("__init__", "concept_kinds", "cuts", "engine", "ranking", "reference_search", "reference_words", "services", "tokens", "uris", "vector_index")}
    assert sum(len(data) for data in files.values()) < 1_000_000   # source only: far below the zip's bound
    task = tmp_path / "task"
    for name in ["__init__", *modules]:
        target = task / "papyrus_content" / f"{name}.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / "src" / "papyrus_content" / f"{name}.py", target)
    for name, data in files.items():
        target = task / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    shutil.copytree(Path(yaml.__file__).parent, task / "yaml")
    script = ("import sys; sys.path.insert(0, sys.argv[1])\n"
              "from papyrus_content import monitoring_vectors, reference_suggestions, suggestion_calibration\n"
              "from papyrus_knowledge_query import vector_index\n"
              "from papyrus_knowledge_query.services import S3VectorsProvider, S3CorpusTextProvider, GraphQLKnowledgeGraphProvider\n"
              "assert vector_index.VectorIndexOptions(stop_check=None).action == 'sync'\n"
              "assert not any(m in sys.modules for m in ('pydantic', 'biblicus', 'httpx', 'tiktoken', 'boto3'))\n")
    done = subprocess.run([sys.executable, "-I", "-S", "-c", script, str(task)], capture_output=True, text=True, cwd=tmp_path)
    assert done.returncode == 0, done.stderr[-1200:]
