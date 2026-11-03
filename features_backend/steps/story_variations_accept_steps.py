"""Accepting a variation (features_backend/story-variations-accept.feature). The backend is an in-memory stand-in for the Items and variations of one Story; the
newsroom's front matter splice is tested in scripts/test-story-variations.ts, so the front matter here is what it sends."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.story_reporting import latest_story_version, save_story_version, story_versions  # noqa: E402
from papyrus_content.story_variations import decide_variation, offer_variation, variation_id_of, variations_of, versions_from_variations  # noqa: E402

LINEAGE = "item-story-1"   # the Story of features_backend/steps/story_variations_steps.py, whose "variation N is on offer" step this feature reuses
NOW = "2026-11-02T12:00:00Z"
CONNECTION = [{"kind": "reference", "id": "reference-1", "title": "A Reference"}]


class Backend:
    """Items and StoryVariation rows, answering what ``save_story_version``, ``offer_variation`` and ``decide_variation`` ask."""

    def __init__(self) -> None:
        self.tables: dict[str, dict[str, dict]] = {"Item": {}, "StoryVariation": {}}

    def get_record(self, model, record_id):
        row = self.tables[model].get(record_id)
        return dict(row) if row else None

    def create_record(self, model, payload):
        self.tables[model][payload["id"]] = dict(payload)

    def update_record(self, model, payload):
        self.tables[model][payload["id"]].update(payload)

    def list_by_index(self, index, key):
        if index == "itemsByLineageAndVersion":
            return [dict(row) for row in self.tables["Item"].values() if row["lineageId"] == key]
        assert index == "storyVariationsByStoryAndNumber", index
        return [dict(row) for row in self.tables["StoryVariation"].values() if row["storyLineageId"] == key]


def front_matter(title, variation_id=None):
    return f"title: {title}\n" + (f"variationId: {variation_id}\n" if variation_id else "")


@given('a Story at version 1 with the headline "{headline}"')
def step_story(context, headline):
    context.backend = Backend()
    context.backend.tables["Item"][LINEAGE] = {
        "id": LINEAGE, "lineageId": LINEAGE, "versionNumber": 1, "versionState": "current", "type": "article", "slug": "foo", "section": None, "status": "draft", "stage": "idea",
        "headline": headline, "title": headline, "aliases": [], "metadata": json.dumps({"frontMatterYaml": front_matter(headline)}), "bodyMarkus": "First.", "createdAt": NOW, "updatedAt": NOW,
    }
    context.headlines = {}


@given('a run offered variations "{first}" and "{second}" to the Story')
def step_offered(context, first, second):
    for number, name in enumerate((first, second), start=1):
        row = offer_variation(context.backend, LINEAGE, point=f"{name} point", headline=f"{name} headline", deck=f"{name} deck", body_markus=f"{name} body", connections=CONNECTION, now=NOW)
        context.headlines[row["id"]] = row["headline"]
    assert [row["variationNumber"] for row in variations_of(context.backend, LINEAGE)] == [1, 2]


@given('the Story belongs to the tenant "{tenant}"')
def step_tenant(context, tenant):
    context.backend.tables["Item"][LINEAGE]["tenantId"] = tenant


def numbered(context, number):
    return variations_of(context.backend, LINEAGE)[int(number) - 1]


def accept(context, number, reason):
    """What the newsroom does: save the wording as the next version first, then record the decision."""
    row = numbered(context, number)
    save_story_version(
        context.backend, LINEAGE, front_matter_yaml=front_matter(row["headline"], row["id"]), body_markus=row["bodyMarkus"], actor="Ryan",
        change_reason=f"Accepted variation {row['variationNumber']}: {row['point']}", now=NOW,
    )
    decide_variation(context.backend, row["id"], "accepted", decided_by_label="Ryan", reason=reason, now=NOW)


@when('an editor accepts variation {number:d} in the newsroom saying "{reason}"')
def step_accept(context, number, reason):
    accept(context, number, reason)


@when('an editor rejects variation {number:d} in the newsroom saying "{reason}"')
def step_reject(context, number, reason):
    decide_variation(context.backend, numbered(context, number)["id"], "rejected", decided_by_label="Ryan", reason=reason, now=NOW)


def version(context, number):
    return next(row for row in story_versions(context.backend, LINEAGE) if row["versionNumber"] == int(number))


@then('the Story is at version {number:d} with the headline "{headline}"')
def step_current(context, number, headline):
    latest = latest_story_version(context.backend, LINEAGE)
    assert latest["versionNumber"] == number and latest["headline"] == headline and latest["title"] == headline, latest


@then("version {number:d} says its wording came from variation {variation:d}")
def step_from(context, number, variation):
    assert variation_id_of(version(context, number)) == numbered(context, variation)["id"]
    assert f"Accepted variation {variation}" in version(context, number)["changeReason"]


@then("version {number:d} says nothing about a variation")
def step_nothing(context, number):
    assert variation_id_of(version(context, number)) is None


@then("the Story's history shows version {first:d} from variation {a:d} and version {second:d} from variation {b:d}")
def step_history(context, first, a, second, b):
    assert versions_from_variations(story_versions(context.backend, LINEAGE)) == {numbered(context, a)["id"]: [first], numbered(context, b)["id"]: [second]}


@then('variation {number:d} is accepted with the reason "{reason}"')
def step_accepted(context, number, reason):
    row = numbered(context, number)
    assert row["status"] == "accepted" and row["decisionReason"] == reason and row["decidedByLabel"] == "Ryan", row


@then('variation {number:d} is rejected with the reason "{reason}"')
def step_rejected(context, number, reason):
    row = numbered(context, number)
    assert row["status"] == "rejected" and row["decisionReason"] == reason, row


@then('version {number:d} belongs to the tenant "{tenant}"')
def step_version_tenant(context, number, tenant):
    assert version(context, number)["tenantId"] == tenant


@then("version {number:d} is superseded")
def step_superseded(context, number):
    assert version(context, number)["versionState"] == "superseded"
