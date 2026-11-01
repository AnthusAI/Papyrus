"""Context packs and anchor-based suppression (features_backend/idea-context-packs.feature)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import test_idea_context_packs as support  # noqa: E402
from papyrus_content.ideas.context_packs import build_packs, evidence_of, suppress_repeats  # noqa: E402
from papyrus_content.ideas.signal_inputs import PendingReference, StoryRecord  # noqa: E402


@given("a thread with nine Messages today after weeks of quiet")
def step_thread(context):
    context.pack_inputs = {"messages": support.lit_thread_messages(), "votes": [support.vote("ref-1", 3)]}


@given("a concept whose References are accepted at a steady rate")
def step_steady(context):
    context.pack_inputs = {"votes": [support.vote(f"ref-{n}", 70 - n * 3) for n in range(1, 22)]}


@given("a concept whose accepts jump in the latest week")
def step_jump(context):
    context.pack_inputs = {"votes": support.acceptance_votes()}


@given("a pending Reference that mentions the concept")
def step_pending(context):
    context.pack_inputs["pending"] = [PendingReference("pend-1", "pend-1", "Waiting", "https://example.org/w", support.moment(1), None, 0.9, ("concept-voice",))]


def drafted(context, state, without_last):
    pack = build_packs(support.inputs(**context.pack_inputs), support.LOOKUPS, now=support.NOW)[0]
    evidence = evidence_of(pack)
    if without_last:
        evidence["referenceLineageIds"] = evidence["referenceLineageIds"][:-1]
    context.existing_ideas = [StoryRecord("idea-1", "T", "", None, state, "2026-10-20", "[]", json.dumps(evidence))]


@given("an idea that was drafted from that pack")
def step_drafted(context):
    drafted(context, "draft", False)


@given("an idea that was drafted from that pack without its last accepted Reference")
def step_drafted_less(context):
    drafted(context, "draft", True)


@given("a spiked idea that was drafted from that pack without its last accepted Reference")
def step_spiked_less(context):
    drafted(context, "declined", True)


@when("the context packs are built")
def step_build(context):
    context.packs = build_packs(support.inputs(**context.pack_inputs), support.LOOKUPS, now=support.NOW)


@when("the context packs are built and repeats are suppressed")
def step_build_suppress(context):
    step_build(context)
    context.suppression = suppress_repeats(context.packs, context.existing_ideas)


@then("a conversation pack exists for that thread")
def step_conversation(context):
    assert [pack.anchor for pack in context.packs if pack.signal_type == "conversation"] == ["thread-a"]


@then("no pack exists")
def step_none(context):
    assert context.packs == []


@then("an acceptance pack exists for that concept")
def step_acceptance(context):
    assert [pack.anchor for pack in context.packs if pack.signal_type == "acceptance"] == ["concept-voice"]


@then("the pack states that its dates are Message dates")
def step_message_dates(context):
    assert context.packs[0].signal["dateBasis"] == "message"


@then("the pack states that its dates are ingestion dates")
def step_ingestion_dates(context):
    assert context.packs[0].signal["dateBasis"] == "ingestion"


@then('the pack lists the pending Reference with a P handle marked "not yet accepted"')
def step_pending_listed(context):
    row = next(row for row in context.packs[0].references if row["status"] == "pending")
    assert row["handle"] == "P1" and row["note"] == "not yet accepted"


@then("the pending Reference is not among the pack's accepted References")
def step_pending_not_evidence(context):
    assert "pend-1" not in context.packs[0].accepted_lineage_ids


@then("no pack is offered and one pack is counted as skipped for no new evidence")
def step_skipped(context):
    assert context.suppression.kept == () and context.suppression.packsSkippedNoNewEvidence == 1


@then("the pack is offered again")
def step_offered(context):
    assert len(context.suppression.kept) == 1


import test_idea_pack_stories as pack_support  # noqa: E402
from papyrus_content.ideas import pack_stories  # noqa: E402
from papyrus_content.ideas.items import generated_of  # noqa: E402
from papyrus_content.story_reporting import story_references  # noqa: E402


def prepare_pack_run(context, ideas, errors=()):
    context.agent_pack = pack_support.acceptance_pack()
    context.agent_client = pack_support.backend(context.agent_pack)
    context.agent_transport = pack_support.transport_of(*ideas)
    context.agent_gate = pack_support.Gate(errors=errors)


@given("an acceptance pack and a model that proposes an idea citing two accepted References and a concept")
def step_agent_valid(context):
    prepare_pack_run(context, [pack_support.idea("Synthetic voices spread through newsrooms", ["R1", "R2", "C1"])])


@given("an acceptance pack and a model that proposes an idea citing two accepted References")
def step_agent_two(context):
    prepare_pack_run(context, [pack_support.idea("Synthetic voices spread through newsrooms", ["R1", "R2"])])


@given("an acceptance pack and a model that proposes one idea citing a single Reference and one citing two")
def step_agent_one_and_two(context):
    prepare_pack_run(context, [pack_support.idea("Only one source", ["R1"]), pack_support.idea("Consent rules lag behind cloning tools", ["R3", "R4"])])


@given("an acceptance pack and a model that proposes an idea citing a pending Reference")
def step_agent_pending(context):
    pack = pack_support.acceptance_pack()
    pending = [row["handle"] for row in pack.references if row["status"] == "pending"]
    prepare_pack_run(context, [pack_support.idea("Waiting on a source", pending)])


@given("an editorial gate that finds an error in the idea")
def step_agent_gate(context):
    context.agent_gate = pack_support.Gate(errors=["Unsupported claim."])


def run_agent(context, dry_run):
    context.agent_result = pack_support.run(context.agent_pack, context.agent_client, context.agent_transport, gate=context.agent_gate, dry_run=dry_run)


@when("the pack ideas are drafted")
def step_agent_run(context):
    run_agent(context, False)


@when("the pack ideas are drafted as a dry run")
def step_agent_dry(context):
    run_agent(context, True)


@then("one idea is filed at the idea stage with a based_on link for each cited Reference")
def step_agent_filed(context):
    result = context.agent_result
    assert result.filed_count == 1
    item = context.agent_client.get_record("Item", result.filed[0]["itemId"])
    assert item["stage"] == "idea"
    linked = {link["referenceLineageId"] for link in story_references(context.agent_client, result.filed[0]["lineageId"]) if link["role"] == "based_on"}
    assert linked == set(result.filed[0]["citedReferences"]) and len(linked) == 2


@then("the idea records the context-pack origin and the pack evidence")
def step_agent_evidence(context):
    generated = generated_of(context.agent_client.get_record("Item", context.agent_result.filed[0]["itemId"]))
    assert generated["origin"] == "context-pack" and generated["evidence"]["packId"] == context.agent_pack.pack_id


@then("the idea is linked to the concept with a derived related_to edge")
def step_agent_concept(context):
    edges = [row for row in context.agent_client.tables["SemanticRelation"].values() if row["objectKind"] == "semanticNode"]
    assert len(edges) == 1 and edges[0]["predicate"] == "related_to" and json.loads(edges[0]["metadata"])["provenance"] == "derived"


@then("the idea body ends with an Evidence section")
def step_agent_body(context):
    body = context.agent_client.get_record("Item", context.agent_result.filed[0]["itemId"])["bodyMarkus"]
    assert "## Evidence" in body and "#voice-cloning" in body


@then("one idea is filed and one idea is dropped for failing the citation check")
def step_agent_one_dropped(context):
    result = context.agent_result
    assert (result.filed_count, result.dropped_count, result.dropped[0]["reason"]) == (1, 1, "citation_check_failed")


@then("no idea is filed and the idea is dropped for citing a pending Reference")
def step_agent_pending_dropped(context):
    result = context.agent_result
    reasons = [problem["reason"] for drop in result.dropped for problem in drop["citationCheck"]["problems"]]
    assert result.filed_count == 0 and "cites_pending_reference" in reasons


@then("no idea is filed and one idea is refused")
def step_agent_refused(context):
    assert (context.agent_result.filed_count, context.agent_result.refused_count) == (0, 1)


@then("no idea is filed and nothing is written")
def step_agent_nothing(context):
    assert context.agent_result.filed_count == 0
    assert not context.agent_client.tables.get("Item") and not context.agent_client.tables.get("SemanticRelation")
