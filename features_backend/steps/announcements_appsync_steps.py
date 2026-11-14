"""features_backend/announcements-appsync-requests.feature: the deployed handler, driven with the requests Amplify sends."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus_content.appsync_event import amplify_function_event, user_pool_identity  # noqa: E402

HANDLER = REPO_ROOT / "amplify" / "functions" / "announcements" / "handler.py"
REDIRECT = "https://mom.example/newsroom/settings/announcements/x/callback"


def load_handler(environment: dict[str, str]):
    """Import the function's handler.py as Lambda does, with the environment the stack sets."""
    saved = {name: os.environ.get(name) for name in environment}
    os.environ.update(environment)

    def restore() -> None:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    spec = importlib.util.spec_from_file_location("announcements_function_handler", HANDLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, restore


@given("the announcements function is running with that site's tables and the fake X")
def running(context):
    module, restore = load_handler({
        "AWS_DEFAULT_REGION": "us-east-1", "SITE_ID": context.site,
        "ANNOUNCEMENT_SETTINGS_TABLE": "settings", "X_CONNECTION_TABLE": "connection", "X_REFRESH_LEASE_SECONDS": "30",
        "X_AUTHORIZE_URL": "https://x.example/i/oauth2/authorize", "X_TOKEN_URL": f"{context.x.base}/2/oauth2/token",
        "X_REVOKE_URL": f"{context.x.base}/2/oauth2/revoke", "X_API_BASE": context.x.base,
    })
    context.add_cleanup(restore)
    context.function = module
    context.function_answers = {}
    context.all_answers = []


def send(context, who: str, groups: list[str], type_name: str, field: str, payload: dict) -> dict:
    event = amplify_function_event(type_name, field, {"input": json.dumps(payload)}, user_pool_identity(who, groups))
    answer = context.function.handler(event, None)
    context.all_answers.append(answer)
    context.answer = answer
    return answer


@when('an admin "{who}" makes these page calls in order, each as the request Amplify sends')
def page_calls(context, who):
    begun: dict = {}
    for row in context.table:
        field = row["field"]
        if field == "announcementsXSaveApp":
            payload = {"clientId": "client-123", "clientSecret": "s3cret-value"}
        elif field == "announcementsXBegin":
            payload = {"redirectUri": REDIRECT}
        elif field == "announcementsXComplete":
            payload = {"code": context.x.approve(begun["authorizeUrl"]), "state": begun["state"], "redirectUri": REDIRECT}
        elif field == "announcementsSaveSettings":
            payload = {"settings": {}}
        elif field == "announcementsPause":
            payload = {"paused": True}
        else:
            payload = {}
        answer = send(context, who, ["admin"], row["type"], field, payload)
        if field == "announcementsXBegin":
            begun = answer
        context.function_answers[field] = answer


@then("every call answered ok with what its operation returns")
def answered(context):
    for row in context.table:
        answer = context.function_answers[row["field"]]
        assert answer.get("ok") is True, (row["field"], answer)
        assert row["answer holds"] in answer, (row["field"], answer)


@then('the saved settings show announcements paused by "{who}"')
def paused_by(context, who):
    pause = context.function_answers["announcementsPause"]["settings"]["pause"]
    assert pause["paused"] is True and pause["by"] == who, pause


@when('an editor "{who}" reads the X status as the request Amplify sends')
def editor_reads(context, who):
    send(context, who, ["editor"], "Query", "announcementsXStatus", {})


@when('an editor "{who}" tries to pause announcements as the request Amplify sends')
def editor_pauses(context, who):
    send(context, who, ["editor"], "Mutation", "announcementsPause", {"paused": True})


@then('the answer is ok and holds "{key}"')
def ok_holds(context, key):
    assert context.answer.get("ok") is True and key in context.answer, context.answer


@then('the answer is refused with "{code}"')
def refused(context, code):
    assert context.answer.get("ok") is False and context.answer.get("error") == code, context.answer


@when("a request with no GraphQL field reaches the announcements function")
def no_field(context):
    event = amplify_function_event("Query", "announcementsSettings", {"input": "{}"}, user_pool_identity("ryan", ["admin"]))
    del event["fieldName"]
    context.answer = context.function.handler(event, None)
    context.all_answers.append(context.answer)


@then('the request is refused as "{code}" with the message "{message}"')
def refused_with_message(context, code, message):
    assert context.answer == {"ok": False, "error": code, "message": message}, context.answer


@then('no answer says "{text}"')
def no_answer_says(context, text):
    assert all(text not in json.dumps(answer) for answer in context.all_answers), context.all_answers
