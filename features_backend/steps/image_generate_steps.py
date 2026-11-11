"""Generating, discarding and applying pictures (features_backend/image-generate.feature). A fake provider and in-memory stores; no network, no AWS."""
from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.images.candidates import InMemoryCandidateStore  # noqa: E402
from papyrus_content.images.generation import generation_handlers  # noqa: E402
from papyrus_content.images.generation_fakes import FakeMedia, FakeStories  # noqa: E402
from papyrus_content.images.handlers import HANDLERS, Caller, execute  # noqa: E402
from papyrus_content.images.profile_fakes import FakeBackend, profile_copy  # noqa: E402
from papyrus_content.images.profile_handlers import with_client  # noqa: E402
from papyrus_content.images.providers import FakeProvider, OpenAIProvider, ProviderFailure, ProviderRequest  # noqa: E402

PERSON = Caller(kind="person", subject="Edie Editor")
ADMIN = Caller(kind="person", subject="Ada Admin", is_admin=True)
AGENT = Caller(kind="agent", subject="Edie Editor", delegated_by="Edie Editor")
MODEL = "gpt-image-2.5-flare"


def backend(context):
    return context.image_backends["ours"]


def profile_with_generation(**generation):
    document = profile_copy()
    document["generation"] = {"models": [{"provider": "fake", "name": MODEL, "quality": "low"}], **generation}
    return document


def install(context, document):
    if not hasattr(context, "image_backends"):
        context.image_backends = {}
    context.image_backends["ours"] = FakeBackend("ours", profile=document)


@given('an image publication "ours" whose guidelines allow the model "{model}" but do not approve spending')
def step_allowed_not_approved(context, model):
    install(context, profile_with_generation(spendApproved=False))


@given('an image publication "ours" whose guidelines approve spending on "{model}"')
def step_approved(context, model):
    install(context, profile_with_generation(spendApproved=True))


@given('an image publication "ours" whose guidelines approve spending on "{model}" with a daily ceiling of {ceiling:f} dollars')
def step_ceiling(context, model, ceiling):
    install(context, profile_with_generation(spendApproved=True, perDayCeilingUsd=ceiling))


@given("a fake image provider")
def step_fake(context):
    context.provider = FakeProvider(name="fake")


@given("a fake image provider that is busy for the first picture")
def step_fake_busy(context):
    context.provider = FakeProvider(name="fake", failures=[ProviderFailure("provider_busy", "Busy.", retry_after_seconds=30)])


def handlers(context):
    if not hasattr(context, "candidate_store"):
        context.candidate_store, context.media, context.stories = InMemoryCandidateStore(), FakeMedia(), FakeStories()
    clock = lambda: "2026-11-10T12:00:00Z"  # noqa: E731
    return {**with_client(backend(context)),
            **generation_handlers(backend(context), context.candidate_store, {"fake": context.provider}, media=context.media, stories=context.stories, now=clock)}


def run(context, name, arguments, caller=PERSON):
    context.answer = execute(name, arguments, caller, handlers(context))
    return context.answer


def generate(context, caller, use, image_type, brief, *, story=None, section=None, count=None, request_id=None):
    arguments = {"use": use, "imageType": image_type, "brief": brief}
    if story:
        arguments["target"] = {"kind": "story", "lineageId": story}
    if section:
        arguments["sectionId"] = section
    if count:
        arguments["count"] = count
    from dataclasses import replace
    run(context, "image_generate", arguments, replace(caller, request_id=request_id) if request_id else caller)


@when('a person generates a "{use}" picture of type "{image_type}" with no Story and no section with the brief "{brief}"')
def step_gen_private(context, use, image_type, brief):
    generate(context, PERSON, use, image_type, brief)


@when('a person generates a "{use}" picture of type "{image_type}" for the section "{section}" with the brief "{brief}"')
def step_gen_section(context, use, image_type, section, brief):
    generate(context, PERSON, use, image_type, brief, section=section)


@when('a person generates as request "{request_id}" a "{use}" picture of type "{image_type}" for the section "{section}" with the brief "{brief}"')
def step_gen_section_request(context, request_id, use, image_type, section, brief):
    generate(context, PERSON, use, image_type, brief, section=section, request_id=request_id)


@when('a person generates a "{use}" picture of type "{image_type}" for the Story "{story}" with the brief "{brief}"')
def step_gen_story(context, use, image_type, story, brief):
    generate(context, PERSON, use, image_type, brief, story=story)


@when('an agent generates a "{use}" picture of type "{image_type}" for the Story "{story}" with the brief "{brief}"')
def step_gen_story_agent(context, use, image_type, story, brief):
    generate(context, AGENT, use, image_type, brief, story=story)


@when('a person generates a set of {count:d} "{use}" pictures of type "{image_type}" with no Story and no section with the brief "{brief}"')
def step_gen_set(context, count, use, image_type, brief):
    generate(context, PERSON, use, image_type, brief, count=count)


@when('an agent generates a set of {count:d} "{use}" pictures of type "{image_type}" with no Story and no section with the brief "{brief}"')
def step_gen_set_agent(context, count, use, image_type, brief):
    generate(context, AGENT, use, image_type, brief, count=count)


def candidates(context):
    assert context.answer["ok"], context.answer
    return context.answer["result"]["candidates"]


def nth(context, number):
    return list(context.candidate_store.candidates.values())[number - 1]


@then('generation is refused with "{code}" because "{reason}"')
def step_refused_because(context, code, reason):
    assert context.answer["ok"] is False and context.answer["error"]["code"] == code, context.answer
    assert context.answer["error"]["details"].get("reason") == reason, context.answer


@then('generation is refused with "{code}"')
def step_refused(context, code):
    assert context.answer["ok"] is False and context.answer["error"]["code"] == code, context.answer


@then("the provider was not called")
def step_not_called(context):
    assert context.provider.requests == [], context.provider.requests


@then("the provider was called once")
def step_called_once(context):
    assert len(context.provider.requests) == 1


@then("the provider was called {count:d} times")
def step_called_times(context, count):
    assert len(context.provider.requests) == count, len(context.provider.requests)


@then('the round has {count:d} candidate that is "{status}" and "{review}"')
@then('the round has {count:d} candidates that are "{status}" and "{review}"')
def step_round(context, count, status, review):
    rows = candidates(context)
    assert len(rows) == count and all(row["status"] == status and row["reviewStatus"] == review for row in rows), rows


@then("the provider was asked for the same text the preview shows")
def step_same_text(context):
    preview = execute("image_prompt_preview", {"use": "cover", "imageType": "cover-illustration", "brief": "A locked filing cabinet"}, PERSON, with_client(backend(context)))
    assert context.provider.requests[0].prompt == preview["result"]["plans"][0]["text"]


@then("the candidate file is kept under the private candidates folder")
def step_private_file(context):
    paths = list(context.candidate_store.files)
    assert len(paths) == 1 and paths[0].startswith("newsroom/image-candidates/") and not paths[0].startswith("media/"), paths


@then("the candidate cost is worked out from the tokens the provider reported")
def step_cost(context):
    row = next(iter(context.candidate_store.candidates.values()))
    assert row["usage"] == {"inputTokens": 40, "outputTokens": 1000} and row["costUsd"] == 0.03032 and row["costKnown"] is True, row


@then("the round is private")
def step_round_private(context):
    assert context.candidate_store.rounds[context.answer["result"]["roundId"]]["private"] is True


@then("the request the provider received holds \"{text}\"")
def step_request_holds(context, text):
    assert text in context.provider.requests[0].prompt


@then('candidate {number:d} failed with the retryable error "{code}"')
def step_failed_retryable(context, number, code):
    row = candidates(context)[number - 1]
    assert row["status"] == "failed" and row["error"]["code"] == code and row["error"]["retryable"] is True, row


@then('candidate {number:d} failed with the error "{code}"')
def step_failed(context, number, code):
    row = candidates(context)[number - 1]
    assert row["status"] == "failed" and row["error"]["code"] == code, row


@then('candidate {number:d} is "{status}"')
def step_candidate_status(context, number, status):
    assert nth(context, number)["status"] == status, nth(context, number)


@then('candidates {first:d} and {second:d} are "{status}"')
def step_candidates_status(context, first, second, status):
    rows = candidates(context)
    assert rows[first - 1]["status"] == status and rows[second - 1]["status"] == status, rows


def settings_document(**generation):
    document = profile_copy()
    document["generation"] = {"models": [{"provider": "fake", "name": MODEL}], **generation}
    return document


def save_guidelines(context, caller, document):
    guard = execute("image_profile_get", {}, PERSON, with_client(backend(context)))["result"]["itemId"]
    context.save_answer = execute("image_profile_save", {"document": document, "reason": "Approve generation.", "expectedCurrentVersionId": guard}, caller, with_client(backend(context)))


@when('an agent saves the guidelines approving spending on "{model}"')
def step_agent_saves(context, model):
    save_guidelines(context, AGENT, settings_document(spendApproved=True))


@when('a person saves the guidelines approving spending on "{model}"')
def step_person_saves(context, model):
    save_guidelines(context, ADMIN, settings_document(spendApproved=True))


@then('the guidelines save is refused with "{code}"')
def step_save_refused(context, code):
    assert context.save_answer["ok"] is False and context.save_answer["error"]["code"] == code, context.save_answer


@then("the guidelines save succeeds")
def step_save_ok(context):
    assert context.save_answer["ok"], context.save_answer


@then("asking what the site can generate says it is configured and approved")
def step_capabilities(context):
    context.provider = FakeProvider()
    answer = run(context, "image_capabilities", {})
    result = answer["result"]
    assert result["configured"] is True and result["approvedForSpend"] is True and result["spentTodayUsd"] == 0, answer


@when('an admin tries to save a section image document for "{section}" that approves spending')
def step_section_generation(context, section):
    from papyrus_content.guidelines.document import GuidelineError

    backend(context).add_section(section)
    context.section_error = None
    try:
        backend(context).save_profile_version({"schemaVersion": 2, "generation": {"models": [{"provider": "fake", "name": MODEL}], "spendApproved": True}}, by="Ada Admin",
                                              reason="Section tries to approve spending.", section=section)
    except GuidelineError as error:
        context.section_error = error


@then("the section save is refused because generation cannot be set from a section")
def step_section_refused(context):
    assert context.section_error is not None and "generation cannot be set from a section" in context.section_error.message


@when('a person discards candidate {number:d} because "{reason}"')
def step_discard(context, number, reason):
    context.discarded_id = nth(context, number)["id"]
    run(context, "image_discard", {"candidateId": context.discarded_id, "reason": reason})


@then('candidate {number:d} is "rejected" and its file is gone')
def step_rejected(context, number):
    row = nth(context, number)
    assert row["status"] == "rejected" and row["filePath"] is None and not any(row["id"] in path for path in context.candidate_store.files), row


@then('discarding candidate {number:d} again is refused with "{code}"')
def step_discard_again(context, number, code):
    run(context, "image_discard", {"candidateId": nth(context, number)["id"], "reason": "Again"})
    assert context.answer["ok"] is False and context.answer["error"]["code"] == code, context.answer


@when('a person discards the whole round because "{reason}"')
def step_discard_round(context, reason):
    round_id = next(iter(context.candidate_store.rounds))
    context.round_id = round_id
    run(context, "image_discard", {"roundId": round_id, "reason": reason})
    assert context.answer["ok"], context.answer


@then('the round is done and every candidate is "{status}"')
def step_round_done(context, status):
    run(context, "image_round_get", {"roundId": context.round_id})
    result = context.answer["result"]
    assert result["done"] and all(row["status"] == status for row in result["candidates"]), result


def story_guard(context, lineage):
    return next(row["id"] for row in backend(context).items if row["lineageId"] == lineage and row["versionState"] == "current")


def apply_candidate(context, caller, number, story, guard=None):
    run(context, "image_apply", {"candidateId": nth(context, number)["id"], "target": {"kind": "story", "lineageId": story}, "use": "cover",
                                 "expectedCurrentVersionId": guard or story_guard(context, story)}, caller)


@when('a person applies candidate {number:d} to the Story "{story}" as the cover')
def step_person_applies(context, number, story):
    apply_candidate(context, PERSON, number, story)


@when('an agent applies candidate {number:d} to the Story "{story}" as the cover')
def step_agent_applies(context, number, story):
    apply_candidate(context, AGENT, number, story)


@when('a person applies candidate {number:d} to the Story "{story}" with an out of date version')
def step_apply_stale(context, number, story):
    apply_candidate(context, PERSON, number, story, guard="story-1-v0")


@then('the apply succeeds as "{review}"')
def step_apply_ok(context, review):
    assert context.answer["ok"] and context.answer["result"]["reviewStatus"] == review, context.answer


@then("the Story got a new version with the cover set and nothing was published")
def step_story_saved(context):
    saved = context.stories.saved
    assert len(saved) == 1 and saved[0]["patch"]["frontMatter"]["image"].startswith("media/assets/story-1/"), saved
    assert "published" not in str(saved[0]).lower()
    assert context.answer["result"]["savedVersion"]["versionNumber"] == 2


@then("no review request was opened")
def step_no_review(context):
    assert context.media.review_requests == []


@then("a review request was opened")
def step_review(context):
    assert len(context.media.review_requests) == 1 and context.answer["result"]["reviewRequestId"] == "review-1"


@then('the apply is refused with "{code}"')
def step_apply_refused(context, code):
    assert context.answer["ok"] is False and context.answer["error"]["code"] == code, context.answer


@when("a person reads the round")
def step_read_round(context):
    run(context, "image_round_get", {"roundId": next(iter(context.candidate_store.rounds))})


@then("the round read says it is done with {count:d} candidates")
def step_read_done(context, count):
    result = context.answer["result"]
    assert result["done"] and len(result["candidates"]) == count and "target" not in result, result


@then('reading a round that does not exist is refused with "{code}"')
def step_read_missing(context, code):
    run(context, "image_round_get", {"roundId": "round-nothing"})
    assert context.answer["error"]["code"] == code


@then("the default image handlers answer not implemented for generate, round, discard and apply")
def step_defaults(context):
    arguments = {"image_generate": {"use": "cover", "brief": "x"}, "image_round_get": {"roundId": "r"}, "image_discard": {"candidateId": "c", "reason": "x"},
                 "image_apply": {"candidateId": "c", "target": {"kind": "story", "lineageId": "s"}, "use": "cover", "expectedCurrentVersionId": "v"}}
    for name, given in arguments.items():
        assert execute(name, given, PERSON, HANDLERS)["error"]["code"] == "not_implemented", name


# --- the OpenAI provider, with a fake network ---------------------------------------------------------------------------------------------------------

def fake_post(status, headers=None, payload=None):
    calls = []

    def post(url, request_headers, body):
        calls.append((url, request_headers, body))
        return status, headers or {}, payload or {}
    post.calls = calls
    return post


@given("an OpenAI provider whose network is a fake that answers with a picture and 30000 output tokens")
def step_openai_ok(context):
    import base64

    from papyrus_content.images.providers import tiny_png
    context.post = fake_post(200, payload={"id": "img-1", "data": [{"b64_json": base64.b64encode(tiny_png()).decode()}], "usage": {"input_tokens": 50, "output_tokens": 30000}})
    context.openai = OpenAIProvider(api_key=lambda: "test-key", post=context.post)


@given("an OpenAI provider whose network is a fake that answers 429")
def step_openai_busy(context):
    context.openai = OpenAIProvider(api_key=lambda: "test-key", post=fake_post(429, {"Retry-After": "12"}))


@given("an OpenAI provider whose network is a fake that answers 400")
def step_openai_bad(context):
    context.openai = OpenAIProvider(api_key=lambda: "test-key", post=fake_post(400, payload={"error": {"message": "Not allowed."}}))


@when('the provider is asked for a landscape picture with the quality "{quality}"')
def step_openai_ask(context, quality):
    context.image = context.openai.generate(ProviderRequest("A cabinet", MODEL, 1920, 1088, quality))


@then('the fake network saw the model, the prompt, the size "{size}" and the quality "{quality}"')
def step_openai_saw(context, size, quality):
    url, headers, body = context.post.calls[0]
    assert body == {"model": MODEL, "prompt": "A cabinet", "n": 1, "size": size, "quality": quality}, body
    assert url.startswith("https://api.openai.com/") and headers["Authorization"] == "Bearer test-key"


@then("the provider returned the picture and its token usage")
def step_openai_returned(context):
    assert context.image.data.startswith(b"\x89PNG") and context.image.output_tokens == 30000 and context.image.input_tokens == 50


def asking_fails(context):
    try:
        context.openai.generate(ProviderRequest("A cabinet", MODEL))
    except ProviderFailure as failure:
        return failure
    raise AssertionError("expected a failure")


@then('asking it fails with the retryable error "{code}"')
def step_openai_retryable(context, code):
    failure = asking_fails(context)
    assert failure.code == code and failure.retryable and failure.retry_after_seconds == 12


@then('asking it fails with the non-retryable error "{code}"')
def step_openai_not_retryable(context, code):
    failure = asking_fails(context)
    assert failure.code == code and not failure.retryable
