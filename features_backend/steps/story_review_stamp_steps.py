"""The human review stamp per lineage (features_backend/stories/story-review-stamp.feature). The stamp is read by the reader announcements use
(``intake.ChecklistReviewStamps``) and described by ``story_checklist.lineage_review_stamp``; the Story world is story_procedure_steps.py's and the translation
world is translation_publishing_steps.py's. Nothing calls AWS or a model."""
from __future__ import annotations

import sys
from pathlib import Path

from behave import then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "features_backend" / "steps"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import story_checklist as checklist  # noqa: E402
from papyrus_content.announcements.intake import ChecklistReviewStamps  # noqa: E402

TRANSLATION = "story-waymo--es-419"
ORIGINAL = "story-waymo"
PERSON = {"kind": "person", "label": "An Editor"}


def _client(context):
    """The Story world's client in a scenario about a Story, the translation world's in a scenario about a translation."""
    world = getattr(context, "world", None)
    if world is not None:
        return world.client or world.build()
    return context.client


def _stamp(context, lineage: str, version: int):
    reviewed = ChecklistReviewStamps(_client(context)).reviewed(lineage, version)
    stamp = checklist.lineage_review_stamp(_client(context), lineage, version)
    assert reviewed == (stamp is not None), (reviewed, stamp)
    return stamp


@then('the lineage "{lineage}" has a human review stamp on version {version:d} by "{person}"')
def has_stamp(context, lineage, version, person):
    stamp = _stamp(context, lineage, version)
    assert stamp is not None, f"{lineage} version {version} has no stamp; steps: {checklist.read_steps(_client(context), lineage)}"
    assert (stamp["by"], stamp["delegated"]) == (person, False), stamp


@then('the lineage "{lineage}" has a delegated human review stamp on version {version:d} naming "{person}" and the agent "{agent}"')
def has_delegated_stamp(context, lineage, version, person, agent):
    stamp = _stamp(context, lineage, version)
    assert stamp is not None, f"{lineage} version {version} has no stamp"
    assert (stamp["by"], stamp["delegated"], stamp["agent"]) == (person, True, agent), stamp


@then('the lineage "{lineage}" has no human review stamp on version {version:d}')
def has_no_stamp(context, lineage, version):
    assert _stamp(context, lineage, version) is None


@then('the checklist item "{key}" records the instruction of "{person}" saying "{quote}"')
def records_instruction(context, key, person, quote):
    row = next(row for row in checklist.read_steps(_client(context), "story-1") if row["stepKey"] == key)
    assert (row.get("onBehalfOf"), row.get("instruction")) == (person, quote), row


@when("a person records the review of the English Story's version {version:d}")
def review_original(context, version):
    checklist.set_step(context.client, ORIGINAL, checklist.SITE_REVIEW_KEY, "done", actor=PERSON, note="Read the English as a reader")
    row = next(row for row in checklist.read_steps(context.client, ORIGINAL) if row["stepKey"] == checklist.SITE_REVIEW_KEY)
    assert row["storyVersion"] == version, row


def _agent_marks_translation_review(context, note, instruction=None):
    context.checklist_error = None
    try:
        checklist.set_step(context.client, TRANSLATION, checklist.HUMAN_REVIEW_KEY, "done", actor={"kind": "agent", "label": context.agent_name}, note=note, instruction=instruction)
    except checklist.ChecklistError as error:
        context.checklist_error = error


@when('the agent "{agent}" marks the translation\'s review done with the note "{note}"')
def agent_marks_review(context, agent, note):
    context.agent_name = agent
    _agent_marks_translation_review(context, note)


@when('the agent "{agent}" marks the translation\'s review done on the instruction of "{person}" saying "{quote}"')
def agent_marks_review_on_instruction(context, agent, person, quote):
    context.agent_name = agent
    _agent_marks_translation_review(context, f"{person} read it", {"person": person, "quote": quote})
    assert context.checklist_error is None, context.checklist_error


@then('the review is refused as "{code}"')
def change_refused(context, code):
    error = context.checklist_error
    assert error is not None and error.code == code, error
