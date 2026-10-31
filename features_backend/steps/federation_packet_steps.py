import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "prospectus-federation-packet.ts"
SECRET_VALUE = "google-client-secret-value"

FAKE_AWS = """#!/usr/bin/env python3
import json, os, sys
state = json.load(open(os.environ["FAKE_FEDERATION_STATE"]))
command = sys.argv[2]
print(json.dumps(state[command]))
"""


def build_state(providers):
    return {
        "describe-user-pool-client": {"UserPoolClient": {
            "ClientName": "prospectus-google-only", "ClientId": "client-id-1",
            "SupportedIdentityProviders": providers, "ExplicitAuthFlows": ["ALLOW_REFRESH_TOKEN_AUTH"],
            "AllowedOAuthFlows": ["code"], "AllowedOAuthScopes": ["openid", "email", "profile"],
            "CallbackURLs": ["https://site.example/api/auth/prospectus/callback", "https://www.site.example/api/auth/prospectus/callback"],
            "LogoutURLs": ["https://site.example/"], "AccessTokenValidity": 60, "IdTokenValidity": 60, "RefreshTokenValidity": 60,
            "TokenValidityUnits": {"AccessToken": "minutes", "IdToken": "minutes", "RefreshToken": "minutes"},
            "PreventUserExistenceErrors": "ENABLED", "EnableTokenRevocation": True}},
        "describe-user-pool": {"UserPool": {"LambdaConfig": {}, "MfaConfiguration": "OFF"}},
        "describe-identity-provider": {"IdentityProvider": {
            "ProviderName": "Google", "ProviderType": "Google",
            "ProviderDetails": {"client_id": "google-client-id", "client_secret": SECRET_VALUE, "authorize_scopes": "openid email profile"},
            "AttributeMapping": {"email": "email", "name": "name"}}},
    }


def prepare(context, providers):
    context.work = Path(tempfile.mkdtemp(prefix="federation-packet-"))
    state_path = context.work / "state.json"
    state_path.write_text(json.dumps(build_state(providers)))
    fake = context.work / "fake-aws"
    fake.write_text(FAKE_AWS)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    outputs = context.work / "amplify_outputs.json"
    outputs.write_text(json.dumps({"auth": {"user_pool_id": "region_pool", "aws_region": "us-east-2"},
                                   "custom": {"prospectusSignIn": {"clientId": "client-id-1"}}}))
    context.outputs_path = outputs
    context.environment = {**os.environ, "FAKE_FEDERATION_STATE": str(state_path), "PAPYRUS_FEDERATION_PACKET_AWS": str(fake)}


def run_script(context, out_dir):
    context.out_dir = out_dir
    context.result = subprocess.run(
        ["node", "--import", "tsx", str(SCRIPT), "--site", "example", "--outputs", str(context.outputs_path), "--profile", "p",
         "--site-origin", "https://site.example", "--out-dir", str(out_dir)],
        cwd=REPO_ROOT, env=context.environment, capture_output=True, text=True, timeout=120)
    context.packet = out_dir / "federation-packet-example.md"


@given("a site whose federation client is Google-only with two callback URLs")
def google_only_site(context):
    prepare(context, ["Google"])


@given("a site whose federation client also allows a non-Google provider")
def mixed_site(context):
    prepare(context, ["Google", "COGNITO"])


@when("the operator generates the federation packet for that site outside the repository")
def generate_outside(context):
    run_script(context, context.work / "packets")


@when("the operator generates the federation packet for that site inside the repository")
def generate_inside(context):
    run_script(context, REPO_ROOT / "scripts" / "federation-packet-test-output")


@then("the packet lists the deployed callback URLs and the callback URLs after the CLI task")
def lists_callbacks(context):
    text = context.packet.read_text()
    assert "https://www.site.example/api/auth/prospectus/callback" in text
    assert "http://127.0.0.1:53682/cli/callback" in text
    assert "https://site.example/cli/callback" in text


@then("the packet names the Google provider with its scopes and attribute mapping")
def names_provider(context):
    text = context.packet.read_text()
    assert "Provider name: Google" in text and "authorize scopes: openid email profile" in text.lower() and "email <- email" in text


@then("the packet states the code flow, the scopes and the token validity")
def states_flow(context):
    text = context.packet.read_text()
    assert "Allowed OAuth flows: code" in text and "openid, email, profile" in text
    assert "Access token: 60 minutes" in text and "S256" in text


@then("the packet states that sign-in is Google-only")
def states_google_only(context):
    assert "Google-only: every check holds." in context.packet.read_text()


@then("the packet never contains the Google client secret")
def no_secret(context):
    assert SECRET_VALUE not in context.packet.read_text()


@then("the script refuses and no packet is written")
def refuses(context):
    assert context.result.returncode != 0
    assert "inside the repository" in context.result.stderr
    assert not context.packet.exists()


@then("the packet states that sign-in is not Google-only")
def states_not_google_only(context):
    assert "NOT Google-only" in context.packet.read_text()


@then("the script exits with a failure status")
def failure_status(context):
    assert context.result.returncode == 2
