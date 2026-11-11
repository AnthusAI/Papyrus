"""Tagging a story or a Reference with an existing concept (features_backend/concept-tags.feature). A stand-in site; no network, login or AWS."""
from __future__ import annotations

import contextlib
import io
import json
import shlex
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import concept_tags_commands  # noqa: E402
from papyrus_content.concept_tags import audit_story_links  # noqa: E402
from test_concept_tags import Site  # noqa: E402

TARGETS = {"big": ("story", "item-big"), "reference-a": ("reference", "reference-a")}


def _relations(context) -> list[dict]:
    return list(context.site.tables.get("SemanticRelation", {}).values())


def _tag(context, kind: str, target: str, concept: str, extra: str = "") -> None:
    command = concept_tags_commands.stories_link_concept if kind == "story" else concept_tags_commands.references_link_concept
    flags = ["--story" if kind == "story" else "--reference", target, "--concept", concept, *shlex.split(extra)]
    out, err = io.StringIO(), io.StringIO()
    context.failure = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
            mock.patch.object(concept_tags_commands, "create_authoring_client", return_value=(context.site, {})), \
            mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=True), \
            mock.patch("papyrus_content.cli_user_auth.signed_in_label", return_value=context.person):
        try:
            command(flags)
        except BaseException as error:  # noqa: BLE001
            context.failure = error
    context.out, context.err = out.getvalue(), err.getvalue()


@given('a site with a published article "A big story", an accepted Reference, and these concepts: an accepted "Voice Cloning" with a public page, an accepted "Unpublished idea" with none, accepted "Translation" concepts of three kinds, and a rejected "Spam"')
def _site(context):
    context.site = Site()
    context.nodes_before = json.dumps(context.site.tables["SemanticNode"], sort_keys=True)
    context.person = "Ada Example"


@given('the story "big" is already tagged with "Voice Cloning" under the older name "related_to"')
def _legacy(context):
    context.site.tables["SemanticRelation"] = {"legacy": {
        "id": "legacy", "relationState": "current", "predicate": "related_to", "subjectKind": "item", "subjectLineageId": "item-big", "objectKind": "semanticNode",
        "objectId": "editor_concept--voice-cloning-v1", "objectLineageId": "semantic-node-editor_concept--voice-cloning", "subjectStateKey": "item#item-big#current",
        "metadata": json.dumps({"kind": "item.concept"})}}


@given('the story "big" has a rejected tag for "Voice Cloning"')
def _rejected(context):
    _legacy(context)
    row = context.site.tables["SemanticRelation"]["legacy"]
    row.update({"predicate": "tagged_with", "relationState": "rejected", "subjectStateKey": "item#item-big#rejected"})
    context.before = json.dumps(context.site.tables["SemanticRelation"], sort_keys=True)


@when('a signed-in editor "{name}" tags the story "{slug}" with the concept "{concept}"')
def _story_tag(context, name, slug, concept):
    context.person = name
    _tag(context, "story", slug, concept)


@when('a signed-in editor "{name}" tags the story "{slug}" with "{concept}" passing the option "{extra}"')
def _story_tag_extra(context, name, slug, concept, extra):
    context.person = name
    _tag(context, "story", slug, concept, extra)


@when('a signed-in editor "{name}" tags the Reference "{target}" with "{concept}"')
def _reference_tag(context, name, target, concept):
    context.person = name
    _tag(context, "reference", target, concept)


@when('an editor audits the links of the story "{slug}"')
def _audit(context, slug):
    context.findings = audit_story_links(context.site, [TARGETS[slug][1]])


@then('the tagging succeeds and prints "{outcome}" for "{name}" with{page}')
def _succeeds(context, outcome, name, page):
    assert context.failure is None, f"{context.failure!r}\n{context.out}\n{context.err}"
    line = next(line.split("\t") for line in context.out.splitlines())
    expected_page = "public page" if page.strip() == "a public page" else "no public page"
    assert (line[4], line[5], line[6]) == (name, expected_page, outcome), line


@then('the tagging fails with "{message}"')
def _fails(context, message):
    assert context.failure is not None and message in str(context.failure), f"{context.failure!r}\n{context.out}"


@then('the tagging fails naming "{one}", "{two}" and "{three}"')
def _fails_naming(context, one, two, three):
    assert context.failure is not None and all(key in str(context.failure) for key in (one, two, three)), context.failure


@then('it lists "{key}" as a close match')
def _close(context, key):
    assert key in str(context.failure), context.failure


@then('it warned that "{name}" has no public wiki page yet')
def _warned(context, name):
    assert f"{name} has no public wiki page yet" in context.err, context.err


@then("no tag was written")
def _no_tag(context):
    assert context.site.tables.get("SemanticRelation", {}) == {}, _relations(context)


@then("no concept was created")
def _no_concept(context):
    assert json.dumps(context.site.tables["SemanticNode"], sort_keys=True) == context.nodes_before


@then('the story has one current "{predicate}" edge to "{key}", kind "{kind}", provenance "{provenance}", added by "{name}"')
def _story_edge(context, predicate, key, kind, provenance, name):
    rows = _relations(context)
    assert len(rows) == 1, rows
    meta = json.loads(rows[0]["metadata"])
    assert (rows[0]["predicate"], rows[0]["relationState"], rows[0]["objectLineageId"], meta["kind"], meta["provenance"], meta["addedBy"]) == (
        predicate, "current", f"semantic-node-{key}", kind, provenance, name), rows[0]


@then('the Reference has one current "{predicate}" edge, kind "{kind}"')
def _reference_edge(context, predicate, kind):
    rows = _relations(context)
    assert len(rows) == 1 and (rows[0]["predicate"], rows[0]["relationState"], rows[0]["subjectKind"], json.loads(rows[0]["metadata"])["kind"]) == (predicate, "current", "reference", kind), rows


@then('the only edge is still the "{predicate}" one')
def _only(context, predicate):
    rows = _relations(context)
    assert [row["predicate"] for row in rows] == [predicate] and rows[0]["id"] == "legacy", rows


@then("the edge is still rejected")
def _still_rejected(context):
    assert json.dumps(context.site.tables["SemanticRelation"], sort_keys=True) == context.before


@then('the audit lists the problem "{problem}"')
def _problem(context, problem):
    assert problem in {finding["problem"] for finding in context.findings}, context.findings
