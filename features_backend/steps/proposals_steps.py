from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

from reader_fixtures import OPERATOR_ACCOUNT, OPERATOR_ARN, ReaderBackend, operator_identity, run_snapshot  # noqa: E402
from papyrus_content.projection.plugins import is_plugin_runtime_key  # noqa: E402
from papyrus_content.projection.writers import LocalDirectoryWriter  # noqa: E402
from papyrus_content.reader_steering.proposals import proposal_subject_key  # noqa: E402

FIXTURES = REPO_ROOT / "features_backend" / "fixtures" / "proposals"
TARGETS = {
    "story_draft": [],
    "new_concept": [],
    "rename": [{"type": "concept", "id": "agents"}],
    "merge": [{"type": "concept", "id": "a"}, {"type": "concept", "id": "b"}],
    "split": [{"type": "cluster", "id": "agents"}],
    "new_column": [],
    "element_symbol": [{"type": "entity", "id": "openai"}],
}


def backend_of(context) -> ReaderBackend:
    return context.proposal_backend


def close_backend(context) -> None:
    backend = getattr(context, "proposal_backend", None)
    if backend is not None:
        backend.__exit__(None, None, None)
        context.proposal_backend = None


def arguments_for(kind: str, title: str = "A proposal", **extra) -> dict:
    return {"kind": kind, "title": title, "body": "Why this matters.\n", "targets": json.dumps(TARGETS[kind]), **extra}


def file_proposal(context, arguments: dict, **call) -> dict:
    answer = backend_of(context).proposal_call("fileProposal", arguments, **call)
    context.proposal_answer = answer
    if answer["status"] == "ok":
        context.proposal_id = answer["id"]
    return answer


def move(context, state: str, **extra) -> dict:
    answer = backend_of(context).proposal_call("transitionProposal", {"proposalId": context.proposal_id, "state": state, **extra})
    context.proposal_answer = answer
    return answer


def publish(context, base_path: str = "") -> None:
    backend = backend_of(context)
    context.proposal_site = context.proposal_site or LocalDirectoryWriter(Path(context.proposal_directory.name))
    backend.now += 120
    run_snapshot(backend, context.proposal_site, base_path=base_path)


def run_with_setting(context, setting) -> None:
    backend = backend_of(context)
    context.proposal_site = context.proposal_site or LocalDirectoryWriter(Path(context.proposal_directory.name))
    backend.now += 120
    context.proposal_report = run_snapshot(backend, context.proposal_site, publish_proposals=setting)


def public_file(context, key: str) -> dict:
    body = context.proposal_site.get(key)
    assert body is not None, f"{key} was not written; the store holds {sorted(entry.key for entry in context.proposal_site.list())}"
    return json.loads(body)


def first_public(context) -> dict:
    return public_file(context, "_data/proposals/index.json")["proposals"][0]


@given("a publication with proposals")
def publication(context) -> None:
    close_backend(context)
    context.proposal_backend = ReaderBackend()
    context.proposal_backend.__enter__()
    context.add_cleanup(close_backend, context)
    context.proposal_directory = tempfile.TemporaryDirectory()
    context.add_cleanup(context.proposal_directory.cleanup)
    context.proposal_site = None
    context.proposal_id = None
    context.proposal_answer = None
    context.proposal_view = None


@given("an editor and a reader")
def people(context) -> None:
    context.proposal_editor_groups = ("editor",)


@given('a filed "{kind}" proposal')
def filed(context, kind: str) -> None:
    assert file_proposal(context, arguments_for(kind))["status"] == "ok"


@given('a filed "{kind}" proposal that is in editor review')
def filed_in_review(context, kind: str) -> None:
    filed(context, kind)
    assert move(context, "in_steering")["status"] == "ok"
    assert move(context, "editor_review")["status"] == "ok"


@given('a filed "{kind}" proposal that was declined')
def filed_declined(context, kind: str) -> None:
    filed_in_review(context, kind)
    assert move(context, "declined", reason="Not now.")["status"] == "ok"


@given("the subjects snapshot counts {up:d} up and {down:d} down on it")
def counted(context, up: int, down: int) -> None:
    context.proposal_items = {"items": {proposal_subject_key(context.proposal_id): {"up": up, "down": down}}}


@when('the editor files a "{kind}" proposal titled "{title}"')
def editor_files_titled(context, kind: str, title: str) -> None:
    file_proposal(context, arguments_for(kind, title))


@when("the editor files proposals of every kind")
def editor_files_every_kind(context) -> None:
    for kind in TARGETS:
        assert file_proposal(context, arguments_for(kind, kind))["status"] == "ok"


@when('the editor files a "merge" proposal naming {count:d} concept')
def editor_files_short_merge(context, count: int) -> None:
    file_proposal(context, arguments_for("merge", targets=json.dumps(TARGETS["merge"][:count])))


@when('the reader tries to file a "{kind}" proposal')
def reader_files(context, kind: str) -> None:
    file_proposal(context, arguments_for(kind), groups=("reader",))


@when('the editor files a "story_draft" proposal with a Markus body')
def editor_files_markus(context) -> None:
    context.proposal_markus = (FIXTURES / "body.md").read_text(encoding="utf-8")
    file_proposal(context, arguments_for("story_draft", body=context.proposal_markus))


@when('the editor moves it to "{state}"')
def editor_moves(context, state: str) -> None:
    move(context, state)


@when('the editor decides "{state}" saying "{reason}"')
def editor_moves_saying(context, state: str, reason: str) -> None:
    move(context, state, reason=reason)


@when("the editor overrides the community declining without a reason")
def override_without_reason(context) -> None:
    move(context, "overridden_by_editor", result="declined")


@when('the editor overrides the community declining saying "{reason}"')
def override_declining(context, reason: str) -> None:
    move(context, "overridden_by_editor", reason=reason, result="declined")


@when('a second editor moves it to "{state}" from the old view')
def second_editor_stale(context, state: str) -> None:
    from reader_fixtures import reader_handler

    backend = backend_of(context)
    row = backend.store.get_proposal(context.proposal_id)
    # The second editor loaded the proposal while it was still a draft, so their move expects that state.
    row = {**row, "state": "draft"}
    plan = reader_handler.proposal_rules.transition_plan(row, state, "Not now.", actor_sub="staff-sub-2", now_iso="2026-10-22T00:00:00Z")
    assert not isinstance(plan, reader_handler.proposal_rules.Outcome), plan
    accepted = backend.store.change_proposal(context.proposal_id, plan, "draft", "2026-10-22T00:00:00Z")
    context.proposal_answer = {"status": "ok" if accepted else "refused", "error": None if accepted else "target_changed"}


@when("the snapshot publishes proposals")
def snapshot_publishes(context) -> None:
    publish(context)


@when("the snapshot runs without the publishing setting")
def snapshot_without_setting(context) -> None:
    run_with_setting(context, None)


@when("the snapshot runs with proposal publishing turned off")
def snapshot_setting_off(context) -> None:
    run_with_setting(context, False)


@when("the snapshot runs with proposal publishing turned on")
def snapshot_setting_on(context) -> None:
    run_with_setting(context, True)


@then("no public proposal file is written")
def nothing_public(context) -> None:
    keys = [entry.key for entry in context.proposal_site.list() if entry.key.startswith("_data/proposals/")]
    assert keys == [], keys


@then("the snapshot counted {count:d} stored proposal")
def counted_stored(context, count: int) -> None:
    assert context.proposal_report.proposals == count, context.proposal_report.proposals


@when("the snapshot publishes proposals again")
def snapshot_publishes_again(context) -> None:
    publish(context)


@when('the snapshot publishes proposals under the base path "{base_path}"')
def snapshot_publishes_under(context, base_path: str) -> None:
    publish(context, base_path)


@then('the editor is told "{error}"')
def editor_told(context, error: str) -> None:
    assert context.proposal_answer["error"] == error, context.proposal_answer


@then('the reader is told "{error}"')
def reader_told(context, error: str) -> None:
    editor_told(context, error)


@then("no proposal is stored")
def none_stored(context) -> None:
    assert backend_of(context).proposals() == []


@then("{count:d} proposals are stored as drafts")
def stored_as_drafts(context, count: int) -> None:
    rows = backend_of(context).proposals()
    assert len(rows) == count and {row["state"] for row in rows} == {"draft"}, rows


@then('the proposal is still in state "{state}"')
def still_in_state(context, state: str) -> None:
    assert backend_of(context).table("proposal").get_item(Key={"id": context.proposal_id})["Item"]["state"] == state


@then("the public proposal list holds {count:d} proposal")
def list_holds(context, count: int) -> None:
    assert len(public_file(context, "_data/proposals/index.json")["proposals"]) == count


@then('the first public proposal is in state "{state}" labelled "{label}"')
def first_state_label(context, state: str, label: str) -> None:
    entry = first_public(context)
    assert (entry["state"], entry["label"]) == (state, label), entry


@then("the first public proposal has {up:d} up, {down:d} down and {net:d} net votes")
def first_votes(context, up: int, down: int, net: int) -> None:
    assert first_public(context)["votes"] == {"up": up, "down": down, "net": net}


@then('the first public proposal shows the editor\'s decision "{result}" saying "{reason}"')
def first_decision(context, result: str, reason: str) -> None:
    decision = first_public(context)["decision"]
    assert (decision["result"], decision["reason"], decision["by"]) == (result, reason, "Editor"), decision


@then("the first public proposal still shows the community result from when review began")
def first_community(context) -> None:
    frozen = json.loads(backend_of(context).table("proposal").get_item(Key={"id": context.proposal_id})["Item"]["communityResult"])
    shown = first_public(context)["communityResult"]
    assert shown is not None and shown["at"] == frozen["at"], (shown, frozen)


@then('the proposal history reads "{states}"')
def history_reads(context, states: str) -> None:
    detail = public_file(context, f"_data/proposals/{context.proposal_id}.json")["proposal"]
    assert ", ".join(step["to"] for step in detail["history"]) == states, detail["history"]


@then("no public proposal file names the proposer or a staff member")
def no_names(context) -> None:
    text = "".join(entry.key + (context.proposal_site.get(entry.key) or b"").decode() for entry in context.proposal_site.list() if "proposals" in entry.key)
    for private in ("staff-sub-1", '"proposer"', '"actor"'):
        assert private not in text, private


@then("the proposal's public votes are {up:d} up, {down:d} down and {net:d} net")
def adapter_votes(context, up: int, down: int, net: int) -> None:
    from papyrus_content.reader_steering.proposals import VoteCounts

    assert VoteCounts.from_items_file(context.proposal_items).votes(context.proposal_id) == {"up": up, "down": down, "net": net}
    assert VoteCounts.from_items_file({"items": {}}).votes(context.proposal_id) == {"up": 0, "down": 0, "net": 0}


@then("the public proposal file holds the Markus body exactly as filed")
def markus_kept(context) -> None:
    assert public_file(context, f"_data/proposals/{context.proposal_id}.json")["proposal"]["body"] == context.proposal_markus


@then("the Markus body renders to the golden fragment")
def markus_golden(context) -> None:
    from papyrus_content.markus_renderer.convert import convert_text_in_process

    assert convert_text_in_process(context.proposal_markus) == (FIXTURES / "body.html").read_text(encoding="utf-8")


@then('the file "{key}" exists')
def file_exists(context, key: str) -> None:
    assert context.proposal_site.get(key) is not None


@then('"{key}" is a plugin runtime file')
def runtime_file(context, key: str) -> None:
    assert is_plugin_runtime_key(key)


@then('the second editor is told "{error}"')
def second_editor_told(context, error: str) -> None:
    editor_told(context, error)


# Operators: IAM callers of the function's own account (features_backend/proposals_operator.feature)

def operator_file(context, arguments: dict, **call) -> dict:
    answer = backend_of(context).operator_proposal_call("fileProposal", arguments, **call)
    context.proposal_answer = answer
    if answer["status"] == "ok":
        context.proposal_id = answer["id"]
    return answer


def operator_move(context, state: str, **extra) -> dict:
    answer = backend_of(context).operator_proposal_call("transitionProposal", {"proposalId": context.proposal_id, "state": state, **extra})
    context.proposal_answer = answer
    return answer


def stored(context) -> dict:
    return backend_of(context).table("proposal").get_item(Key={"id": context.proposal_id})["Item"]


@given("an operator role in the site's own account")
def operator_role(context) -> None:
    context.operator_arn = OPERATOR_ARN


@given('the operator filed a "{kind}" proposal')
def operator_filed(context, kind: str) -> None:
    assert operator_file(context, arguments_for(kind))["status"] == "ok"


@given('the operator moves it to "{state}"')
@when('the operator moves it to "{state}"')
def operator_moves(context, state: str) -> None:
    operator_move(context, state)


@when('the operator sends it to "{state}" because "{reason}"')
def operator_moves_saying(context, state: str, reason: str) -> None:
    operator_move(context, state, reason=reason)


@when('the operator files a "{kind}" proposal titled "{title}"')
def operator_files_titled(context, kind: str, title: str) -> None:
    operator_file(context, arguments_for(kind, title))


@when('the operator files a "{kind}" proposal naming a reader as the proposer')
def operator_files_as_reader(context, kind: str) -> None:
    operator_file(context, arguments_for(kind, proposer="reader-subject-1"))


@when('an identity-pool user tries to file a "{kind}" proposal')
def pooled_files(context, kind: str) -> None:
    identity = operator_identity(cognitoIdentityId="eu-west-1:1111", cognitoIdentityPoolId="eu-west-1_pool", cognitoIdentityAuthType="authenticated")
    operator_file(context, arguments_for(kind), identity=identity)


@when('a principal of another account tries to file a "{kind}" proposal')
def foreign_files(context, kind: str) -> None:
    identity = operator_identity(accountId="999999999999", userArn="arn:aws:sts::999999999999:assumed-role/ideas-pipeline/run-1")
    operator_file(context, arguments_for(kind), identity=identity)


@then('the operator is told "{error}"')
def operator_told(context, error: str) -> None:
    answer = context.proposal_answer
    assert (answer["status"] if error == "ok" else answer["error"]) == error, answer


@then('the stored proposal is a draft proposed by "{proposer}"')
def stored_draft(context, proposer: str) -> None:
    row = stored(context)
    assert (row["state"], row["proposer"]) == ("draft", proposer), row


@then("the stored history records the filing by the operator's principal")
def history_filing(context) -> None:
    first = json.loads(stored(context)["history"])[0]
    assert first["actor"] == f"operator:{context.operator_arn}" and first["by"] == "ai", first


@then("the stored history records the move by the operator's principal")
def history_move(context) -> None:
    last = json.loads(stored(context)["history"])[-1]
    assert last["actor"] == f"operator:{context.operator_arn}" and last["by"] == "operator", last


@then("no public proposal file names the operator")
def no_operator_named(context) -> None:
    text = "".join(entry.key + (context.proposal_site.get(entry.key) or b"").decode() for entry in context.proposal_site.list() if "proposals" in entry.key)
    assert text, "no proposal files were written"
    for private in ("operator", OPERATOR_ACCOUNT, "ideas-pipeline"):
        assert private not in text, private
