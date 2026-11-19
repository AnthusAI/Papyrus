"""The lifecycle features (reference-lifecycle.feature and its siblings): the files are read through the loader agents use, never parsed by the steps."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

from behave import given, then, when

for entry in (Path(__file__).resolve().parents[2] / "src", Path(__file__).resolve().parents[2]):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import lifecycles  # noqa: E402
from papyrus_content.responsibilities import BY_KEY  # noqa: E402

BASE = {"schemaVersion": 1, "record": "Thing", "title": "Thing", "summary": "A thing.",
        "stages": [{"id": "made", "title": "Made", "mover": "intake", "person": "never", "nobodyActs": {"kind": "moves_on", "text": "Nothing waits."}}]}


def stage_titled(context, title):
    matches = [stage for stage in context.lifecycle.stages if stage.title == title or stage.title.startswith(title) or stage.id == title.lower()]
    assert len(matches) == 1, (title, [stage.title for stage in context.lifecycle.stages])
    return matches[0]


@given('the lifecycle of "{record}"')
def lifecycle_of(context, record):
    context.lifecycle = lifecycles.load(record)


@then('its stages are "{titles}"')
def stages_are(context, titles):
    assert ", ".join(stage.title for stage in context.lifecycle.stages) == titles


@then("every stage names a mover that is a responsibility in the catalog or the engine")
def movers(context):
    assert all(stage.mover == lifecycles.ENGINE or stage.mover in BY_KEY for stage in context.lifecycle.stages)


@then('the stages "{titles}" ask no person')
def no_person(context, titles):
    for title in titles.split(", "):
        assert stage_titled(context, title).person == "never", title


@then('the "{title}" stage is moved by "{mover}"')
def moved_by(context, title, mover):
    assert BY_KEY[stage_titled(context, title).mover].title == mover


@then('the "{title}" stage asks a person below the rung "{rung}"')
def asks_below(context, title, rung):
    stage = stage_titled(context, title)
    assert (stage.person, stage.rung) == ("by_policy", rung), stage


@then('the "{title}" stage is always a person\'s decision because "{why}"')
def always_person(context, title, why):
    stage = stage_titled(context, title)
    assert (stage.person, stage.why) == ("always", why), stage


@then('when nobody acts the "{title}" stage retries and then flags')
def retries_then_flags(context, title):
    stage = stage_titled(context, title)
    assert (stage.nobody_acts, stage.then) == ("retries", "flags"), stage


@then("its words say a final failure waits for a person and shows capture_failed")
def final_failure_words(context):
    text = stage_titled(context, "Captured").nobody_text
    assert "final failure waits for a person" in text and "capture_failed" in text, text


@then('when nobody acts the "{title}" stage keeps the record and counts it')
def keeps_and_counts(context, title):
    stage = stage_titled(context, title)
    assert (stage.nobody_acts, stage.counted) == ("stays", True), stage


@then("no stage removes a record for its age")
def never_removes(context):
    assert all(stage.nobody_acts in lifecycles.NOBODY_ACTS and stage.nobody_acts in ("moves_on", "stays", "retries", "flags") for stage in context.lifecycle.stages)
    assert "spikes" not in lifecycles.NOBODY_ACTS and "removes" not in lifecycles.NOBODY_ACTS


@when("an agent asks for the lifecycle in words")
def words(context):
    context.words = lifecycles.describe(context.lifecycle.record)


@then('the words begin "{start}"')
def words_begin(context, start):
    assert context.words.startswith(start), context.words


@then('the words say the "{title}" stage is moved by "{mover}" and "{asked}"')
def words_say(context, title, mover, asked):
    line = next(line for line in context.words.splitlines() if f". {title}. " in line)
    assert f"Moved by {mover}" in line and asked in line, line


CHANGES = {
    'is moved by "an editor"': lambda stage: stage.update(mover="an editor"),
    'is moved by "person"': lambda stage: stage.update(mover="person"),
    "asks a person by policy with no rung": lambda stage: stage.update(person="by_policy"),
    "spikes the record when nobody acts": lambda stage: stage.update(nobodyActs={"kind": "spikes", "text": "It is spiked after a month."}),
    "keeps the record without counting it": lambda stage: stage.update(nobodyActs={"kind": "stays", "text": "It stays."}),
    "is always a person's decision with no reason": lambda stage: stage.update(person="always"),
}


@given("a lifecycle file whose first stage {change}")
def broken_file(context, change):
    context.raw = copy.deepcopy(BASE)
    CHANGES[change](context.raw["stages"][0])


@when("the file is read")
def read_file(context):
    context.refusal = None
    try:
        lifecycles.parse(context.raw)
    except lifecycles.LifecycleError as error:
        context.refusal = str(error)


@then('it is refused saying "{reason}"')
def refused(context, reason):
    assert context.refusal and reason in context.refusal, context.refusal
