"""Translation lifecycle (features_backend/translation-lifecycle.feature): the requests a run records, in a records fake that has only point reads and writes."""
from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

for entry in (Path(__file__).resolve().parents[2] / "src", Path(__file__).resolve().parents[2], Path(__file__).resolve().parent):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import lifecycles  # noqa: E402
from papyrus_content.localize import desired_state, lifecycle_state  # noqa: E402

LINEAGE = "slow-water"


class RequestTable:
    def __init__(self):
        self.rows, self.gets = {}, 0

    def upsert(self, model, record):
        assert model == "LocalizationRequest"
        self.rows[record["id"]] = dict(record)

    def get_record(self, model, record_id):
        self.gets += 1
        return dict(self.rows[record_id]) if record_id in self.rows else None

    def list_by_index(self, index, lineage):
        return []   # no independently authored companion exists for any language of this Story

    def list_records(self, model, **_):
        raise AssertionError(f"the whole {model} table was listed")


def source(version):
    return {"id": f"{LINEAGE}-v{version}", "lineageId": LINEAGE, "versionNumber": version, "contentHash": f"hash-{version}"}


def put(context, language, state, *, version=None, reason=None):
    version = version or context.source_version
    row = desired_state.want(context.client, source=source(version), language=language, requested_by="test", now="2026-11-19T09:00:00Z")
    context.client.rows[row["id"]].update(state=state, reason=reason)


@given('a published Story "{story}" at version {version:d} that the site publishes in "{first}", "{second}" and "{third}"')
def background(context, story, version, first, second, third):
    context.client, context.source_version, context.languages = RequestTable(), version, [first, second, third]


@when('the site wants a translation of "{story}" in "{first}", "{second}" and "{third}"')
def wants(context, story, first, second, third):
    for language in (first, second, third):
        desired_state.want(context.client, source=source(context.source_version), language=language, requested_by="publish", now="2026-11-19T09:00:00Z")
    read(context)


@given('the translation of "{story}" into "{language}" is saved')
def saved(context, story, language):
    put(context, language, "saved")


@given('the translation of "{story}" into "{language}" is held with the reason "{reason}"')
def held(context, story, language, reason):
    put(context, language, "held", reason=reason)


@given('the translation of "{story}" into "{language}" is published for source version {version:d}')
def published_for(context, story, language, version):
    put(context, language, "published", version=version)


@given('no translation of "{story}" into "{language}" was ever requested')
def never_requested(context, story, language):
    assert desired_state.request_id(story, language) not in context.client.rows


@given('the request for "{language}" is in the run state "{state}"')
def run_state(context, language, state):
    put(context, language, state)


@when('the states of "{story}" are read')
def read(context, story=None):
    context.client.gets, context.error = 0, None
    try:
        context.states = lifecycle_state.story_states(context.client, source(context.source_version), context.languages)
    except ValueError as error:
        context.states, context.error = None, str(error)


@then('"{story}" is "{state}" in "{first}", "{second}" and "{third}"')
def all_in(context, story, state, first, second, third):
    assert [context.states[language]["state"] for language in (first, second, third)] == [state] * 3, context.states


@then('the "{language}" translation is "{state}"')
def is_state(context, language, state):
    assert context.states[language]["state"] == state, context.states


@then('the "{language}" translation\'s reason is "{reason}"')
def has_reason(context, language, reason):
    assert context.states[language]["reason"] == reason, context.states


@then("each of the {count:d} languages has exactly one state")
def exactly_one(context, count):
    assert len(context.states) == count and all(entry["state"] in lifecycle_state.STATES for entry in context.states.values()), context.states


@then("the lifecycle says a held translation raises one flag and blocks only that translation")
def lifecycle_says(context):
    held_stage = lifecycles.load("Translation").stage("held")
    assert held_stage.nobody_acts == "flags" and "blocks only this translation" in (held_stage.why or ""), held_stage


@then("the site made exactly {count:d} point reads and listed no table")
def point_reads(context, count):
    assert context.client.gets == count, context.client.gets


@then('the read is refused saying "{words}"')
def refused(context, words):
    assert context.error and words in context.error, context.error
