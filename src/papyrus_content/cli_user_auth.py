"""Native Google/Cognito user sessions; IAM remains the explicit operator lane.

Only the OS credential store holds renewable secrets. A registry of public site
metadata lets child CLI/Tactus processes pick the signed-in site that owns a GraphQL
endpoint without token argv/env. Many sites can be signed in at once.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from cli_login.session import Session
from cli_login.target import Target
from cli_login.errors import AuthError, OAuthError  # noqa: F401 (OAuthError is re-exported)
from cli_login.locks import key_lock
from cli_login.oauth import receive_code
from cli_login.target import https_url as _https

# The secure-store namespace. On macOS it is the Keychain service name, so sessions written by earlier
# CLIs (service `papyrus-newsroom-oauth`, account = the per-site key) are found unchanged.
NAMESPACE = 'papyrus-newsroom-oauth'


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
    # The library's per-key lock (POSIX flock, Windows msvcrt); the registry is one more key.
    with key_lock(state_dir(), 'registry'):
        yield


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
            raise AuthError(f'{host} does not publish CLI login (its sign-in client does not register the CLI callback). '
                            'Deploy the site frontend that serves the file, or use `papyrus login --config <public-config.json>`.') from None
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


def _target(config: AuthConfig) -> Target:
    return Target(issuer=config.issuer, client_id=config.client_id, oauth_domain=config.oauth_domain,
                  token_endpoint=config.oauth_domain+'/oauth2/token', api_endpoint=config.graphql_endpoint,
                  key=config.key, namespace=NAMESPACE, callback_uri=config.callback_uri)


class SiteSession:
    """One site's signed-in session: the shared `cli_login.Session` plus what only Papyrus knows.

    The library owns the OAuth exchange, token checks, renewal, locking, secure storage and honest logout.
    This layer names the site in messages and adds the Papyrus-only status fields.
    """

    def __init__(self, config: AuthConfig, *, store=None, provider=None, clock=time.time, receive=receive_code):
        self.receive = receive
        self._config = config
        self._session = Session(_target(config), store=store, provider=provider, clock=clock,
                                receive=lambda *arguments: self.receive(*arguments), state_dir=state_dir(),
                                login_command=f'papyrus login {site_host(config)}', identity_provider='Google')

    @property
    def config(self) -> AuthConfig:
        return self._config

    @config.setter
    def config(self, config: AuthConfig) -> None:
        self._config = config
        self._session.target = _target(config)
        self._session.login_command = f'papyrus login {site_host(config)}'

    @property
    def store(self):
        return self._session.store

    @property
    def provider(self):
        return self._session.provider

    def login(self):
        result = self._session.login()
        return {'subject': result['subject'], 'label': result['label'], 'publication': self.config.publication}

    def headers(self, endpoint):
        if endpoint != self.config.graphql_endpoint:
            raise AuthError('GraphQL endpoint does not match the signed-in publication; log in to the site that owns it, '
                            'or set PAPYRUS_GRAPHQL_AUTH=iam to use your AWS credentials for this endpoint instead.')
        return self._session.headers(endpoint)

    def status(self):
        result = self._session.status() | {'publication': self.config.publication}
        if result['signed_in']:
            result |= {'configured_refresh_lifetime_seconds': self.config.refresh_lifetime_seconds,
                       'elapsed_24h_live_verified': False}
        return result

    def logout(self):
        # Keep the public binding as a signed-out marker: never silently downgrade to IAM.
        return self._session.logout()


_sessions: dict[str, SiteSession] = {}


def session_for(config):
    if config.key not in _sessions or _sessions[config.key].config != config:
        _sessions[config.key] = SiteSession(config)
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
        if name == 'login':
            sub.add_argument('--remote', action='store_true', help='sign in from another device (not available yet)')
    auth = commands.add_parser('auth')
    auth.add_argument('operation', choices=['status'])
    auth.add_argument('sites', nargs='*', metavar='site')
    auth.add_argument('--all', action='store_true')
    auth.add_argument('--config')
    auth.add_argument('--publication')
    args = parser.parse_args(arguments)
    if args.action == 'login':
        if args.remote:
            raise AuthError('Remote sign-in (`papyrus login --remote`) is not available yet: the sites do not publish '
                            'a sign-in broker. Run `papyrus login <site>` on a machine with a browser.')
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
