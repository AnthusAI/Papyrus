"""Signed, URL-safe tokens: ``v1.<base64url(json)>.<base64url(hmac)>``.

Claims: ``h`` subscriber id, ``p`` purpose (``confirm`` or ``manage``), ``l`` list ids, ``n`` nonce, ``e`` expiry (epoch seconds).
A confirm token expires in 72 hours and is single use (its nonce must match the profile's). A manage token has no expiry:
it is invalid once the subscriber is deleted.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass

VERSION = "v1"
PURPOSES = ("confirm", "manage")
CONFIRM_TOKEN_LIFETIME_SECONDS = 72 * 60 * 60
MAXIMUM_TOKEN_CHARACTERS = 2048


class InvalidToken(ValueError):
    """Malformed, tampered, or for another purpose."""


class ExpiredToken(InvalidToken):
    """Correctly signed, but past its expiry."""


@dataclass(frozen=True)
class Claims:
    hid: str
    purpose: str
    lists: tuple[str, ...] = ()
    nonce: str | None = None
    expires_at: int | None = None


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(key: bytes, payload: str) -> bytes:
    return hmac.new(key, f"{VERSION}.{payload}".encode("ascii"), hashlib.sha256).digest()


def issue(key: bytes, claims: Claims) -> str:
    if claims.purpose not in PURPOSES:
        raise ValueError(f"Unknown token purpose {claims.purpose!r}")
    body: dict[str, object] = {"h": claims.hid, "p": claims.purpose}
    if claims.lists:
        body["l"] = list(claims.lists)
    if claims.nonce is not None:
        body["n"] = claims.nonce
    if claims.expires_at is not None:
        body["e"] = int(claims.expires_at)
    payload = _encode(json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{VERSION}.{payload}.{_encode(_signature(key, payload))}"


def verify(key: bytes, token: object, purpose: str, now_seconds: float) -> Claims:
    """The claims of a valid token, else ``InvalidToken`` or ``ExpiredToken``. Signature first, in constant time."""
    if not isinstance(token, str) or not 0 < len(token) <= MAXIMUM_TOKEN_CHARACTERS:
        raise InvalidToken("malformed")
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != VERSION:
        raise InvalidToken("malformed")
    try:
        presented = _decode(parts[2])
        body = json.loads(_decode(parts[1]))
    except (ValueError, UnicodeDecodeError) as error:
        raise InvalidToken("malformed") from error
    if not hmac.compare_digest(presented, _signature(key, parts[1])):
        raise InvalidToken("signature")
    if not isinstance(body, dict) or body.get("p") != purpose or not isinstance(body.get("h"), str):
        raise InvalidToken("purpose")
    lists, nonce, expires_at = body.get("l", []), body.get("n"), body.get("e")
    if (
        not isinstance(lists, list)
        or not all(isinstance(entry, str) for entry in lists)
        or (nonce is not None and not isinstance(nonce, str))
        or (expires_at is not None and (isinstance(expires_at, bool) or not isinstance(expires_at, int)))
    ):
        raise InvalidToken("claims")
    if expires_at is not None and now_seconds > expires_at:
        raise ExpiredToken("expired")
    return Claims(hid=body["h"], purpose=purpose, lists=tuple(lists), nonce=nonce, expires_at=expires_at)
