"""The rating agent through the procedure runner's own entry point (features_backend/agents/rating-agent.feature).

The runner, the site's policy document, its run records, the shipped procedure file (through Tactus), the tool, the model call (its prompt, schema and usage)
and the rating write (its handler, with the gate) are the real code. What is stood in for is the world: the site's Story index and Story store, the guidelines
read, and the model service, which is a scripted transport that answers by Story title. The backend, policy and wake steps are in runner_reads_policy_steps.py.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from behave import given, then, when

from papyrus_content import model_usage, procedure_runner as pr, procedure_runner_child, rating_agent, rating_handlers, run_outcomes, story_reporting, story_signals
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


def _row(lineage, title, **extra):
    return {"id": f"{lineage}-v1", "lineageId": lineage, "stage": "published", "status": "published", "type": "article", "section": "news", "versionState": "current",
            "title": title, "headline": title, "deck": "", "bodyMarkus": f"The body of {title}.", **extra}


def _begin(context):
    if getattr(context, "rating_ready", False):
        return
    context.rating_ready = True
    context.index_rows, context.index_reads, context.index_missing = [], [], False
    context.store, context.writes = {}, []        # the site's Story records: lineage -> {"starRating", "starRatedBy"}; every rating written, in order
    context.answers, context.fail_all, context.fail_for = {}, False, set()   # what the scripted model says, by Story title
    context.asked, context.guidelines_seen, context.call_seconds, context.seconds_left = [], [], 0.0, None
    context.guidelines_text, context.seen_wake_keys = "", []
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
        return {"id": f"{lineage}-v1", **context.store[lineage]}

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
    handlers = {"guidelines_resolve": _guidelines(context), **rating_handlers.signed_in_handlers(lambda: object())}
    client = FakeIndexClient(context)
    return rating_agent.Services(stories=lambda: rating_agent.published_unrated(client), judge=rating_agent.openai_judge("test-key", "gpt-6-luna", tier="bulk", transport=_transport(context)),
                                 execute=execute, clock=lambda: context.clock[0], handlers=handlers)


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


def _deliver(context):
    _begin(context)
    lineage = getattr(context, "fail_for_lineage", None)
    if lineage:
        context.fail_for.update(row["title"] for row in context.index_rows if row["lineageId"] == lineage)
    context.client.attachments[-1]["body"] = PROCEDURE.read_bytes()
    original_services = rating_agent.default_services
    rating_agent.default_services = lambda environ: _services(context)
    context.add_cleanup(setattr, rating_agent, "default_services", original_services)
    request = _wake_request(context)

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


@then('the ratings written are "{first}" at {first_stars:d} stars and "{second}" at {second_stars:d} stars, each by "{label}"')
def written(context, first, first_stars, second, second_stars, label):
    assert context.writes == [{"story": first, "stars": first_stars, "ratedBy": label}, {"story": second, "stars": second_stars, "ratedBy": label}], context.writes
    assert [(entry["story"], entry["stars"]) for entry in _result(context)["written_ratings"]] == [(first, first_stars), (second, second_stars)]


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
    handlers = rating_handlers.signed_in_handlers(lambda: object())
    context.answer = execute(operation, {"story": lineage, "stars": stars}, Caller(kind="agent", subject="rate"), handlers)


@then('the answer is the error "{code}"')
def answer_error(context, code):
    assert context.answer["ok"] is False and context.answer["error"]["code"] == code, context.answer
