import json
from pathlib import Path
import sys

from behave import given, then, when

from papyrus_content import reference_vote_backfill as backfill
from papyrus_content.reference_exports import build_reference_scope_training_export
from papyrus_content.reference_vote import latest_vote, vote_fields
from papyrus_content.relevance_decisions import human_label_for_review
from papyrus_newsroom.reference_actions import review_reference_curation

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "papyrus_content"))
from reference_vote_backfill_test import FakeClient, message, reference as old_reference  # noqa: E402

SECTION = {"id": "section-research", "enabled": True, "enabledStatus": "enabled"}
LABELS = ("include", "exclude")


def recording_graphql(context):
    reference = {"id": "reference-1", "lineageId": "reference-1", "corpusId": "corpus", "title": "T"}
    context.calls = []

    def graphql(query, variables):
        if "getReference(" in query:
            return {"getReference": reference}
        if "getNewsroomSection" in query:
            return {"getNewsroomSection": SECTION}
        context.calls.append((query, variables))
        return {"updateReference": {"id": "reference-1"}}
    return graphql


@given("a pending Reference in a corpus with an enabled Section")
def pending_reference(context):
    context.graphql = recording_graphql(context)


@when('an agent rejects the Reference as "{reason}" saying "{note}"')
def agent_rejects(context, reason, note):
    review_reference_curation(context.graphql, reference_id="reference-1", action="reject", reason_code=reason, note=note)


@when("an agent accepts the Reference into that Section")
def agent_accepts(context):
    review_reference_curation(context.graphql, reference_id="reference-1", action="accept", section_id="section-research")


def update_input(context):
    (query, variables), = [call for call in context.calls if "updateReference" in call[0]]
    return variables["input"]


@then('the Reference update carries the status, the note and the reason code "{reason}"')
def update_carries(context, reason):
    update = update_input(context)
    assert update["curationStatus"] == "rejected" and update["curationStatusReason"] == "Wrong topic."
    assert update["curationReasonCode"] == reason


@then('the vote\'s actor kind on the Reference is "{kind}"')
def actor_kind(context, kind):
    assert update_input(context)["curationActorKind"] == kind


@then("the vote's Section on the Reference is that Section")
def section_on_reference(context):
    assert update_input(context)["curationSectionId"] == "section-research"


@then("no Message and no relation were created")
def nothing_created(context):
    assert len(context.calls) == 1 and "updateReference" in context.calls[0][0], [call[0] for call in context.calls]


@given('a Reference whose latest vote was a person\'s reject as "{reason}"')
def earlier_reject(context, reason):
    context.reference = {"id": "r-v1", "lineageId": "r", "versionState": "current", "curationStatus": "rejected",
                         "curationStatusUpdatedAt": "2026-10-01T00:00:00Z", "curationStatusUpdatedBy": "editor",
                         **vote_fields("human", reason_code=reason)}


@when("a person's accept without a reason is recorded on it")
def later_accept(context):
    context.reference = {**context.reference, "curationStatus": "accepted", "curationStatusUpdatedAt": "2026-10-02T00:00:00Z",
                         **vote_fields("human")}


@then("the Reference's latest vote is an accept with no reason code")
def latest_is_accept(context):
    vote = latest_vote(context.reference)
    assert vote["action"] == "accept" and vote["reasonCode"] is None


@given('a Reference with an accepted status and a latest vote by "{actor}"')
def voted_by(context, actor):
    context.reference = {"id": "r-v1", "lineageId": "r", "versionState": "current", "curationStatus": "accepted", **vote_fields(actor)}


@given("a Reference with an accepted status and no recorded vote")
def unvoted(context):
    context.reference = {"id": "r-v1", "lineageId": "r", "versionState": "current", "curationStatus": "accepted"}


@given('a Reference rejected by a person with the reason "{reason}"')
def rejected_by_person(context, reason):
    context.reference = {"id": "r-v1", "lineageId": "r", "versionState": "current", "curationStatus": "rejected",
                         "corpusId": "corpus", "externalItemId": "item-1", **vote_fields("human", reason_code=reason)}


@when("its Cyclotron label is read from the vote")
def read_label(context):
    context.label = human_label_for_review(context.reference, labels=LABELS)


@when("the scope-training export is built")
def build_export(context):
    context.export = build_reference_scope_training_export(
        corpus_config={"key": "corpus"}, corpus_id="corpus", references=[context.reference], attachments=[])


@then('the export labels the Reference as out of scope with the reason "{reason}"')
def export_labels(context, reason):
    (item,) = context.export["items"]
    assert item["scope_training_label"] == "out_of_scope" and item["reason_code"] == reason


@given("References with old curation Messages: a person's accept, an agent's reject and a Reference never voted on")
def old_votes(context):
    rows = [(old_reference("accepted-ref"), [("m1", "accepted-ref", "2026-10-01T00:00:00Z", {"actorKind": "human", "action": "accept"})]),
            (old_reference("rejected-ref", curationStatus="rejected"),
             [("m2", "rejected-ref", "2026-10-01T00:00:00Z", {"actorKind": "service", "action": "reject", "reasonCode": "duplicate"})]),
            (old_reference("never-ref"), [])]
    references, messages, relations = [], [], []
    for reference, votes in rows:
        references.append(reference)
        for vote in votes:
            row, relation = message(*vote[:3], **vote[3])
            messages.append(row)
            relations.append(relation)
    context.client = FakeClient(references, messages, relations)


@when("the vote backfill runs as a dry run")
def backfill_dry(context):
    context.result = backfill.run_backfill(context.client, apply=False)


@then("the vote backfill plans 2 References and writes nothing")
def plans_two(context):
    assert context.result["planned"] == 2 and context.result["written"] == 0 and context.client.updates == []


@when("the vote backfill runs for real")
def backfill_real(context):
    context.result = backfill.run_backfill(context.client, apply=True)


@then("the person's accept and the agent's reject are recorded on their References")
def recorded(context):
    accepted = latest_vote(context.client.references["accepted-ref-v1"])
    rejected = latest_vote(context.client.references["rejected-ref-v1"])
    assert (accepted["actorKind"], accepted["action"]) == ("human", "accept")
    assert (rejected["actorKind"], rejected["reasonCode"]) == ("agent", "duplicate")


@then("the Reference never voted on is left alone")
def never_left(context):
    assert latest_vote(context.client.references["never-ref-v1"]) is None
