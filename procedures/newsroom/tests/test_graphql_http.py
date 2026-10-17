from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from botocore.stub import Stubber  # noqa: E402

from papyrus_content import content_commands, graphql_http  # noqa: E402
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient, create_authoring_client  # noqa: E402

ENDPOINT = "https://example.appsync-api.us-east-1.amazonaws.com/graphql"
STATIC_CREDENTIALS = {
    "AWS_ACCESS_KEY_ID": "AKIDEXAMPLE",
    "AWS_SECRET_ACCESS_KEY": "secret-example",
    "AWS_SESSION_TOKEN": "session-example",
}
NO_CREDENTIALS = {
    "AWS_EC2_METADATA_DISABLED": "true",
    "AWS_CONFIG_FILE": os.devnull,
    "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
}


class SigV4AuthoringTests(unittest.TestCase):
    def setUp(self) -> None:
        graphql_http._credential_session = None
        self.addCleanup(setattr, graphql_http, "_credential_session", None)

    def test_requests_are_signed_with_sigv4_from_the_credential_chain(self) -> None:
        body = json.dumps({"query": "query { __typename }", "variables": {}}).encode("utf-8")
        with patch.dict(os.environ, STATIC_CREDENTIALS, clear=True):
            headers = graphql_http.graphql_request_headers(endpoint=ENDPOINT, body=body)
        authorization = headers["Authorization"]
        self.assertTrue(authorization.startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/"))
        self.assertIn("/us-east-1/appsync/aws4_request", authorization)
        self.assertEqual(headers["X-Amz-Security-Token"], "session-example")
        self.assertNotIn("x-amz-appsync-authtype", {key.lower() for key in headers})

    def test_region_follows_the_endpoint_unless_overridden(self) -> None:
        with patch.dict(os.environ, {**STATIC_CREDENTIALS, "AWS_REGION": "eu-west-1"}, clear=True):
            headers = graphql_http.iam_signed_graphql_headers(ENDPOINT, b"{}")
        self.assertIn("/eu-west-1/appsync/aws4_request", headers["Authorization"])

    def test_missing_credentials_explain_how_to_authenticate(self) -> None:
        with patch.dict(os.environ, NO_CREDENTIALS, clear=True):
            self.assertFalse(graphql_http.aws_credentials_available())
            with self.assertRaisesRegex(ValueError, "AWS_PROFILE"):
                graphql_http.iam_signed_graphql_headers(ENDPOINT, b"{}")

    def test_authoring_client_signs_without_any_token(self) -> None:
        with patch.dict(os.environ, {**STATIC_CREDENTIALS, "PAPYRUS_GRAPHQL_ENDPOINT": ENDPOINT}, clear=True):
            client, claims = create_authoring_client()
            headers = client._request_headers(b"{}")
        self.assertEqual(claims, {})
        self.assertTrue(headers["Authorization"].startswith("AWS4-HMAC-SHA256 "))

    def test_authoring_client_inside_lambda_uses_the_same_signing(self) -> None:
        with patch.dict(os.environ, {**STATIC_CREDENTIALS, "AWS_LAMBDA_FUNCTION_NAME": "fn"}, clear=True):
            headers = PapyrusGraphQLAuthoringClient(endpoint=ENDPOINT)._request_headers(b"{}")
        self.assertTrue(headers["Authorization"].startswith("AWS4-HMAC-SHA256 "))

    def test_content_inspect_reports_the_aws_caller(self) -> None:
        import boto3

        sts = boto3.client("sts", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="y")
        arn = "arn:aws:sts::335163751677:assumed-role/example-papyrus-authoring/session"
        with Stubber(sts) as stubber, patch.dict(
            os.environ, {**STATIC_CREDENTIALS, "PAPYRUS_GRAPHQL_ENDPOINT": ENDPOINT}, clear=True
        ), patch("boto3.client", return_value=sts), patch.object(
            PapyrusGraphQLAuthoringClient, "inspect_reachability", return_value={}
        ):
            stubber.add_response("get_caller_identity", {"UserId": "u", "Account": "335163751677", "Arn": arn})
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                content_commands.content_inspect([])
        text = output.getvalue()
        self.assertIn("Auth source: AWS credential chain (IAM, SigV4)", text)
        self.assertIn(arn, text)
        self.assertIn("GraphQL reachability: ok", text)

    def test_newsroom_graphql_uses_shared_client(self) -> None:
        from papyrus_newsroom import newsroom

        with patch(
            "papyrus_content.graphql_http.execute_graphql",
            return_value={"getAssignment": {"id": "a1"}},
        ) as execute:
            data = newsroom._graphql("query {}", {"id": "a1"})
        self.assertEqual(data["getAssignment"]["id"], "a1")
        execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
