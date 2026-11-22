"""Skips carried onto later versions (features_backend/stories/story-skip-carry.feature). The Story world is story_procedure_steps.py's in-memory backend
and the translation world translation_publishing_steps.py's; nothing calls AWS or a model."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "features_backend" / "steps"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import story_checklist as checklist  # noqa: E402
from story_checklist_steps import LINEAGE, client_of, close_required, item  # noqa: E402

TRANSLATION = "story-waymo--es-419"


def _with_picture(metadata: str, picture: str) -> str:
    loaded = json.loads(metadata) if isinstance(metadata, str) else dict(metadata or {})
    loaded["frontMatterYaml"] = "\n".join([line for line in str(loaded.get("frontMatterYaml") or "").splitlines() if not line.startswith("image:")]
                                          + [f"image: /pictures/{picture}.jpg"])
    return json.dumps(loaded)


@given("the Story is saved as version {number:d} with {change}")
def saved_as_version(context, number, change):
    """A new current version of story-1 made from the one before it: the same row with only the picture, only the text, or nothing changed."""
    client = client_of(context)
    items = client.tables["Item"]
    previous = items[f"{LINEAGE}-v{number - 1}"]
    row = copy.deepcopy(previous)
    row.update({"id": f"{LINEAGE}-v{number}", "versionNumber": number, "versionState": "current", "versionCreatedAt": f"2026-11-08T10:0{number}:00Z",
                "previousVersionId": previous["id"]})
    if change == "only its picture changed":
        row["metadata"] = _with_picture(previous.get("metadata") or "{}", f"cover-{number}")
    elif change == "its text edited":
        row["bodyMarkus"] = (previous.get("bodyMarkus") or "") + f"\n\nA sentence added in version {number}."
    else:
        assert change == "nothing changed", change
    items[previous["id"]]["versionState"] = "superseded"
    items[row["id"]] = row
    context.world.version_number = number


@then('the checklist item "{key}" was skipped on version {version:d} as "{kind}"')
def skipped_on(context, key, version, kind):
    row = item(context, key)
    assert (row["state"], row["storyVersion"], row["changeKind"]) == ("skipped", version, kind), row


@then('the procedure output does not mention "{text}"')
def output_does_not_mention(context, text):
    assert text not in context.output, context.output


@when("every required step except the review of readers is closed")
def required_closed_but_review(context):
    close_required(context, except_keys=("review_people",))


@given('a person skips the translation\'s review because "{reason}"')
def skip_translation_review(context, reason):
    checklist.set_step(context.client, TRANSLATION, checklist.HUMAN_REVIEW_KEY, "skipped", actor={"kind": "person", "label": "An Editor"}, reason=reason)
