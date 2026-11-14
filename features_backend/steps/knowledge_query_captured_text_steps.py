"""Steps for features_backend/knowledge-query-captured-text.feature. Everything is in memory: no AWS, no network, no model."""

from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT / "src", REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from captured_text_support import LONG_ID, SENTINEL, CapturedTextGraph, CorporaOnlyText, edit, query  # noqa: E402

AGENT_NOTE = "Captured by an AI agent; not independently completeness-checked."


def start(context) -> CapturedTextGraph:
    context.graph = CapturedTextGraph()
    context.corpus = CorporaOnlyText()
    return context.graph


@given("an accepted Reference whose captured text was supplied by an agent")
def step_agent_text(context):
    graph = start(context)
    graph.card(text_sort_key="curation-edit-0001-text", edits=[edit(1, "curation-edit-0001-text")])
    graph.body("curation-edit-0001-text", SENTINEL)


@given("an accepted Reference whose captured text was replaced by a second correction")
def step_two_corrections(context):
    graph = start(context)
    graph.card(text_sort_key="curation-edit-0002-text", edits=[edit(1, "curation-edit-0001-text"), edit(2, "curation-edit-0002-text", by="editor-ann", note="")])
    graph.body("curation-edit-0001-text", "OLD TEXT about something unrelated to oversight " * 6)
    graph.body("curation-edit-0002-text", SENTINEL)


@given("an accepted Reference with an extracted-text attachment and a later editor correction")
def step_extracted_and_correction(context):
    graph = start(context)
    path = graph.extracted("x")
    context.corpus = CorporaOnlyText({path: "STALE MACHINE EXTRACTION " * 20})
    graph.card(text_sort_key="curation-edit-0001-text", edits=[edit(1, "curation-edit-0001-text", by="editor-ann")])
    graph.body("curation-edit-0001-text", SENTINEL)


@given("an accepted Reference with an extracted-text attachment and only a machine capture")
def step_extracted_and_machine(context):
    graph = start(context)
    path = graph.extracted("x")
    context.corpus = CorporaOnlyText({path: SENTINEL})
    graph.card(text_sort_key="curation-text")
    graph.body("curation-text", "MACHINE CAPTURE " * 20)


@given("an accepted Reference whose captured text the caller is not allowed to download")
def step_refused(context):
    graph = start(context)
    graph.card(text_sort_key="curation-edit-0001-text", edits=[edit(1, "curation-edit-0001-text")])
    graph.denied_downloads.add(graph.body("curation-edit-0001-text", SENTINEL))


@given("an accepted Reference whose captured text attachment was deleted")
def step_deleted(context):
    graph = start(context)
    graph.card(text_sort_key="curation-edit-0001-text", edits=[edit(1, "curation-edit-0001-text")])
    graph.body("curation-edit-0001-text", SENTINEL, status="deleted")


@given("an accepted Reference whose captured text was stored under an attachment id the client would not compute")
def step_odd_id(context):
    graph = start(context)
    graph.card(text_sort_key="curation-text")
    graph.body("curation-text", SENTINEL)
    graph.body("curation-text", "ANOTHER VERSION", owner="another-reference-v1")


@when("a researcher queries the relevant topic")
def step_query(context):
    context.result = query(context.graph, corpus_text=context.corpus)


def passages(context):
    return context.result["structured"]["evidencePassages"]


@then("the query returns evidence passages from the captured text")
def step_has_passages(context):
    assert passages(context) and "independent audit logs" in passages(context)[0]["text"], context.result["warnings"]


@then("the evidence names the agent and keeps its note that the text is not independently checked")
def step_label(context):
    capture = passages(context)[0]["capture"]
    assert capture["editedBy"] == "agent:researcher" and capture["note"] == AGENT_NOTE, capture
    assert "not independently completeness-checked" in context.result["context"]["text"]


@then("the query returns passages from the second correction only")
def step_second_only(context):
    assert passages(context) and all("OLD TEXT" not in p["text"] for p in passages(context)), passages(context)


@then("the evidence is attributed to the editor who made the second correction")
def step_second_attributed(context):
    capture = passages(context)[0]["capture"]
    assert capture["editedBy"] == "editor-ann" and capture["sortKey"] == "curation-edit-0002-text", capture


@then("the query returns passages from the correction")
def step_from_correction(context):
    assert passages(context) and "STALE" not in passages(context)[0]["text"] and "independent audit logs" in passages(context)[0]["text"]


@then("the extracted-text attachment is not read")
def step_extracted_unread(context):
    assert context.corpus.reads == [], context.corpus.reads


@then("the query returns passages from the extracted-text attachment")
def step_from_extracted(context):
    assert passages(context) and "independent audit logs" in passages(context)[0]["text"]
    assert not [r for r in context.graph.requests if r[0] == "download"]


@then("the query returns no passages from it")
def step_none(context):
    assert passages(context) == [] and SENTINEL not in context.result["context"]["text"]


@then("the warnings say the captured text exists but could not be read")
def step_warn_unreadable(context):
    assert any("exists but could not be read" in w for w in context.result["warnings"]), context.result["warnings"]


@then("the warnings say no active attachment was found for the captured text")
def step_warn_missing(context):
    assert any("no active attachment" in w for w in context.result["warnings"]), context.result["warnings"]


@then("only that Reference's attachments were listed")
def step_owner_only(context):
    lookups = [r for r in context.graph.requests if r[0] == "owner_index"]
    assert lookups and all(r[1]["ownerId"] == LONG_ID for r in lookups), lookups


# --- the CLI's reader (AttachmentStore), with the identifier the deployed upload function makes -------------------------------------------------


@given("a Reference with a long identifier whose correction the upload function stored")
def step_long_id_stored(context):
    from curation_support import MemoryClient, reference

    context.cli_reference = reference("r" + "x" * 90)
    context.cli_client = MemoryClient([context.cli_reference])
    context.cli_client.tables["ModelAttachment"]["id-made-by-the-upload-function"] = {
        "id": "id-made-by-the-upload-function", "ownerKind": "reference", "ownerId": context.cli_reference["id"], "role": "metadata",
        "sortKey": "curation-edit-0001-text", "status": "active", "storagePath": "newsroom/payloads/x"}


@when("the signed-in CLI reads the current text of that Reference")
def step_cli_reads(context):
    from unittest import mock

    from papyrus_content import reference_curation_store

    with mock.patch.object(reference_curation_store, "download_attachment_buffer", lambda client, attachment: b"The corrected text."):
        context.cli_text = reference_curation_store.AttachmentStore(context.cli_client).read_text(context.cli_reference, "curation-edit-0001-text")


@then("the CLI gets the corrected text")
def step_cli_text(context):
    assert context.cli_text == "The corrected text."


@then("the same holds for the attachment identifier the client computes for any identifier length")
def step_ids_match(context):
    from papyrus_content.model_attachments import attachment_safe_id

    # The expected values come from the upload function's own `safeId` (node), for a short id, an id at the limit and one past it.
    assert attachment_safe_id("a" * 80) == "a" * 80
    assert attachment_safe_id("a" * 81) == "a" * 67 + "-8c48280d57fb" and len(attachment_safe_id("a" * 81)) == 80
