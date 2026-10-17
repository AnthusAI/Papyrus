from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.graphql_authoring import create_authoring_client  # noqa: E402
from papyrus_content.guest_auth import GuestConfiguration, GuestSession  # noqa: E402
from papyrus_content.markus_export_commands import content_export_published  # noqa: E402

ENDPOINT = "https://abc.appsync-api.us-east-1.amazonaws.com/graphql"


class StubIdentityClient:
    def get_id(self, IdentityPoolId):
        return {"IdentityId": "us-east-1:guest"}

    def get_credentials_for_identity(self, IdentityId):
        return {
            "Credentials": {
                "AccessKeyId": "AKIAGUEST",
                "SecretKey": "secret",
                "SessionToken": "guest-session-token",
                "Expiration": datetime.now(timezone.utc) + timedelta(hours=1),
            }
        }


def remember_refusal(context, action) -> None:
    context.refusal = ""
    try:
        action()
    except ValueError as error:
        context.refusal = str(error)


@when("I run export-published with auth guest and drafts")
def run_guest_drafts(context) -> None:
    flags = ["--out", "x", "--auth", "guest", "--drafts"]
    os.environ["PAPYRUS_GRAPHQL_ENDPOINT"] = ENDPOINT
    os.environ["PAPYRUS_IDENTITY_POOL_ID"] = "us-east-1:pool"
    os.environ["AWS_REGION"] = "us-east-1"
    context.add_cleanup(
        lambda: [os.environ.pop(name, None) for name in ("PAPYRUS_GRAPHQL_ENDPOINT", "PAPYRUS_IDENTITY_POOL_ID", "AWS_REGION")]
    )
    remember_refusal(context, lambda: content_export_published(flags))


@given("the environment selects guest auth")
def select_guest(context) -> None:
    os.environ["PAPYRUS_GRAPHQL_AUTH"] = "guest"
    context.add_cleanup(lambda: os.environ.pop("PAPYRUS_GRAPHQL_AUTH", None))


@when("I create an authoring client for a write command")
def create_client(context) -> None:
    remember_refusal(context, create_authoring_client)


@then('the command is refused with "{text}"')
def refused(context, text) -> None:
    assert text in context.refusal, context.refusal


@given("a stubbed identity pool that issues guest credentials")
def stub_pool(context) -> None:
    configuration = GuestConfiguration(endpoint=ENDPOINT, identity_pool_id="us-east-1:pool", bucket=None, region="us-east-1")
    context.session = GuestSession(configuration, identity_client=StubIdentityClient())


@when("I sign an AppSync request as a guest")
def sign(context) -> None:
    context.headers = {key.lower(): value for key, value in context.session.appsync_headers(b"{}").items()}


@then("the request is signed for the appsync service with the guest session token")
def check_signed(context) -> None:
    assert context.headers["x-amz-security-token"] == "guest-session-token"
    assert "/appsync/aws4_request" in context.headers["authorization"]
    assert "AKIAGUEST" in context.headers["authorization"]
