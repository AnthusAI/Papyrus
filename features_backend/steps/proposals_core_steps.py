from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import boto3
from behave import given, then, when
from moto import mock_aws

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

from reader_fixtures import OPERATOR_ACCOUNT, operator_identity, proposal_handler, START_SECONDS  # noqa: E402

TABLE = "Proposal-core"
BODY = "Why this matters.\n"


def staff(sub: str, group: str) -> dict:
    return {"sub": sub, "claims": {"cognito:groups": [group], "sub": sub}}


def call(context, field: str, arguments: dict, identity: dict, account_id: str | None = None) -> dict:
    event = {"typeName": "Query" if field == "listStoryDrafts" else "Mutation", "fieldName": field, "arguments": arguments, "identity": identity}
    arn = f"arn:aws:lambda:us-east-1:{account_id}:function:proposal-actions" if account_id else None
    context.core_now += 1
    answer = proposal_handler.handle_event(event, store=context.core_store, now_seconds=context.core_now, account_id=proposal_handler.function_account(SimpleNamespace(invoked_function_arn=arn)))
    context.core_answer = answer
    return answer


def operator(context, field: str, arguments: dict) -> dict:
    return call(context, field, arguments, operator_identity(), OPERATOR_ACCOUNT)


def rows(context) -> list[dict]:
    return sorted(context.core_resource.Table(TABLE).scan()["Items"], key=lambda row: row["createdAt"])


def draft(title: str, **extra) -> dict:
    return {"kind": "story_draft", "title": title, "body": BODY, **extra}


@given("a site backend with no plugins")
def site_without_plugins(context) -> None:
    context.core_mock = mock_aws()
    context.core_mock.start()
    context.add_cleanup(context.core_mock.stop)
    context.core_resource = boto3.resource("dynamodb", region_name="us-east-1")
    context.core_resource.create_table(
        TableName=TABLE, KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}], AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST"
    )
    context.core_store = proposal_handler.DynamoProposalStore(resource=context.core_resource, proposal_table=TABLE)
    context.core_now = START_SECONDS
    context.core_ids = []


@given("the site's automation runs as an operator role")
def operator_role(context) -> None:
    context.operator_ready = True


@given("an editor and an admin are signed in")
def editor_and_admin(context) -> None:
    context.editor = staff("editor-sub", "editor")
    context.admin = staff("admin-sub", "admin")


@when('the automation files a story draft titled "{title}" with a one-line summary')
def operator_files_with_summary(context, title: str) -> None:
    answer = operator(context, "fileProposal", draft(title, summary="One line."))
    assert answer["status"] == "ok", answer
    context.core_ids.append(answer["id"])


@given('the automation filed a story draft titled "{title}"')
def operator_filed(context, title: str) -> None:
    answer = operator(context, "fileProposal", draft(title))
    assert answer["status"] == "ok", answer
    context.core_ids.append(answer["id"])


@given('the automation filed story drafts titled "{first}" and "{second}"')
def operator_filed_two(context, first: str, second: str) -> None:
    for title in (first, second):
        operator_filed(context, title)


@then('the draft is stored as a core proposal in state "{state}" proposed by AI')
def stored_by_ai(context, state: str) -> None:
    stored = rows(context)
    assert len(stored) == 1 and stored[0]["state"] == state and stored[0]["proposer"] == "ai", stored


@then("the site has no reader tables")
def no_reader_tables(context) -> None:
    names = [table.name for table in context.core_resource.tables.all()]
    assert names == [TABLE], names


@when("the automation lists the story drafts")
def operator_lists(context) -> None:
    operator(context, "listStoryDrafts", {})


@then("the answer holds {count:d} drafts, newest first")
def holds_newest_first(context, count: int) -> None:
    drafts = context.core_answer["drafts"]
    assert len(drafts) == count, drafts
    assert [entry["title"] for entry in drafts] == ["Second", "First"], drafts


@then("each draft shows only its id, title, summary, targets, state and creation time")
def six_fields(context) -> None:
    for entry in context.core_answer["drafts"]:
        assert sorted(entry) == sorted(["id", "title", "summary", "targets", "state", "createdAt"]), entry


def move_as(context, identity: dict | None, state: str) -> None:
    arguments = {"proposalId": context.core_ids[-1], "state": state}
    if identity is None:
        operator(context, "transitionProposal", arguments)
    else:
        call(context, "transitionProposal", arguments, identity)


@when('the editor advances the draft to "{state}"')
def editor_moves(context, state: str) -> None:
    move_as(context, context.editor, state)


@when('the admin advances the draft to "{state}"')
def admin_moves(context, state: str) -> None:
    move_as(context, context.admin, state)
    assert context.core_answer["status"] == "ok", context.core_answer


@when('the operator advances the draft to "{state}"')
def operator_moves(context, state: str) -> None:
    move_as(context, None, state)


@then('the draft is now in state "{state}"')
def proposal_state(context, state: str) -> None:
    assert rows(context)[0]["state"] == state, rows(context)


@then("its history records {count:d} moves, none of them naming a person in the public files")
def history_moves(context, count: int) -> None:
    history = json.loads(rows(context)[0]["history"])
    # Moves are recorded with the staff member's subject privately; the public files (reader-steering) never publish it.
    assert len([entry for entry in history if entry.get("from")]) == count, history


@then('the automation is told "{error}"')
def operator_told(context, error: str) -> None:
    assert context.core_answer["error"] == error, context.core_answer


@when("the automation tries to hold the draft")
def operator_holds(context) -> None:
    operator(context, "editProposal", {"proposalId": context.core_ids[-1], "action": "hold"})


@when("the editor holds the draft")
def editor_holds(context) -> None:
    call(context, "editProposal", {"proposalId": context.core_ids[-1], "action": "hold"}, context.editor)
    assert context.core_answer["status"] == "ok", context.core_answer


@then("the draft is on hold")
def on_hold(context) -> None:
    assert rows(context)[0].get("held") is True, rows(context)


@when("an identity-pool user tries to file a story draft")
def identity_pool(context) -> None:
    context.refusals = [call(context, "fileProposal", draft("T"), operator_identity(cognitoIdentityId="us-east-1:abc", cognitoIdentityPoolId="us-east-1:pool"), OPERATOR_ACCOUNT)]


@when("an operator of another account tries to file a story draft")
def other_account(context) -> None:
    context.refusals.append(call(context, "fileProposal", draft("T"), operator_identity(accountId="999999999999", userArn="arn:aws:sts::999999999999:assumed-role/x/y"), OPERATOR_ACCOUNT))


@then('both callers are told "{error}"')
def both_refused(context, error: str) -> None:
    assert [answer["error"] for answer in context.refusals] == [error, error], context.refusals


@then("the site stores no proposal")
def none_stored(context) -> None:
    assert rows(context) == []


def source(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


@then("the Proposal model and its operations are defined by the core schema")
def core_defines(context) -> None:
    core = source("amplify/functions/proposal-actions/schema.ts")
    for name in ("Proposal: a", "fileProposal: a", "transitionProposal: a", "editProposal: a", "listStoryDrafts: a"):
        assert name in core, name
    assert "proposalActionsSchemaDefinitions" in source("amplify/data/schema.ts")


@then("the reader-steering plugin defines none of them")
def plugin_defines_none(context) -> None:
    plugin = source("amplify/plugins/reader-steering/schema.ts")
    for name in ("Proposal: a", "fileProposal", "transitionProposal", "editProposal", "listStoryDrafts"):
        assert name not in plugin, name


@then("the plugin still reads the same table for reader votes and public publishing")
def plugin_reads_table(context) -> None:
    wiring = source("amplify/plugins/reader-steering/papyrus.plugin.ts")
    assert "PAPYRUS_READER_PROPOSAL_TABLE" in wiring and "tables.Proposal" in wiring


def edit_as(context, identity: dict, action: str) -> None:
    call(context, "editProposal", {"proposalId": context.core_ids[-1], "action": action}, identity)
    assert context.core_answer["status"] == "ok", context.core_answer


@when("the editor pins the draft")
def editor_pins(context) -> None:
    edit_as(context, context.editor, "pin")


@when("the editor unpins the draft")
def editor_unpins(context) -> None:
    edit_as(context, context.editor, "unpin")


@when("the editor releases the draft")
def editor_releases(context) -> None:
    edit_as(context, context.editor, "release")


@then("the draft is pinned and on hold")
def pinned_and_held(context) -> None:
    row = rows(context)[0]
    assert row.get("pinned") is True and row.get("held") is True, row


@then("the draft is not pinned")
def not_pinned(context) -> None:
    assert rows(context)[0].get("pinned") is False, rows(context)


@then('the editor is refused "{error}"')
def editor_refused(context, error: str) -> None:
    assert context.core_answer["error"] == error, context.core_answer


def panel_source() -> str:
    return source("components/proposals-view.tsx") + source("lib/proposals-admin.ts")


@then("the Proposals panel is in Administration for every site")
def panel_everywhere(context) -> None:
    workspace = source("components/topic-steering-workspace.tsx")
    assert 'administrationPanel === "proposals" ? <ProposalsPanel />' in workspace
    # The link is not inside the reader-steering condition: it sits before it.
    link = workspace.index('data-news-desk-admin-nav="proposals"')
    before = workspace[: workspace.rindex("<Link", 0, link)].rstrip()
    assert before.endswith(") : null}"), "the Proposals link is not inside a plugin condition"
    assert 'value === "proposals"' in workspace


@then("the panel offers a draft a straight move to editor review, pin, hold and decline")
def panel_offers(context) -> None:
    text = panel_source()
    for label in ("Move to editor review", '"in_steering", "editor_review"', "Pin", "Hold", "Decline"):
        assert label in text, label


@then("the panel says nothing of steering, votes or readers when the site has no reader-steering")
def panel_quiet(context) -> None:
    # Covered by scripts/test-proposals-panel.ts, which renders the panel without readers and finds none of those words.
    assert "props.readers" in source("components/proposals-view.tsx")
