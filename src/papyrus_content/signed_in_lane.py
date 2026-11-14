"""The signed-in lane: commands that run on the `papyrus login` session alone, with no AWS credentials.

`monitoring_view_cli`, the signed-in side of `papyrus automations` and the signed-in side of `papyrus knowledge query`
share this. Nothing here imports boto3, reads an AWS profile or falls back to IAM: a missing session is a one-line
refusal. The shared fallback in `graphql_http.graphql_request_headers` is untouched (PPY-5f119a).
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .operator_errors import GraphQLRequestError

SIGN_IN = "Sign in with `papyrus login <site>` first."


class Refusal(Exception):
    """A one-line, operator-facing reason the command did not run."""


def endpoint(site: str | None = None) -> str:
    if site:
        from .cli_user_auth import registered_site
        return registered_site(site).graphql_endpoint
    from .env import graphql_endpoint
    try:
        return graphql_endpoint()
    except ValueError:
        from .cli_user_auth import resolve_config
        return resolve_config().graphql_endpoint


def signed_in_headers(target: str) -> dict[str, str]:
    """The signed-in user's headers for this endpoint. A missing session is an error, never IAM."""
    from .cli_user_auth import selected_headers
    found = selected_headers(target)
    if found is None:
        raise Refusal(f"Not signed in. {SIGN_IN}")
    return found


def client(site: str | None = None):
    """The shared authoring client, held to the signed-in user's headers."""
    from .graphql_authoring import PapyrusGraphQLAuthoringClient
    target = endpoint(site)
    return PapyrusGraphQLAuthoringClient(endpoint=target, header_factory=lambda _payload: signed_in_headers(target))


def fetch(graphql_client, query: str, field: str, variables: dict[str, Any], *, noun: str,
          forbidden: Callable[[], Refusal]) -> Any:
    """One query or mutation whose result is a JSON field. Errors become one-line refusals worded with `noun`."""
    try:
        data = graphql_client.graphql(query, variables)
    except GraphQLRequestError as error:
        text = str(error)
        if error.status_code in (401, 403) or any(word in text.lower() for word in ("unauthorized", "not authorized", "forbidden")):
            raise forbidden() from None
        raise Refusal(f"{noun} request failed: {text.splitlines()[0][:300]}") from None
    raw = data.get(field)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raise Refusal(f"{noun} response was not valid JSON.") from None
    if raw is None:
        raise Refusal(f"{noun} is unavailable: the site returned no data.")
    if isinstance(raw, dict) and raw.get("error"):
        if raw["error"] == "forbidden":
            raise forbidden()
        raise Refusal(f"{noun} refused the request: {raw['error']}.")
    return raw
