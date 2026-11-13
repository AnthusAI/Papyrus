"""The site owner's X account: OAuth 2.0 Authorization Code with PKCE, keys in SSM SecureString, one refresh at a time.

The owner brings their own X developer app (the owner pays X). The client secret and the account's rotating refresh
token live only in SSM SecureString, per site and account, and no operation here ever returns them. The stores are
passed in: a parameter store (SSM), a connection store (one DynamoDB row with a lease) and a settings store (for the pause).

Parameters, under ``/papyrus/<siteId>/announcements/x``:

- ``client-secret``: the developer app's client secret (write only).
- ``<accountId>/refresh-token``: single use; every refresh returns a new one, which is saved before anything else.
- ``<accountId>/access-token``: JSON ``{"token", "expiresAt"}``. X's access token lasts two hours. It is kept (not only in
  memory) because the Lambda invocations that post cannot share memory, and a single-use refresh token means every
  invocation that refreshed would otherwise spend the token the next one needs.

A refresh takes a lease on the connection row (a DynamoDB conditional write), so two posts at the same moment cause one
refresh and both use its token. A refresh X refuses marks the connection "needs reconnecting" and pauses the site's
announcements; nothing falls back to another account.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

SCOPES = ("tweet.write", "tweet.read", "users.read", "offline.access")
CONNECTION_ID = "x"
CONNECTED = "connected"
NOT_CONNECTED = "not_connected"
NEEDS_RECONNECTING = "needs_reconnecting"
LEASE_POLL_SECONDS = 0.2


class AnnouncementError(Exception):
    """A refusal the console shows in plain words. ``code`` is stable; ``message`` is for the owner."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ParameterStore(Protocol):
    def get(self, name: str) -> str | None: ...
    def put(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class ConnectionStore(Protocol):
    def get(self) -> dict[str, Any] | None: ...
    def save(self, fields: dict[str, Any]) -> None: ...
    def acquire_lease(self, holder: str, now: float, until: float) -> bool: ...
    def release_lease(self, holder: str) -> None: ...


class PauseStore(Protocol):
    def pause(self, reason: str, detail: str, by: str, at: str) -> None: ...
    def resume_if(self, reason: str) -> None: ...


@dataclass(frozen=True)
class XEndpoints:
    authorize_url: str
    token_url: str
    revoke_url: str
    api_base: str


def utc_iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def secret_name(site_id: str) -> str:
    return f"/papyrus/{site_id}/announcements/x/client-secret"


def refresh_token_name(site_id: str, account_id: str) -> str:
    return f"/papyrus/{site_id}/announcements/x/{account_id}/refresh-token"


def access_token_name(site_id: str, account_id: str) -> str:
    return f"/papyrus/{site_id}/announcements/x/{account_id}/access-token"


def _post_form(url: str, form: dict[str, str], client_id: str, client_secret: str) -> dict[str, Any]:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(form).encode(),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {basic}"},
    )
    return _send(request)


def _get_json(url: str, access_token: str) -> dict[str, Any]:
    return _send(urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"}))


def _send(request: urllib.request.Request) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        raise XRefused(error.code, error.read().decode(errors="replace")) from error
    except urllib.error.URLError as error:
        raise AnnouncementError("x_unreachable", f"X could not be reached: {error.reason}") from error
    return json.loads(body) if body else {}


class XRefused(Exception):
    """X answered with an error status. The body is X's own message; it holds no secret of ours."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"X answered {status}: {body}")
        self.status = status
        self.body = body

    @property
    def message(self) -> str:
        try:
            parsed = json.loads(self.body)
        except ValueError:
            return self.body
        return str(parsed.get("error_description") or parsed.get("detail") or parsed.get("error") or self.body)


class XAccounts:
    def __init__(self, *, site_id: str, endpoints: XEndpoints, parameters: ParameterStore, connection: ConnectionStore,
                 pauses: PauseStore, lease_seconds: float, clock: Any = time.time, sleep: Any = time.sleep) -> None:
        self.site_id = site_id
        self.endpoints = endpoints
        self.parameters = parameters
        self.connection = connection
        self.pauses = pauses
        self.lease_seconds = lease_seconds
        self.clock = clock
        self.sleep = sleep

    # --- the developer app -------------------------------------------------------------------------------

    def save_app(self, client_id: str, client_secret: str, by: str) -> dict[str, Any]:
        client_id, client_secret = client_id.strip(), client_secret.strip()
        if not client_id or not client_secret:
            raise AnnouncementError("app_keys_missing", "Enter both the client ID and the client secret from your X developer app.")
        self.parameters.put(secret_name(self.site_id), client_secret)
        self.connection.save({"clientId": client_id, "secretSavedAt": utc_iso(self.clock()), "secretSavedBy": by})
        return self.status()

    def _app(self) -> tuple[str, str]:
        row = self.connection.get() or {}
        client_id = row.get("clientId")
        client_secret = self.parameters.get(secret_name(self.site_id))
        if not client_id or not client_secret:
            raise AnnouncementError("app_keys_missing", "Save your X app's client ID and client secret first.")
        return client_id, client_secret

    # --- connecting --------------------------------------------------------------------------------------

    def _verifier(self, client_secret: str, nonce: str) -> str:
        return _b64(hmac.new(client_secret.encode(), b"pkce-verifier:" + nonce.encode(), hashlib.sha256).digest())

    def _state(self, client_secret: str, nonce: str) -> str:
        mac = _b64(hmac.new(client_secret.encode(), b"state:" + nonce.encode(), hashlib.sha256).digest())
        return f"{nonce}.{mac}"

    def begin(self, redirect_uri: str) -> dict[str, str]:
        """The address to send the owner to at X, and the state the browser must see again on the way back.

        The PKCE verifier is derived from the client secret and the state's nonce, so nothing has to be stored between the
        two steps and the verifier is never sent to the browser.
        """
        client_id, client_secret = self._app()
        nonce = secrets.token_urlsafe(24)
        verifier = self._verifier(client_secret, nonce)
        challenge = _b64(hashlib.sha256(verifier.encode()).digest())
        state = self._state(client_secret, nonce)
        query = urllib.parse.urlencode(
            {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "scope": " ".join(SCOPES),
             "state": state, "code_challenge": challenge, "code_challenge_method": "S256"},
            quote_via=urllib.parse.quote,
        )
        return {"authorizeUrl": f"{self.endpoints.authorize_url}?{query}", "state": state}

    def complete(self, code: str, state: str, redirect_uri: str, by: str) -> dict[str, Any]:
        client_id, client_secret = self._app()
        nonce, _, _ = state.partition(".")
        if not nonce or not hmac.compare_digest(self._state(client_secret, nonce), state):
            raise AnnouncementError("state_mismatch", "This connection did not start here. Choose Connect X account again.")
        try:
            tokens = _post_form(self.endpoints.token_url, {"grant_type": "authorization_code", "code": code,
                                "redirect_uri": redirect_uri, "code_verifier": self._verifier(client_secret, nonce)},
                                client_id, client_secret)
        except XRefused as error:
            raise AnnouncementError("x_refused", f"X did not accept the connection: {error.message}") from error
        missing = [name for name in ("access_token", "refresh_token") if not tokens.get(name)]
        if missing:
            raise AnnouncementError("x_no_refresh_token", "X did not return a refresh token. Check that the app asks for offline.access and try again.")
        granted = set(str(tokens.get("scope", "")).split())
        lacking = [scope for scope in SCOPES if scope not in granted]
        if lacking:
            raise AnnouncementError("scopes_missing", f"X did not grant: {', '.join(lacking)}. Check the app's permissions are Read and write.")
        try:
            profile = _get_json(f"{self.endpoints.api_base}/2/users/me", tokens["access_token"])["data"]
        except XRefused as error:
            raise AnnouncementError("x_refused", f"X would not show the account's profile: {error.message}") from error
        account_id, handle = str(profile["id"]), str(profile["username"])
        previous = (self.connection.get() or {}).get("accountId")
        if previous and previous != account_id:
            self._revoke_and_forget(previous, client_id, client_secret)
        now = self.clock()
        self.parameters.put(refresh_token_name(self.site_id, account_id), tokens["refresh_token"])
        self._store_access_token(account_id, tokens["access_token"], now + float(tokens["expires_in"]))
        self.connection.save({"accountId": account_id, "handle": handle, "scopes": sorted(granted), "status": CONNECTED,
                              "statusReason": None, "connectedAt": utc_iso(now), "connectedBy": by,
                              "lastRefreshAt": utc_iso(now), "lastRefreshError": None})
        self.pauses.resume_if("disconnected")
        return self.status()

    def disconnect(self, by: str) -> dict[str, Any]:
        row = self.connection.get() or {}
        account_id = row.get("accountId")
        if not account_id:
            raise AnnouncementError("not_connected", "No X account is connected.")
        client_id, client_secret = self._app()
        self._revoke_and_forget(account_id, client_id, client_secret)
        self.connection.save({"accountId": None, "handle": None, "scopes": [], "status": NOT_CONNECTED, "statusReason": None,
                              "connectedAt": None, "lastRefreshAt": None, "lastRefreshError": None})
        self.pauses.pause("disconnected", "The X account was disconnected.", by, utc_iso(self.clock()))
        return self.status()

    def _revoke_and_forget(self, account_id: str, client_id: str, client_secret: str) -> None:
        refresh = self.parameters.get(refresh_token_name(self.site_id, account_id))
        if refresh:
            try:
                _post_form(self.endpoints.revoke_url, {"token": refresh, "token_type_hint": "refresh_token"}, client_id, client_secret)
            except XRefused as error:
                raise AnnouncementError("x_refused", f"X would not revoke the token, so nothing was deleted: {error.message}") from error
        self.parameters.delete(refresh_token_name(self.site_id, account_id))
        self.parameters.delete(access_token_name(self.site_id, account_id))

    # --- tokens for posting ------------------------------------------------------------------------------

    def _store_access_token(self, account_id: str, token: str, expires_at: float) -> None:
        self.parameters.put(access_token_name(self.site_id, account_id), json.dumps({"token": token, "expiresAt": expires_at}))

    def _live_access_token(self, account_id: str) -> str | None:
        raw = self.parameters.get(access_token_name(self.site_id, account_id))
        if not raw:
            return None
        stored = json.loads(raw)
        return stored["token"] if stored["expiresAt"] > self.clock() else None

    def access_token(self) -> str:
        """A valid access token for the connected account, refreshing it (once, under the lease) when it has expired."""
        holder = secrets.token_hex(8)
        while True:
            row = self.connection.get() or {}
            account_id = row.get("accountId")
            if not account_id:
                raise AnnouncementError("not_connected", "No X account is connected.")
            if row.get("status") == NEEDS_RECONNECTING:
                raise AnnouncementError("needs_reconnecting", row.get("statusReason") or "The X connection needs to be made again.")
            token = self._live_access_token(account_id)
            if token:
                return token
            now = self.clock()
            if self.connection.acquire_lease(holder, now, now + self.lease_seconds):
                try:
                    token = self._live_access_token(account_id)  # another invocation may have refreshed while we waited
                    return token if token else self._refresh(account_id)
                finally:
                    self.connection.release_lease(holder)
            self.sleep(LEASE_POLL_SECONDS)

    def _refresh(self, account_id: str) -> str:
        client_id, client_secret = self._app()
        refresh = self.parameters.get(refresh_token_name(self.site_id, account_id))
        if not refresh:
            self._break("The stored token is missing.")
        try:
            tokens = _post_form(self.endpoints.token_url, {"grant_type": "refresh_token", "refresh_token": refresh}, client_id, client_secret)
        except XRefused as error:
            self._break(f"X refused to refresh the token: {error.message}")
        if not tokens.get("access_token") or not tokens.get("refresh_token"):
            self._break("X did not return new tokens.")
        now = self.clock()
        # The new single-use refresh token is saved before anything else can use the access token.
        self.parameters.put(refresh_token_name(self.site_id, account_id), tokens["refresh_token"])
        self._store_access_token(account_id, tokens["access_token"], now + float(tokens["expires_in"]))
        self.connection.save({"lastRefreshAt": utc_iso(now), "lastRefreshError": None})
        return tokens["access_token"]

    def _break(self, reason: str) -> None:
        now = utc_iso(self.clock())
        self.connection.save({"status": NEEDS_RECONNECTING, "statusReason": reason, "lastRefreshError": reason})
        self.pauses.pause("disconnected", reason, "system", now)
        raise AnnouncementError("needs_reconnecting", reason)

    # --- what the console shows --------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Everything the console may show of the connection. Never a secret."""
        row = self.connection.get() or {}
        return {
            "clientId": row.get("clientId"),
            "secretSaved": bool(row.get("secretSavedAt")),
            "secretSavedAt": row.get("secretSavedAt"),
            "connection": row.get("status") or NOT_CONNECTED,
            "handle": row.get("handle"),
            "accountId": row.get("accountId"),
            "scopes": row.get("scopes") or [],
            "connectedAt": row.get("connectedAt"),
            "lastRefreshAt": row.get("lastRefreshAt"),
            "refreshHealth": {"healthy": row.get("status") == CONNECTED, "error": row.get("lastRefreshError")},
        }

    def usage(self) -> dict[str, Any]:
        """X's own count of posts for the app (read only), so a mismatch with our spend counter is visible."""
        token = self.access_token()
        query = urllib.parse.urlencode({"usage.fields": "cap_reset_day,project_usage,project_cap"})
        try:
            data = _get_json(f"{self.endpoints.api_base}/2/usage/tweets?{query}", token).get("data", {})
        except XRefused as error:
            raise AnnouncementError("x_refused", f"X would not show usage: {error.message}") from error
        return {"postsThisCycle": data.get("project_usage"), "postCap": data.get("project_cap"), "capResetDay": data.get("cap_reset_day")}
