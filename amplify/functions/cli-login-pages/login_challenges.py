"""Login challenges for `papyrus login --remote`: one signed Prospectus challenge bound to one CLI transaction.

Central Prospectus admits challenge and resolve calls only from the site's registered compute role, which this function
is not. So on Approve the approval pages ask the site's own `/cli/challenge` route, which runs as that role and
calls Prospectus, passing `sha256hex(T)` where T is the broker transaction. The challenge nonce becomes the Google
sign-in nonce and the signed challenge token is the opaque enrollment string the broker hands to the polling CLI.
Any unusable answer raises `Unavailable` and nothing is bound; the same strict checks the route applies are applied
again here.

Copied, not imported, from the Prospectus CLI pages (cli/src/prospectus_cli/pages.py); this function imports nothing
from papyrus_content.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from urllib.parse import urlsplit

CHALLENGE_SECONDS = 300
CHALLENGE_PATH = "/cli/challenge"
UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
NONCE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
CHALLENGE_TOKEN = re.compile(r"^v1\.[a-z0-9]{1,16}\.[A-Za-z0-9_-]{1,1500}\.[A-Za-z0-9_-]{1,100}$")


class Unavailable(Exception):
    """The site could not obtain a usable challenge; nothing is bound."""


def site_origin(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.netloc or parts.path not in ("", "/") or parts.query or parts.fragment or parts.username:
        raise ValueError("SITE_CHALLENGE_ORIGIN must be a plain https origin")
    return f"https://{parts.netloc}"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *arguments, **keywords):
        return None


def site_get(url: str, *, opener=None):  # pragma: no cover - network
    opener = opener or urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=5) as response:
            return response.status, json.loads(response.read(65536) or b"null")
    except urllib.error.HTTPError as error:
        return error.code, None


class LoginChallenges:
    def __init__(self, origin: str, get: Callable[[str], tuple[int, object]] = site_get, *, clock=time.time):
        self.origin = site_origin(origin)
        self.get, self.clock = get, clock

    def prepare(self, transaction: str, described: Mapping) -> tuple[str, str]:
        digest = hashlib.sha256(transaction.encode()).hexdigest()
        try:
            status, answer = self.get(self.origin + CHALLENGE_PATH + "?" + urllib.parse.urlencode({"loginStateDigest": digest}))
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
            raise Unavailable("the site answered no usable login challenge")
        return answer["nonce"], answer["challengeToken"]
