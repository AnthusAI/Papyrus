"""Association suggestions (features_backend/suggest-associations.feature). A stand-in site; no network, login, model or AWS."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.association_suggestions import suggest_associations  # noqa: E402
from papyrus_content.link_suggestions import suggest_links  # noqa: E402


def _story(context, lineage, title, body=""):
    row = context.site.tables["Item"][f"{lineage}-v1"]
    row.update({"headline": title, "title": title, "body": [body] if body else []})


def _ask(context, kind, ref):
    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
        context.associations = suggest_associations(context.site, kind, ref)


@given('the untagged story "{lineage}" has a title about privacy and voice cloning')
def _untagged(context, lineage):
    _story(context, lineage, "Privacy risks of voice cloning")


@given('the untagged story "{lineage}" has "{title_concept}" in the title and "{body_concept}" only in the body')
def _ranked(context, lineage, title_concept, body_concept):
    _story(context, lineage, f"All about {title_concept}", f"Later we turn to {body_concept}.")


@given('the untagged story "{lineage}" mentions "paid" and "said" but not the concept "AI"')
def _short(context, lineage):
    _story(context, lineage, "He said it was paid for", "She paid and he said so.")


@given("this shell has no embedding key")
def _nokey(context):
    _story(context, "s9", "Privacy risks of voice cloning")


@when('I ask for associations for the story "{lineage}"')
def _story_ask(context, lineage):
    _ask(context, "item", lineage)


@when('I ask for associations for the Reference "{ref}"')
def _reference_ask(context, ref):
    _ask(context, "reference", ref)


@then('the candidate concepts include "{first}" and "{second}" with a "papyrus stories link-concept" command')
def _concepts(context, first, second):
    found = {entry["name"]: entry for entry in context.associations["concepts"]}
    assert first in found and second in found, list(found)
    assert found[first]["command"].startswith("papyrus stories link-concept --story s9"), found[first]


@then('related items are ranked from those concepts with a "papyrus stories link-story" command')
def _related(context):
    items = [item for kind in context.associations["candidates"].values() for item in kind]
    assert items and all(item["command"].startswith("papyrus stories link-story") for item in items), items


@then('"{first}" ranks above "{second}"')
def _above(context, first, second):
    names = [entry["name"] for entry in context.associations["concepts"]]
    assert names.index(first) < names.index(second), names


@then("its already tagged concepts are not offered again as a link command")
def _tagged(context):
    tagged = [entry for entry in context.associations["concepts"] if entry["alreadyTagged"]]
    assert all(entry["command"] is None for entry in tagged), tagged


@then('the first related article is the one "stories suggest-links" ranks first')
def _same_first(context):
    plain = suggest_links(context.site, "s0")["candidates"]["articles"][0]["id"]
    assert context.associations["candidates"]["articles"][0]["id"] == plain


@then("the item is a Reference and related stories carry a command that links them to it")
def _reference(context):
    assert context.associations["item"]["kind"] == "reference"
    stories = [item for kind in ("articles", "posts") for item in context.associations["candidates"][kind]]
    assert stories and all(item["command"].endswith("--reference ref-1") for item in stories), stories


@then("the result says in one line that concepts were matched by name only")
def _note(context):
    assert any("name only" in note and "\n" not in note for note in context.associations["notes"]), context.associations["notes"]


@then('"AI" is not a candidate concept')
def _no_ai(context):
    assert "AI" not in [entry["name"] for entry in context.associations["concepts"]]
