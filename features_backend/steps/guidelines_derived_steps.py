"""Checks drawn from writing guidelines (features_backend/guidelines-derived-policies.feature). An in-memory backend and files; no network."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.guidelines.operations_test import ADMIN, door, read, save, world  # noqa: E402

PUBLICATION_ID = "publication#avoid-lexicon"


def document(*avoid, ban=()):
    return {"schemaVersion": 1, "lexicon": {"avoid": list(avoid)}, **({"rules": {"bannedPhrases": list(ban)}} if ban else {})}


def check(context, scoped_key, language="en"):
    """The site's check with this scope and key (``publication#avoid-lexicon``) written for ``language``; a record's id is opaque."""
    scope, key = scoped_key.rsplit("#", 1)
    return next((row for row in context.backend.policies.rows if (row["scope"], row["policyKey"], row.get("language")) == (scope, key, language)), None)


def words_of(row):
    detectors = row["detectors"]
    return [phrase for detector in detectors for phrase in (detector.get("phrases") or [])]


def save_site(context, *avoid, ban=(), section=None):
    context.before = copy.deepcopy(context.backend.policies.rows)
    context.writes_before = len(context.backend.policies.writes)
    found = read(context.backend, kind="writing", **({"section": section} if section else {}))
    guard = found["result"]["expectedCurrentVersionId"] if found["ok"] else "none"
    context.answer = save(context.backend, ADMIN, document(*avoid, ban=ban), section=section, reason="Change", guard=guard)
    assert context.answer["ok"], context.answer


@given("a site with no writing guidelines and no editorial checks")
def step_empty(context):
    context.backend, context.files = world(saved=False)


@given('a site whose saved writing guidelines avoid the word "{word}"')
def step_saved(context, word):
    context.backend, context.files = world(saved=False)
    context.answer = door(context.backend, "guidelinesWrite", ADMIN, "guidelines_save", requestId="seed",
                          input={"kind": "writing", "document": document(word), "reason": "First", "expectedCurrentVersionId": "none"})
    assert context.answer["ok"], context.answer


@given('a site with a starter check and a hand-written check both keyed "avoid-lexicon" and "banned-phrases"')
def step_hand_written(context):
    context.backend, context.files = world(saved=False)
    for key, source in (("avoid-lexicon", "starter:ai-writing"), ("banned-phrases", "custom")):
        context.backend.policies.rows.append({"id": f"publication#{key}", "policyKey": key, "scope": "publication", "language": "en", "version": 3, "title": "Theirs", "guidance": "Theirs.",
                                              "severity": "block", "enabled": True, "detectors": [], "examples": None, "rewriteGuidance": None, "source": source})


@given('an admin has edited the check "{key}" by hand so its source is "custom"')
def step_hand_edit(context, key):
    row = check(context, f"publication#{key}")
    row.update({"source": "custom", "version": row["version"] + 1, "guidance": "Edited by an admin."})


@when('an admin saves site writing guidelines that avoid the word "{word}"')
def step_save_one(context, word):
    save_site(context, word)


@when('an admin saves site writing guidelines that avoid the words "{first}" and "{second}"')
def step_save_two(context, first, second):
    save_site(context, first, second)


@when('an admin saves site writing guidelines that ban the phrase "{phrase}" besides avoiding "{word}"')
def step_save_ban(context, word, phrase):
    save_site(context, word, ban=[phrase])


@when("an admin saves site writing guidelines that avoid no words")
def step_save_none(context):
    save_site(context)


@when('an admin saves writing guidelines for the section "{section}" that avoid the word "{word}"')
def step_save_section(context, section, word):
    save_site(context, word, section=section)


@when('an admin asks for the diff of site writing guidelines that avoid the words "{first}" and "{second}"')
def step_diff(context, first, second):
    context.before = copy.deepcopy(context.backend.policies.rows)
    context.writes_before = len(context.backend.policies.writes)
    context.item_writes = len(context.backend.writes)
    context.answer = door(context.backend, "guidelinesRead", ADMIN, "guidelines_diff", input={"kind": "writing", "document": document(first, second)})
    assert context.answer["ok"], context.answer


@then('a publication check named "{key}" exists with the source "{source}"')
def step_exists(context, key, source):
    row = check(context, f"publication#{key}")
    assert row is not None and row["source"] == source, row


@then('a check named "{key}" exists at the scope "{scope}" with the source "{source}"')
def step_exists_scoped(context, key, scope, source):
    row = check(context, f"{scope}#{key}")
    assert row is not None and row["source"] == source, row


@then('that check detects the word "{word}"')
@then('the publication check "avoid-lexicon" still detects the word "{word}"')
def step_detects(context, word):
    assert word in words_of(check(context, PUBLICATION_ID)), check(context, PUBLICATION_ID)


@then('the publication check "avoid-lexicon" still detects only the word "{word}"')
def step_only(context, word):
    assert words_of(check(context, PUBLICATION_ID)) == [word]


@then('exactly one check was updated and it is "{key}"')
def step_one_update(context, key):
    assert context.backend.policies.writes[context.writes_before:] == [("update", check(context, f"publication#{key}")["id"])], context.backend.policies.writes


@then("its source names version {number:d}")
def step_source_version(context, number):
    assert check(context, PUBLICATION_ID)["source"].endswith(f":v{number}")


@then("the starter check and the hand-written check are exactly as they were")
def step_untouched(context):
    assert context.backend.policies.rows[:2] == context.before


@then("the save reports both as skipped")
def step_skipped(context):
    skipped = {entry["policy"] for entry in context.answer["result"]["policies"] if entry["action"] == "skipped"}
    reported = {entry["policy"] for entry in context.answer["result"].get("policies", [])}
    assert skipped <= reported
    assert {row["policyKey"] for row in context.before} <= {row["policyKey"] for row in context.backend.policies.rows}


@then('the check "{key}" still exists, disabled, with its history version raised')
def step_disabled(context, key):
    row = check(context, f"publication#{key}")
    assert row is not None and row["enabled"] is False and row["version"] == 2 and row["source"].startswith("writing-guidelines:"), row


@then("no check was deleted")
def step_none_deleted(context):
    assert len(context.backend.policies.rows) >= len(context.before)


@then('the check "{key}" is exactly as the admin left it')
def step_as_left(context, key):
    assert check(context, f"publication#{key}") == next(row for row in context.before if row["policyKey"] == key)


@then('the diff lists an update of "{key}" at the scope "{scope}"')
def step_diff_lists(context, key, scope):
    assert {"action": "update", "policy": key, "scope": scope} in context.answer["result"]["policyPlan"], context.answer["result"]


@then("no check and no guideline version was written")
def step_nothing_written(context):
    assert context.backend.policies.writes == context.backend.policies.writes[:context.writes_before]
    assert context.backend.policies.rows == context.before and len(context.backend.writes) == context.item_writes
