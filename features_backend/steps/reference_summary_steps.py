import json
from unittest.mock import patch

from behave import given, then, when

from papyrus_newsroom import reference_curation_signals

SOURCE_TEXT_OF_THE_REFERENCE = "A national survey of 1,060 teenagers asked how often they talk to AI companions."


@given('a Reference titled "{title}" with no summary yet')
def reference_with_no_summary_yet(context, title):
    context.reference_to_summarise = {
        "id": "reference-a-v1",
        "lineageId": "reference-a",
        "versionNumber": 1,
        "corpusId": "knowledge-corpus-test",
        "externalItemId": "item-a",
        "title": title,
        "importRunId": "import-1",
    }
    context.metadata_the_reference_already_has = {}
    context.summary_plan = None
    context.summary_refusal = None


@given('the Reference already has the summary "{summary}"')
def reference_already_has_summary(context, summary):
    context.metadata_the_reference_already_has = {"summary": summary}


def plan_the_summary(context, *, summary_text: str, max_tokens, model: str, refresh: bool = False):
    metadata_stored_with_the_reference = patch.object(
        reference_curation_signals,
        "_load_reference_metadata_payload",
        return_value=dict(context.metadata_the_reference_already_has),
    )
    token_count_estimated_from_words_without_downloading_a_tokenizer = patch.object(reference_curation_signals, "tiktoken", None)
    with metadata_stored_with_the_reference, token_count_estimated_from_words_without_downloading_a_tokenizer:
        try:
            context.summary_plan = reference_curation_signals.build_reference_summary_plan(
                reference=context.reference_to_summarise,
                max_tokens=max_tokens,
                summary_text=summary_text,
                source_text=SOURCE_TEXT_OF_THE_REFERENCE,
                model=model,
                refresh=refresh,
                doctrine_context=reference_curation_signals.manual_summary_doctrine_context() if model == "manual" else None,
                now="2026-11-20T12:00:00Z",
            )
        except ValueError as refusal:
            context.summary_refusal = str(refusal)


@when('the model "{model}" summarises the Reference in {max_tokens:d} tokens as "{summary}"')
def model_summarises(context, model, max_tokens, summary):
    plan_the_summary(context, summary_text=summary, max_tokens=max_tokens, model=model)


@when('the model "{model}" summarises the Reference in {max_tokens:d} tokens as ""')
def model_summarises_with_no_words(context, model, max_tokens):
    plan_the_summary(context, summary_text="", max_tokens=max_tokens, model=model)


@when('the model "{model}" is asked to summarise the Reference afresh in {max_tokens:d} tokens as "{summary}"')
def model_summarises_afresh(context, model, max_tokens, summary):
    plan_the_summary(context, summary_text=summary, max_tokens=max_tokens, model=model, refresh=True)


@when('a person writes the {max_tokens:d} token summary "{summary}"')
def person_writes_summary(context, max_tokens, summary):
    plan_the_summary(context, summary_text=summary, max_tokens=max_tokens, model="manual")


@when('a summary of length "{length}" is asked for')
def summary_of_length_is_asked_for(context, length):
    plan_the_summary(context, summary_text="Any summary.", max_tokens=length, model="gpt-5.4-mini")


def saved_metadata(context) -> dict:
    assert context.summary_refusal is None, context.summary_refusal
    assert context.summary_plan["action"] == "create", context.summary_plan
    writes = context.summary_plan["records"]
    assert [(write["modelName"], write["action"]) for write in writes] == [("ModelAttachment", "create")], writes
    assert writes[0]["input"]["ownerId"] == context.reference_to_summarise["id"], writes[0]["input"]
    return json.loads(writes[0]["body"])


@then('one write saves "{summary}" as the Reference\'s summary')
def one_write_saves_the_summary(context, summary):
    assert saved_metadata(context)["summary"] == summary, saved_metadata(context)


@then('the summary is recorded as written by a model, "{model}", at the {max_tokens:d} token length')
def summary_recorded_as_written_by_a_model(context, model, max_tokens):
    resolution = saved_metadata(context)["summary_resolution"]
    assert resolution["source"] == "llm_reference_summary", resolution
    assert resolution["model"] == model, resolution
    assert resolution["summaryTokenBudget"] == max_tokens, resolution


@then("the summary records which source text it was written from")
def summary_records_its_source_text(context):
    assert context.summary_plan["metadata"]["sourceContentHash"] == reference_curation_signals._hash_text(
        SOURCE_TEXT_OF_THE_REFERENCE
    ), context.summary_plan["metadata"]


@then("the summary is recorded as written by a person")
def summary_recorded_as_written_by_a_person(context):
    assert saved_metadata(context)["summary_resolution"]["source"] == "manual_override", saved_metadata(context)


@then("the summary records that the publication's doctrine was not used")
def summary_records_doctrine_not_used(context):
    assert context.summary_plan["metadata"]["doctrineContextStatus"] == "not_used_manual_summary", context.summary_plan["metadata"]


@then("no summary is written")
def no_summary_is_written(context):
    assert context.summary_refusal is None, context.summary_refusal
    assert context.summary_plan["action"] == "noop", context.summary_plan
    assert context.summary_plan["records"] == [], context.summary_plan


@then("the summary is accepted")
def summary_is_accepted(context):
    assert context.summary_refusal is None, context.summary_refusal
    assert context.summary_plan["action"] == "create", context.summary_plan


@then('the summary is refused with "{message}"')
def summary_is_refused_with(context, message):
    assert context.summary_plan is None, context.summary_plan
    assert context.summary_refusal == message, context.summary_refusal


@then("the summary is refused because it has no words")
def summary_is_refused_for_no_words(context):
    assert context.summary_plan is None, context.summary_plan
    assert "summary_text" in (context.summary_refusal or ""), context.summary_refusal
