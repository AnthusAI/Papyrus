"""Steps for features_backend/proposals_editor.feature: the editor tier of proposals."""

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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from proposals_steps import arguments_for, backend_of, close_backend, file_proposal, first_public, move, stored  # noqa: E402
from reader_fixtures import ReaderBackend, run_snapshot, subject_for  # noqa: E402
from papyrus_content.projection.writers import LocalDirectoryWriter  # noqa: E402

TYPES = ("item", "proposal")
ACTIONS = {
    "pin the proposal": ("pin", {}),
    "hold the proposal": ("hold", {}),
    "exclude votes from new accounts": ("exclude_votes", {"rule": "new-accounts-24h"}),
}


def edit(context, action: str, **extra) -> dict:
    answer = backend_of(context).proposal_call("editProposal", {"proposalId": context.proposal_id, "action": action, **extra})
    context.proposal_answer = answer
    return answer


def voters(context, prefix: str, count: int, value: int, *, seasoned: bool) -> None:
    """``count`` readers sign up and vote on the proposal; seasoned readers have accounts three days old by the time they vote."""
    backend = backend_of(context)
    for index in range(count):
        assert backend.call(subject_for(f"{prefix}{index}"), "handle", {"handle": f"{prefix}-{index}"})["statusCode"] == 200
    if seasoned:
        backend.age_everyone()
        context.seasoned_prefix = prefix
    for index in range(count):
        answer = backend.call(subject_for(f"{prefix}{index}"), "vote", {"subject": {"type": "proposal", "id": context.proposal_id}, "value": value})
        assert answer["statusCode"] == 200, answer


def next_prefix(context, kind: str) -> str:
    context.voter_batches = getattr(context, "voter_batches", 0) + 1
    return f"{kind}{context.voter_batches}x"


def reader_id(context, index: int) -> str:
    profile = backend_of(context).table("profile").get_item(Key={"id": subject_for(f"{context.seasoned_prefix}{index}")})["Item"]
    return profile["readerId"]


@given("a publication with proposals that take votes")
def publication_with_votes(context) -> None:
    close_backend(context)
    context.proposal_backend = ReaderBackend(subject_types=TYPES)
    context.proposal_backend.__enter__()
    context.add_cleanup(close_backend, context)
    context.proposal_directory = tempfile.TemporaryDirectory()
    context.add_cleanup(context.proposal_directory.cleanup)
    context.proposal_site = None
    context.proposal_id = None
    context.proposal_answer = None
    context.proposal_view = None
    context.proposal_editor_groups = ("editor",)


@given("a proposal in steering")
def proposal_in_steering(context) -> None:
    assert file_proposal(context, arguments_for("story_draft"))["status"] == "ok"
    assert move(context, "in_steering")["status"] == "ok"


@given("the proposal is in editor review")
def proposal_in_review(context) -> None:
    assert move(context, "editor_review")["status"] == "ok"


@given("{count:d} seasoned readers vote up")
def seasoned_up(context, count: int) -> None:
    voters(context, next_prefix(context, "old"), count, 1, seasoned=True)


@given("{up:d} seasoned reader votes up and {down:d} vote down")
def seasoned_split(context, up: int, down: int) -> None:
    prefix = next_prefix(context, "old")
    backend = backend_of(context)
    for index in range(up + down):
        assert backend.call(subject_for(f"{prefix}{index}"), "handle", {"handle": f"{prefix}-{index}"})["statusCode"] == 200
    backend.age_everyone()
    context.seasoned_prefix = prefix
    for index in range(up + down):
        value = 1 if index < up else -1
        assert backend.call(subject_for(f"{prefix}{index}"), "vote", {"subject": {"type": "proposal", "id": context.proposal_id}, "value": value})["statusCode"] == 200


@given("{count:d} brand-new accounts vote down")
def new_down(context, count: int) -> None:
    voters(context, next_prefix(context, "new"), count, -1, seasoned=False)


@given("{count:d} brand-new accounts vote up")
def new_up(context, count: int) -> None:
    voters(context, next_prefix(context, "new"), count, 1, seasoned=False)


@given("the editor pins it")
@when("the editor pins it")
def editor_pins(context) -> None:
    assert edit(context, "pin")["status"] == "ok"


@when("the editor unpins it")
def editor_unpins(context) -> None:
    assert edit(context, "unpin")["status"] == "ok"


@when("the editor puts it on hold")
def editor_holds(context) -> None:
    assert edit(context, "hold")["status"] == "ok"


@when("the editor releases it")
def editor_releases(context) -> None:
    assert edit(context, "release")["status"] == "ok"


@given("the editor excluded votes from accounts under 24 hours old")
@when("the editor excludes votes from accounts under 24 hours old")
def editor_excludes(context) -> None:
    answer = edit(context, "exclude_votes", rule="new-accounts-24h")
    assert answer["status"] == "ok", answer
    context.exclusion_id = answer["id"]


@when("the editor undoes that exclusion")
def editor_undoes(context) -> None:
    answer = edit(context, "undo_exclusion", exclusionId=context.exclusion_id)
    assert answer["status"] == "ok", answer


@when('the editor asks to exclude votes by the rule "{rule}"')
def editor_asks_rule(context, rule: str) -> None:
    edit(context, "exclude_votes", rule=rule)


@when("the editor limits seasoned reader {index:d}")
def editor_limits(context, index: int) -> None:
    assert backend_of(context).staff_call("limit", "reader", reader_id(context, index))["status"] == "ok"


@when("the editor bans seasoned reader {index:d} as spam")
def editor_bans(context, index: int) -> None:
    assert backend_of(context).staff_call("ban", "reader", reader_id(context, index), reason="Spam.")["status"] == "ok"


@when("a reader tries to {action}")
def reader_tries(context, action: str) -> None:
    name, extra = ACTIONS[action]
    context.proposal_answer = backend_of(context).proposal_call("editProposal", {"proposalId": context.proposal_id, "action": name, **extra}, groups=("reader",))


@when("an anonymous caller tries to pin the proposal")
def anonymous_tries(context) -> None:
    context.proposal_answer = backend_of(context).appsync("editProposal", {"proposalId": context.proposal_id, "action": "pin"}, {})


@when("the operator tries to {action}")
def operator_tries(context, action: str) -> None:
    name, extra = ACTIONS[action]
    context.proposal_answer = backend_of(context).operator_proposal_call("editProposal", {"proposalId": context.proposal_id, "action": name, **extra})


@when("the snapshot publishes proposals with votes")
def publish_with_votes(context) -> None:
    backend = backend_of(context)
    context.proposal_site = context.proposal_site or LocalDirectoryWriter(Path(context.proposal_directory.name))
    backend.now += 120
    run_snapshot(backend, context.proposal_site, subject_types=TYPES)


@then("the editor's request is accepted")
def request_accepted(context) -> None:
    assert context.proposal_answer["status"] == "ok", context.proposal_answer


@then('the caller is told "{error}"')
def caller_told(context, error: str) -> None:
    assert context.proposal_answer["error"] == error, context.proposal_answer


@then("the proposal is not pinned or on hold")
def not_pinned_or_held(context) -> None:
    row = stored(context)
    assert not row.get("pinned") and not row.get("held") and "editorLog" not in row, row


@then("the first public proposal is pinned")
def is_pinned(context) -> None:
    assert first_public(context)["pinned"] is True


@then("the first public proposal is not pinned")
def is_not_pinned(context) -> None:
    assert first_public(context)["pinned"] is False


@then('the first public proposal shows the override "{result}" saying "{reason}"')
def shows_override(context, result: str, reason: str) -> None:
    override = first_public(context)["override"]
    assert (override["result"], override["reason"], override["by"]) == (result, reason, "Editor"), override


@then("the first public proposal still shows {up:d} up votes in its community result")
def community_up(context, up: int) -> None:
    assert first_public(context)["communityResult"]["up"] == up, first_public(context)["communityResult"]


@then("the first public proposal still shows {down:d} down votes in its community result")
def community_down(context, down: int) -> None:
    assert first_public(context)["communityResult"]["down"] == down, first_public(context)["communityResult"]


@then("the first public proposal has {up:d} up and {down:d} down votes")
def public_votes(context, up: int, down: int) -> None:
    votes = first_public(context)["votes"]
    assert (votes["up"], votes["down"]) == (up, down), votes


@then('the first public proposal says "{note}"')
def public_note(context, note: str) -> None:
    assert first_public(context)["excluded"]["note"] == note, first_public(context)["excluded"]


@then("the first public proposal has no exclusion note")
def no_note(context) -> None:
    assert first_public(context)["excluded"] == {"votes": 0, "rules": [], "note": None}, first_public(context)["excluded"]


def reasons(context) -> list[dict]:
    row = stored(context)
    return json.loads(row["needsLook"])["reasons"] if row.get("needsLook") else []


@then('the proposal needs a look because of "{code}"')
def needs_look(context, code: str) -> None:
    assert [reason["code"] for reason in reasons(context)] == [code], reasons(context)


@then("the proposal does not need a look")
def does_not_need_look(context) -> None:
    assert reasons(context) == [], reasons(context)


@then("no public proposal file holds needs-a-look reasons, the editor log or an editor's id")
def nothing_editor_only(context) -> None:
    text = "".join(entry.key + (context.proposal_site.get(entry.key) or b"").decode() for entry in context.proposal_site.list())
    assert "proposals" in text
    for private in ("needsLook", "vote_spike", "reasons", "editorLog", "staff-sub-1", '"actor"'):
        assert private not in text, private
