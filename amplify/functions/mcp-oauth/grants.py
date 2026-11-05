"""Site-bound OAuth grant state. Storage implements atomic compare-and-swap."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from typing import Any, Protocol

MAX_LIFETIME = 7 * 24 * 60 * 60
CODE_LIFETIME = 300
ACCESS_LIFETIME = 3600


class InvalidGrant(Exception):
    pass


class Store(Protocol):
    def create(self, key: str, value: dict[str, Any]) -> bool: ...
    def get(self, key: str) -> dict[str, Any] | None: ...
    def replace(self, key: str, version: int, value: dict[str, Any]) -> bool: ...


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def pkce(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def token() -> str:
    return secrets.token_urlsafe(32)


def split(value: str) -> tuple[str, str]:
    parts = value.split(".")
    if len(parts) != 2 or not all(parts):
        raise InvalidGrant()
    return parts[0], parts[1]


class Grants:
    def __init__(self, store: Store, origin: str, *, clock=time.time):
        self.store, self.origin, self.clock = store, origin, clock

    def issue_code(self, *, client: str, redirect: str, resource: str, challenge: str,
                   principal: dict[str, Any], upstream_expiry: int) -> str:
        now = int(self.clock())
        if resource != self.origin + "/api/mcp" or not client or not redirect or not re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge):
            raise InvalidGrant()
        if principal.get("kind") == "reader":
            subject = principal.get("siteSubject", "")
            if not isinstance(subject, str) or not re.fullmatch(r"ss1_[A-Za-z0-9_-]{43}", subject):
                raise InvalidGrant()
        elif principal.get("kind") == "staff":
            if not principal.get("subject") or not principal.get("accessToken"):
                raise InvalidGrant()
        else:
            raise InvalidGrant()
        expires = min(now + MAX_LIFETIME, upstream_expiry)
        if expires <= now:
            raise InvalidGrant()
        key, secret = token(), token()
        row = {"version": 0, "client": client, "redirect": redirect, "resource": resource,
               "challenge": challenge, "principal": principal, "expires": expires,
               "code_expires": min(now + CODE_LIFETIME, expires), "code": digest(secret),
               "state": "code", "used_refresh": []}
        if not self.store.create(key, row):
            raise InvalidGrant()
        return key + "." + secret

    def exchange(self, code: str, *, client: str, redirect: str, resource: str, verifier: str) -> dict[str, Any]:
        key, secret = split(code)
        row = self.store.get(key)
        now = int(self.clock())
        try:
            valid = (row is not None and row["state"] == "code" and now < row["code_expires"]
                     and row["client"] == client and row["redirect"] == redirect and row["resource"] == resource
                     and re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier) is not None and hmac.compare_digest(row["code"], digest(secret))
                     and hmac.compare_digest(row["challenge"], pkce(verifier)))
        except (UnicodeError, ValueError):
            valid = False
        if not valid or row is None:
            raise InvalidGrant()
        return self._rotate(key, row, now)

    def _rotate(self, key: str, row: dict[str, Any], now: int) -> dict[str, Any]:
        access, refresh = token(), token()
        updated = dict(row, state="active", access=digest(access), refresh=digest(refresh),
                       access_expires=min(now + ACCESS_LIFETIME, row["expires"]), version=row["version"] + 1)
        if not self.store.replace(key, row["version"], updated):
            raise InvalidGrant()
        return {"access_token": key + "." + access, "refresh_token": key + "." + refresh,
                "token_type": "Bearer", "expires_in": updated["access_expires"] - now}

    def refresh(self, value: str, *, client: str, resource: str) -> dict[str, Any]:
        key, secret = split(value)
        secret_hash = digest(secret)
        for _ in range(4):
            row = self.store.get(key)
            now = int(self.clock())
            if not row or row["state"] != "active" or now >= row["expires"] or row["client"] != client or row["resource"] != resource:
                raise InvalidGrant()
            if secret_hash in row["used_refresh"]:
                revoked = dict(row, state="revoked", version=row["version"] + 1)
                if self.store.replace(key, row["version"], revoked):
                    raise InvalidGrant()
                continue
            if not hmac.compare_digest(secret_hash, row["refresh"]):
                raise InvalidGrant()
            row["used_refresh"] = [*row["used_refresh"], secret_hash]
            try:
                return self._rotate(key, row, now)
            except InvalidGrant:
                continue
        raise InvalidGrant()

    def verify(self, value: str, *, resource: str) -> dict[str, Any] | None:
        try:
            key, secret = split(value)
            row = self.store.get(key)
            now = int(self.clock())
            if (row and row["state"] == "active" and row["resource"] == resource == self.origin + "/api/mcp"
                    and now < row["expires"] and now < row["access_expires"]
                    and hmac.compare_digest(row["access"], digest(secret))):
                return row["principal"]
        except (InvalidGrant, UnicodeError, ValueError):
            pass
        return None

    def revoke(self, value: str, *, client: str) -> None:
        try:
            key, secret = split(value)
            secret_hash = digest(secret)
            for _ in range(4):
                row = self.store.get(key)
                if not row or row["client"] != client or secret_hash not in [row.get("access"), row.get("refresh"), *row.get("used_refresh", [])]:
                    return
                if self.store.replace(key, row["version"], dict(row, state="revoked", version=row["version"] + 1)):
                    return
        except (InvalidGrant, UnicodeError, ValueError):
            return
