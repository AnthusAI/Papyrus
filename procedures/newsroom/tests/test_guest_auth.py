import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import boto3  # noqa: E402
from botocore import UNSIGNED  # noqa: E402
from botocore.config import Config  # noqa: E402
from botocore.stub import Stubber  # noqa: E402

from papyrus_content import guest_auth  # noqa: E402
from papyrus_content.graphql_authoring import create_authoring_client  # noqa: E402
from papyrus_content.guest_auth import GuestSession, guest_auth_requested, resolve_guest_configuration  # noqa: E402
from papyrus_content.markus_export_commands import content_export_published  # noqa: E402

ENDPOINT = "https://abc.appsync-api.us-east-1.amazonaws.com/graphql"
POOL = "us-east-1:11111111-2222-3333-4444-555555555555"
GUEST_ENV = {
    "PAPYRUS_GRAPHQL_ENDPOINT": ENDPOINT,
    "PAPYRUS_IDENTITY_POOL_ID": POOL,
    "AWS_REGION": "us-east-1",
}


def stubbed_identity_client(expiration):
    client = boto3.client(
        "cognito-identity",
        region_name="us-east-1",
        config=Config(signature_version=UNSIGNED),
    )
    stubber = Stubber(client)
    stubber.add_response("get_id", {"IdentityId": "us-east-1:guest"}, {"IdentityPoolId": POOL})
    stubber.add_response(
        "get_credentials_for_identity",
        {
            "IdentityId": "us-east-1:guest",
            "Credentials": {
                "AccessKeyId": "AKIAGUEST",
                "SecretKey": "secret",
                "SessionToken": "guest-token",
                "Expiration": expiration,
            },
        },
        {"IdentityId": "us-east-1:guest"},
    )
    stubber.activate()
    return client, stubber


class ResolveGuestConfigurationTests(unittest.TestCase):
    def test_environment_values_win(self):
        with mock.patch.dict(os.environ, {**GUEST_ENV, "PAPYRUS_MEDIA_BUCKET": "media-bucket"}):
            configuration = resolve_guest_configuration()
        self.assertEqual(configuration.endpoint, ENDPOINT)
        self.assertEqual(configuration.identity_pool_id, POOL)
        self.assertEqual(configuration.bucket, "media-bucket")
        self.assertEqual(configuration.region, "us-east-1")

    def test_falls_back_to_amplify_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "amplify_outputs.json"
            path.write_text(
                json.dumps(
                    {
                        "aws_region": "us-west-2",
                        "data": {"url": ENDPOINT},
                        "auth": {"identity_pool_id": POOL},
                        "storage": {"bucket_name": "outputs-bucket"},
                    }
                )
            )
            cleared = {name: "" for name in (*GUEST_ENV, "PAPYRUS_MEDIA_BUCKET")}
            with mock.patch.dict(os.environ, cleared), mock.patch.object(guest_auth, "amplify_outputs_path", return_value=path):
                configuration = resolve_guest_configuration()
        self.assertEqual(configuration.bucket, "outputs-bucket")
        self.assertEqual(configuration.region, "us-west-2")
        self.assertEqual(configuration.identity_pool_id, POOL)

    def test_missing_values_are_named(self):
        cleared = {name: "" for name in (*GUEST_ENV, "PAPYRUS_MEDIA_BUCKET")}
        with mock.patch.dict(os.environ, cleared), mock.patch.object(
            guest_auth, "amplify_outputs_path", return_value=Path("/nonexistent/amplify_outputs.json")
        ):
            with self.assertRaisesRegex(ValueError, "PAPYRUS_IDENTITY_POOL_ID"):
                resolve_guest_configuration()


class GuestSessionTests(unittest.TestCase):
    def make_session(self, expiration):
        client, stubber = stubbed_identity_client(expiration)
        with mock.patch.dict(os.environ, GUEST_ENV):
            configuration = resolve_guest_configuration()
        return GuestSession(configuration, identity_client=client), stubber

    def test_signs_appsync_requests_with_unauthenticated_credentials(self):
        session, stubber = self.make_session(datetime.now(timezone.utc) + timedelta(hours=1))
        headers = {key.lower(): value for key, value in session.appsync_headers(b'{"query":"{}"}').items()}
        stubber.assert_no_pending_responses()
        self.assertEqual(headers["x-amz-security-token"], "guest-token")
        self.assertIn("AKIAGUEST", headers["authorization"])
        self.assertIn("/us-east-1/appsync/aws4_request", headers["authorization"])

    def test_credentials_are_cached_until_near_expiry(self):
        session, stubber = self.make_session(datetime.now(timezone.utc) + timedelta(hours=1))
        first = session.credentials()
        self.assertIs(session.credentials(), first)
        stubber.assert_no_pending_responses()

    def test_s3_client_uses_guest_credentials(self):
        session, _stubber = self.make_session(datetime.now(timezone.utc) + timedelta(hours=1))
        frozen = session.s3_client()._request_signer._credentials
        self.assertEqual(frozen.token, "guest-token")


class GuestRefusalTests(unittest.TestCase):
    def test_guest_with_drafts_is_refused(self):
        with mock.patch.dict(os.environ, GUEST_ENV):
            with self.assertRaisesRegex(ValueError, "cannot be combined with --drafts"):
                content_export_published(["--out", "x", "--auth", "guest", "--drafts"])

    def test_guest_environment_refuses_authoring_client(self):
        with mock.patch.dict(os.environ, {"PAPYRUS_GRAPHQL_AUTH": "guest"}):
            with self.assertRaisesRegex(ValueError, "only valid for 'content export-published'"):
                create_authoring_client()

    def test_guest_environment_refuses_graphql_headers(self):
        from papyrus_content.graphql_http import graphql_request_headers

        with mock.patch.dict(os.environ, {"PAPYRUS_GRAPHQL_AUTH": "guest"}):
            with self.assertRaisesRegex(ValueError, "read-only"):
                graphql_request_headers(endpoint=ENDPOINT, body=b"{}", token="t")

    def test_guest_requested_by_flag_or_environment(self):
        self.assertTrue(guest_auth_requested("guest"))
        with mock.patch.dict(os.environ, {"PAPYRUS_GRAPHQL_AUTH": "Guest"}):
            self.assertTrue(guest_auth_requested(None))
        with mock.patch.dict(os.environ, {"PAPYRUS_GRAPHQL_AUTH": ""}):
            self.assertFalse(guest_auth_requested(True))


if __name__ == "__main__":
    unittest.main()
