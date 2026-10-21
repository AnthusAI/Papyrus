"""Native Google/Cognito user sessions; IAM remains the explicit operator lane.

Only the OS credential store holds renewable secrets. Public selection metadata
lets child CLI/Tactus processes choose the same publication without token argv/env.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import os
from pathlib import Path
import secrets
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import webbrowser


class AuthError(ValueError):
    """Safe operator-facing message; never include provider payloads or secrets."""


class OAuthError(AuthError):
    def __init__(self, code: str, *, transient: bool = False):
        self.code = code
        self.transient = transient
        super().__init__("Sign-in provider temporarily unavailable; retry later." if transient else
                         "Newsroom session expired or was revoked; run `papyrus login`.")


def _https(value: str, label: str, *, origin: bool = False) -> None:
    if not isinstance(value, str):
        raise AuthError(f'Invalid {label}: a configured HTTPS URL is required.')
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or (origin and parsed.path not in ('', '/'))):
        raise AuthError(f'Invalid {label}: a configured HTTPS {"origin" if origin else "URL"} is required.')


@dataclass(frozen=True)
class AuthConfig:
    publication: str
    issuer: str
    client_id: str
    oauth_domain: str
    graphql_endpoint: str
    callback_uri: str
    refresh_lifetime_seconds: int | None = None

    def __post_init__(self):
        for name in ('publication', 'issuer', 'oauth_domain', 'graphql_endpoint'):
            _https(getattr(self, name), name, origin=name in ('publication', 'oauth_domain'))
        for name in ('publication', 'oauth_domain'):
            object.__setattr__(self, name, getattr(self, name).rstrip('/'))
        if not isinstance(self.callback_uri, str):
            raise AuthError('A registered loopback callback URI is required.')
        callback = urllib.parse.urlsplit(self.callback_uri)
        try:
            valid_port = callback.port is not None and 1024 <= callback.port <= 65535
        except ValueError:
            valid_port = False
        if (callback.scheme != 'http' or callback.hostname not in ('127.0.0.1', 'localhost') or not valid_port
                or callback.username or callback.password or callback.query or callback.fragment):
            raise AuthError('Native OAuth callback must be a registered HTTP URL on literal 127.0.0.1 or localhost with a fixed unprivileged port.')
        if not self.client_id or not isinstance(self.client_id, str):
            raise AuthError('A registered native OAuth client id is required.')
        if self.refresh_lifetime_seconds is not None and (type(self.refresh_lifetime_seconds) is not int or self.refresh_lifetime_seconds <= 0):
            raise AuthError('Configured refresh lifetime must be a positive number of seconds.')

    @property
    def key(self) -> str:
        # Full binding prevents cross-client/publication token reuse, even on a shared pool.
        public = asdict(self)
        public.pop('refresh_lifetime_seconds')
        return hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()


def state_dir() -> Path:
    path = Path(os.environ.get('PAPYRUS_CLI_STATE_DIR') or Path.home()/'.config'/'papyrus')
    if path.is_symlink():
        raise AuthError('CLI session metadata directory must not be a symlink.')
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.chmod(0o700)
    except OSError:
        raise AuthError('Unable to access private CLI session metadata; check directory permissions.') from None
    return path


def selection_path() -> Path:
    return state_dir()/'user-session.json'


def load_config(path: str | Path) -> AuthConfig:
    try:
        data = json.loads(Path(path).read_text())
        return AuthConfig(**data)
    except (OSError, TypeError, json.JSONDecodeError):
        raise AuthError('No valid native OAuth configuration. Ask the publication owner to configure a native client; use `papyrus login --config <public-config.json>`.') from None


def save_selection(config: AuthConfig) -> None:
    path = selection_path()
    temporary = path.with_name('selection-'+secrets.token_hex(8))
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(asdict(config), handle)
        os.replace(temporary, path)
    except OSError:
        raise AuthError('Unable to save public CLI session selection; check directory permissions.') from None
    finally:
        temporary.unlink(missing_ok=True)


def resolve_config(path: str | Path | None = None, publication: str | None = None) -> AuthConfig:
    configured = path or os.environ.get('PAPYRUS_CLI_AUTH_CONFIG')
    selected = selection_path()
    config = load_config(configured or (selected if selected.exists() else Path.cwd()/'.papyrus'/'cli-auth.json'))
    if publication and publication.rstrip('/') != config.publication.rstrip('/'):
        raise AuthError('Selected publication does not match native OAuth configuration; use its own --config file.')
    return config


def user_auth_requested() -> bool:
    explicit = os.environ.get('PAPYRUS_GRAPHQL_AUTH', '').strip().lower()
    if explicit not in ('', 'user', 'iam', 'guest'):
        raise AuthError('Unknown PAPYRUS_GRAPHQL_AUTH; choose user, iam, or the read-only guest lane explicitly.')
    if explicit:
        return explicit == 'user'
    # Do not create directories just to inspect whether a default session exists.
    root = Path(os.environ.get('PAPYRUS_CLI_STATE_DIR') or Path.home()/'.config'/'papyrus')
    return (root/'user-session.json').exists()


class KeychainStore:
    SERVICE = 'papyrus-newsroom-oauth'

    def __init__(self, backend=None):
        if backend is None:
            try:
                from .macos_keychain import MacOSKeychain
                backend = MacOSKeychain()
            except Exception:
                raise AuthError('macOS Keychain is unavailable. Use the configured CLI on an unlocked Mac; no plaintext credential fallback is supported.') from None
        from .macos_keychain import MacOSKeychain
        if not isinstance(backend, MacOSKeychain):
            raise AuthError('A supported OS secure credential store is required; plaintext/fallback backends are refused.')
        self.backend = backend

    def get(self, key):
        try:
            return self.backend.get_password(self.SERVICE, key)
        except Exception:
            raise AuthError('Unable to read OS secure credential storage; unlock it and retry.') from None

    def set(self, key, value):
        try:
            self.backend.set_password(self.SERVICE, key, value)
        except Exception:
            raise AuthError('Unable to save the session in OS secure credential storage; unlock it and retry login.') from None

    def delete(self, key):
        if self.get(key) is None:
            return
        try:
            self.backend.delete_password(self.SERVICE, key)
        except Exception:
            raise AuthError('Unable to remove the local OS credential; unlock the secure store and retry logout.') from None


@contextmanager
def session_lock(config: AuthConfig):
    # Rotation must read and replace the current secret under one process-shared lock.
    try:
        import fcntl
    except ImportError:
        raise AuthError('Process-safe user-session locking is currently supported on macOS and Linux.') from None
    lock_path = state_dir()/('session-'+config.key+'.lock')
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    except OSError:
        raise AuthError('Unable to open the private CLI session lock; check directory permissions.') from None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError:
            raise AuthError('Unable to lock the CLI session safely; retry after checking directory permissions.') from None
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class HTTPProvider:
    def post(self, url: str, fields: dict[str, str]) -> dict[str, Any]:
        _https(url, 'OAuth endpoint')
        request = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(),
                                         headers={'Content-Type':'application/x-www-form-urlencoded'}, method='POST')
        try:
            # Refuse redirects: bearer/refresh secrets may only go to the configured provider.
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *args, **kwargs):
                    return None
            opener = urllib.request.build_opener(NoRedirect())
            with opener.open(request, timeout=20) as response:
                raw = response.read(1024*1024)
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            try:
                payload = json.loads(error.read(4096))
                code = payload.get('error')
            except (ValueError, AttributeError):
                code = None
            if code == 'invalid_grant':
                raise OAuthError('invalid_grant') from None
            if error.code == 429 or error.code >= 500:
                raise OAuthError('temporarily_unavailable', transient=True) from None
            raise AuthError('OAuth request rejected. Check the registered native client/callback configuration; no provider payload was logged.') from None
        except (OSError, urllib.error.URLError):
            raise OAuthError('temporarily_unavailable', transient=True) from None
        except (ValueError, TypeError):
            raise AuthError('Sign-in provider returned an invalid response; retry without discarding your session.') from None


def receive_code(callback_uri: str, authorization_url: str, state: str, timeout: float) -> str:
    callback = urllib.parse.urlsplit(callback_uri)
    outcome: dict[str, str] = {}
    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # The request URL contains the authorization code.

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            valid = (parsed.path == (callback.path or '/') and query.get('state') == [state]
                     and ((len(query.get('code', [])) == 1 and bool(query['code'][0])) or len(query.get('error', [])) == 1))
            self.send_response(200 if valid else 400)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(b'Papyrus sign-in response received. You may close this page.' if valid else b'Invalid sign-in response.')
            if valid:
                outcome.update(code=query.get('code', [''])[0], error='denied' if query.get('error') else '')
    class CallbackServer(HTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(min(5, timeout))
            return connection, address
    try:
        # Preserve the exact registered redirect host in OAuth, but never resolve
        # it to choose the listening interface or bind to wildcard interfaces.
        server = CallbackServer(('127.0.0.1', callback.port), Callback)
    except OSError:
        raise AuthError('Native OAuth callback port is unavailable; close the conflicting login and retry.') from None
    with server:
        server.timeout = min(0.25, timeout)
        if not webbrowser.open(authorization_url):
            raise AuthError('Could not open the system browser. Run `papyrus login` in an interactive desktop session.')
        deadline = time.monotonic()+timeout
        while not outcome and time.monotonic() < deadline:
            server.handle_request()
    if not outcome:
        raise AuthError('Google sign-in timed out. Run `papyrus login` to try again.')
    if outcome.get('error') or not outcome.get('code'):
        raise AuthError('Google sign-in was declined. No session was saved.')
    return outcome['code']


class Session:
    def __init__(self, config: AuthConfig, *, store=None, provider=None, clock=time.time, receive=receive_code):
        self.config = config
        self.store = store if store is not None else KeychainStore()
        self.provider = provider if provider is not None else HTTPProvider()
        self.clock = clock
        self.receive = receive
        self._token = None
        self._expires = 0.0
        self._subject = None

    def _record(self):
        raw = self.store.get(self.config.key)
        if raw is None:
            raise AuthError('No newsroom session for this publication; run `papyrus login`.')
        try:
            record = json.loads(raw)
            if (not isinstance(record.get('refresh_token'), str) or not record['refresh_token']
                    or not isinstance(record.get('subject'), str) or not record['subject']
                    or not isinstance(record.get('label'), str)):
                raise ValueError()
            record['created_at'] = float(record['created_at'])
            if not math.isfinite(record['created_at']):
                raise ValueError()
            return record
        except (KeyError, ValueError, AttributeError, TypeError):
            raise AuthError('Stored newsroom session is invalid; run `papyrus login` to replace it.') from None

    def _consume(self, response, old=None):
        try:
            value = response['id_token']
            claims = json.loads(base64.urlsafe_b64decode(value.split('.')[1]+'==='))
            expected = self.config
            if (claims['iss'] != expected.issuer or claims['aud'] != expected.client_id or claims['token_use'] != 'id'
                    or not claims['sub'] or (old and claims['sub'] != old['subject']) or float(claims['exp']) <= self.clock()):
                raise ValueError()
            expires = min(float(claims['exp']), self.clock()+float(response['expires_in']))
            if not math.isfinite(expires) or not math.isfinite(float(response['expires_in'])) or expires <= self.clock():
                raise ValueError()
            refresh = response.get('refresh_token') or (old or {}).get('refresh_token')
            if not isinstance(refresh, str) or not refresh:
                raise ValueError()
        except (KeyError, ValueError, TypeError, IndexError, AttributeError):
            raise AuthError('Provider token does not match the configured newsroom identity/client. No new session was saved.') from None
        # Tokens arrive only from the configured TLS token endpoint; the API verifies
        # JWT signature/claims and permissions. Local decoded claims are display/binding only.
        record = {'subject':claims['sub'], 'label':str(claims.get('email') or claims['sub']),
                  'refresh_token':refresh, 'created_at':(old or {}).get('created_at', self.clock())}
        self.store.set(self.config.key, json.dumps(record))
        self._token, self._expires = value, expires
        self._subject = record['subject']
        return record

    def login(self):
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        fields = {'response_type':'code', 'client_id':self.config.client_id, 'redirect_uri':self.config.callback_uri,
                  'scope':'openid email profile', 'identity_provider':'Google', 'state':state,
                  'code_challenge':challenge, 'code_challenge_method':'S256'}
        url = self.config.oauth_domain+'/oauth2/authorize?'+urllib.parse.urlencode(fields)
        code = self.receive(self.config.callback_uri, url, state, 180.0)
        with session_lock(self.config):
            record = self._consume(self.provider.post(self.config.oauth_domain+'/oauth2/token', {
                'grant_type':'authorization_code', 'client_id':self.config.client_id, 'code':code,
                'redirect_uri':self.config.callback_uri, 'code_verifier':verifier}))
        return {'subject':record['subject'], 'label':record['label'], 'publication':self.config.publication}

    def headers(self, endpoint):
        if endpoint != self.config.graphql_endpoint:
            raise AuthError('GraphQL endpoint does not match the signed-in publication; select its own login configuration, '
                            'or set PAPYRUS_GRAPHQL_AUTH=iam to use your AWS credentials for this endpoint instead.')
        with session_lock(self.config):
            record = self._record()  # Check even with a cached access token: local logout must win.
            if self._subject is not None and self._subject != record['subject']:
                self._token = None  # Another process explicitly signed in as a different person.
            if not self._token or self._expires <= self.clock()+60:
                try:
                    response = self.provider.post(self.config.oauth_domain+'/oauth2/token', {
                        'grant_type':'refresh_token', 'client_id':self.config.client_id, 'refresh_token':record['refresh_token']})
                except OAuthError as error:
                    if error.code == 'invalid_grant':
                        self.store.delete(self.config.key)
                        self._token = None
                    raise
                self._consume(response, record)
            return {'content-type':'application/json', 'Authorization':self._token}

    def status(self):
        try:
            record = self._record()
        except AuthError:
            # Locked/unavailable stores must remain errors, not fabricated signed-out state.
            if self.store.get(self.config.key) is not None:
                raise
            return {'signed_in':False, 'publication':self.config.publication}
        return {'signed_in':True, 'subject':record['subject'], 'label':record['label'], 'publication':self.config.publication,
                'access_expires_at':self._expires or None,
                'elapsed_session_seconds':max(0, self.clock()-record['created_at']),
                'configured_refresh_lifetime_seconds':self.config.refresh_lifetime_seconds,
                'elapsed_24h_live_verified':False}

    def logout(self):
        remote = 'not_needed'
        with session_lock(self.config):
            raw = self.store.get(self.config.key)
            try:
                if raw:
                    remote = 'unconfirmed'
                    record = self._record()
                    self.provider.post(self.config.oauth_domain+'/oauth2/revoke', {'client_id':self.config.client_id, 'token':record['refresh_token']})
                    remote = 'confirmed'
            except AuthError:
                pass
            finally:
                self.store.delete(self.config.key)
                self._token = None
                self._expires = 0.0
        # Keep public binding as a signed-out marker: never silently downgrade to IAM.
        return {'local_session_removed':True, 'remote_revocation':remote}


_sessions: dict[str, Session] = {}


def session_for(config):
    if config.key not in _sessions or _sessions[config.key].config != config:
        _sessions[config.key] = Session(config)
    return _sessions[config.key]


def selected_headers(endpoint):
    if not user_auth_requested():
        return None
    return session_for(resolve_config()).headers(endpoint)


def command(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog='papyrus')
    commands = parser.add_subparsers(dest='action', required=True)
    for name in ('login', 'logout', 'whoami'):
        sub = commands.add_parser(name)
        sub.add_argument('--config')
        sub.add_argument('--publication')
    auth = commands.add_parser('auth')
    auth.add_argument('operation', choices=['status'])
    auth.add_argument('--config')
    auth.add_argument('--publication')
    args = parser.parse_args(arguments)
    config = resolve_config(args.config, args.publication)
    session = session_for(config)
    if args.action == 'login':
        result = session.login()
        save_selection(config)
    elif args.action == 'logout':
        result = session.logout()
    elif args.action == 'whoami':
        session.headers(config.graphql_endpoint)  # Renew normally, without AWS SSO.
        result = session.status()
    else:
        result = session.status()
    print(json.dumps(result, sort_keys=True))
    return 0
