from behave import given, then, when

from papyrus_newsroom.reference_curation_signals import resolve_reference_title_subtitle

NO_IDENTIFIER_TO_CHECK = {"status": "skipped"}


def new_reference_to_settle(context, *, reference: dict, catalog_entry: dict):
    context.reference_to_settle = reference
    context.catalog_entry_of_the_reference = catalog_entry
    context.web_search_is_allowed = False
    context.identifier_check = NO_IDENTIFIER_TO_CHECK
    context.models_that_were_asked = []
    context.answer_of_the_model = None
    context.failure_of_the_model = None


def model_named(context, model_name: str):
    def asked_model(**_ignored_arguments):
        context.models_that_were_asked.append(model_name)
        if context.failure_of_the_model:
            raise RuntimeError(context.failure_of_the_model)
        return context.answer_of_the_model or {}

    return asked_model


@given('a Reference whose source supplied the title "{title}" and the subtitle "{subtitle}"')
def reference_with_title_and_subtitle_from_its_source(context, title, subtitle):
    new_reference_to_settle(
        context,
        reference={"id": "reference-1-v1", "title": ""},
        catalog_entry={"title": title, "metadata": {"subtitle": subtitle}},
    )


@given('a Reference titled "{title}" with no subtitle')
def reference_with_no_subtitle(context, title):
    new_reference_to_settle(context, reference={"id": "reference-1-v1", "title": title}, catalog_entry={})


@given("web search is {on_or_off} for the publication")
def web_search_setting(context, on_or_off):
    context.web_search_is_allowed = on_or_off == "on"


@given('the model would write the subtitle "{subtitle}"')
def model_would_write(context, subtitle):
    context.answer_of_the_model = {
        "title": context.reference_to_settle["title"],
        "subtitle": subtitle,
        "title_mode": "original_metadata",
        "subtitle_mode": "generated",
        "source_urls": [],
        "rationale": "Written from the source text.",
    }


@given('the model asked for a subtitle fails with "{failure}"')
def model_fails(context, failure):
    context.failure_of_the_model = failure


@given('the check of the Reference\'s identifier failed with "{failure}"')
def identifier_check_failed(context, failure):
    context.identifier_check = {"status": "failed", "failureReason": failure}


@when("Papyrus settles the Reference's title and subtitle")
def papyrus_settles_title_and_subtitle(context):
    context.settled = resolve_reference_title_subtitle(
        reference=context.reference_to_settle,
        catalog_entry=context.catalog_entry_of_the_reference,
        sidecar={},
        web_search_enabled=context.web_search_is_allowed,
        llm_resolver=model_named(context, "searches the web"),
        llm_toolless_resolver=model_named(context, "cannot search the web"),
        identifier_prepass=context.identifier_check,
        now="2026-11-20T12:00:00Z",
    )


@then('the Reference is titled "{title}" with the subtitle "{subtitle}"')
def reference_is_titled_with_subtitle(context, title, subtitle):
    assert context.settled["status"] == "resolved", context.settled
    assert (context.settled["title"], context.settled["subtitle"]) == (title, subtitle), context.settled


@then('the Reference is titled "{title}" with no subtitle')
def reference_is_titled_with_no_subtitle(context, title):
    assert context.settled["status"] == "resolved", context.settled
    assert (context.settled["title"], context.settled["subtitle"]) == (title, ""), context.settled
    assert context.settled["subtitle_mode"] == "unresolved", context.settled


@then("both are recorded as the source's own words")
def both_are_the_source_s_own_words(context):
    assert context.settled["title_mode"] == "original_metadata", context.settled
    assert context.settled["subtitle_mode"] == "original_metadata", context.settled


@then("the subtitle is recorded as generated")
def subtitle_is_recorded_as_generated(context):
    assert context.settled["subtitle_mode"] == "generated", context.settled


@then("no model was asked")
def no_model_was_asked(context):
    assert context.models_that_were_asked == [], context.models_that_were_asked


@then("the model that was asked is the one that {searches_or_not}")
def the_model_that_was_asked(context, searches_or_not):
    assert context.models_that_were_asked == [searches_or_not], context.models_that_were_asked
    assert context.settled["web_search_used"] is (searches_or_not == "searches the web"), context.settled


@then("a warning says the generated subtitle was rejected because it {reason}")
def warning_says_subtitle_was_rejected(context, reason):
    words_of_the_reason = reason.removeprefix("is a ")
    rejections = [warning for warning in context.settled["warnings"] if warning.startswith("generated subtitle rejected")]
    assert any(words_of_the_reason in rejection for rejection in rejections), context.settled["warnings"]


@then('a warning names the failure "{failure}"')
def warning_names_the_failure(context, failure):
    assert any(failure in warning for warning in context.settled["warnings"]), context.settled["warnings"]


@then('settling is blocked with the reason "{reason}"')
def settling_is_blocked(context, reason):
    assert context.settled["status"] == "blocked", context.settled
    assert (context.settled["title"], context.settled["subtitle"]) == ("", ""), context.settled
    assert any(reason in warning for warning in context.settled["warnings"]), context.settled["warnings"]
