from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

import parse
from behave import given, register_type, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.knowledge_cloud import ai_review as review  # noqa: E402
from papyrus_content.knowledge_snapshot import commands  # noqa: E402
from papyrus_content.knowledge_snapshot.actors import decode_review, make_actor  # noqa: E402
from papyrus_content.knowledge_snapshot.entity_add import DISAMBIGUATION_LINEAGE  # noqa: E402
from papyrus_content.knowledge_snapshot.entity_dedupe_commands_test import (  # noqa: E402
    AcceptingModel,
    current,
    mention,
    seed,
)
from papyrus_content.knowledge_snapshot.entity_duplicates import RULES_FILE, default_rules  # noqa: E402


@parse.with_pattern(r'[^"]+')
def parse_text(text):
    return text


@parse.with_pattern(r"[a-z_]+")
def parse_kind(text):
    return text


register_type(Text=parse_text, Kind=parse_kind)

NOW = "2026-11-10T00:00:00Z"
REVIEW_TEXT = "Redwood announced a new alignment programme this week. Pilot Lab described the programme in detail."


def call(context, function, *flags):
    """Run a command against the fake store, with the two site mutations of the Disambiguation tag recorded instead of sent."""
    context.error = None
    context.writes_before = len(context.client.writes)
    context.made, context.linked = [], []
    captured = io.StringIO()

    def make(client, typed, shown=None):
        context.made.append((typed, shown))
        return {"ok": True}

    def link(client, *, subject, object_, note):
        context.linked.append((subject, object_, note))
        return {"outcome": "created", "relationId": f"relation-{len(context.linked)}"}

    try:
        with mock.patch.object(commands, "create_authoring_client", lambda *args, **kwargs: (context.client, {})), mock.patch(
            "papyrus_content.signed_in_concepts.create_editor_concept", make
        ), mock.patch("papyrus_content.signed_in_concepts.create_concept_link", link), contextlib.redirect_stdout(captured):
            function(list(flags))
    except ValueError as error:
        context.error = str(error)
    context.output = captured.getvalue()


def entities_file(context, kind, name, item):
    entity = {"id": "e1", "kind": kind, "text": name, "state": "proposed", "entity_key": None, "span": None, "score": 0.9}
    path = context.work / f"entities-{len(list(context.work.glob('entities-*.json')))}.json"
    path.write_text(json.dumps({"schema_version": 1, "items": [{"item_id": f"item-{item}", "entities": [entity], "relations": []}]}))
    return str(path)


def named(context, name, kind=None):
    return [row for row in context.client.rows.get("SemanticNode", {}).values() if row["displayName"] == name and (kind is None or row["nodeKind"] == kind)]


def one(context, name, kind=None):
    [row] = named(context, name, kind)
    return row


def mentions_in(context, node, item):
    return [row for row in current(context.client) if row["objectLineageId"] == node["lineageId"] and row["subjectLineageId"] == f"lineage-{item}"]


def import_run(context, kind, name, item, corpus):
    call(context, commands.knowledge_publish_run, "--entities", entities_file(context, kind, name, item), "--skip-front-matter", "--corpus-key", corpus, "--apply")
    assert context.error is None, context.error


def names_in(text):
    return [part.strip().strip('"') for part in text.split(",") if part.strip()]


# ----------------------------------------------------------------------------------------------------- the map
@given('the map holds the accepted {kind:Kind} "{name:Text}"')
def step_accepted(context, kind, name):
    seed(context.client, kind, name)


@given('the map holds the generated {kind:Kind} "{name:Text}"')
def step_generated(context, kind, name):
    seed(context.client, kind, name, status="generated")


@given('"{name:Text}" is mentioned in the item "{item:Text}"')
def step_mentioned(context, name, item):
    mention(context.client, one(context, name), item)


@given('the extractor brought the {kind:Kind} "{name:Text}" in the item "{item:Text}" and the run was imported for the corpus "{corpus:Text}"')
def step_brought_before(context, kind, name, item, corpus):
    import_run(context, kind, name, item, corpus)


@given('a person rejected the proposal about "{name:Text}"')
def step_rejected_proposal(context, name):
    [proposal] = [row for row in context.client.rows["SteeringProposal"].values() if row["displayName"] == name]
    proposal["status"] = "rejected"
    context.decided = proposal["id"]


# ----------------------------------------------------------------------------------------------- the extractor
@when('the extractor brings the {kind:Kind} "{name:Text}" in the item "{item:Text}" and the run is imported for the corpus "{corpus:Text}"')
def step_brings(context, kind, name, item, corpus):
    import_run(context, kind, name, item, corpus)


@then('the map still has one entity named "{name:Text}"')
def step_one(context, name):
    assert len(named(context, name)) == 1, [row["nodeKey"] for row in context.client.rows["SemanticNode"].values()]
    assert len(context.client.rows["SemanticNode"]) == 1


@then('the map has an entity named "{first:Text}" and an entity named "{second:Text}"')
def step_two(context, first, second):
    assert len(named(context, first)) == 1 and len(named(context, second)) == 1


@then('the map has an entity named "{name:Text}"')
def step_has(context, name):
    assert len(named(context, name)) == 1


@then('the map has {count:d} entities named "{name:Text}"')
def step_count(context, count, name):
    assert len(named(context, name)) == count


@then('the map has no entity named "{name:Text}"')
def step_has_none(context, name):
    assert not named(context, name)


@then('"{name:Text}" has the alias "{alias:Text}"')
def step_alias(context, name, alias):
    assert alias in one(context, name)["aliases"], one(context, name)["aliases"]


@then('"{name:Text}" is mentioned in the item "{item:Text}"')
def step_is_mentioned(context, name, item):
    assert mentions_in(context, one(context, name), item), context.client.rows.get("SemanticRelation")


@then('"{name:Text}" is mentioned in the item "{item:Text}" once')
def step_mentioned_once(context, name, item):
    assert len(mentions_in(context, one(context, name), item)) == 1


@then('"{name:Text}" is mentioned in no item')
def step_no_mention(context, name):
    assert not [row for row in current(context.client) if row["objectLineageId"] == one(context, name)["lineageId"]]


@then("the import report says the duplicate was {outcome:Text}")
def step_report(context, outcome):
    assert f"duplicate\t{outcome}\t" in context.output, context.output


@then('one proposal asks a person whether "{brought:Text}" is "{existing:Text}"')
def step_proposal(context, brought, existing):
    [proposal] = context.client.rows["SteeringProposal"].values()
    assert (proposal["proposalKind"], proposal["displayName"], proposal["graphEntityId"]) == ("entity-alias-edit", brought, one(context, existing)["nodeKey"])


@then("that proposal is still rejected")
def step_still_rejected(context):
    assert context.client.rows["SteeringProposal"][context.decided]["status"] == "rejected"


@then("no proposal was filed")
def step_no_proposal(context):
    assert not context.client.rows.get("SteeringProposal")


# ----------------------------------------------------------------------------------------------------- AI review
@when("the AI review would accept every generated entity on a quote")
def step_review(context):
    generated = [row for row in context.client.rows["SemanticNode"].values() if row["status"] == "generated"]
    accepted = [row for row in context.client.rows["SemanticNode"].values() if row["status"] == "accepted"]
    rows = []
    for index, node in enumerate(generated):
        name = node["displayName"]
        start = REVIEW_TEXT.index(name)
        rows.append({"id": f"e{index}", "kind": node["nodeKind"], "text": name, "span": {"start": start, "end": start + len(name)}})
    typed = review.TypedRun({"items": [{"item_id": "i1", "entities": rows, "relations": []}]}, {"i1": REVIEW_TEXT})
    context.proposals = []
    context.patches, context.decisions = review.review_entities(
        generated, typed, lambda node: [], AcceptingModel(), make_actor("ai", None, "2026-11-10"), now=NOW, vocabulary={}, accepted=accepted, proposals=context.proposals
    )
    context.client.rows["SteeringProposal"] = {row["id"]: row for row in context.proposals}


def decision_of(context, name):
    return next(decision for decision in context.decisions if decision.subject.endswith(f": {name}"))


@then('the AI review left "{name:Text}" generated and unsure because it may duplicate "{existing:Text}"')
def step_held(context, name, existing):
    decision = decision_of(context, name)
    assert (decision.verdict, decision.applied, decision.gate) == ("unsure", False, review.GATE_POSSIBLE_DUPLICATE)
    assert existing in decision.reason
    assert not [patch for patch in context.patches if patch["expected"]["id"] == one(context, name)["id"]]


@then('the AI review accepted "{name:Text}"')
def step_review_accepted(context, name):
    assert decision_of(context, name).applied is True
    assert any(patch["expected"]["id"] == one(context, name)["id"] and patch["expected"].get("status") == "accepted" for patch in context.patches)


@then('one proposal asks a person to merge "{name:Text}" into "{existing:Text}"')
def step_merge_proposal(context, name, existing):
    [proposal] = context.proposals
    assert proposal["proposalKind"] == "merge-graph-entity" and proposal["graphEntityId"] == one(context, existing)["nodeKey"]
    assert f"--from {one(context, name)['nodeKey']} --into {one(context, existing)['nodeKey']}" in proposal["description"]


# ---------------------------------------------------------------------------------------------------------- add
def add(context, kind, name, aliases=(), *flags):
    arguments = ["--kind", kind, "--name", name, "--actor", "ai", "--actor-name", "Agent", *flags]
    for alias in aliases:
        arguments += ["--alias", alias]
    call(context, commands.knowledge_entities_add, *arguments)


@when('an agent adds the {kind:Kind} "{name:Text}" with the aliases "{first:Text}" and "{second:Text}"')
def step_add_two(context, kind, name, first, second):
    add(context, kind, name, [first, second])
    assert context.error is None, context.error


@when('an agent adds the {kind:Kind} "{name:Text}" with the alias "{alias:Text}"')
def step_add_one(context, kind, name, alias):
    add(context, kind, name, [alias])
    assert context.error is None, context.error


@when('an agent adds the {kind:Kind} "{name:Text}"')
def step_add(context, kind, name):
    add(context, kind, name)


@when('an agent previews adding the {kind:Kind} "{name:Text}" with the alias "{alias:Text}"')
def step_add_preview(context, kind, name, alias):
    add(context, kind, name, [alias], "--dry-run")
    assert context.error is None, context.error


@then('the map has the accepted {kind:Kind} "{name:Text}" with the aliases "{aliases:Text}"')
def step_added(context, kind, name, aliases):
    node = one(context, name, kind)
    assert node["status"] == "accepted" and node["aliases"] == [alias.strip() for alias in aliases.split(",")], node


@then("the entity was accepted by the AI agent")
def step_by_agent(context):
    [node] = context.client.rows["SemanticNode"].values()
    marks = decode_review(node["changeReason"])
    assert (marks.accepted_by.actor, marks.accepted_by.name) == ("ai", "Agent")


@then("no record was changed")
def step_nothing_written(context):
    assert context.error is None, context.error
    assert len(context.client.writes) == context.writes_before


@then("the preview says the entity would be created")
def step_preview(context):
    assert "created" in context.output and "dry-run" in context.output


@then('the entity command is refused with "{text:Text}"')
def step_refused(context, text):
    assert context.error and text in context.error, context.error


@then("the Disambiguation concept was made")
def step_concept_made(context):
    assert context.made == [("Disambiguation", "Disambiguation")]


@then('the {first_kind:Kind} "{first:Text}" and the {second_kind:Kind} "{second:Text}" are each linked to the Disambiguation concept with a note that says they must not be merged')
def step_tagged(context, first_kind, first, second_kind, second):
    lineages = {one(context, first, first_kind)["lineageId"], one(context, second, second_kind)["lineageId"]}
    assert {subject for subject, _, _ in context.linked} == lineages
    assert {object_ for _, object_, _ in context.linked} == {DISAMBIGUATION_LINEAGE}
    assert all("do not merge them" in note for _, _, note in context.linked)


@then("nothing was linked to the Disambiguation concept")
def step_not_tagged(context):
    assert not context.linked and not context.made


# --------------------------------------------------------------------------------------------------------- merge
@when('a person merges "{duplicate:Text}" into "{survivor:Text}"')
def step_merge(context, duplicate, survivor):
    context.merged = one(context, duplicate)
    call(context, commands.knowledge_entities_merge, "--from", context.merged["nodeKey"], "--into", one(context, survivor)["nodeKey"], "--actor", "human", "--actor-name", "Ryan")
    assert context.error is None, context.error


@when('a person previews merging "{duplicate:Text}" into "{survivor:Text}"')
def step_merge_preview(context, duplicate, survivor):
    call(context, commands.knowledge_entities_merge, "--from", one(context, duplicate)["nodeKey"], "--into", one(context, survivor)["nodeKey"], "--actor", "human", "--dry-run")


@when('a person merges the {kind:Kind} "{duplicate:Text}" into "{survivor:Text}"')
def step_merge_kind(context, kind, duplicate, survivor):
    call(context, commands.knowledge_entities_merge, "--from", one(context, duplicate, kind)["nodeKey"], "--into", one(context, survivor)["nodeKey"], "--actor", "human")


@when('a person merges "{duplicate:Text}" into the generated "{survivor:Text}"')
def step_merge_generated(context, duplicate, survivor):
    call(context, commands.knowledge_entities_merge, "--from", one(context, duplicate)["nodeKey"], "--into", one(context, survivor)["nodeKey"], "--actor", "human")


@then('"{name:Text}" is no longer a current entity')
def step_superseded(context, name):
    assert context.merged["id"] == one(context, name)["id"]
    row = context.client.rows["SemanticNode"][context.merged["id"]]
    assert (row["versionState"], row["status"]) == ("superseded", "superseded")


@then('no current link touches "{name:Text}"')
def step_no_links(context, name):
    lineage = context.merged["lineageId"]
    assert not [row for row in current(context.client) if lineage in (row["objectLineageId"], row["subjectLineageId"])]


@then("the merge output says the duplicate's page is left as it is because the sync never takes a page down")
def step_next(context):
    assert "is left as it is, since the sync never takes a page down" in context.output, context.output


# ----------------------------------------------------------------------------------------------------- duplicates
@when("an agent asks for the duplicates")
def step_duplicates(context):
    call(context, commands.knowledge_entities_duplicates)
    assert context.error is None, context.error


@then('the report lists "{duplicate:Text}" as a duplicate of "{existing:Text}"')
def step_listed(context, duplicate, existing):
    assert f"\t{duplicate}\t{existing}\t" in context.output, context.output


@then('the report does not list "{name:Text}"')
def step_not_listed(context, name):
    assert name.casefold().replace(" ", "-") not in context.output, context.output


# --------------------------------------------------------------------------------------------------- the rules
@then('the duplicate rules file lists the rules "{ids:Text}"')
def step_rules(context, ids):
    assert RULES_FILE.is_file()
    assert [rule.id for rule in default_rules().rules] == names_in(ids)


@then('the rule "{first:Text}" applies only to organizations and the rule "{second:Text}" only to people')
def step_rule_kinds(context, first, second):
    by_id = {rule.id: rule for rule in default_rules().rules}
    assert by_id[first].kinds == {"organization"} and by_id[second].kinds == {"person"}
