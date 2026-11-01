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

from papyrus_content.ideas.context_packs import rank_packs  # noqa: E402
from papyrus_content.ideas.item_signals import ordered_queue, score_items  # noqa: E402
import test_item_signals as item_support  # noqa: E402


@given("a site whose accepted References are mostly quiet")
def step_quiet_site(context):
    context.item_inputs = {"votes": item_support.background(), "messages": []}
    context.item_candidates = []


@given("an accepted Reference no monitor delivered, with a lively thread of Messages")
def step_lively_unmonitored(context):
    context.item_inputs["messages"] += item_support.lively_thread("lively")
    context.item_candidates.append(item_support.candidate("lively"))


@given("an accepted Reference no monitor delivered, whose thread lights up after weeks of quiet")
def step_lit_unmonitored(context):
    context.item_inputs["messages"] += support.lit_thread_messages()
    context.item_inputs["votes"] = [*context.item_inputs["votes"], support.vote("ref-1", 3)]
    context.item_candidates.append(item_support.candidate("ref-1"))


@given("an accepted Reference a monitor delivered, with no activity")
def step_quiet_monitored(context):
    context.item_candidates.append(item_support.candidate("quiet", "hn"))


@when("the single-item candidates are scored")
def step_score_items(context):
    context.scored_items = score_items(support.inputs(**context.item_inputs), context.item_candidates)


@then("the Reference with the lively thread is the first candidate")
def step_lively_first(context):
    assert context.scored_items[0].item.lineage_id == "lively", context.scored_items


@then("the quiet monitored Reference is not a candidate")
def step_quiet_not_candidate(context):
    assert "quiet" not in [row.item.lineage_id for row in context.scored_items]


@then("there are no single-item candidates")
def step_no_candidates(context):
    assert context.scored_items == []


@when("the packs and the single-item candidates are queued together")
def step_queue(context):
    signals = support.inputs(**context.item_inputs)
    context.queue = ordered_queue(rank_packs(build_packs(signals, support.LOOKUPS, now=support.NOW)), score_items(signals, context.item_candidates))


@then("the queue holds both a pack and a single item")
def step_queue_both(context):
    assert {entry.kind for entry in context.queue} == {"pack", "item"}, context.queue


# --- up to three ideas, the Idea stage and the editorial gate ------------------------------------------------------------------------------


@given("an acceptance pack and a model that proposes four ideas that each cite two accepted References")
def step_agent_four(context):
    prepare_pack_run(context, [
        pack_support.idea("Synthetic voices spread through newsrooms", ["R1", "R2"], dek="Editors keep accepting this material."),
        pack_support.idea("Consent rules lag behind cloning tools", ["R3", "R4"], dek="Policies trail the tools that need them."),
        pack_support.idea("Licensing terms for cloned voices diverge", ["R5", "R6"], dek="Contracts differ on who owns a voice."),
        pack_support.idea("Audiobook studios test narrator clones", ["R7", "R8"], dek="Studios weigh cost against listener trust."),
    ])


@given("an editorial gate that finds nothing")
def step_agent_clean_gate(context):
    context.agent_gate = pack_support.Gate()


@then("three ideas are filed and one idea is dropped for being the fourth")
def step_agent_three(context):
    result = context.agent_result
    assert result.filed_count == 3, result.as_dict()
    assert [row["reason"] for row in result.dropped] == ["more_than_three_ideas"]


@then("every filed idea cites at least two accepted References")
def step_agent_two_each(context):
    assert all(len(row["citedReferences"]) >= 2 for row in context.agent_result.filed)


@then("the editorial gate checked the idea before it was filed")
def step_agent_gate_checked(context):
    assert len(context.agent_gate.checked) == 1 and context.agent_result.filed_count == 1


@then("the filed idea sits in the Idea stage")
def step_agent_idea_stage(context):
    assert context.agent_client.get_record("Item", context.agent_result.filed[0]["itemId"])["stage"] == "idea"


# --- the router task and the command -----------------------------------------------------------------------------------------------------

import shutil  # noqa: E402
import tempfile  # noqa: E402
from functools import partial  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest import mock  # noqa: E402

import test_monitoring_packs as router_support  # noqa: E402
from fake_idea_store import FakeIdeaStore  # noqa: E402
from test_idea_items import FakeGate  # noqa: E402
from papyrus_content.monitoring_stories import run_publication  # noqa: E402


class Patching:
    """``monkeypatch.setattr`` for the helpers of the tests, undone when the scenario ends."""

    def __init__(self, context) -> None:
        self.context = context

    def setattr(self, target, name, value) -> None:
        patcher = mock.patch.object(target, name, value)
        patcher.start()
        self.context.add_cleanup(patcher.stop)


def start_patch(context, patcher):
    patcher.start()
    context.add_cleanup(patcher.stop)


@given("a publication with a concept whose accepts jump and a monitored Reference with a lively thread")
def step_router_world(context):
    start_patch(context, mock.patch.dict("os.environ", {"PAPYRUS_GRAPHQL_AUTH": "iam"}))
    start_patch(context, mock.patch("papyrus_content.ideas.items.ItemStore", lambda client, **options: FakeIdeaStore(client, gate=options.get("gate"))))
    start_patch(context, mock.patch("papyrus_content.ideas.gate.HumanusGate.for_client", classmethod(lambda cls, client, **options: FakeGate())))
    filing = router_support.FilingRecorder(Patching(context))
    context.router = SimpleNamespace(client=router_support.pack_world(2, lively=(1,)), settings={"singleItem": True, "contextPacks": {"enabled": True}},
                                     model=router_support.RouterModel(), filing=filing, drafter_options={}, stop=None, line=None, output=None)


@given("an idea that was drafted from that pack on an earlier run")
def step_router_earlier_idea(context):
    context.router.client.items.append(router_support.existing_idea_from(context.router.client))


@given("the publication sets singleItem to false")
def step_router_pack_only(context):
    context.router.settings["singleItem"] = False


@given("the publication turns context packs off")
def step_router_packs_off(context):
    context.router.settings["contextPacks"] = {"enabled": False}


@given("the publication names only the conversation signal")
def step_router_signal(context):
    context.router.settings["contextPacks"] = {"enabled": True, "signals": ["conversation"]}


@given("the Lambda runs out of time as soon as the pack has been drafted")
def step_router_time(context):
    context.router.stop = lambda: bool(context.router.model.order)


@given("filing a pack idea fails with a missing grant")
def step_router_file_error(context):
    context.router.filing.fail_after = 0


@given("a model-spend backstop that the pack's call nearly uses up")
def step_router_cost(context):
    context.router.model = router_support.RouterModel(input_tokens=400_000, output_tokens=6_000)
    context.router.drafter_options["maximum_cost_usd"] = 0.0435


@when("the monitor-stories task runs")
def step_router_run(context):
    state = context.router
    _, store = router_support.router(settings={router_support.PUBLICATION: state.settings})

    def drafter(client, publication, **options):
        options = {**options, **({"out_of_time": state.stop} if state.stop else {})}
        return partial(run_publication, fetch=router_support.pages(1, 2), explorer=None, **state.drafter_options)(client, publication, **options)

    _, lines = router_support.run_task_with(store, state.client, state.model, drafter)
    state.line = lines[router_support.PUBLICATION]


@then("the model is asked about the pack before the single item")
def step_router_order(context):
    assert context.router.model.order == ["pack", "item"]


@then("the pack's ideas and the single item's idea are all filed")
def step_router_all_filed(context):
    state = context.router
    assert len(state.filing.filed) == 2 and len(state.client.filed) == 1 and state.line["drafted"] == 3


@then("one review request covers the run")
def step_router_review(context):
    assert len(context.router.client.reviews) == 1 and context.router.line["review"] == "requested"


@then("the log line counts one pack and the two ideas it produced")
def step_router_counts(context):
    assert (context.router.line["packs"], context.router.line["ideasFromPacks"]) == (1, 2)


@then("the log line names the pack's signal, anchor and corrected p-value")
def step_router_pack_detail(context):
    [detail] = context.router.line["packDetails"]
    assert (detail["signal"], detail["anchor"], detail["ideas"]) == ("acceptance", "concept-voice", 2) and 0 < detail["correctedPValue"] < 0.01


@then("the log line counts no pack held back for want of new evidence")
def step_router_not_held_back(context):
    assert context.router.line["packsSkippedNoNewEvidence"] == 0


@then("the model is not asked about the pack")
def step_router_no_pack_call(context):
    assert context.router.model.pack_requests == [] and context.router.filing.filed == []


@then("the log line counts one pack held back for want of new evidence")
def step_router_held_back(context):
    assert (context.router.line["packs"], context.router.line["packsSkippedNoNewEvidence"]) == (0, 1)


@then("only the pack's ideas are filed")
def step_router_only_pack(context):
    state = context.router
    assert len(state.filing.filed) == 2 and state.client.filed == [] and state.model.order == ["pack"]


@then("no pack is built and only single items are drafted")
def step_router_only_items(context):
    state = context.router
    assert state.line["packs"] == 0 and state.filing.filed == [] and state.model.pack_requests == [] and len(state.client.filed) == 2


@then("no acceptance pack is drafted")
def step_router_no_acceptance(context):
    state = context.router
    assert state.line["packs"] == 0 and state.model.pack_requests == []


@then("the publication is stopped by time with the pack's ideas filed and no single item drafted")
def step_router_stopped_time(context):
    state = context.router
    assert state.line["stoppedBy"] == "time" and len(state.filing.filed) == 2 and state.client.filed == []


@then("the publication is stopped by the filing error and the single item is not asked for")
def step_router_stopped_file(context):
    state = context.router
    assert state.line["stoppedBy"] == "file_error" and state.model.order == ["pack"]


@then("the publication is stopped by cost after the pack and the single item is not asked for")
def step_router_stopped_cost(context):
    state = context.router
    assert state.line["stoppedBy"] == "cost" and state.model.order == ["pack"] and len(state.filing.filed) == 2


def run_command_as_dry_run(context, flags):
    state = context.router
    state.model = router_support.RouterModel()
    state.client = router_support.pack_world(2, lively=(1,))
    directory = tempfile.mkdtemp()
    context.add_cleanup(shutil.rmtree, directory, True)
    code, state.output = router_support.run_command(["--dry-run", "--limit", "5", *flags], state.client, state.model, None, directory)
    assert code == 0, state.output


@when("the monitor-stories command runs as a dry run")
def step_command_dry(context):
    run_command_as_dry_run(context, [])


@when("the monitor-stories command runs as a dry run with packs only")
def step_command_packs_only(context):
    run_command_as_dry_run(context, ["--packs-only"])


@when("the monitor-stories command runs as a dry run with single items only")
def step_command_single_only(context):
    run_command_as_dry_run(context, ["--single-only"])


@then("the output lists the pack with its signal, anchor, corrected p-value and date basis")
def step_command_lists_pack(context):
    output = context.router.output
    assert "pack\tacceptance\tconcept-voice\tcorrected p " in output and "dates: ingestion" in output


@then("no idea is filed and no review is requested")
def step_command_writes_nothing(context):
    state = context.router
    assert state.filing.filed == [] and state.client.filed == [] and state.client.reviews == {}


@then("the model is asked only about the pack")
def step_command_pack_only_asked(context):
    assert context.router.model.order == ["pack"]


@then("the model is asked only about single items and no pack is listed")
def step_command_single_only_asked(context):
    state = context.router
    assert state.model.order and set(state.model.order) == {"item"} and "packs\t" not in state.output


from papyrus_content.ideas.signal_inputs import ConceptLink  # noqa: E402


@given("a lively thread on one Reference whose concept has other accepted References")
def step_lively_related(context):
    others = [support.vote(f"other-{n}", 10 + n) for n in range(1, 4)]
    context.related_inputs = support.inputs(
        messages=support.lit_thread_messages(), votes=[support.vote("ref-1", 3), *others],
        links=[ConceptLink(lineage, "concept-voice", "mentions") for lineage in ("ref-1", "other-1", "other-2", "other-3")])


@when("the context packs are built and the pack ideas are drafted")
def step_related_build_and_draft(context):
    [context.related_pack] = [p for p in build_packs(context.related_inputs, support.LOOKUPS, now=support.NOW) if p.signal_type == "conversation"]
    client = pack_support.backend(context.related_pack)
    context.agent_result = pack_support.run(context.related_pack, client, pack_support.transport_of(pack_support.idea("Editors keep returning to one voice story", ["R1", "R2"])))


@then("the conversation pack holds the anchor first and the related accepted References marked with their shared concept")
def step_related_pack(context):
    pack = context.related_pack
    assert pack.accepted_lineage_ids[0] == "ref-1" and len(pack.accepted_lineage_ids) == 4
    assert pack.references[0].get("relation") is None and all(row["relation"].startswith("shared concept") for row in pack.references[1:])


@then("one idea is filed citing two accepted References")
def step_related_idea(context):
    assert context.agent_result.filed_count == 1 and len(context.agent_result.filed[0]["citedReferences"]) == 2
