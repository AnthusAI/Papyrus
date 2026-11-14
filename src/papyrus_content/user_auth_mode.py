"""Which GraphQL lane a process uses: the signed-in lane (the default) or a lane it names.

* `user` (the default): the person signed in with `papyrus login <site>`, whose site broker issued a Cognito token.
* `iam`: the process's own AWS credentials (SigV4). Only when named: `papyrus --auth iam ...` or `PAPYRUS_GRAPHQL_AUTH=iam`.
  Workers, scheduled jobs and deploy or CI steps that run as their own role name it in their definition.
* `guest`: read-only published content for `ops content export-published`.

Nothing falls back from one lane to another: with no lane named and no `papyrus login` session, a request refuses with
`NOT_SIGNED_IN` (PPY-5f119a).

Stdlib only. Lambda bundles ship `papyrus_content` without the CLI sign-in library (`cli_login`), so code that runs in
both places asks this module, and only imports `cli_user_auth` once a user session is actually used.
"""
from __future__ import annotations

import os
from pathlib import Path

LANE_VARIABLE = 'PAPYRUS_GRAPHQL_AUTH'
LANES = ('user', 'iam', 'guest')

NOT_SIGNED_IN = ('Not signed in: run `papyrus login <site>`. A job that runs as its own AWS role (a worker, a deploy or CI step) '
                 'declares the operator lane instead: `papyrus --auth iam <group> <command>`, or PAPYRUS_GRAPHQL_AUTH=iam.')


def graphql_lane() -> str:
    """The lane this process uses: the one named in PAPYRUS_GRAPHQL_AUTH, else the signed-in lane."""
    explicit = os.environ.get(LANE_VARIABLE, '').strip().lower()
    if explicit and explicit not in LANES:
        from cli_login.errors import AuthError
        raise AuthError('Unknown PAPYRUS_GRAPHQL_AUTH; choose user, iam, or the read-only guest lane explicitly.')
    return explicit or 'user'


def user_auth_requested() -> bool:
    return graphql_lane() == 'user'


def iam_requested() -> bool:
    return graphql_lane() == 'iam'


def signed_in_anywhere() -> bool:
    """True when `papyrus login` has registered at least one site (or a native client config is named explicitly)."""
    if os.environ.get('PAPYRUS_CLI_AUTH_CONFIG'):
        return True
    # Do not create directories just to inspect whether a session exists.
    root = Path(os.environ.get('PAPYRUS_CLI_STATE_DIR') or Path.home()/'.config'/'papyrus')
    return (root/'user-session.json').exists()
