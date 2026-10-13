"""The <papyrus-signup> request signing and submit flow, run in Node against a fake network."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from papyrus_content.projection.plugins import PLUGIN_ASSET_DIRECTORY

COMPONENT = PLUGIN_ASSET_DIRECTORY / "papyrus-signup.js"
ENDPOINT = "https://abc123.appsync-api.us-east-1.amazonaws.com/graphql"
POOL = "us-east-1:00000000-0000-0000-0000-000000000000"
SIGNATURE_FROM_BOTOCORE = "7219f713ea3b467079eb0bde178e0c205eb73f98bfb9f7f4af7c05ad0a282dcf"

HARNESS = r"""
const component = require(%(component)s);
const calls = [];
let appsync = %(appsync)s;
globalThis.window = { localStorage: { getItem: () => null, setItem: () => {} } };
globalThis.fetch = async (url, options) => {
  calls.push({ url, headers: options.headers, body: options.body });
  if (url.startsWith("https://cognito-identity.")) {
    const target = options.headers["x-amz-target"];
    return { ok: true, json: async () => target.endsWith("GetId")
      ? { IdentityId: "us-east-1:identity" }
      : { Credentials: { AccessKeyId: "AKIDEXAMPLE", SecretKey: "secret", SessionToken: "token", Expiration: Date.now() / 1000 + 3600 } } };
  }
  return { status: appsync.status, headers: { get: (name) => appsync.headers[name] || null }, json: async () => appsync.body };
};
(async () => {
  %(script)s
})().catch((error) => { console.error(error); process.exit(1); });
"""


def run_node(script: str, appsync: dict | None = None):
    appsync = appsync or {"status": 200, "headers": {}, "body": {"data": {"submitSignup": {"status": "accepted"}}}}
    code = HARNESS % {"component": json.dumps(str(COMPONENT)), "appsync": json.dumps(appsync), "script": script}
    done = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True)
    return json.loads(done.stdout.strip().splitlines()[-1])


SUBMIT = f'const settings = {{ endpoint: "{ENDPOINT}", identityPool: "{POOL}", region: "us-east-1" }};'


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class SignupComponentTests(unittest.TestCase):
    def test_the_request_signature_matches_botocore(self) -> None:
        script = (
            'const headers = await component.sign({ url: "%s", body: JSON.stringify({query:"q",variables:{a:1}}), '
            'date: new Date("2026-10-13T12:00:00Z"), region: "us-east-1", service: "appsync", '
            'credentials: { accessKeyId: "AKIDEXAMPLE", secretKey: "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", sessionToken: "SESSIONTOKENEXAMPLE" } });'
            "console.log(JSON.stringify(headers));" % ENDPOINT
        )
        headers = run_node(script)
        self.assertTrue(headers["authorization"].endswith("Signature=" + SIGNATURE_FROM_BOTOCORE), headers["authorization"])
        self.assertIn("SignedHeaders=content-type;host;x-amz-date;x-amz-security-token", headers["authorization"])

    def test_a_submission_asks_cognito_for_a_guest_then_sends_one_signed_mutation(self) -> None:
        script = SUBMIT + (
            'const outcome = await component.submit(settings, "newsletter", "reader@example.test", 1700000000000, "");'
            "console.log(JSON.stringify({ outcome, calls }));"
        )
        result = run_node(script)
        self.assertEqual(result["outcome"], {"status": "accepted"})
        targets = [call["headers"].get("x-amz-target") for call in result["calls"][:2]]
        self.assertEqual(targets, ["AWSCognitoIdentityService.GetId", "AWSCognitoIdentityService.GetCredentialsForIdentity"])
        last = result["calls"][-1]
        self.assertEqual(last["url"], ENDPOINT)
        self.assertIn("Credential=AKIDEXAMPLE/", last["headers"]["authorization"])
        variables = json.loads(last["body"])["variables"]
        self.assertEqual(variables, {"form": "newsletter", "value": "reader@example.test", "renderedAt": "1700000000000", "website": ""})
        self.assertNotIn("secret", last["body"])

    def test_the_hidden_field_value_is_sent_as_is(self) -> None:
        script = SUBMIT + 'await component.submit(settings, "newsletter", "a@example.test", 1, "filled"); console.log(JSON.stringify(calls.at(-1).body));'
        self.assertEqual(json.loads(run_node(script))["variables"]["website"], "filled")

    def test_a_block_by_the_firewall_reads_as_throttled(self) -> None:
        script = SUBMIT + 'console.log(JSON.stringify(await component.submit(settings, "newsletter", "a@example.test", 1, "")));'
        self.assertEqual(run_node(script, {"status": 429, "headers": {}, "body": {}}), {"status": "throttled"})
        self.assertEqual(run_node(script, {"status": 403, "headers": {"x-amzn-waf-action": "BLOCK"}, "body": {}}), {"status": "throttled"})

    def test_the_server_status_is_passed_through_and_errors_read_as_failed(self) -> None:
        script = SUBMIT + 'console.log(JSON.stringify(await component.submit(settings, "newsletter", "a@example.test", 1, "")));'
        for status in ["invalid", "expired", "throttled"]:
            self.assertEqual(run_node(script, {"status": 200, "headers": {}, "body": {"data": {"submitSignup": {"status": status}}}}), {"status": status})
        self.assertEqual(run_node(script, {"status": 200, "headers": {}, "body": {"errors": [{"message": "Not Authorized"}]}}), {"status": "failed"})

    def test_the_component_is_one_file_without_dependencies(self) -> None:
        source = Path(COMPONENT).read_text(encoding="utf-8")
        for forbidden in ["import ", "require(", "innerHTML", "eval(", "document.write"]:
            self.assertNotIn(forbidden, source.replace("module.exports", ""))
        self.assertIn('role: "status"', source)
        self.assertIn("Error:", source)


if __name__ == "__main__":
    unittest.main()
