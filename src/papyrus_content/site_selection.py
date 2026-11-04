"""Which signed-in Papyrus site a CLI command talks to, so a person needs no amplify_outputs.json to run it.

`install()` is called by the CLI entry points and nowhere else; `env.graphql_endpoint()` then asks `endpoint()`. A Lambda never
installs it, so a Lambda never reaches the sign-in registry. The order of choice:

1. the site named by `papyrus --site <host> ...` (it sets `PAPYRUS_SITE`), which must be signed in;
2. `PAPYRUS_GRAPHQL_ENDPOINT` (nothing here; it is used as it always was);
3. the site the working directory declares in `infra/site.json` (`cms.consoleOrigin`, else `cms.siteOrigin`), when signed in;
4. an `amplify_outputs.json` with an endpoint (nothing here; it is used as it always was);
5. the only signed-in site.

Steps 3 and 5 look at the registry only on the signed-in lane (`PAPYRUS_GRAPHQL_AUTH` unset with a session, or `user`), so an
operator who chose IAM is never sent to a signed-in site. Several signed-in sites and no choice is an error that lists them.
A token still goes only to the registered site that owns the endpoint (`cli_user_auth.config_for_endpoint`).
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys

from . import env, site_document
from .user_auth_mode import user_auth_requested

SITE_VARIABLE = 'PAPYRUS_SITE'
ENDPOINT_VARIABLE = 'PAPYRUS_GRAPHQL_ENDPOINT'
UPGRADE_HINT = 'Upgrade with `pipx upgrade papyrus-newsroom` (or `uv tool upgrade papyrus-newsroom`).'


@dataclass(frozen=True)
class Choice:
    config: object   # the registered `cli_user_auth.AuthConfig`
    reason: str


def install() -> None:
    env.install_site_selection(sys.modules[__name__])


def uninstall() -> None:
    env.install_site_selection(None)


def declared_origin() -> str | None:
    """The site origin the working directory's `infra/site.json` names (PAPYRUS_SITE_ROOT first), or None."""
    from .cli_user_auth import AuthError, normalize_site
    roots = []
    site_root = os.environ.get('PAPYRUS_SITE_ROOT', '').strip()
    if site_root:
        roots.append(Path(site_root))
    cwd = Path.cwd()
    roots += [cwd, *cwd.parents]
    for root in roots:
        path = root/'infra'/'site.json'
        if not path.is_file():
            continue
        try:
            cms = json.loads(path.read_text(encoding='utf-8')).get('cms') or {}
            return normalize_site(cms.get('consoleOrigin') or cms.get('siteOrigin') or '')
        except (OSError, ValueError, AttributeError, AuthError):
            return None
    return None


def outputs_endpoint() -> str | None:
    """The endpoint of the amplify_outputs.json that would be read, or None when there is no such file or it names none."""
    path = env.amplify_outputs_path()
    try:
        outputs = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return (outputs.get('data') or {}).get('url') or outputs.get('aws_appsync_graphqlEndpoint') or None


def choose() -> Choice | None:
    """The signed-in site the registry decides on, or None when the environment or an amplify_outputs.json decides."""
    from .cli_user_auth import AuthError, load_registry, registered_site, site_host
    named = os.environ.get(SITE_VARIABLE, '').strip()
    from_environment = os.environ.get(ENDPOINT_VARIABLE, '').strip()
    if named:
        config = registered_site(named)
        if from_environment and from_environment != config.graphql_endpoint:
            raise AuthError(f'{ENDPOINT_VARIABLE} names a different backend than {site_host(config)}, the site you chose. '
                            f'Unset {ENDPOINT_VARIABLE}, or drop the site choice, so only one of them speaks.')
        return Choice(config, f'the site you named ({site_host(config)})')
    if from_environment or not user_auth_requested():
        return None
    sites = load_registry()
    if not sites:
        return None
    declared = declared_origin()
    for config in sites:
        if declared and config.publication == declared:
            return Choice(config, f'the site this directory declares ({site_host(config)})')
    if outputs_endpoint():
        return None
    hosts = ', '.join(site_host(config) for config in sites)
    if declared:
        host = declared[len('https://'):]
        raise AuthError(f'This directory belongs to {host}, and you are not signed in to it (signed in: {hosts}). '
                        f'Run `papyrus login {host}`, or name a signed-in site with `papyrus --site <site> <group> <command>`.')
    if len(sites) > 1:
        raise AuthError(f'Several sites are signed in ({hosts}) and nothing says which one to use. Name one with '
                        f'`papyrus --site {site_host(sites[0])} <group> <command>` (or PAPYRUS_SITE), or run from the site\'s checkout.')
    return Choice(sites[0], f'the only signed-in site ({site_host(sites[0])})')


def endpoint() -> str | None:
    choice = choose()
    return choice.config.graphql_endpoint if choice else None


def accepts_outputs(outputs: dict) -> bool:
    """False for an amplify_outputs.json that names a different backend than the site chosen: its bucket and identity pool are
    not that site's, so they must not be used for it."""
    try:
        choice = choose()
    except ValueError:
        return True
    if choice is None:
        return True
    found = (outputs.get('data') or {}).get('url') or outputs.get('aws_appsync_graphqlEndpoint')
    return found == choice.config.graphql_endpoint


def tenant_for(endpoint: str | None = None) -> str | None:
    """The tenant published by the signed-in site that owns this endpoint (default: the one in use). Only on the signed-in lane."""
    from .cli_user_auth import load_registry
    try:
        if not user_auth_requested():
            return None
        target = endpoint or env.graphql_endpoint()
        owner = next((config for config in load_registry() if config.graphql_endpoint == target), None)
    except ValueError:
        return None
    return site_document.for_site(owner.publication).get('tenant_id') if owner else None


def _release(version: str) -> tuple[int, int, int] | None:
    parts = version.split('-')[0].split('+')[0].split('.')
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except (IndexError, ValueError):
        return None


def newer_site_hint(*, installed: str | None = None, sites=None, opener=None) -> str | None:
    """For an unknown command: the sentence naming a signed-in site that runs a newer Papyrus than this CLI, with the upgrade
    command. None when no site is newer, none publishes a version, or any lookup fails; a version never fails a command."""
    try:
        from .cli_doctor import installed_version
        from .cli_user_auth import load_registry, site_host
        current = installed or installed_version()
        mine = _release(current)
        newer = []
        for config in (load_registry() if sites is None else sites):
            theirs = site_document.for_site(config.publication, refresh=True, opener=opener).get('papyrus_version')
            if mine and theirs and _release(theirs) and _release(theirs) > mine:
                newer.append((site_host(config), theirs))
    except Exception:
        return None
    if not newer:
        return None
    runs = ' and '.join(f'{host} runs {version}' for host, version in newer)
    return f'This papyrus is {current}, and {runs}, so the command may exist there. '+UPGRADE_HINT


def unsupported_command(what: str) -> ValueError:
    """The error for a command this CLI does not know, carrying the upgrade hint when a signed-in site is newer."""
    hint = newer_site_hint()
    return ValueError(f'Unsupported papyrus {what}' + (f'\n{hint}' if hint else ''))


def older_cli_warning(config, *, installed: str | None = None, opener=None) -> str | None:
    """After a login: a line when this CLI is older than the site just signed in to. Never an error."""
    try:
        from .cli_doctor import installed_version
        from .cli_user_auth import site_host
        mine = installed or installed_version()
        theirs = site_document.for_site(config.publication, refresh=True, opener=opener).get('papyrus_version')
        if not theirs or not _release(theirs) or not _release(mine) or _release(theirs) <= _release(mine):
            return None
        return f'This papyrus is {mine}, older than {site_host(config)}, which runs {theirs}. '+UPGRADE_HINT
    except Exception:
        return None
