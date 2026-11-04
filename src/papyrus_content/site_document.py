"""What a site tells the CLI about itself beyond how to sign in: `/.well-known/papyrus-site.json`.

The sign-in file (`papyrus-cli.json`, read by `cli_user_auth.discover`) is strict: an unknown field makes every installed CLI
refuse the site. This second public file carries the rest, so it can grow without breaking anyone: the site's tenant id (only
when the site has one) and the Papyrus version it runs. A site that has not been upgraded serves no such file, and nothing
fails because of that. Everything here is public and is never a credential; the tenant scopes requests and authorizes nothing.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import urllib.error
import urllib.request

from .tenancy import TenantError, validate_tenant_id

SITE_DOCUMENT_PATH = '/.well-known/papyrus-site.json'
SITE_DOCUMENT_MAX_BYTES = 4*1024
SITE_DOCUMENT_TIMEOUT_SECONDS = 5
_VERSION = re.compile(r'^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.+-]{1,40})?$')
_not_served: set[str] = set()


def parse(raw: bytes) -> dict | None:
    """The known, valid fields of a site document, or None when it is not a usable document. Unknown fields are ignored."""
    if len(raw) > SITE_DOCUMENT_MAX_BYTES:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    found: dict = {}
    tenant, version = data.get('tenant_id'), data.get('papyrus_version')
    if tenant is not None:
        try:
            found['tenant_id'] = validate_tenant_id(tenant)
        except (TenantError, TypeError):
            return None
    if version is not None:
        if not isinstance(version, str) or not _VERSION.match(version):
            return None
        found['papyrus_version'] = version
    return found


def fetch(origin: str, *, opener=None) -> dict | None:
    """The site's document, or None for any reason it is unavailable: HTTPS only, no redirects, size-capped, never raises."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    if not origin.startswith('https://'):
        return None
    opener = opener or urllib.request.build_opener(NoRedirect())
    try:
        request = urllib.request.Request(origin+SITE_DOCUMENT_PATH, headers={'Accept': 'application/json'})
        with opener.open(request, timeout=SITE_DOCUMENT_TIMEOUT_SECONDS) as response:
            raw = response.read(SITE_DOCUMENT_MAX_BYTES+1)
    except (OSError, urllib.error.URLError, ValueError):
        return None
    return parse(raw)


def _path() -> Path:
    from .cli_user_auth import state_dir
    return state_dir()/'site-documents.json'


def cached() -> dict[str, dict]:
    """Every site document the CLI has kept, by site origin (public values; damage reads as empty)."""
    try:
        data = json.loads(_path().read_text())
    except (OSError, ValueError):
        return {}
    return {origin: entry for origin, entry in data.items() if isinstance(origin, str) and isinstance(entry, dict)} if isinstance(data, dict) else {}


def store(origin: str, document: dict) -> None:
    """Keep a site's document; best effort, because losing the cache only costs a fetch."""
    try:
        path = _path()
        entries = {**cached(), origin: document}
        temporary = path.with_name('site-documents-'+secrets.token_hex(8))
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as handle:
                json.dump(entries, handle)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    except (OSError, ValueError):
        return


def for_site(origin: str, *, refresh: bool = False, opener=None) -> dict:
    """What the site published, from the kept copy; fetched (and kept) when there is none or `refresh` asks for the current one.
    Empty when the site publishes no document, so a site that has not been upgraded is simply unknown."""
    if not refresh:
        kept = cached().get(origin)
        if kept is not None:
            return kept
        if origin in _not_served:
            return {}
    found = fetch(origin, opener=opener)
    if found is None:
        _not_served.add(origin)
        return cached().get(origin, {}) if refresh else {}
    _not_served.discard(origin)
    store(origin, found)
    return found
