"""``papyrus stories share``, ``stories shares`` and ``stories share-revoke`` (docs/story-share-links.md).

All three ask the newsroom's own mutations as the signed-in person (``papyrus login``), so the newsroom checks editor or admin on the server and records who made or ended a link.
They have no local fallback: a link is drawn by the site's own function, which the CLI does not have. The link is printed once, when it is made.
"""

from __future__ import annotations

import json
from typing import Any

from .graphql_authoring import create_authoring_client
from .operator_errors import GraphQLRequestError, OperatorError
from .options import normalize_string, parse_options, resolve_mutation_apply
from .story_shares import ANYONE, DEFAULT_EXPIRY_DAYS, EXPIRY_DAYS, SIGNED_IN

CREATE = "mutation CreateStoryShare($input: AWSJSON!) { createStoryShare(input: $input) }"
LIST = "query ListStoryShares($input: AWSJSON!) { listStoryShares(input: $input) }"
REVOKE = "mutation RevokeStoryShare($input: AWSJSON!) { revokeStoryShare(input: $input) }"
SIGN_IN_HINT = "Sharing a draft asks the newsroom as you: sign in with `papyrus login <site>` first (PAPYRUS_GRAPHQL_AUTH=user)."


def _required(options: dict, name: str) -> str:
    value = normalize_string(options.get(name))
    if not value:
        raise ValueError(f"--{name} is required.")
    return value


def _call(document: str, field: str, payload: dict[str, Any]) -> dict[str, Any]:
    from .user_auth_mode import user_auth_requested

    if not user_auth_requested():
        raise OperatorError(SIGN_IN_HINT)
    client, _ = create_authoring_client()
    try:
        answer = client.graphql(document, {"input": json.dumps(payload)}).get(field)
    except GraphQLRequestError as error:
        raise OperatorError(f"The newsroom refused the request: {str(error).splitlines()[0][:300]}") from error
    result = json.loads(answer) if isinstance(answer, str) else (answer or {})
    if result.get("ok") is not True:
        raise OperatorError("; ".join(str(entry.get("message") or entry) for entry in result.get("errors") or []) or "The newsroom did not accept the request.")
    result["_endpoint"] = getattr(client, "endpoint", None)
    return result


def _origin(endpoint: str | None) -> str | None:
    """The newsroom's address for the signed-in site: the link lives on the same host as the console."""
    if not endpoint:
        return None
    from .cli_user_auth import config_for_endpoint

    try:
        return config_for_endpoint(endpoint).publication.rstrip("/")
    except Exception:  # noqa: BLE001 - without an address the path is printed alone
        return None


def parse_expiry(options: dict) -> int:
    raw = options.get("expires")
    if raw is None:
        return DEFAULT_EXPIRY_DAYS
    try:
        days = int(str(raw).strip())
    except ValueError:
        days = -1
    if days not in EXPIRY_DAYS:
        raise ValueError(f"--expires is {', '.join(str(day) for day in EXPIRY_DAYS[:-1])} or {EXPIRY_DAYS[-1]} (days); there is no link that never expires.")
    return days


def stories_share(flags: list[str]) -> None:
    """papyrus stories share --story <lineage> [--version N] [--signed-in] [--expires 7|30|90] [--dry-run] [--json]

    Makes a share link: the Story, in the site's public layout, labelled DRAFT. By default anyone with the link can open it and it shows the Story's current version, following new
    versions; --version N shows that version only; --signed-in lets only signed-in editors and admins open it. It expires in 30 days unless --expires says 7 or 90. The URL is printed
    once and cannot be shown again (list the links with `stories shares`, end one with `stories share-revoke`)."""
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories share")
    lineage = _required(options, "story")
    version = normalize_string(options.get("version"))
    if version is not None and (not version.isdigit() or int(version) < 1):
        raise ValueError("--version is the number of a saved version.")
    viewers = SIGNED_IN if options.get("signed-in") else ANYONE
    days = parse_expiry(options)
    plan = {"lineageId": lineage, "viewers": viewers, "version": int(version) if version else "current", "expiresInDays": days}
    if not apply:
        print(json.dumps({"ok": True, "dryRun": True, "wouldShare": plan}, indent=2) if options.get("json") else
              f"stories\tshare\t{lineage}\t{viewers}\t{plan['version']}\texpires in {days} days\tdry run")
        return
    payload = {"lineageId": lineage, "viewers": viewers, "expiresInDays": days, **({"version": int(version)} if version else {})}
    result = _call(CREATE, "createStoryShare", payload)
    origin = _origin(result.get("_endpoint"))
    url = f"{origin}{result['path']}" if origin else result["path"]
    share = result["share"]
    if options.get("json"):
        print(json.dumps({"ok": True, "url": url, "share": share}, indent=2))
        return
    print(f"stories\tshare\t{lineage}\t{viewers}\t{share['version']}\texpires {share['expiresAt']}\tshare {share['shareId']}")
    print(url)
    print("stories\tshare\tThis URL is shown once and cannot be shown again. Anyone who has it " + ("and is signed in as an editor or admin " if viewers == SIGNED_IN else "") + "can open the draft until it expires or is revoked.")


def stories_shares(flags: list[str]) -> None:
    """papyrus stories shares --story <lineage> [--json]

    Lists a Story's share links: who made each, who can view, what it shows, when it expires and when it was last opened. Never a token or a URL."""
    options = parse_options(flags)
    lineage = _required(options, "story")
    result = _call(LIST, "listStoryShares", {"lineageId": lineage})
    shares = result.get("shares") or []
    if options.get("json"):
        print(json.dumps({"ok": True, "shares": shares}, indent=2))
        return
    if not shares:
        print(f"stories\tshares\t{lineage}\tno links")
    for share in shares:
        print("\t".join(["stories", "shares", str(share.get("shareId")), str(share.get("state")), f"by {share.get('createdBy') or 'unknown'}", str(share.get("viewers")),
                         f"version {share.get('version')}", f"expires {share.get('expiresAt')}", f"last opened {share.get('lastOpenedOn') or 'never'}", f"opened {share.get('openCount')}"]))


def stories_share_revoke(flags: list[str]) -> None:
    """papyrus stories share-revoke --story <lineage> --share <share id> [--dry-run] [--json]

    Ends a share link at once. The share id is the one `stories shares` lists."""
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "stories share-revoke")
    lineage, share_id = _required(options, "story"), _required(options, "share")
    if not apply:
        print(f"stories\tshare-revoke\t{lineage}\t{share_id}\tdry run")
        return
    result = _call(REVOKE, "revokeStoryShare", {"lineageId": lineage, "shareId": share_id})
    if options.get("json"):
        print(json.dumps({"ok": True, "changed": result.get("changed"), "share": result.get("share")}, indent=2))
        return
    print(f"stories\tshare-revoke\t{lineage}\t{share_id}\t{'revoked' if result.get('changed') else 'was already ended'}")
