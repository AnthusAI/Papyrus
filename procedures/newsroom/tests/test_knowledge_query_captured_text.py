"""PPY-caa222: a knowledge query reads the Reference's current captured text, not only an `extracted_text` attachment."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from captured_text_support import LINEAGE, LONG_ID, SENTINEL, CapturedTextGraph, CorporaOnlyText, edit, query  # noqa: E402

from papyrus_content.model_attachments import attachment_safe_id, model_attachment_id, model_payload_storage_path  # noqa: E402
from papyrus_content.reference_curation_store import AttachmentStore  # noqa: E402
from curation_support import MemoryClient, reference as curation_reference  # noqa: E402


def passages(result):
    return result["structured"]["evidencePassages"]


# --- the writer's id (PPY-caa222, the CLI symptom) ---------------------------------------------------------------------------------------------


def test_the_attachment_id_matches_the_deployed_writer_for_a_long_reference_id():
    # Computed with `safeId` from amplify/functions/model-attachment-upload/handler.ts (node), not with this module.
    assert attachment_safe_id(LONG_ID) == "reference-knowledge-corpus-machines-on-machines-0123456789abcdef012-913ca99b5bf0"
    assert attachment_safe_id("Curation Edit 0001") == "curation-edit-0001"
    assert attachment_safe_id("") == "payload" and attachment_safe_id(None) == "payload"
    assert attachment_safe_id("a" * 100 + "-b") == "a" * 67 + "-3509dc148195"
    assert model_attachment_id("reference", LONG_ID, "metadata", "curation-edit-0001-text") == (
        "model-attachment-reference-reference-knowledge-corpus-machines-on-machines-0123456789abcdef012-913ca99b5bf0-metadata-curation-edit-0001-text")
    assert "913ca99b5bf0" in model_payload_storage_path("reference", LONG_ID, "metadata", "x.md")


def test_the_store_finds_a_body_by_the_owner_index_whatever_id_the_writer_made():
    ref = curation_reference("r1")
    client = MemoryClient([ref])
    client.tables["ModelAttachment"]["whatever-the-writer-made"] = {"id": "whatever-the-writer-made", "ownerKind": "reference", "ownerId": ref["id"],
        "role": "metadata", "sortKey": "curation-edit-0001-text", "status": "active", "storagePath": "newsroom/payloads/x"}
    client.tables["ModelAttachment"]["old"] = {"id": "old", "ownerKind": "reference", "ownerId": ref["id"], "role": "metadata",
        "sortKey": "curation-edit-0001-text", "status": "deleted", "storagePath": "newsroom/payloads/y"}
    store = AttachmentStore(client)
    assert store.find(ref, "curation-edit-0001-text")["id"] == "whatever-the-writer-made"
    assert store.find(ref, "curation-text") is None


# --- the knowledge query -----------------------------------------------------------------------------------------------------------------------


def test_a_captured_reference_supplies_evidence_passages():
    graph = CapturedTextGraph()
    graph.card(text_sort_key="curation-edit-0001-text", edits=[edit(1, "curation-edit-0001-text")])
    graph.body("curation-edit-0001-text", SENTINEL)
    result = query(graph)
    found = passages(result)
    assert found and "independent audit logs" in found[0]["text"]
    assert result["context"]["sourceTextMode"] != "metadata"
    assert not [w for w in result["warnings"] if "text" in w.lower()], result["warnings"]


def test_the_evidence_names_who_captured_it_and_keeps_the_agent_label():
    graph = CapturedTextGraph()
    graph.card(text_sort_key="curation-edit-0001-text", edits=[edit(1, "curation-edit-0001-text")],
               labels=[{"kind": "capture_completeness", "assessment": "incomplete", "editSortKeys": ["curation-edit-0001-text"]}])
    graph.body("curation-edit-0001-text", SENTINEL)
    result = query(graph)
    capture = passages(result)[0]["capture"]
    assert capture["editedBy"] == "agent:researcher" and capture["note"] == "Captured by an AI agent; not independently completeness-checked."
    assert capture["source"] == "curation_edit" and capture["assessmentOfMachineCapture"] == "incomplete"
    assert passages(result)[0]["textSource"] == "curation_edit"
    assert "not independently completeness-checked" in result["context"]["text"]


def test_a_later_correction_beats_the_earlier_one_and_is_attributed():
    graph = CapturedTextGraph()
    graph.card(text_sort_key="curation-edit-0002-text", edits=[edit(1, "curation-edit-0001-text"), edit(2, "curation-edit-0002-text", by="editor-ann", note="")])
    graph.body("curation-edit-0001-text", "OLD TEXT about something unrelated to oversight " * 6)
    graph.body("curation-edit-0002-text", SENTINEL)
    found = passages(query(graph))
    assert found and all("OLD TEXT" not in p["text"] for p in found)
    assert found[0]["capture"]["editedBy"] == "editor-ann" and found[0]["capture"]["sortKey"] == "curation-edit-0002-text"


def test_a_human_correction_beats_an_extracted_text_attachment():
    graph = CapturedTextGraph()
    path = graph.extracted("x")
    graph.card(text_sort_key="curation-edit-0001-text", edits=[edit(1, "curation-edit-0001-text", by="editor-ann")])
    graph.body("curation-edit-0001-text", SENTINEL)
    corpus = CorporaOnlyText({path: "STALE MACHINE EXTRACTION " * 20})
    found = passages(query(graph, corpus_text=corpus))
    assert found and "STALE" not in found[0]["text"] and corpus.reads == []


def test_extracted_text_beats_the_machine_capture_when_nobody_corrected_it():
    graph = CapturedTextGraph()
    path = graph.extracted("x")
    graph.card(text_sort_key="curation-text")
    graph.body("curation-text", "MACHINE CAPTURE " * 20)
    corpus = CorporaOnlyText({path: SENTINEL})
    found = passages(query(graph, corpus_text=corpus))
    assert found and "independent audit logs" in found[0]["text"] and "capture" not in found[0]
    assert not [r for r in graph.requests if r[0] == "download"]


def test_the_machine_capture_is_used_when_it_is_all_there_is():
    graph = CapturedTextGraph()
    graph.card(text_sort_key="curation-text")
    graph.body("curation-text", SENTINEL)
    found = passages(query(graph))
    assert found and found[0]["textSource"] == "curation_text"


def test_only_the_matched_reference_is_looked_up_by_its_owner_and_no_id_is_built():
    graph = CapturedTextGraph()
    graph.card(text_sort_key="curation-edit-0001-text", edits=[edit(1, "curation-edit-0001-text")])
    graph.body("curation-edit-0001-text", SENTINEL)
    graph.body("curation-edit-0001-text", "A DIFFERENT VERSION'S BODY", owner="someone-elses-v1")
    result = query(graph)
    lookups = [r for r in graph.requests if r[0] == "owner_index"]
    assert lookups and all(r == ("owner_index", {"ownerId": LONG_ID, "limit": 50, "nextToken": None}) for r in lookups)   # one owner, never a table
    assert all("DIFFERENT VERSION" not in p["text"] for p in passages(result))
    assert [r[1]["attachmentId"] for r in graph.requests if r[0] == "download"] == ["model-attachment-writer-made-0"]


def test_a_deleted_or_inactive_body_is_not_read_and_the_gap_is_reported():
    graph = CapturedTextGraph()
    graph.card(text_sort_key="curation-edit-0001-text", edits=[edit(1, "curation-edit-0001-text")])
    graph.body("curation-edit-0001-text", SENTINEL, status="deleted")
    result = query(graph)
    assert passages(result) == [] and result["context"]["sourceTextMode"] == "metadata"
    assert any("curation-edit-0001-text" in w and "no active attachment" in w for w in result["warnings"]), result["warnings"]


def test_a_refused_download_is_reported_not_swallowed():
    graph = CapturedTextGraph()
    graph.card(text_sort_key="curation-edit-0001-text", edits=[edit(1, "curation-edit-0001-text")])
    attachment_id = graph.body("curation-edit-0001-text", SENTINEL)
    graph.denied_downloads.add(attachment_id)
    result = query(graph)
    assert passages(result) == []
    assert any("exists but could not be read" in w and "Not Authorized" in w for w in result["warnings"]), result["warnings"]
    assert SENTINEL not in result["context"]["text"]


def test_a_failed_owner_lookup_is_reported():
    graph = CapturedTextGraph()
    graph.card(text_sort_key="curation-text")
    graph.owner_index_error = "boom"
    result = query(graph)
    assert passages(result) == [] and any("Could not look up the captured text" in w and "boom" in w for w in result["warnings"]), result["warnings"]


def test_an_empty_body_is_reported():
    graph = CapturedTextGraph()
    graph.card(text_sort_key="curation-text")
    graph.body("curation-text", "   ")
    assert any("exists but is empty" in w for w in query(graph)["warnings"])


def test_a_reference_with_no_text_anywhere_says_so():
    graph = CapturedTextGraph()
    result = query(graph)
    assert any("No extracted or captured text found" in w for w in result["warnings"]) and passages(result) == []
    assert not [r for r in graph.requests if r[0] == "download"]


def test_a_reference_the_query_does_not_return_is_never_read():
    graph = CapturedTextGraph(status="pending")
    graph.card(text_sort_key="curation-text")
    graph.body("curation-text", SENTINEL)
    result = query(graph)
    assert passages(result) == [] and not [r for r in graph.requests if r[0] == "download"]
