from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from papyrus_newsroom.reference_policy import (
    is_evidence_eligible_reference,
    normalize_reference_curation_status,
    normalize_reference_rejection_reason_code,
    scope_training_label_for_reference,
)

LESSON_WORD_FOR_EACH_TRAINING_LABEL = {"positive": "positive", "negative": "negative", None: "nothing"}


@given('a Reference in its "{version}" version that an editor has left "{status}"')
def given_reference_with_version_and_status(context, version, status):
    context.reference_under_policy = {"versionState": version, "curationStatus": status}


@given('an editor left the "{version}" version of a Reference "{status}" and gave the reason "{reason}"')
def given_reference_with_version_status_and_reason(context, version, status, reason):
    context.reference_under_policy = {
        "versionState": version,
        "curationStatus": status,
        "curationReasonCode": None if reason == "none" else reason,
    }


@given("no Reference at all")
def given_no_reference(context):
    context.reference_under_policy = None


@given('a rejected Reference whose latest vote says "{vote_reason}" and whose metadata says "{metadata_reason}"')
def given_rejected_reference_with_vote_and_metadata_reasons(context, vote_reason, metadata_reason):
    context.reference_under_policy = {
        "versionState": "current",
        "curationStatus": "rejected",
        "curationReasonCode": vote_reason,
        "metadata": json.dumps({"reasonCode": metadata_reason}),
    }


@given('a rejected Reference with no vote reason whose metadata says "{metadata_reason}"')
def given_rejected_reference_with_only_a_metadata_reason(context, metadata_reason):
    context.reference_under_policy = {
        "versionState": "current",
        "curationStatus": "rejected",
        "metadata": json.dumps({"rejectionReasonCode": metadata_reason}),
    }


@then("a Story may cite that Reference as evidence")
def then_story_may_cite_reference(context):
    assert is_evidence_eligible_reference(context.reference_under_policy) is True


@then("a Story may not cite that Reference as evidence")
def then_story_may_not_cite_reference(context):
    assert is_evidence_eligible_reference(context.reference_under_policy) is False


@when('an editor records the decision "{what_the_editor_wrote}"')
def when_editor_records_decision(context, what_the_editor_wrote):
    context.filed_curation_status = normalize_reference_curation_status(what_the_editor_wrote)


@when("an editor records no decision")
def when_editor_records_no_decision(context):
    context.filed_curation_status = normalize_reference_curation_status(None)


@then('the Reference is filed as "{status}"')
def then_reference_is_filed_as(context, status):
    assert context.filed_curation_status == status, context.filed_curation_status


@when('an editor gives the rejection reason "{what_the_editor_wrote}"')
def when_editor_gives_rejection_reason(context, what_the_editor_wrote):
    context.kept_rejection_reason = None
    context.rejection_reason_refusal = None
    try:
        context.kept_rejection_reason = normalize_reference_rejection_reason_code(what_the_editor_wrote)
    except ValueError as refusal:
        context.rejection_reason_refusal = refusal


@then('the rejection reason is kept as "{reason}"')
def then_rejection_reason_is_kept_as(context, reason):
    assert context.rejection_reason_refusal is None, context.rejection_reason_refusal
    assert context.kept_rejection_reason == reason, context.kept_rejection_reason


@then("the rejection reason is refused as unsupported")
def then_rejection_reason_is_refused(context):
    assert context.rejection_reason_refusal is not None
    assert "Unsupported reference rejection reason code" in str(context.rejection_reason_refusal)


@then('the relevance model learns "{lesson}" from that Reference')
def then_relevance_model_learns(context, lesson):
    training_label = scope_training_label_for_reference(context.reference_under_policy)
    assert LESSON_WORD_FOR_EACH_TRAINING_LABEL[training_label] == lesson, training_label
