from __future__ import annotations

import json
import logging
import sys
import threading
import urllib.parse
from pathlib import Path

import boto3
from behave import given, then, step
from moto import mock_aws

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", Path(__file__).resolve().parent):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.announcements.actions import handle  # noqa: E402
from papyrus_content.announcements.settings import AnnouncementSettings  # noqa: E402
from papyrus_content.announcements.stores import DynamoConnection, DynamoSettings, SsmParameters  # noqa: E402
from papyrus_content.announcements.x_account import AnnouncementError, XAccounts, XEndpoints  # noqa: E402
from x_fake_server import FakeX  # noqa: E402

REDIRECT = "https://mom.example/newsroom/settings/announcements/x/callback"
SECRET = "s3cret-value"


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


class LogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


def world(context):
    return context


@given('a site "{site}" with a fake X and encrypted parameter storage')
def build_world(context, site):
    context.mock = mock_aws()
    context.mock.start()
    context.site = site
    context.clock = Clock()
    context.x = FakeX()
    context.logs = LogCapture()
    logging.getLogger().addHandler(context.logs)
    logging.getLogger().setLevel(logging.INFO)
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    for name in ("settings", "connection"):
        ddb.create_table(TableName=name, KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
                         AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
    context.ssm = boto3.client("ssm", region_name="us-east-1")
    context.settings = AnnouncementSettings(DynamoSettings(ddb.Table("settings"), context.clock), context.clock)
    context.accounts = XAccounts(
        site_id=site,
        endpoints=XEndpoints(authorize_url="https://x.example/i/oauth2/authorize", token_url=f"{context.x.base}/2/oauth2/token",
                             revoke_url=f"{context.x.base}/2/oauth2/revoke", api_base=context.x.base),
        parameters=SsmParameters(context.ssm), connection=DynamoConnection(ddb.Table("connection"), context.clock),
        pauses=context.settings, lease_seconds=30, clock=context.clock,
    )
    context.answers = []
    context.groups = {}
    context.answer = None
    context.add_cleanup(lambda: (context.x.stop(), logging.getLogger().removeHandler(context.logs), context.mock.stop()))


@given('an admin named "{admin}" and an editor named "{editor}"')
def people(context, admin, editor):
    context.groups = {admin: ["admin"], editor: ["editor"]}


def call(context, who, operation, **payload):
    answer = handle(operation, payload, context.groups[who], who, context.accounts, context.settings)
    context.answers.append(json.dumps(answer))
    context.answer = answer
    return answer


def connect(context, who="ryan", handle_name="mom_test"):
    context.x.handle = handle_name
    begun = call(context, who, "announcementsXBegin", redirectUri=REDIRECT)
    assert begun["ok"], begun
    context.begun = begun
    code = context.x.approve(begun["authorizeUrl"])
    return call(context, who, "announcementsXComplete", code=code, state=begun["state"], redirectUri=REDIRECT)


@step('ryan saves the X app\'s client id "{client_id}" and client secret "{secret}"')
def save_app(context, client_id, secret):
    call(context, "ryan", "announcementsXSaveApp", clientId=client_id, clientSecret=secret)


@step('ellie tries to save the X app\'s client id "{client_id}" and client secret "{secret}"')
def editor_save_app(context, client_id, secret):
    call(context, "ellie", "announcementsXSaveApp", clientId=client_id, clientSecret=secret)


@step("ryan saved the X app's keys")
def saved_keys(context):
    call(context, "ryan", "announcementsXSaveApp", clientId="client-123", clientSecret=SECRET)
    assert context.answer["ok"], context.answer


@step('ryan connected the X account "{handle_name}"')
def connected(context, handle_name):
    saved_keys(context)
    answer = connect(context, handle_name=handle_name)
    assert answer["ok"], answer


@step('the answer shows the client id "{client_id}" and says the secret is saved')
def shows_client(context, client_id):
    status = context.answer["status"]
    assert status["clientId"] == client_id and status["secretSaved"] is True, status


@step('no answer to any request contains "{text}"')
def never_shown(context, text):
    everything = "\n".join(context.answers + context.logs.lines)
    assert text not in everything, f"{text!r} appeared in an answer or a log"


@step('the secret is stored encrypted at "{name}"')
def stored_encrypted(context, name):
    meta = context.ssm.describe_parameters(ParameterFilters=[{"Key": "Name", "Values": [name]}])["Parameters"]
    assert meta and meta[0]["Type"] == "SecureString", meta
    assert context.ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"] == SECRET


@step('the refresh token is stored encrypted at "{name}"')
def refresh_encrypted(context, name):
    meta = context.ssm.describe_parameters(ParameterFilters=[{"Key": "Name", "Values": [name]}])["Parameters"]
    assert meta and meta[0]["Type"] == "SecureString", meta


@step('the announcement request is refused with "{message}"')
def refused(context, message):
    assert context.answer["ok"] is False and context.answer["message"] == message, context.answer


@step("ellie can read the connection status")
def editor_reads(context):
    call(context, "ellie", "announcementsXStatus")
    assert context.answer["ok"], context.answer


@step('ryan chooses Connect X account and approves at X as "{handle_name}"')
def choose_connect(context, handle_name):
    answer = connect(context, handle_name=handle_name)
    assert answer["ok"], answer


@step('the page shows "Connected: @{handle_name}"')
def shows_connected(context, handle_name):
    status = context.answer["status"]
    assert status["connection"] == "connected" and status["handle"] == handle_name, status


@step('the permissions asked for were "{scopes}"')
def asked_scopes(context, scopes):
    query = urllib.parse.parse_qs(urllib.parse.urlparse(context.begun["authorizeUrl"]).query)
    assert query["scope"][0] == scopes, query["scope"]
    assert "media.write" not in scopes


@step("the sign-in used a PKCE challenge and the app's secret in the Authorization header")
def pkce(context):
    token_calls = [r for r in context.x.requests if r["path"] == "/2/oauth2/token"]
    assert token_calls and token_calls[0]["authorization"].startswith("Basic "), token_calls
    assert token_calls[0]["form"]["code_verifier"], token_calls  # the fake X checked it against the S256 challenge


@step("someone returns from X with a state this site never issued")
def forged_state(context):
    call(context, "ryan", "announcementsXComplete", code="code-x", state="nonce.forged", redirectUri=REDIRECT)


@step("no account is connected")
def none_connected(context):
    call(context, "ryan", "announcementsXStatus")
    assert context.answer["status"]["connection"] == "not_connected", context.answer


@step("more than two hours pass")
def two_hours(context):
    context.clock.now += 7201


@step("an announcement needs to post")
def needs_to_post(context):
    try:
        context.token = context.accounts.access_token()
        context.post_error = None
    except AnnouncementError as error:
        context.token, context.post_error = None, error


@step("a new access token is obtained from X")
def new_access(context):
    assert context.token == "access-2", context.token


@step("the stored refresh token is the newest one X issued")
def newest_refresh(context):
    stored = context.ssm.get_parameter(Name=f"/papyrus/{context.site}/announcements/x/1001/refresh-token", WithDecryption=True)["Parameter"]["Value"]
    assert stored == f"refresh-{context.x.issued}", stored


@step("the status shows a last refresh time")
def last_refresh(context):
    assert context.accounts.status()["lastRefreshAt"].startswith("2027"), context.accounts.status()


@step("X takes a moment to answer a refresh")
def slow_refresh(context):
    context.x.refresh_delay = 0.6


@step("two announcements need to post at the same moment")
def two_posts(context):
    results = []
    threads = [threading.Thread(target=lambda: results.append(context.accounts.access_token())) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    context.tokens = results


@step("X was asked to refresh once")
def refreshed_once(context):
    refreshes = [r for r in context.x.requests if r["path"] == "/2/oauth2/token" and r["form"]["grant_type"] == "refresh_token"]
    assert len(refreshes) == 1, len(refreshes)


@step("both posts use the same access token")
def same_token(context):
    assert len(context.tokens) == 2 and context.tokens[0] == context.tokens[1], context.tokens


@step("X refuses to refresh the token")
def refuses(context):
    context.x.refuse_refresh = True


@step('the connection shows "Needs reconnecting"')
def needs_reconnecting(context):
    assert context.accounts.status()["connection"] == "needs_reconnecting"
    assert context.accounts.status()["refreshHealth"]["healthy"] is False


@step('announcements are paused with the reason "{reason}"')
def paused_reason(context, reason):
    pause = context.settings.read()["pause"]
    assert pause["paused"] and pause["reason"] == reason, pause


@step('posting is refused with "{text}"')
def posting_refused(context, text):
    assert context.post_error is not None and text in context.post_error.message, context.post_error


@step("ryan chooses Disconnect")
def disconnect(context):
    call(context, "ryan", "announcementsXDisconnect")
    assert context.answer["ok"], context.answer


@step("X was asked to revoke the refresh token")
def revoked(context):
    calls = [r for r in context.x.requests if r["path"] == "/2/oauth2/revoke"]
    assert len(calls) == 1 and calls[0]["form"]["token"] == "refresh-1", calls


@step("the encrypted parameters of the account are gone")
def params_gone(context):
    names = [p["Name"] for p in context.ssm.describe_parameters()["Parameters"]]
    assert not [n for n in names if "/1001/" in n], names


@step("the page shows no connected account")
def no_account(context):
    status = context.answer["status"]
    assert status["connection"] == "not_connected" and not status["handle"], status


@step("announcements are not paused")
def not_paused(context):
    assert context.settings.read()["pause"]["paused"] is False


@step("ellie reads X's usage")
def read_usage(context):
    call(context, "ellie", "announcementsXUsage")
    assert context.answer["ok"], context.answer


@step("the usage shows {posts:d} posts counted and a cap of {cap:d}")
def usage_shown(context, posts, cap):
    usage = context.answer["usage"]
    assert usage["postsThisCycle"] == str(posts) and usage["postCap"] == str(cap), usage


# --- settings ----------------------------------------------------------------------------------------------

def propose(context, who, **changes):
    current = call(context, who, "announcementsSettings")["settings"] if context.groups[who] else {}
    proposed = {**current, **changes}
    call(context, who, "announcementsSaveSettings", settings=proposed)


def rules(context, **changes):
    return {**context.settings.read()["rules"], **changes}


@step("ellie reads the announcement settings")
def read_settings(context):
    call(context, "ellie", "announcementsSettings")


@step('the mode is "{mode}"')
def mode_is(context, mode):
    settings = context.answer.get("settings") or context.settings.read()
    assert settings["mode"] == mode, settings


@step("the minimum rating is {stars:d} stars")
def stars_is(context, stars):
    settings = context.answer.get("settings") or context.settings.read()
    assert settings["rules"]["minStars"] == stars, settings


@step("the budget is not set")
def budget_unset(context):
    assert context.answer["settings"]["budget"] is None


@step("the budget is {amount:d}")
def budget_is(context, amount):
    assert context.settings.read()["budget"] == amount


@step("ryan saves the announcement settings with a minimum of {stars:d} stars")
def save_stars(context, stars):
    propose(context, "ryan", rules=rules(context, minStars=stars))


@step('ryan saves the announcement settings with the mode "{mode}"')
def save_mode(context, mode):
    propose(context, "ryan", mode=mode)


@step('ellie tries to save the announcement settings with the mode "{mode}"')
def editor_save_mode(context, mode):
    propose(context, "ellie", mode=mode)


@step('ryan confirms the Automated label and saves the mode "{mode}"')
def label_then_mode(context, mode):
    propose(context, "ryan", mode=mode, labelConfirmed=True)


@step('ryan confirms the Automated label, sets the budget to {amount:d} and saves the mode "{mode}"')
def label_budget_mode(context, amount, mode):
    propose(context, "ryan", mode=mode, labelConfirmed=True, budget=amount)


@step('ryan saves the announcement settings with the story types "{types}"')
def save_types(context, types):
    propose(context, "ryan", rules=rules(context, storyTypes=types.split(",")))


@step('ryan saves the announcement settings with a minimum of {stars:d} stars in the sections "{sections}"')
def save_sections(context, stars, sections):
    propose(context, "ryan", rules=rules(context, minStars=stars, sections=sections.split(",")))


@step('the sections are "{sections}"')
def sections_are(context, sections):
    assert context.settings.read()["rules"]["sections"] == sections.split(",")


@step('ryan saves the price of a post with a link as {price:f} as of "{date}"')
def save_price(context, price, date):
    prices = {**context.settings.read()["prices"], "createPostWithUrl": price, "asOf": date}
    propose(context, "ryan", prices=prices)


@step('the price of a post with a link is {price:f} as of "{date}"')
def price_is(context, price, date):
    prices = context.settings.read()["prices"]
    assert prices["createPostWithUrl"] == price and prices["asOf"] == date, prices


@step("ryan pauses announcements")
def pause(context):
    call(context, "ryan", "announcementsPause", paused=True)


@step("ryan resumes announcements")
def resume(context):
    call(context, "ryan", "announcementsPause", paused=False)


@step('the pause names "{who}"')
def pause_names(context, who):
    assert context.settings.read()["pause"]["by"] == who
