"""Pack ideas: one call per pack, up to three theme ideas, multi-source citation check, filing with evidence and links (PPY-c373f1, PPY-0c8c36)."""

from __future__ import annotations

import json

from papyrus_content.ideas import pack_stories
from papyrus_content.ideas.context_packs import build_packs
from papyrus_content.ideas.items import ItemStore, generated_of
from papyrus_content.ideas.signal_inputs import PendingReference
from papyrus_content.story_reporting import story_references
from procedures.newsroom.tests import test_idea_context_packs as support
from procedures.newsroom.tests.fake_client import FakeAuthoringClient

NODE = {"id": "node-voice-v1", "lineageId": "node-voice", "versionNumber": 1}


def acceptance_pack():
    pending = [PendingReference("pend-1", "pend-1", "Waiting", "https://example.org/w", support.moment(1), None, 0.9, ("concept-voice",))]
    packs = build_packs(support.inputs(votes=support.acceptance_votes(), pending=pending), support.LOOKUPS, now=support.NOW)
    return [pack for pack in packs if pack.signal_type == "acceptance"][0]


def backend(pack) -> FakeAuthoringClient:
    client = FakeAuthoringClient()
    client.tables["Reference"] = {
        f"{lineage}-v1": {"id": f"{lineage}-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current", "title": f"Title {lineage}",
                          "sourceUri": f"https://example.org/{lineage}", "curationStatus": "accepted"}
        for lineage in [*pack.accepted_lineage_ids, "pend-1"]
    }
    client.tables["ReferenceAttachment"] = {}
    return client


def sentence(text, *cites):
    return {"text": text, "cites": list(cites)}


def idea(headline, cites, section="Analysis", dek="Editors keep accepting this material."):
    return {
        "headline": sentence(headline, *cites), "dek": sentence(dek, *cites), "section": section,
        "paragraphs": [{"sentences": [sentence(f"{headline} appears in several sources.", *cites), sentence("Each source adds a different angle on voice cloning.", *cites)]}],
        "cites_summary": list(cites),
    }


def transport_of(*ideas):
    calls = []

    def transport(url, headers, payload):
        calls.append(payload)
        return {"output_text": json.dumps({"ideas": list(ideas)}), "usage": {"input_tokens": 1000, "output_tokens": 500}}

    transport.calls = calls
    return transport


class Gate:
    def __init__(self, errors=()):
        self.errors = errors

    def check(self, body, section):
        return {"findings": [{"severity": "error", "status": "violation", "policyId": "p1", "message": message} for message in self.errors]}

    def record(self, item, result):
        return None


def run(pack, client, transport, *, gate=None, dry_run=False, meter=None, titles=()):
    store = ItemStore(client)
    return pack_stories.draft_pack_ideas(
        client, pack, store=store, gate=gate or Gate(), transport=transport, cost_meter=meter or pack_stories.CostMeter(), existing_titles=titles,
        run_id="run-1", dry_run=dry_run, concept_nodes={"#voice-cloning": NODE}, now=support.NOW,
    )


def test_a_valid_response_files_ideas_with_based_on_links_evidence_and_concept_edges():
    pack = acceptance_pack()
    client = backend(pack)
    meter = pack_stories.CostMeter()
    transport = transport_of(idea("Synthetic voices spread through newsrooms", ["R1", "R2", "C1"]), idea("Consent rules lag behind cloning tools", ["R3", "R4"]))
    result = run(pack, client, transport, meter=meter)
    assert (result.filed_count, result.refused_count, result.dropped_count, len(transport.calls)) == (2, 0, 0, 1)
    assert meter.spent_usd == result.cost_usd > 0
    first = client.get_record("Item", result.filed[0]["itemId"])
    assert first["stage"] == "idea"
    generated = generated_of(first)
    assert generated["origin"] == "context-pack"
    assert generated["evidence"]["packId"] == pack.pack_id and generated["evidence"]["citedConcepts"] == ["#voice-cloning"]
    assert {"signal", "anchor", "window", "surprise", "citedMessages"} <= set(generated["evidence"])
    based_on = {link["referenceLineageId"] for link in story_references(client, result.filed[0]["lineageId"]) if link["role"] == "based_on"}
    assert based_on == set(result.filed[0]["citedReferences"]) and len(based_on) == 2
    assert "## Evidence" in first["bodyMarkus"] and "#voice-cloning" in first["bodyMarkus"] and "accepted References linked to" in first["bodyMarkus"]
    edges = [row for row in client.tables["SemanticRelation"].values() if row["objectKind"] == "semanticNode"]
    assert len(edges) == 1 and edges[0]["subjectKind"] == "item" and edges[0]["predicate"] == "related_to" and edges[0]["relationState"] == "current"
    assert json.loads(edges[0]["metadata"])["provenance"] == "derived"


def test_an_idea_citing_one_reference_is_dropped_and_the_pack_goes_on():
    pack = acceptance_pack()
    result = run(pack, backend(pack), transport_of(idea("Only one source", ["R1"]), idea("Consent rules lag behind cloning tools", ["R3", "R4"])))
    assert result.filed_count == 1 and result.dropped_count == 1
    assert result.dropped[0]["reason"] == "citation_check_failed"
    assert any("accepted_references_cited" in problem["reason"] for problem in result.dropped[0]["citationCheck"]["problems"])


def test_an_idea_citing_only_a_pending_reference_is_dropped():
    pack = acceptance_pack()
    pending = [row["handle"] for row in pack.references if row["status"] == "pending"]
    assert pending
    result = run(pack, backend(pack), transport_of(idea("Waiting on a source", pending), idea("Mixed sources", ["R1", "R2", pending[0]])))
    assert result.filed_count == 0 and result.dropped_count == 2
    reasons = [problem["reason"] for drop in result.dropped for problem in drop["citationCheck"]["problems"]]
    assert "cites_pending_reference" in reasons


def test_a_message_is_cited_only_together_with_a_reference():
    packs = build_packs(support.inputs(messages=support.lit_thread_messages(), links=[], votes=[support.vote("ref-1", 3), support.vote("ref-2", 3)]), support.LOOKUPS, now=support.NOW)
    pack = [row for row in packs if row.signal_type == "conversation"][0]
    handles = pack_stories.handles_of(pack)
    alone = idea("Editors argue about a source", ["R1", "R2"])
    alone["paragraphs"][0]["sentences"][0] = sentence("Editors argued.", "M1")
    alone["headline"] = sentence("Editors argue about a source", "R1")
    alone["dek"] = sentence("Editors keep accepting this material.", "R1")
    checked, record = pack_stories.check_idea(alone, handles, pack.allowed_sections)
    assert checked is None and any(problem["reason"] == "message_cited_without_reference" for problem in record["problems"])
    together = idea("Editors argue about a source", ["R1"])
    together["paragraphs"][0]["sentences"][0] = sentence("Editors argued about it.", "M1", "R1")
    checked, record = pack_stories.check_idea(together, handles, pack.allowed_sections)
    assert [problem["reason"] for problem in record["problems"]] == ["fewer_than_2_accepted_references_cited"]


def test_a_number_that_is_not_in_the_cited_handle_drops_the_idea():
    pack = acceptance_pack()
    bad = idea("Sources agree", ["R1", "R2"])
    bad["dek"] = sentence("There are 4711 sources.", "R1", "R2")
    result = run(pack, backend(pack), transport_of(bad))
    assert result.filed_count == 0 and result.dropped[0]["reason"] == "citation_check_failed"


def test_an_idea_the_editorial_gate_refuses_is_not_filed():
    pack = acceptance_pack()
    client = backend(pack)
    result = run(pack, client, transport_of(idea("Synthetic voices spread through newsrooms", ["R1", "R2", "C1"])), gate=Gate(errors=["Unsupported claim."]))
    assert (result.filed_count, result.refused_count) == (0, 1)
    assert result.refused[0]["reason"] == "editorial_check_failed"
    assert not client.tables.get("Item") and not client.tables.get("SemanticRelation")


def test_a_duplicate_of_an_existing_idea_is_dropped():
    pack = acceptance_pack()
    result = run(pack, backend(pack), transport_of(idea("Synthetic voices spread through newsrooms", ["R1", "R2"])), titles=["Synthetic voices spread through newsrooms"])
    assert result.filed_count == 0 and result.dropped[0]["reason"] == "near_duplicate"


def test_a_dry_run_asks_the_model_and_writes_nothing():
    pack = acceptance_pack()
    client = backend(pack)
    transport = transport_of(idea("Synthetic voices spread through newsrooms", ["R1", "R2", "C1"]))
    result = run(pack, client, transport, dry_run=True)
    assert result.filed_count == 0 and len(result.would_file) == 1 and len(transport.calls) == 1
    assert not client.tables.get("Item") and not client.tables.get("SemanticRelation")


def test_a_model_error_is_reported_and_costs_nothing():
    pack = acceptance_pack()
    result = run(pack, backend(pack), lambda url, headers, payload: {"status": "incomplete"})
    assert result.error and result.cost_usd == 0 and result.filed_count == 0
