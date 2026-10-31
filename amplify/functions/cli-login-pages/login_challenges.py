"""Login challenges for `papyrus login --remote`: one signed Prospectus challenge bound to one CLI transaction.

On Approve the approval pages call `LoginChallenges.prepare`, which asks Prospectus (as this function's IAM role) for a
challenge bound to `sha256hex(T)`, where T is the broker transaction. The challenge nonce becomes the Google sign-in
nonce and the signed challenge token is the opaque enrollment string the broker hands to the polling CLI. Any
unusable answer raises `Unavailable` and nothing is bound.

Copied, not imported, from the Prospectus CLI pages (cli/src/prospectus_cli/pages.py); this function imports nothing
from papyrus_content.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from urllib.parse import urlsplit

CHALLENGE_SECONDS = 300
CHALLENGE_PATH = "/v1/identities/google/challenge"
UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
NONCE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
CHALLENGE_TOKEN = re.compile(r"^v1\.[a-z0-9]{1,16}\.[A-Za-z0-9_-]{1,1500}\.[A-Za-z0-9_-]{1,100}$")
EXECUTE_API_HOST = re.compile(r"^[a-z0-9]+\.execute-api\.([a-z0-9-]+)\.amazonaws\.com$")


class Unavailable(Exception):
    """Prospectus could not issue a usable challenge; nothing is bound."""


def accounts_api_origin(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme != "https" or not EXECUTE_API_HOST.match(parts.netloc or "") or parts.query or parts.fragment:
        raise ValueError("PROSPECTUS_ACCOUNTS_API must be an https API Gateway execute-api endpoint")
    return f"https://{parts.netloc}{parts.path.rstrip('/')}"


def signed_post(url: str, headers: Mapping[str, str], body: str, *, credentials=None, opener=urllib.request.urlopen):  # pragma: no cover - network
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    if credentials is None:
        import boto3

        credentials = boto3.Session().get_credentials()
    host = urlsplit(url).netloc
    region = EXECUTE_API_HOST.match(host).group(1)
    request = AWSRequest(method="POST", url=url, data=body.encode(), headers={**headers, "host": host})
    SigV4Auth(credentials.get_frozen_credentials(), "execute-api", region).add_auth(request)
    http_request = urllib.request.Request(url, data=body.encode(), headers=dict(request.headers.items()), method="POST")
    try:
        with opener(http_request, timeout=5) as response:
            return response.status, json.loads(response.read(65536) or b"null")
    except urllib.error.HTTPError as error:
        return error.code, None


class LoginChallenges:
    def __init__(self, accounts_api: str, post: Callable[[str, Mapping[str, str], str], tuple[int, object]] = signed_post,
                 *, clock=time.time):
        self.accounts_api = accounts_api_origin(accounts_api)
        self.post, self.clock = post, clock

    def prepare(self, transaction: str, described: Mapping) -> tuple[str, str]:
        digest = hashlib.sha256(transaction.encode()).hexdigest()
        try:
            status, answer = self.post(self.accounts_api + CHALLENGE_PATH, {"Content-Type": "application/json"},
                                       json.dumps({"loginStateDigest": digest}))
        except Exception:  # noqa: BLE001 - any transport failure is the same outage to the person
            raise Unavailable("the login challenge could not be requested") from None
        now = self.clock()
        if (
            status != 200
            or not isinstance(answer, dict)
            or not isinstance(answer.get("challengeId"), str)
            or not UUID4.match(answer["challengeId"])
            or not isinstance(answer.get("nonce"), str)
            or not NONCE.match(answer["nonce"])
            or type(answer.get("expiresAt")) is not int
            or not now < answer["expiresAt"] <= now + CHALLENGE_SECONDS
            or not isinstance(answer.get("challengeToken"), str)
            or not CHALLENGE_TOKEN.match(answer["challengeToken"])
        ):
            raise Unavailable("Prospectus answered no usable login challenge")
        return answer["nonce"], answer["challengeToken"]
