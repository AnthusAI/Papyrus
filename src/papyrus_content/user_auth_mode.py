"""Which GraphQL lane a process uses: a signed-in user session, or IAM.

Stdlib only. Lambda bundles ship `papyrus_content` without the CLI sign-in library (`cli_login`), so code that
runs in both places asks this module, and only imports `cli_user_auth` once a user session is actually requested.
"""
from __future__ import annotations

import os
from pathlib import Path


def user_auth_requested() -> bool:
    explicit = os.environ.get('PAPYRUS_GRAPHQL_AUTH', '').strip().lower()
    if explicit not in ('', 'user', 'iam', 'guest'):
        from cli_login.errors import AuthError
        raise AuthError('Unknown PAPYRUS_GRAPHQL_AUTH; choose user, iam, or the read-only guest lane explicitly.')
    if explicit:
        return explicit == 'user'
    # Do not create directories just to inspect whether a default session exists.
    root = Path(os.environ.get('PAPYRUS_CLI_STATE_DIR') or Path.home()/'.config'/'papyrus')
    return (root/'user-session.json').exists()
