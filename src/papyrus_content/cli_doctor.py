"""`papyrus doctor`: install, version and signed-in-site health. Prints no secrets or identities."""
from __future__ import annotations

import json
import re
import shutil
import sys
import urllib.request

from . import cli_user_auth as auth
from .cli_user_auth import AuthError, OAuthError, load_registry, site_host

PACKAGE = 'papyrus-newsroom'
INSTALL_HINT = f'pipx install {PACKAGE}   (or: uv tool install {PACKAGE})'


def installed_version() -> str:
    try:
        from importlib.metadata import version
        return version(PACKAGE)
    except Exception:
        from papyrus import __version__
        return __version__


def latest_version(*, opener=urllib.request.urlopen) -> str | None:
    """Latest release on PyPI, or None when offline or the lookup fails."""
    try:
        with opener(f'https://pypi.org/pypi/{PACKAGE}/json', timeout=3) as response:
            return str(json.loads(response.read(2*1024*1024))['info']['version'])
    except Exception:
        return None


def _numbers(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r'\d+', value.split('+')[0])[:4])


def install_kind(prefix: str | None = None, base_prefix: str | None = None) -> str:
    prefix, base_prefix = prefix or sys.prefix, base_prefix or sys.base_prefix
    normalized = prefix.replace('\\', '/')
    if '/pipx/venvs/' in normalized:
        return 'pipx tool install'
    if '/uv/tools/' in normalized:
        return 'uv tool install'
    if prefix != base_prefix:
        return 'virtualenv'
    return 'system Python'


def site_health(config) -> str:
    host = site_host(config)
    session = auth.session_for(config)
    try:
        if not session.status()['signed_in']:
            return f'signed out; run `papyrus login {host}`'
        session.headers(config.graphql_endpoint)
        return 'signed in, session valid'
    except OAuthError as error:
        if error.transient:
            return 'signed in, but the sign-in provider is unreachable right now (session kept)'
        return f'expired or revoked; run `papyrus login {host}`'
    except AuthError as error:
        return f'cannot verify: {error}'


def run(arguments: list[str], *, latest=latest_version) -> int:
    offline = '--offline' in arguments
    unknown = [value for value in arguments if value != '--offline']
    if unknown:
        raise ValueError('Usage: papyrus doctor [--offline]')
    problems = 0
    current = installed_version()
    newest = None if offline else latest()
    line = f'version\t{current}'
    if newest is None:
        line += '\t(latest version unknown: offline or PyPI unreachable)'
    elif _numbers(newest) > _numbers(current):
        line += f'\t(newer release {newest} available; upgrade with `pipx upgrade {PACKAGE}` or `uv tool upgrade {PACKAGE}`)'
    else:
        line += '\t(up to date)'
    print(line)
    kind = install_kind()
    on_path = shutil.which('papyrus')
    print(f'install\t{kind}')
    print(f'on-path\t{on_path or "no"}')
    if kind in ('virtualenv', 'system Python') or not on_path:
        print(f'hint\tfor `papyrus` on your PATH everywhere: {INSTALL_HINT}')
    try:
        sites = load_registry()
    except AuthError as error:
        print(f'sites\t{error}')
        return 1
    if not sites:
        print('sites\tnone signed in; run `papyrus login <site>` (for example `papyrus login shipped.anth.us`)')
    for config in sites:
        health = site_health(config)
        problems += 0 if health.startswith('signed in') else 1
        print(f'site\t{site_host(config)}\t{health}')
    return 1 if problems else 0
