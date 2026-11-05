"""An agent on the signed-in CLI relays an editor's decisions under a delegation (features_backend/cli-delegated-curation-signed-in.feature).

The CLI half runs the real commands against a stand-in HTTPS connection, so the headers they would send can be read. The Newsroom half
runs the real category-action Lambda in `scripts/test-curation-delegation-signed-in.ts`, one named behaviour per scenario step. No network,
login or AWS.
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import references_commands  # noqa: E402
from papyrus_content.delegated_stars_test import FakeConnection  # noqa: E402
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient  # noqa: E402

SESSION_TOKEN = "id-token-of-the-session"
RELAY = ["--reference", "reference-1", "--on-behalf-of", "editor@example.org", "--agent", "Claude", "--instruction", "Accept it, four stars."]


# ---- the Newsroom's side: the real Lambda, one behaviour at a time -------------------------------------------------------------

def run_behaviour(context, behaviour: str) -> None:
    done = subprocess.run(["node", "--import", "tsx", "scripts/test-curation-delegation-signed-in.ts", behaviour],
                          cwd=REPO_ROOT, capture_output=True, text=True, timeout=240)
    context.behaviours = getattr(context, "behaviours", {})
    context.behaviours[behaviour] = done
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"ok {behaviour}" in done.stdout, done.stdout


def holds(context, behaviour: str) -> None:
    """The named behaviour of the Lambda test holds. A Then that follows a CLI-side When has not run it yet, so it runs here."""
    if behaviour not in getattr(context, "behaviours", {}):
        run_behaviour(context, behaviour)
    assert context.behaviours[behaviour].returncode == 0


def newsroom_step(text: str, behaviour: str, kind):
    """One step whose whole meaning is that a named behaviour of the Lambda test holds."""
    def run(context):
        if kind is when:
            run_behaviour(context, behaviour)
        else:
            holds(context, behaviour)
    run.__name__ = "step_" + "".join(character if character.isalnum() else "_" for character in text)[:80]
    return kind(text)(run)


@given("a site that signs its CLI in on its own client")
def _separated(context):
    context.site_separates_cli = True


@given("a site that signs its CLI in on the same client as the Newsroom")
def _unseparated(context):
    context.site_separates_cli = False


@given("the agent asked for a delegation from a signed-in session")
def _asked_signed_in(context):
    context.asked = True


@given("the agent asked for a delegation and the editor approved its code in the Newsroom")
def _asked_and_approved(context):
    context.asked = context.approved = True


# Each scenario's When names the behaviour that exercises it; its Then steps assert the same run held.
newsroom_step("the agent asks for a delegation from a signed-in session", "the_cli_session_asks_a_person_approves_and_the_agent_relays", when)
newsroom_step("the request waits for a person's approval", "the_cli_session_asks_a_person_approves_and_the_agent_relays", then)
newsroom_step("a decision relayed under it is refused as not approved by a person", "the_cli_session_asks_a_person_approves_and_the_agent_relays", then)

@then("the Reference keeps its vote and rating")
def _unchanged(context):
    """Every behaviour that ran asserts, itself, that the Reference kept its vote and rating when a decision was refused."""
    ran = getattr(context, "behaviours", {})
    assert ran and all(done.returncode == 0 for done in ran.values())


newsroom_step("the same editor's CLI session tries to approve the code, create a delegation or list the pending codes", "a_cli_session_cannot_approve_its_own_request", when)
newsroom_step("each attempt is refused because approval belongs to the Newsroom", "a_cli_session_cannot_approve_its_own_request", then)
newsroom_step("the request is still waiting", "a_cli_session_cannot_approve_its_own_request", then)
newsroom_step("the editor's approval in the Newsroom is accepted", "a_cli_session_cannot_approve_its_own_request", then)

newsroom_step("a signed-in session asks for a delegation or relays a decision", "a_backend_that_did_not_separate_the_cli_refuses_signed_in_requests", when)
newsroom_step("it is refused with the setting the site needs", "a_backend_that_did_not_separate_the_cli_refuses_signed_in_requests", then)
newsroom_step("no delegation is stored", "a_backend_that_did_not_separate_the_cli_refuses_signed_in_requests", then)
newsroom_step("an operator on AWS credentials can still ask and the Newsroom still approves", "a_backend_that_did_not_separate_the_cli_refuses_signed_in_requests", then)

newsroom_step("a reader, or a person in no group, asks for a delegation, approves a code or relays a decision", "only_editors_and_administrators_may_ask_approve_or_relay", when)
newsroom_step("each is refused as not an editor or administrator", "only_editors_and_administrators_may_ask_approve_or_relay", then)

newsroom_step("the agent asks for no hours, a negative number of hours or more than seventy-two hours", "the_hours_limit_and_the_expiry_hold", when)
newsroom_step("the request is refused and no delegation is stored", "the_hours_limit_and_the_expiry_hold", then)
newsroom_step("an approved delegation lasts exactly the hours asked for", "the_hours_limit_and_the_expiry_hold", then)
newsroom_step("a relayed decision after it expires is refused", "the_hours_limit_and_the_expiry_hold", then)

newsroom_step("the editor revokes an approved delegation after the agent relayed a decision", "deny_and_revoke_work_from_the_session_that_asked", when)
newsroom_step("nothing more is recorded under it", "deny_and_revoke_work_from_the_session_that_asked", then)
newsroom_step("the agent's own session can deny or withdraw a pending request", "deny_and_revoke_work_from_the_session_that_asked", then)
newsroom_step("an editor who did not grant a delegation cannot revoke it", "deny_and_revoke_work_from_the_session_that_asked", then)

newsroom_step("another agent name, another person's name, a guessed secret or another site's backend is used with it", "a_token_works_only_for_its_own_agent_person_and_site", when)
newsroom_step("each is refused and nothing is recorded", "a_token_works_only_for_its_own_agent_person_and_site", then)

newsroom_step("the agent relays an accept and a four star rating", "relayed_decisions_name_the_agent_and_the_delegation", when)
newsroom_step("the vote records the delegation, the agent and the editor's words", "relayed_decisions_name_the_agent_and_the_delegation", then)
newsroom_step("the rating is filed as the editor's rating relayed by the agent under that delegation", "relayed_decisions_name_the_agent_and_the_delegation", then)
newsroom_step("the audit record keeps the agent's name, the approver and the editor whose session asked", "relayed_decisions_name_the_agent_and_the_delegation", then)

newsroom_step("a CLI session votes without a delegation and a Newsroom session votes", "a_direct_vote_from_a_cli_session_is_the_agents_and_not_a_person_label", when)
newsroom_step("the first is recorded as an agent's vote and the second as a person's", "a_direct_vote_from_a_cli_session_is_the_agents_and_not_a_person_label", then)

newsroom_step("the agent relays ratings from zero to six, a half star, a four, a five and a clear", "stars_follow_the_set_reference_stars_rules", when)
newsroom_step("ratings outside one to five are refused and write nothing", "stars_follow_the_set_reference_stars_rules", then)
newsroom_step("the newest rating wins and a clear removes who and when", "stars_follow_the_set_reference_stars_rules", then)
newsroom_step("a rating never changes the accept or reject", "stars_follow_the_set_reference_stars_rules", then)

newsroom_step("the deployed authorization of the delegation routes is read", "the_declared_authorization_has_no_broad_signed_in_rule", when)
newsroom_step("the agent routes allow the operator lane and the editor and admin groups", "the_declared_authorization_has_no_broad_signed_in_rule", then)
newsroom_step("the person routes allow the editor and admin groups only", "the_declared_authorization_has_no_broad_signed_in_rule", then)

newsroom_step("the Newsroom records the agent's request, the editor's approval and the relayed decisions", "the_cli_session_asks_a_person_approves_and_the_agent_relays", then)


# ---- the CLI's side: the real commands, and the headers they would send ----------------------------------------------------------

@given("the CLI is signed in to a site and has no AWS credentials")
def _signed_in(context):
    context.requests = []

    def answer(body):
        query, variables = body["query"], body["variables"]
        if "requestCurationDelegation" in query:
            return {"requestCurationDelegation": {"ok": True, "delegationId": variables["delegationId"], "userCode": "ABCD-2345",
                                                  "pendingExpiresAt": "2026-11-04T12:10:00.000Z", "requestedHours": variables["hours"]}}
        if "recordDelegatedStars" in query:
            return {"recordDelegatedStars": {"ok": True, "referenceId": variables["referenceId"], "stars": variables["stars"], "status": "accepted"}}
        return {"recordDelegatedCuration": {"ok": True, "referenceId": variables["referenceId"], "status": "accepted"}}

    client = PapyrusGraphQLAuthoringClient(
        endpoint="https://api.example.test/graphql", tenant_id=None, site_tenant=False,
        header_factory=lambda body: {"content-type": "application/json", "Authorization": SESSION_TOKEN})
    client._connection = FakeConnection(answer, context.requests)
    context.cli_client = client
    context.printed = io.StringIO()
    original = references_commands.create_authoring_client
    references_commands.create_authoring_client = lambda: (client, None)
    context.add_cleanup(lambda: setattr(references_commands, "create_authoring_client", original))
    import tempfile
    directory = tempfile.TemporaryDirectory()
    context.add_cleanup(directory.cleanup)
    context.token_file = Path(directory.name) / "delegation.token"


def _run(context, action):
    with contextlib.redirect_stdout(context.printed):
        action()


@when('the agent asks for a two hour delegation as "Claude"')
def _ask(context):
    _run(context, lambda: references_commands.references_request_delegation(
        ["--agent", "Claude", "--hours", "2", "--token-file", str(context.token_file)], graphql=context.cli_client.graphql))


@then("the request goes with the session's token and no AWS signature")
def _session_token(context):
    (request,) = context.requests
    assert request["headers"]["Authorization"] == SESSION_TOKEN
    assert not any(key.lower().startswith("x-amz") for key in request["headers"])
    assert "requestCurationDelegation" in request["body"]["query"] and request["body"]["variables"]["hours"] == 2


@then("the agent is given an approval code and a private file holds the secret")
def _code_and_file(context):
    output = context.printed.getvalue()
    token = context.token_file.read_text(encoding="utf-8")
    assert "ABCD-2345" in output and token.startswith("curation-delegation-")
    assert token.partition("~")[2] not in output, "the secret half is never printed"
    assert (context.token_file.stat().st_mode & 0o777) == 0o600


@then("the agent is told that only a person in the Newsroom can approve it")
def _told(context):
    assert "Only a person in the Newsroom can approve it" in context.printed.getvalue()


@then("the CLI has no command that approves a delegation")
def _no_approval_command(context):
    from papyrus_content.cli import PORTED_COMMANDS

    assert not [route for route in PORTED_COMMANDS if "delegation" in route and route != "references:request-delegation"]
    sources = [path for path in (REPO_ROOT / "src").rglob("*.py") if "approveCurationDelegation" in path.read_text(encoding="utf-8")
               and not path.name.endswith("_test.py")]
    assert sources == [], sources


@given("the agent holds a delegation file that the editor approved")
def _holds_file(context):
    context.token_file.write_text("curation-delegation-1~agent-held-secret\n", encoding="utf-8")


@when("the agent relays an approve, a reject and a four star rating for the editor")
def _relay(context):
    arguments = [*RELAY, "--delegation-file", str(context.token_file)]
    _run(context, lambda: references_commands.references_record_on_behalf_of(arguments, action="approve"))
    _run(context, lambda: references_commands.references_record_on_behalf_of([*arguments, "--reason-code", "duplicate"], action="reject"))
    _run(context, lambda: references_commands.references_set_stars_on_behalf_of([*arguments, "--stars", "4"]))


@then("the three decisions are sent with the delegation file's secret and the session's token")
def _three(context):
    assert len(context.requests) == 3
    for request in context.requests:
        assert request["headers"]["Authorization"] == SESSION_TOKEN
        assert request["body"]["variables"]["delegationToken"] == "curation-delegation-1~agent-held-secret"
        assert request["body"]["variables"]["agentLabel"] == "Claude"
    assert "recordDelegatedStars" in context.requests[2]["body"]["query"] and context.requests[2]["body"]["variables"]["stars"] == 4
    assert "agent-held-secret" not in context.printed.getvalue()


@then("the approve is recorded as an accept")
def _accept(context):
    assert [request["body"]["variables"]["action"] for request in context.requests[:2]] == ["accept", "reject"]


@when("the agent runs set-stars with a rating outside one to five, with a dry run, and with help")
def _set_stars_refusals(context):
    context.refused = []
    arguments = [*RELAY, "--delegation-token", "curation-delegation-1~agent-held-secret"]
    for stars in ("0", "6", "2.5", "many"):
        try:
            _run(context, lambda: references_commands.references_set_stars_on_behalf_of([*arguments, "--stars", stars]))
        except ValueError as error:
            context.refused.append(str(error))
    _run(context, lambda: references_commands.references_set_stars_on_behalf_of([*arguments, "--stars", "4", "--dry-run"]))
    _run(context, lambda: references_commands.references_set_stars_on_behalf_of(["--help"]))


@then("no request is sent for any of them")
def _nothing_sent(context):
    assert context.requests == []
    assert len(context.refused) == 4 and all("1 to 5" in message for message in context.refused)
    assert "dry-run: nothing sent" in context.printed.getvalue()
    json.dumps(context.refused)
