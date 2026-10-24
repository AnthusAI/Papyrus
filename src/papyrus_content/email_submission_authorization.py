"""Resolve editor eligibility from a publication's current Cognito directory.

The caller must provide a separately scoped Cognito user-pool id for every
publication. SES verdicts authenticate the From domain; this module additionally
requires the exact verified address to belong to an enabled user in the editor
group of the publication being considered.
"""
from __future__ import annotations

import re

USER_POOL_ID = re.compile(r"^[A-Za-z0-9-]+_[A-Za-z0-9]+$")
CONTENT_WRITE_GROUPS = frozenset({"editor", "admin"})


class EditorLookupUnavailable(RuntimeError):
    """Membership could not be checked; callers must fail closed and retry/report."""


def publication_ids_for_editor(sender: str, publications: list[dict], cognito) -> list[str]:
    """Return only publication ids where sender is a current, verified editor.

    Every candidate is looked up in that publication's own user pool. A single
    lookup error fails the whole resolution rather than silently routing to a
    partial or broader destination set.
    """
    sender = _normalize_email(sender)
    authorized = []
    try:
        for publication in publications:
            publication_id = publication.get("publicationId")
            pool_id = publication.get("userPoolId")
            if not isinstance(publication_id, str) or not publication_id or not isinstance(pool_id, str) or not USER_POOL_ID.fullmatch(pool_id):
                raise ValueError("publication editor user pool is invalid")
            if _is_verified_editor(sender, pool_id, cognito):
                authorized.append(publication_id)
    except EditorLookupUnavailable:
        raise
    except Exception as error:
        raise EditorLookupUnavailable("editor membership lookup unavailable") from error
    return authorized


def _is_verified_editor(sender: str, pool_id: str, cognito) -> bool:
    # Escape Cognito's quoted filter value so an address cannot alter the query.
    filter_value = sender.replace("\\", "\\\\").replace('"', '\\"')
    users = cognito.list_users(
        UserPoolId=pool_id,
        Filter=f'email = "{filter_value}"',
        AttributesToGet=["email", "email_verified"],
        Limit=2,
    ).get("Users", [])
    if len(users) != 1:
        return False
    user = users[0]
    attributes = {entry.get("Name"): entry.get("Value") for entry in user.get("Attributes", [])}
    user_email = attributes.get("email")
    if (user.get("Enabled") is not True or user_email is None
            or _normalize_email(user_email) != sender or attributes.get("email_verified", "").lower() != "true"):
        return False
    username = user.get("Username")
    if not isinstance(username, str) or not username:
        return False
    groups = cognito.admin_list_groups_for_user(UserPoolId=pool_id, Username=username).get("Groups", [])
    return any(group.get("GroupName") in CONTENT_WRITE_GROUPS for group in groups)


def _normalize_email(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("email address is invalid")
    normalized = value.strip().lower()
    if not normalized or any(character.isspace() for character in normalized) or normalized.count("@") != 1:
        raise ValueError("email address is invalid")
    return normalized
