"""A signed-in editor marks a Story's consulted source as cited (features_backend/story-reference-role.feature).

The CLI half runs the real `papyrus stories link-reference` command against `SignedInSite`, a stand-in that refuses what AppSync refuses a
signed-in token; the route's half runs the site's own code through scripts/story-reference-role-probe.ts. No network, login or AWS.
"""
from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import story_commands  # noqa: E402
from papyrus_content.operator_errors import GraphQLRequestError  # noqa: E402
from papyrus_content.story_reporting import story_reference_relation_id  # noqa: E402
from story_reference_role_site import SignedInSite  # noqa: E402
from test_story_cli_live_test_edges import run  # noqa: E402

LINEAGE = "item-reported-story"
REFERENCE = "reference-knowledge-corpus-ai-ml-research-url-abc123"
RELATION = story_reference_relation_id(LINEAGE, REFERENCE)
RECORDS = {
    "Item": [{"id": f"{LINEAGE}-v1", "lineageId": LINEAGE, "versionNumber": 1, "versionState": "current", "headline": "A story", "title": "A story",
              "stage": "draft", "slug": "a-story", "type": "untyped", "section": "news"}],
    "Reference": [{"id": REFERENCE, "lineageId": REFERENCE, "versionNumber": 1, "versionState": "current", "title": "A source"}],
}
GROUPS = {"editor": ["editor"], "administrator": ["admin"], "viewer": ["viewer"], "person in no group": ["Google_123"]}


def relation(context, relation_id=RELATION) -> dict:
    return context.site.tables["SemanticRelation"][relation_id]


def metadata(context, relation_id=RELATION) -> dict:
    return json.loads(relation(context, relation_id)["metadata"])


def run_command(context, command: str, *, signed_in: bool, label: str | None) -> None:
    words = shlex.split(command)
    assert words[:3] == ["papyrus", "stories", "link-reference"], command
    flags = ["--story", LINEAGE, "--reference", REFERENCE, *words[3:]]
    context.out, context.err, context.failure = run(story_commands.stories_link_reference, context.site, *flags, signed_in=signed_in, label=label)


@given("a Story with one saved version and one Reference it was reported from")
def _story(context):
    context.site = SignedInSite(RECORDS, groups=["editor"], label="Ada Example", run_site_code=True)


@given('the Reference is attached to the Story as consulted by "{name}"')
def _attached(context, name):
    run_command(context, "papyrus stories link-reference --role consulted", signed_in=True, label=name)
    assert context.failure is None, context.failure
    assert metadata(context)["role"] == "consulted" and metadata(context)["addedBy"] == name
    context.site.refused.clear()
    context.site.route_calls.clear()


@given("the Reference is attached to the Story as based on")
def _based_on(context):
    row = relation(context)
    row["metadata"] = json.dumps({**metadata(context), "role": "based_on"}, sort_keys=True)


@given("the site's backend has not been deployed with the route yet")
def _no_route(context):
    context.site.has_route = False


@given("the site holds a category note relation and a reference link relation")
def _others(context):
    base = {k: v for k, v in relation(context).items() if k not in ("id", "metadata")}
    context.others = {
        "semantic-relation-category-note": {**base, "id": "semantic-relation-category-note", "predicate": "has_note",
                                            "metadata": json.dumps({"kind": "category.note", "note": "Keep this as written"})},
        "semantic-relation-reference-link": {**base, "id": "semantic-relation-reference-link", "predicate": "related_to", "subjectKind": "reference",
                                             "metadata": json.dumps({"kind": "reference.link", "decision": "accepted"})},
    }
    context.site.tables["SemanticRelation"].update(json.loads(json.dumps(context.others)))


@when('a signed-in {who} "{name}" runs "{command}"')
def _signed_in_runs(context, who, name, command):
    context.site.groups = GROUPS[who]
    context.site.label = name
    run_command(context, command, signed_in=True, label=name)


@when('an operator on the IAM lane runs "{command}"')
def _iam_runs(context, command):
    context.site = _iam_site(context.site)
    run_command(context, command, signed_in=False, label=None)


def _iam_site(site: SignedInSite) -> SignedInSite:
    """The same rows behind an IAM caller, which the model's IAM rule lets update a relation."""
    from fake_client import FakeAuthoringClient

    class IamSite(SignedInSite):
        upsert = FakeAuthoringClient.upsert

    iam = IamSite({}, groups=[], run_site_code=False)
    iam.tables = site.tables
    return iam


@when("a signed-in editor tries to rewrite the Story's source relation directly")
def _direct(context):
    context.site.groups = ["editor"]
    try:
        context.site.update_record("SemanticRelation", {"id": RELATION, "metadata": json.dumps({**metadata(context), "role": "cited"})})
        context.failure = None
    except GraphQLRequestError as error:
        context.failure = error


@when("a signed-in editor asks the route to mark each of them cited")
def _route_others(context):
    from papyrus_content.story_reporting import set_story_reference_role

    context.site.groups = ["editor"]
    context.failures = []
    for relation_id in context.others:
        try:
            set_story_reference_role(context.site, relation_id, role="cited", citation_key="k")
            context.failures.append(None)
        except GraphQLRequestError as error:
            context.failures.append(str(error))


@then("the command succeeds and prints that the link was updated")
def _succeeds(context):
    assert context.failure is None, f"{context.failure!r}\n{context.out}\n{context.err}"
    assert f"stories\tlink-reference\tupdated\t{RELATION}" in context.out, context.out


@then('the source is cited with the citation key "{key}"')
def _cited(context, key):
    assert (metadata(context)["role"], metadata(context).get("citationKey")) == ("cited", key), metadata(context)


@then('the source is still based on, with the citation key "{key}"')
def _still_based_on(context, key):
    assert (metadata(context)["role"], metadata(context).get("citationKey")) == ("based_on", key), metadata(context)


@then('the change is recorded as made by "{name}" through the CLI, and "{adder}" is still who attached it')
def _recorded(context, name, adder):
    stored = metadata(context)
    assert (stored["updatedBy"], stored["updatedVia"], stored["addedBy"]) == (name, "cli", adder), stored


@then("the site refused the CLI's direct update before writing anything, and the route made the change")
def _refused_then_route(context):
    assert context.site.refused == ["updateSemanticRelation"], context.site.refused
    assert len(context.site.route_calls) == 1, context.site.route_calls


@then("it is still one link between the Story and the source")
def _one_link(context):
    assert list(context.site.tables["SemanticRelation"]) == [RELATION]


@then('the site refuses with "{message}"')
def _refuses(context, message):
    assert context.failure is not None and message in str(context.failure), context.failure


@then("the source is still consulted")
def _still_consulted(context):
    assert metadata(context)["role"] == "consulted" and "citationKey" not in metadata(context), metadata(context)


@then('the site refuses each with "{message}"')
def _refuses_each(context, message):
    assert context.failures and all(failure and message in failure for failure in context.failures), context.failures


@then("neither relation changed")
def _unchanged(context):
    for relation_id, row in context.others.items():
        assert relation(context, relation_id) == row, relation(context, relation_id)


@then('the command fails with "{message}"')
def _fails(context, message):
    assert context.failure is not None and message in str(context.failure), f"{context.failure!r}\n{context.out}"


@then("the command printed no write line")
def _no_write(context):
    assert "\twrite" not in context.out, context.out


@then("the route was not called")
def _route_not_called(context):
    assert context.site.route_calls == [], context.site.route_calls


@then("the failure names the operator's IAM lane as the way to do it today")
def _names_iam(context):
    assert "PAPYRUS_GRAPHQL_AUTH=iam" in str(context.failure), context.failure
