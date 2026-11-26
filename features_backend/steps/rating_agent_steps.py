"""The rating agent through the procedure runner's own entry point (features_backend/agents/rating-agent.feature, rating-suggestions.feature and
rating-suggestion-triggers.feature).

The runner, the site's policy document, its run records, the shipped procedure file (through Tactus), the tool, the model call (its prompt, schema and usage)
and the rating write (its handler, with the gate) are the real code. What is stood in for is the world: the site's Story index and Story store, the guidelines
read, and the model service, which is a scripted transport that answers by Story title. The backend, policy and wake steps are in runner_reads_policy_steps.py.

For the change wakes, the Item and Reference change feeds, the listener index written from the engine's core definitions, the wake gate and its follow-up timers
are the real code too, over an in-memory queue and scheduler; the quiet-window and queue steps are in wake_gate_steps.py.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from behave import given, then, when

STEPS = Path(__file__).resolve().parent
if str(STEPS) not in sys.path:
    sys.path.insert(0, str(STEPS))

from papyrus_content import model_usage, procedure_runner as pr, procedure_runner_child, rating_agent, rating_handlers, rating_suggestions, run_outcomes, story_reporting, story_signals
from papyrus_content.agent_gate import run_context
from papyrus_content.ideas import synthesis
from papyrus_content.images.handlers import Caller, Outcome, execute

REPO = Path(__file__).resolve().parents[2]
PROCEDURE = REPO / "procedures" / "newsroom" / "rate_items.tac"
TENANT, BUCKET = "alpha", "site-bucket"
ADMIN_NAME = "ada"


class FakeIndexClient:
    """The site's published head partition as the authoring client reads it: newest first, one row each. Counts what was read."""

    def __init__(self, context):
        self.context = context

    def iterate_newest_first(self, index_name, key_value, *, page_size=50):
        self.context.index_reads.append((index_name, key_value))
        if self.context.index_missing:
            raise RuntimeError("Validation error of type FieldUndefined: Field 'listItemsByHeadStageAndUpdatedAt' in type 'Query' is undefined")
        yield from list(self.context.index_rows)


class StoryStore:
    """The site's Story records and review requests as the rating handlers reach them: the suggestion read, the suggestion write and the review request rows."""

    def __init__(self, context):
        self.context = context

    def list_semantic_relations_by_object_state(self, object_state_key):
        """The relation index read by the object: the Stories whose sources name a Reference (their ``uses_evidence`` links)."""
        self.context.relation_reads.append(object_state_key)
        reference = object_state_key.removeprefix("reference#").removesuffix("#current")
        return [{"id": f"relation-{lineage}-{reference}", "predicate": story_reporting.STORY_REFERENCE_PREDICATE, "subjectKind": "item", "subjectLineageId": lineage,
                 "objectKind": "reference", "objectLineageId": reference, "metadata": json.dumps({"role": "based_on"})}
                for lineage in self.context.based_on.get(reference, [])]

    def graphql(self, query, variables):
        assert "StorySuggestion" in query, query
        lineage = variables["id"].removesuffix("-v1")
        if lineage not in self.context.store:
            return {"getItem": None}
        return {"getItem": {"id": variables["id"], "lineageId": lineage, **self.context.store[lineage]}}

    def update_record(self, model, payload):
        if model == "Item":
            assert not {"starRating", "starRatedBy", "starRatedAt"} & set(payload), payload   # a suggestion never touches the rating
            self.context.store[payload["id"].removesuffix("-v1")].update({key: value for key, value in payload.items() if key != "id"})
        else:
            self.context.reviews[payload["id"]].update(payload)

    def get_record(self, model, record_id):
        assert model == "ReviewRequest", model
        found = self.context.reviews.get(record_id)
        return dict(found) if found else None

    def create_record(self, model, payload):
        assert model == "ReviewRequest", model
        self.context.reviews[payload["id"]] = dict(payload)


def _row(lineage, title, **extra):
    return {"id": f"{lineage}-v1", "lineageId": lineage, "stage": "published", "status": "published", "type": "article", "section": "news", "versionState": "current",
            "title": title, "headline": title, "deck": "", "bodyMarkus": f"The body of {title}.", **extra}


def _begin(context):
    if getattr(context, "rating_ready", False):
        return
    context.rating_ready = True
    context.index_rows, context.index_reads, context.index_missing = [], [], False
    context.store, context.writes = {}, []        # the site's Story records: lineage -> {"starRating", "starRatedBy"}; every rating written, in order
    context.reviews = {}                          # the site's ReviewRequest rows, by id
    context.answers, context.fail_all, context.fail_for = {}, False, set()   # what the scripted model says, by Story title
    context.asked, context.guidelines_seen, context.call_seconds, context.seconds_left = [], [], 0.0, None
    context.guidelines_text, context.seen_wake_keys = "", []
    context.story_rows, context.based_on, context.relation_reads = {}, {}, []   # the Stories a change wake reads: lineage -> row; Reference -> Stories based on it
    context.clock = [0.0]
    site_graphql = context.client.graphql

    def graphql(query, variables):   # the newsroom's once-only create: a wake key that already has its run comes back as a duplicate
        run_id = "run-for-" + str(variables.get("wakeKey"))
        if "startNewsroomProcedureRun" in query and run_id in context.client.records:
            return {"startNewsroomProcedureRun": json.dumps({"ok": True, "duplicate": True, "runId": run_id, "procedureVersionId": "version-1"})}
        return site_graphql(query, variables)

    context.client.graphql = graphql

    def current(client, lineage):
        if lineage not in context.store:
            raise ValueError(f"No story found for lineage {lineage}.")
        return {"id": f"{lineage}-v1", "lineageId": lineage, **context.story_rows.get(lineage, {}), **context.store[lineage]}

    def set_stars(client, lineage, stars, *, apply, agent=None):
        context.store[lineage] = {"starRating": stars, "starRatedBy": agent or ADMIN_NAME}
        context.writes.append({"story": lineage, "stars": stars, "ratedBy": agent})
        return {"lineageId": lineage, "stars": stars, "applied": True}

    for owner, name, replacement in ((story_reporting, "current_story_version", current), (story_signals, "set_story_stars", set_stars),
                                     (rating_handlers, "_publication", lambda client: "site")):
        original = getattr(owner, name)
        setattr(owner, name, replacement)
        context.add_cleanup(setattr, owner, name, original)


def _transport(context):
    def send(url, headers, payload):
        message = payload["input"]
        story = json.loads(message.split("Story:\n", 1)[1])
        title = story["title"]
        context.asked.append(title)
        context.guidelines_seen.append(message.split("\n\nStory:\n", 1)[0])
        context.clock[0] += context.call_seconds
        if context.fail_all or title in context.fail_for:
            raise synthesis.SynthesisError("The model service answered 500.")
        answer = {"stars": context.answers[title], "reason": f"One plain sentence about {title}."}
        return {"output_text": json.dumps(answer), "status": "completed", "usage": {"input_tokens": 120, "output_tokens": 14}}
    return send


def _services(context):
    handlers = {"guidelines_resolve": _guidelines(context), **rating_handlers.signed_in_handlers(lambda: StoryStore(context))}
    client = FakeIndexClient(context)
    return rating_agent.Services(stories=lambda: rating_agent.published_unrated(client), judge=rating_agent.openai_judge("test-key", "gpt-6-luna", tier="bulk", transport=_transport(context)),
                                 execute=execute, story=lambda lineage: rating_agent.story_as_it_is(StoryStore(context), lineage),
                                 stories_based_on=lambda reference: rating_agent.stories_based_on(StoryStore(context), reference),
                                 clock=lambda: context.clock[0], handlers=handlers, today=lambda: "2026-11-21")


def _guidelines(context):
    def read(arguments, caller):
        found = bool(context.guidelines_text)
        document = {"voice": {"name": "Plain"}, "evidenceRules": [context.guidelines_text]} if found else {}
        return Outcome({"kind": "writing", "found": found, "document": document, "fieldSources": {}, "layers": [], "warnings": []}, "site")
    return read


@given("the automation is not adopted")
def not_adopted(context):
    context.client.automations[context.automation_id].pop("responsibility", None)


@given("the site has these published Stories nobody has rated")
def unrated_stories(context):
    _begin(context)
    for entry in context.table:
        lineage = entry["story"]
        context.index_rows.append(_row(lineage, entry["title"]))
        context.store[lineage] = {}
        context.answers[entry["title"]] = int(entry["model says"])


@given('the site has a published Story "{lineage}" a person rated {stars:d} stars')
def rated_story(context, lineage, stars):
    _begin(context)
    context.index_rows.append(_row(lineage, f"Rated story {lineage}", starRating=stars, starRatedBy=ADMIN_NAME))
    context.store[lineage] = {"starRating": stars, "starRatedBy": ADMIN_NAME}


@given('the site has a published translation "{lineage}" of the Story "{source}"')
def translation(context, lineage, source):
    _begin(context)
    context.index_rows.append(_row(lineage, "Una nota de lanzamiento", sourceLineageId=source))
    context.store[lineage] = {}


@given('the site has a published imported translation "{lineage}" of the Story "{source}" in "{language}"')
def imported_translation(context, lineage, source, language):
    _begin(context)   # as `stories import-translation` stores it: a tenant-prefixed language group and no sourceLineageId
    context.index_rows.append(_row(lineage, "一则发布说明", tenantId="alpha", language=language, languageGroupId=f"alpha#{source}"))
    context.store[lineage] = {}


@given('the site\'s writing guidelines say "{words}"')
def guidelines(context, words):
    _begin(context)
    context.guidelines_text = words


@given('a person rates "{lineage}" {stars:d} stars before the run reaches it')
def rated_meanwhile(context, lineage, stars):
    context.store[lineage] = {"starRating": stars, "starRatedBy": ADMIN_NAME}   # the index row still says unrated: the write finds the person's rating


@given("each model call takes {seconds:d} seconds and the run has {left:d} seconds left")
def timing(context, seconds, left):
    _begin(context)
    context.call_seconds, context.seconds_left = float(seconds), float(left)


@given("the model service fails every call")
def model_fails(context):
    _begin(context)
    context.fail_all = True


@given('the model service fails for "{lineage}"')
def model_fails_for(context, lineage):
    _begin(context)
    context.fail_for_lineage = lineage


@given("the site has no head stage index")
def no_index(context):
    _begin(context)
    context.index_missing = True


@given('a Story "{lineage}" nobody has rated and a Story "{other}" a person rated {stars:d} stars')
def two_stories(context, lineage, other, stars):
    _begin(context)
    context.store[lineage] = {}
    context.store[other] = {"starRating": stars, "starRatedBy": ADMIN_NAME}


def _wake_request(context):
    import test_procedure_runner as tpr
    return {**tpr.REQUEST, "procedureKey": context.procedure_key, "wakeKey": f"{context.automation_id}|schedule|2026-11-18T08:30:00Z",
            "tenantId": TENANT, "siteBucket": BUCKET, "input": {}, "trigger": {"kind": "schedule", "automationId": context.automation_id}}


def _deliver(context, request=None):
    _begin(context)
    lineage = getattr(context, "fail_for_lineage", None)
    if lineage:
        context.fail_for.update(row["title"] for row in context.index_rows if row["lineageId"] == lineage)
    context.client.attachments[-1]["body"] = PROCEDURE.read_bytes()
    original_services = rating_agent.default_services
    rating_agent.default_services = lambda environ: _services(context)
    context.add_cleanup(setattr, rating_agent, "default_services", original_services)
    request = request or _wake_request(context)

    def run_in_child(workdir, source_path, inputs, *, timeout_seconds, environment):
        context.executed.append(request["wakeKey"])
        agent = json.loads(environment[run_context.ENVIRONMENT_KEY])
        if context.seconds_left is not None:
            agent["deadline"] = context.clock[0] + context.seconds_left
        saved = os.environ.get(run_context.ENVIRONMENT_KEY)
        os.environ[run_context.ENVIRONMENT_KEY] = json.dumps(agent)
        model_usage.drain()
        try:
            return {**procedure_runner_child.run(source_path, inputs), "seconds": 1}
        finally:
            if saved is None:
                os.environ.pop(run_context.ENVIRONMENT_KEY, None)
            else:
                os.environ[run_context.ENVIRONMENT_KEY] = saved

    policy = pr.policy_for(request, context.client, lambda: context.s3)
    answer = pr.run_procedure_request(request, policy=policy, client=context.client, execute=run_in_child, seconds_available=900, environment={})
    return answer


@when("the daily wake arrives for the automation")
def daily_wake(context):
    context.result = _deliver(context)


@when("the daily wake arrives twice with the same wake key")
def daily_wake_twice(context):
    context.result = _deliver(context)
    context.second = _deliver(context)


def _stored(context):
    runs = [run for run in context.client.records.values()]
    assert len(runs) == 1, runs
    return runs[0]


def _output(context):
    stored = _stored(context)
    output = stored["output"]
    return json.loads(output) if isinstance(output, str) else output


def _result(context):
    return _output(context)["result"]


@then("the run proposes {count:d} ratings: {listing}")
@then("the run proposes {count:d} rating: {listing}")
def proposes(context, count, listing):
    proposals = _result(context)["proposals"]
    expected = [(lineage, int(stars)) for lineage, stars in _pairs(listing)]
    assert [(entry["story"], entry["stars"]) for entry in proposals] == expected, proposals
    assert len(proposals) == count


def _pairs(listing):
    import re
    return re.findall(r'"([^"]+)" at (\d) stars?', listing)


@then("every proposal has a reason")
def reasons(context):
    assert all(entry["reason"].strip() for entry in _result(context)["proposals"])


@then("no proposal in the run is for 5 stars")
def no_five_proposed(context):
    assert all(entry["stars"] in (3, 4) for entry in _result(context)["proposals"])


@then('the run lists "{lineage}" as a five-star candidate for a person')
def candidate(context, lineage):
    assert lineage in [entry["story"] for entry in _result(context)["five_star_candidates"]], _result(context)["five_star_candidates"]


@then('the run lists "{lineage}" as unjudged because "{reason}"')
def unjudged(context, lineage, reason):
    assert any(entry["story"] == lineage and entry["reason"] == reason for entry in _result(context)["unjudged"]), _result(context)["unjudged"]


@then('the run lists "{lineage}" as failed because "{reason}"')
def failed_story(context, lineage, reason):
    assert any(entry["story"] == lineage and entry["reason"] == reason for entry in _result(context)["failed"]), _result(context)["failed"]


@then('the run lists "{lineage}" as left alone because "{reason}"')
def left_alone(context, lineage, reason):
    assert any(entry["story"] == lineage and entry["reason"] == reason for entry in _result(context)["left_alone"]), _result(context)["left_alone"]


@then("no rating was written")
def nothing_written(context):
    assert context.writes == [], context.writes


@then("no rating of 5 was written")
def no_five_written(context):
    assert all(entry["stars"] in (3, 4) for entry in context.writes), context.writes


@then('the person\'s rating of "{lineage}" is still {stars:d} stars')
def person_rating_stands(context, lineage, stars):
    assert context.store[lineage] == {"starRating": stars, "starRatedBy": ADMIN_NAME}, context.store[lineage]
    assert all(entry["story"] != lineage for entry in context.writes)


@then("the run record counts {looked:d} looked at and {written:d} written")
def counts(context, looked, written):
    result = _result(context)
    assert (result["looked_at"], result["written"]) == (looked, written), result


@then('the run record says it stopped because "{reason}"')
def stopped(context, reason):
    assert _result(context)["stopped"] == reason, _result(context)


@then("the model was asked about {count:d} Story")
@then("the model was asked about {count:d} Stories")
def model_asked(context, count):
    _begin(context)
    assert len(context.asked) == count, context.asked


@then('the model was given the guidelines "{words}"')
def guidelines_given(context, words):
    assert context.guidelines_seen and all(words in seen for seen in context.guidelines_seen), context.guidelines_seen


@then('the run record stores the gate\'s answer "{answer}" for "{operation}" needing the rung "{needed}"')
def gate_answer_needing(context, answer, operation, needed):
    entries = [entry for entry in _result(context)["gate_answers"]["gate"] if entry["operation"] == operation]
    assert entries and all(entry["answer"] == answer and entry["neededRung"] == needed for entry in entries), entries


@then('the run record stores the gate\'s answer "{answer}" for "{operation}"')
def gate_answer(context, answer, operation):
    entries = [entry for entry in _result(context)["gate_answers"]["gate"] if entry["operation"] == operation]
    assert entries and all(entry["answer"] == answer for entry in entries), entries


@then("the Story index was not read")
def index_not_read(context):
    _begin(context)
    assert context.index_reads == [], context.index_reads


@then("the Story index was read only as the published head partition")
def index_read_once(context):
    assert context.index_reads == [("itemsByHeadStageForRating", "published")], context.index_reads


@then('the run\'s error says "{words}"')
def error_says(context, words):
    stored = _stored(context)
    assert words in str(stored["errorSummary"]), stored["errorSummary"]


@then('the run record carries the usage of {calls:d} model call by "{model}"')
def usage(context, calls, model):
    usage_record = _stored(context)["usage"]
    usage_record = json.loads(usage_record) if isinstance(usage_record, str) else usage_record
    assert usage_record["calls"] == calls and model in usage_record["models"], usage_record


@then("the second answer is a duplicate of the first run")
def duplicate(context):
    assert context.second["duplicate"] is True and context.second["runId"] == context.result["runId"], context.second


@then("the site holds one run record for that wake key")
def one_record(context):
    assert len(context.client.records) == 1, list(context.client.records)


@when('an agent asks the operation "{operation}" for "{lineage}" at {stars:d} stars')
def agent_asks(context, operation, lineage, stars):
    _begin(context)
    handlers = rating_handlers.signed_in_handlers(lambda: StoryStore(context))
    context.answer = execute(operation, {"story": lineage, "stars": stars}, Caller(kind="agent", subject="rate"), handlers)


@then('the answer is the error "{code}"')
def answer_error(context, code):
    assert context.answer["ok"] is False and context.answer["error"]["code"] == code, context.answer


# --- suggestions (features_backend/agents/rating-suggestions.feature) ---------------------------------------------------------------


@given('the site has a published Story "{lineage}" with {stars:d} stars suggested and no rating')
def suggested_story(context, lineage, stars):
    _begin(context)
    context.index_rows.append(_row(lineage, f"Suggested story {lineage}", starSuggestion=stars, starSuggestedBy="agent:rate"))
    context.store[lineage] = {"starSuggestion": stars, "starSuggestedBy": "agent:rate"}


@given('a Story "{lineage}" with {stars:d} stars suggested by "{by}" and no rating')
def story_with_suggestion(context, lineage, stars, by):
    _begin(context)
    context.store[lineage] = {"starSuggestion": stars, "starSuggestedBy": by, "starSuggestedAt": "2026-11-21T08:30:00.000Z", "starSuggestionRun": "run-1"}


@then('"{lineage}" has the suggestion {stars:d} stars by "{by}" from the run, and no rating')
def has_suggestion(context, lineage, stars, by):
    record = context.store[lineage]
    assert record.get("starSuggestion") == stars and record.get("starSuggestedBy") == by and record.get("starRating") is None, record
    assert record.get("starSuggestionRun") == _stored(context)["id"] and record.get("starSuggestedAt"), record


@then('"{lineage}" has no suggestion')
def no_suggestion(context, lineage):
    assert "starSuggestion" not in context.store[lineage], context.store[lineage]


def _only_review(context):
    assert len(context.reviews) == 1, list(context.reviews)
    return next(iter(context.reviews.values()))


@then('the site has one review request, a soft review "{reason}"')
def one_review(context, reason):
    review = _only_review(context)
    assert review["mode"] == "soft_review" and review["reason"] == reason and review["state"] == "open", review


@then("the site has no review request")
def no_review(context):
    _begin(context)
    assert context.reviews == {}, context.reviews


@then('the review links "{first}", "{second}" and "{third}"')
def review_links(context, first, second, third):
    links = json.loads(_only_review(context)["links"])
    assert [link["id"] for link in links if link["type"] == "story"] == [first, second, third], links


def _caller():
    return Caller(kind="agent", subject="rate")


@given('the day\'s review already lists "{lineage}" with {stars:d} stars suggested')
def review_exists(context, lineage, stars):
    _begin(context)
    rating_suggestions.raise_daily_review(StoryStore(context), day="2026-11-21", entries=[{"story": lineage, "title": lineage, "stars": stars}], raised_by="agent:rate")


@when('the agent raises the day\'s review for "{first}" at {first_stars:d} stars and "{second}" at {second_stars:d} stars')
def raise_again(context, first, first_stars, second, second_stars):
    handlers = rating_handlers.signed_in_handlers(lambda: StoryStore(context))
    context.answer = execute("ratings_suggestions_review", {"day": "2026-11-21", "suggestions": [{"story": first, "title": first, "stars": first_stars},
                                                                                              {"story": second, "title": second, "stars": second_stars}]}, _caller(), handlers)
    assert context.answer["ok"], context.answer


@when('a person confirms the suggestion for "{lineage}"')
def confirm(context, lineage):
    handlers = rating_handlers.signed_in_handlers(lambda: StoryStore(context))
    context.answer = execute("ratings_confirm", {"story": lineage}, Caller(kind="person", subject=ADMIN_NAME), handlers)
    assert context.answer["ok"], context.answer


@when('a person confirms the suggestion for "{lineage}" with {stars:d} stars instead')
def confirm_other(context, lineage, stars):
    handlers = rating_handlers.signed_in_handlers(lambda: StoryStore(context))
    context.answer = execute("ratings_confirm", {"story": lineage, "stars": stars}, Caller(kind="person", subject=ADMIN_NAME), handlers)
    assert context.answer["ok"], context.answer


@then('the person\'s rating of "{lineage}" is {stars:d} stars')
def person_rating(context, lineage, stars):
    assert context.store[lineage]["starRating"] == stars and context.store[lineage]["starRatedBy"] == ADMIN_NAME, context.store[lineage]
    assert context.writes[-1] == {"story": lineage, "stars": stars, "ratedBy": None}, context.writes


@then("the answer says the suggestion was confirmed unchanged")
def unchanged(context):
    assert context.answer["result"]["changed"] is False and context.answer["result"]["suggested"] == context.answer["result"]["stars"], context.answer


@then("the answer says the person changed the suggestion from {stars:d} stars")
def changed(context, stars):
    assert context.answer["result"]["changed"] is True and context.answer["result"]["suggested"] == stars, context.answer


# --- change wakes (features_backend/agents/rating-suggestion-triggers.feature) ----------------------------------------------------------------
#
# A Story's publish and a person's rating reach the real Item change feed as stream records, through the real wake gate (a paid agent waits for quiet on a
# follow-up timer); a Reference's acceptance reaches the real change feed of the other tables. The listener index is written from the engine's own core
# definitions, so the rating agent wakes on exactly what rate.yaml says. The queue and the scheduler are the in-memory fakes the gate's own specs use, and the
# wake the rating agent takes from the queue is handed, as it is, to the procedure runner.

FEED_SITE = "sample"
FEED_REFERENCE_STREAM = "arn:aws:dynamodb:us-east-1:123456789012:table/Reference/stream/1"


def _open_feeds(context):
    from papyrus_content import agent_listeners, agent_wakes, follow_up_timers
    from papyrus_content.agent_definitions import definition, schedules
    from papyrus_content.change_feed_fakes import CountingS3, CountingTable, FakeQueue
    from papyrus_content.site_store import SiteStore
    from schedule_fakes import ACCOUNT, REGION, TimerScheduler

    class TimerQueue:   # the scheduler puts a timer's wake on the same FIFO queue the feeds use, deduplicated by its wake key
        def send(self, body, group):
            context.queue.send(body, group, agent_wakes.digest(json.loads(body)["wake"]["key"]))

    _begin(context)
    context.site_id, context.queue, context.rating_wakes_taken = FEED_SITE, FakeQueue(), 0
    context.fake_scheduler = TimerScheduler(schedules.names_for(FEED_SITE).group, TimerQueue())
    context.timers = follow_up_timers.FollowUpTimers.for_site(FEED_SITE, account=ACCOUNT, region=REGION, client=context.fake_scheduler)
    context.listener_store = SiteStore(CountingS3(), BUCKET, CountingTable(), now=lambda: "2026-11-21T00:00:00Z")
    context.listener_index = agent_listeners.ListenerIndex(context.listener_store, TENANT)
    agent_listeners.publish(context.listener_store, TENANT, definition.load_sets(definition.CORE_DIRECTORY).definitions, actor="release", apply=True)


def _feed_site():
    from papyrus_content import item_change_feed
    from papyrus_content.change_feed_fakes import ENDPOINT

    return item_change_feed.Site(publication_id=FEED_SITE, appsync_endpoint=ENDPOINT, tenant_id=TENANT, site_bucket=BUCKET)


def _feed_send(context):
    from papyrus_content import agent_wakes
    from papyrus_content.change_feed_fakes import FakeSqs

    return agent_wakes.wake_sender(FakeSqs({agent_wakes.queue_name(FEED_SITE): context.queue}))


class _NoOtherRecords:
    """The wake gate's counter reads the Story's current version (the Story store above); a person's change names that same version, so nothing else is read."""

    def get_record(self, model, record_id):
        raise AssertionError(f"the gate read {model} {record_id}")


def _deliver_story_change(context, old, new):
    from papyrus_content import item_change_feed, wake_gate
    from papyrus_content.change_feed_fakes import stream_record
    from papyrus_content.localize.dispatch import decode_image
    from schedule_fakes import utc

    context.sequence = getattr(context, "sequence", 0) + 1
    gate = wake_gate.WakeGate(policy=lambda: context.policy.read(TENANT).document, timers=context.timers, chain=wake_gate.StoryChain(_NoOtherRecords()),
                              review=lambda **found: None, clock=lambda: utc(new["updatedAt"]))
    answer = item_change_feed.handle([stream_record("MODIFY", old, new, context.sequence)], decode=decode_image, listeners=lambda: context.listener_index.document(),
                                     send=_feed_send(context), site=_feed_site(), gate=gate)
    assert answer["batchItemFailures"] == [], answer


@given("the site's change feeds wake agents by the engine's core definitions")
def feeds_by_core_definitions(context):
    _open_feeds(context)


@given('the site has the typeset Story "{lineage}" titled "{title}", which the model would give {stars:d} stars')
def typeset_story(context, lineage, title, stars):
    _begin(context)
    context.story_rows[lineage] = _row(lineage, title, stage="typesetting", status="draft", updatedAt="2026-11-21T08:00:00Z", metadata="{}")
    context.store[lineage] = {}
    context.answers[title] = stars


@given('the site has the published Story "{lineage}" titled "{title}" based on the Reference "{reference}", which the model would give {stars:d} stars')
def published_story_based_on(context, lineage, title, reference, stars):
    _begin(context)
    context.story_rows[lineage] = _row(lineage, title, updatedAt="2026-11-21T08:00:00Z", metadata="{}")
    context.store[lineage] = {}
    context.answers[title] = stars
    context.based_on.setdefault(reference, []).append(lineage)


@given('the site has the published Story "{lineage}" a person rated {stars:d} stars, based on the Reference "{reference}"')
def rated_story_based_on(context, lineage, stars, reference):
    _begin(context)
    context.story_rows[lineage] = _row(lineage, f"Rated story {lineage}", updatedAt="2026-11-21T08:00:00Z", metadata="{}")
    context.store[lineage] = {"starRating": stars, "starRatedBy": ADMIN_NAME}
    context.based_on.setdefault(reference, []).append(lineage)


@when('a person publishes "{lineage}" at "{moment}"')
def person_publishes(context, lineage, moment):
    old = dict(context.story_rows[lineage])
    new = {**old, "stage": "published", "status": "published", "updatedAt": moment, "publishedAt": moment}
    context.story_rows[lineage] = new
    _deliver_story_change(context, old, new)


@when('a person rates "{lineage}" {stars:d} stars at "{moment}"')
def person_rates_at(context, lineage, stars, moment):
    old = {**context.story_rows[lineage], **context.store[lineage]}
    context.store[lineage] = {"starRating": stars, "starRatedBy": ADMIN_NAME}
    new = {**old, "starRating": stars, "starRatedBy": ADMIN_NAME, "starRatedAt": moment, "updatedAt": moment}
    _deliver_story_change(context, old, new)


@when('the Reference "{reference}" is accepted by a person at "{moment}"')
def person_accepts(context, reference, moment):
    from papyrus_content import change_feeds
    from papyrus_content.change_feed_fakes import stream_record
    from papyrus_content.localize.dispatch import decode_image

    old = {"id": f"{reference}-v1", "lineageId": reference, "tenantId": TENANT, "versionNumber": 1, "corpusId": "papers", "medium": "paper",
           "curationStatus": "pending", "updatedAt": "2026-11-21T07:00:00Z"}
    new = {**old, "curationStatus": "accepted", "curationActorKind": "person", "curationStatusUpdatedBy": ADMIN_NAME, "curationStatusUpdatedAt": moment,
           "updatedAt": moment}
    context.sequence = getattr(context, "sequence", 0) + 1
    answer = change_feeds.handle([stream_record("MODIFY", old, new, context.sequence, FEED_REFERENCE_STREAM)],
                                 streams=change_feeds.Streams(tables={FEED_REFERENCE_STREAM: "Reference"}), decode=decode_image,
                                 listeners=lambda: context.listener_index.document(), send=_feed_send(context), site=_feed_site(), thread_of=lambda thread: None)
    assert answer["batchItemFailures"] == [], answer


def _rating_wake_messages(context):
    return [message for message in context.queue.messages if json.loads(message.body)["wake"]["agent"] == "rate"]


@when("the rating agent takes its wake")
def takes_wake(context):
    from papyrus_content import agent_wakes

    waiting = _rating_wake_messages(context)[context.rating_wakes_taken:]
    assert len(waiting) == 1, [json.loads(message.body)["wake"]["key"] for message in waiting]
    context.rating_wakes_taken += 1
    request = agent_wakes.request_from_event({"Records": [{"eventSource": agent_wakes.SQS_SOURCE, "body": waiting[0].body}]})   # as the runner's queue hands it over
    context.taken_wake_key = request["wakeKey"]
    context.result = _deliver(context, request=request)


@then('the run ran for the wake "{kind}"')
def ran_for(context, kind):
    assert _result(context)["wake"] == kind, _result(context)
    assert _stored(context)["wakeKey"] == context.taken_wake_key, (_stored(context), context.taken_wake_key)


@then('the run lists "{lineage}" as skipped because "{reason}"')
def skipped(context, lineage, reason):
    assert {"story": lineage, "reason": reason} in _result(context)["skipped"], _result(context)["skipped"]


@then('the Stories based on "{reference}" were read by the relation index')
def relations_read(context, reference):
    assert context.relation_reads == [f"reference#{reference}#current"], context.relation_reads


@then('the review links "{first}" and "{second}"')
def review_links_two(context, first, second):
    links = json.loads(_only_review(context)["links"])
    assert [link["id"] for link in links if link["type"] == "story"] == [first, second], links
