"""A fake X: the OAuth 2.0 token, revoke, profile and usage endpoints on a local port. No real call to X is ever made."""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

SCOPES = "tweet.write tweet.read users.read offline.access"


class FakeX:
    def __init__(self, handle: str = "mom_test", user_id: str = "1001") -> None:
        self.handle, self.user_id = handle, user_id
        self.requests: list[dict[str, Any]] = []
        self.issued = 0
        self.refresh_delay = 0.0
        self.refuse_refresh = False
        self.codes: dict[str, dict[str, str]] = {}
        self.valid_refresh: set[str] = set()
        self.expires_in = 7200
        self._lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # silent
                pass

            def _answer(self, status: int, body: dict[str, Any]) -> None:
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                form = {key: values[0] for key, values in urllib.parse.parse_qs(self.rfile.read(length).decode()).items()}
                fake.requests.append({"path": self.path, "form": form, "authorization": self.headers.get("Authorization")})
                if self.path == "/2/oauth2/token":
                    status, body = fake._token(form)
                    self._answer(status, body)
                elif self.path == "/2/oauth2/revoke":
                    fake.valid_refresh.discard(form.get("token", ""))
                    self._answer(200, {"revoked": True})
                else:
                    self._answer(404, {"error": "not found"})

            def do_GET(self) -> None:
                fake.requests.append({"path": self.path, "authorization": self.headers.get("Authorization")})
                if self.path.startswith("/2/users/me"):
                    self._answer(200, {"data": {"id": fake.user_id, "username": fake.handle}})
                elif self.path.startswith("/2/usage/tweets"):
                    self._answer(200, {"data": {"project_usage": "12", "project_cap": "2000", "cap_reset_day": 9}})
                else:
                    self._answer(404, {"error": "not found"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def approve(self, authorize_url: str) -> str:
        """The owner signs in at X and approves: returns the code X would send back to the callback."""
        query = {key: values[0] for key, values in urllib.parse.parse_qs(urllib.parse.urlparse(authorize_url).query).items()}
        code = f"code-{len(self.codes) + 1}"
        self.codes[code] = {"challenge": query["code_challenge"], "method": query["code_challenge_method"], "redirect": query["redirect_uri"]}
        return code

    def _next_tokens(self) -> dict[str, Any]:
        with self._lock:
            self.issued += 1
            number = self.issued
        refresh = f"refresh-{number}"
        self.valid_refresh.add(refresh)
        return {"access_token": f"access-{number}", "refresh_token": refresh, "expires_in": self.expires_in, "scope": SCOPES, "token_type": "bearer"}

    def _token(self, form: dict[str, str]) -> tuple[int, dict[str, Any]]:
        if form["grant_type"] == "authorization_code":
            grant = self.codes.pop(form["code"], None)
            if grant is None:
                return 400, {"error": "invalid_grant", "error_description": "Value passed for the authorization code was invalid."}
            digest = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).decode().rstrip("=")
            if grant["method"] != "S256" or digest != grant["challenge"] or form["redirect_uri"] != grant["redirect"]:
                return 400, {"error": "invalid_grant", "error_description": "code_verifier did not match."}
            return 200, self._next_tokens()
        time.sleep(self.refresh_delay)
        if self.refuse_refresh or form["refresh_token"] not in self.valid_refresh:
            return 400, {"error": "invalid_request", "error_description": "Value passed for the token was invalid."}
        self.valid_refresh.discard(form["refresh_token"])  # refresh tokens are single use
        return 200, self._next_tokens()

    def count(self, path: str) -> int:
        return sum(1 for request in self.requests if request["path"].split("?")[0] == path)
