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
