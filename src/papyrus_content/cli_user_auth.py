"""Native Google/Cognito user sessions; IAM remains the explicit operator lane.

Only the OS credential store holds renewable secrets. A registry of public site
metadata lets child CLI/Tactus processes pick the signed-in site that owns a GraphQL
endpoint without token argv/env. Many sites can be signed in at once.
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
    def __init__(self, code: str, *, transient: bool = False, site: str | None = None):
        self.code = code
        self.transient = transient
        login = 'papyrus login' + (f' {site}' if site else '')
        super().__init__("Sign-in provider temporarily unavailable; retry later." if transient else
                         f"Newsroom session expired or was revoked; run `{login}`.")


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
    # Historic file name: it held one selected publication; it now holds the registry of signed-in sites.
    return state_dir()/'user-session.json'


def site_host(config: AuthConfig) -> str:
    return urllib.parse.urlsplit(config.publication).netloc


def normalize_site(value: str) -> str:
    """A site given as `shipped.anth.us` or `https://shipped.anth.us/` becomes its HTTPS origin."""
    text = (value or '').strip()
    if '://' not in text:
        text = 'https://'+text
    try:
        _https(text, 'site', origin=True)
    except AuthError:
        raise AuthError('Site must be a host name such as shipped.anth.us or an https origin with no path, query or credentials.') from None
    parts = urllib.parse.urlsplit(text)
    return 'https://'+parts.netloc.lower()


def load_config(path: str | Path) -> AuthConfig:
    try:
        data = json.loads(Path(path).read_text())
        return AuthConfig(**data)
    except (OSError, TypeError, json.JSONDecodeError):
        raise AuthError('No valid native OAuth configuration. Ask the publication owner to configure a native client; use `papyrus login <site>` or `papyrus login --config <public-config.json>`.') from None


@contextmanager
def _registry_lock():
    try:
        import fcntl
    except ImportError:
        raise AuthError('Process-safe user-session locking is currently supported on macOS and Linux.') from None
    try:
        fd = os.open(state_dir()/'registry.lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    except OSError:
        raise AuthError('Unable to open the private CLI session lock; check directory permissions.') from None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    except OSError:
        raise AuthError('Unable to lock the CLI session registry safely; retry after checking directory permissions.') from None
    finally:
        os.close(fd)


def load_registry() -> list[AuthConfig]:
    """Public metadata of every site the CLI has been signed in to (signed-out sites stay listed)."""
    path = selection_path()
    if path.is_symlink():
        raise AuthError('CLI session registry must not be a symlink.')
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        # A pre-registry file held one config at the top level; read it as a one-site registry.
        entries = data['sites'] if isinstance(data, dict) and 'sites' in data else [data]
        configs = [AuthConfig(**entry) for entry in entries]
    except (OSError, TypeError, KeyError, ValueError):
        raise AuthError('CLI session registry is unreadable; sign in again with `papyrus login <site>`.') from None
    return configs


def _write_registry(configs: list[AuthConfig]) -> None:
    path = selection_path()
    temporary = path.with_name('selection-'+secrets.token_hex(8))
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump({'version': 2, 'sites': [asdict(config) for config in configs]}, handle)
        os.replace(temporary, path)
    except OSError:
        raise AuthError('Unable to save public CLI session registry; check directory permissions.') from None
    finally:
        temporary.unlink(missing_ok=True)


def save_selection(config: AuthConfig) -> None:
    """Add or update a site in the registry. Public metadata only; also migrates a pre-registry file."""
    with _registry_lock():
        sites = load_registry()
        for other in sites:
            if other.publication != config.publication and other.graphql_endpoint == config.graphql_endpoint:
                raise AuthError(f'GraphQL endpoint is already registered for {site_host(other)}; refusing to register it for {site_host(config)}. '
                                f'Run `papyrus logout {site_host(other)}` first if that site really moved.')
        _write_registry([other for other in sites if other.publication != config.publication]+[config])


def registered_site(site: str) -> AuthConfig:
    origin = normalize_site(site)
    for config in load_registry():
        if config.publication == origin:
            return config
    raise AuthError(f'Not signed in to {origin[len("https://"):]}; run `papyrus login {origin[len("https://"):]}`.')


DISCOVERY_PATH = '/.well-known/papyrus-cli.json'
DISCOVERY_MAX_BYTES = 16*1024
_PUBLIC_FIELDS = {'publication', 'issuer', 'client_id', 'oauth_domain', 'graphql_endpoint', 'callback_uri'}
_OPTIONAL_FIELDS = {'refresh_lifetime_seconds'}


def discover(site: str, *, opener=None) -> AuthConfig:
    """Fetch a site's public login values: HTTPS only, no redirects, size-capped, strict schema."""
    origin = normalize_site(site)
    host = origin[len('https://'):]
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = opener or urllib.request.build_opener(NoRedirect())
    request = urllib.request.Request(origin+DISCOVERY_PATH, headers={'Accept':'application/json'})
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(DISCOVERY_MAX_BYTES+1)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise AuthError(f'{host} does not publish CLI login (no native CLI client is configured for it). '
                            'Ask the site owner to enable it, or use `papyrus login --config <public-config.json>`.') from None
        raise AuthError(f'{host} did not serve its CLI login metadata (HTTP {error.code}); redirects are refused.') from None
    except (OSError, urllib.error.URLError, ValueError):
        raise AuthError(f'Could not reach {host} to read its CLI login metadata; check the name and your connection.') from None
    invalid = AuthError(f'{host} published invalid CLI login metadata; nothing was saved.')
    if len(raw) > DISCOVERY_MAX_BYTES:
        raise invalid
    try:
        data = json.loads(raw)
    except ValueError:
        raise invalid from None
    if not isinstance(data, dict) or not _PUBLIC_FIELDS <= set(data) or set(data) - _PUBLIC_FIELDS - _OPTIONAL_FIELDS:
        raise invalid
    try:
        config = AuthConfig(**data)
    except (AuthError, TypeError):
        raise invalid from None
    if config.publication != origin:
        raise AuthError(f'{host} published login metadata for a different publication; nothing was saved.')
    return config


def resolve_config(path: str | Path | None = None, publication: str | None = None) -> AuthConfig:
    """One config from an explicit file, the environment, the registry (when unambiguous) or ./.papyrus."""
    configured = path or os.environ.get('PAPYRUS_CLI_AUTH_CONFIG')
    if configured:
        config = load_config(configured)
    else:
        sites = load_registry()
        if publication:
            sites = [site for site in sites if site.publication == publication.rstrip('/')] or sites
        if len(sites) > 1:
            raise AuthError('Several sites are signed in ('+', '.join(site_host(site) for site in sites)+'); name one, e.g. `papyrus whoami '+site_host(sites[0])+'`.')
        config = sites[0] if sites else load_config(Path.cwd()/'.papyrus'/'cli-auth.json')
    if publication and publication.rstrip('/') != config.publication.rstrip('/'):
        raise AuthError('Selected publication does not match native OAuth configuration; use its own --config file.')
    return config


def config_for_endpoint(endpoint: str) -> AuthConfig:
    """The signed-in site whose GraphQL endpoint this is; never a site for a different endpoint."""
    if os.environ.get('PAPYRUS_CLI_AUTH_CONFIG'):
        return resolve_config()
    sites = load_registry()
    if not sites:
        return resolve_config()
    matches = [site for site in sites if site.graphql_endpoint == endpoint]
    if not matches:
        raise AuthError(f'No signed-in Papyrus site uses GraphQL endpoint {endpoint}. Signed in: '+', '.join(site_host(site) for site in sites)
                        +'. Run `papyrus login <site>` for the site that owns this endpoint, '
                        'or set PAPYRUS_GRAPHQL_AUTH=iam to use your AWS credentials for it instead.')
    return matches[0]


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
            raise AuthError(f'No newsroom session for {site_host(self.config)}; run `papyrus login {site_host(self.config)}`.')
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
            raise AuthError(f'Stored newsroom session is invalid; run `papyrus login {site_host(self.config)}` to replace it.') from None

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
            raise AuthError('GraphQL endpoint does not match the signed-in publication; log in to the site that owns it, '
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
                    raise OAuthError(error.code, transient=error.transient, site=site_host(self.config)) from None
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
    return session_for(config_for_endpoint(endpoint)).headers(endpoint)


def _login_targets(args) -> list[AuthConfig]:
    targets: list[AuthConfig] = []
    if args.config or args.publication or not (args.sites or args.all):
        targets.append(resolve_config(args.config, args.publication))
    targets += [discover(site) for site in args.sites]
    if args.all:
        targets += load_registry()
    return list({config.publication: config for config in targets}.values())


def _existing_targets(args, *, all_by_default: bool) -> list[AuthConfig]:
    if args.config or args.publication:
        return [resolve_config(args.config, args.publication)]
    if args.sites:
        return [registered_site(site) for site in args.sites]
    sites = load_registry()
    if sites and (args.all or all_by_default):
        return sites
    return [resolve_config()]  # One signed-in site, or an actionable "name a site" error.


def _run_each(targets, action) -> int:
    failed = False
    for config in targets:
        try:
            result = action(config)
        except AuthError as error:
            if len(targets) == 1:
                raise
            failed = True
            result = {'publication': config.publication, 'error': str(error)}
        print(json.dumps(result, sort_keys=True))
    return 1 if failed else 0


def command(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog='papyrus')
    commands = parser.add_subparsers(dest='action', required=True)
    for name in ('login', 'logout', 'whoami'):
        sub = commands.add_parser(name)
        sub.add_argument('sites', nargs='*', metavar='site', help='host such as shipped.anth.us, or an https origin')
        sub.add_argument('--all', action='store_true', help='every site in the registry')
        sub.add_argument('--config')
        sub.add_argument('--publication')
    auth = commands.add_parser('auth')
    auth.add_argument('operation', choices=['status'])
    auth.add_argument('sites', nargs='*', metavar='site')
    auth.add_argument('--all', action='store_true')
    auth.add_argument('--config')
    auth.add_argument('--publication')
    args = parser.parse_args(arguments)
    if args.action == 'login':
        def log_in(config):
            result = session_for(config).login()
            save_selection(config)
            return result
        return _run_each(_login_targets(args), log_in)
    targets = _existing_targets(args, all_by_default=args.action != 'logout')
    if args.action == 'logout':
        return _run_each(targets, lambda config: session_for(config).logout() | {'publication': config.publication})
    def whoami(config):
        session = session_for(config)
        if args.action == 'whoami':
            session.headers(config.graphql_endpoint)  # Renew normally, without AWS SSO.
        return session.status()
    return _run_each(targets, whoami)
