"""The name a signed-in person's checklist change is recorded under: the display name of their own newsroom profile, read on the server.

The console's checklist calls ``setStoryStep`` as the signed-in person. Their name is never taken from the request, which the browser controls and could set to
anyone's: the content-actions function reads the token's Cognito subject, finds the person's active identity (``UserIdentity``, by ``cognitoSub``) and reads the
display name of that profile (or of the profile it was merged into). That name is what a review stamp names, and so what a published page may name as its
reviewer (``published_reviewer.py`` still withholds a name shaped like an email address). A person with no identity or no display name yet is recorded under their
Cognito username, as before, which is never published when it is a UUID or an email address.

This module reads ``displayName`` only for this purpose; the home-page export keeps reading nothing of a profile but its opt-in handle.
"""
from __future__ import annotations

from typing import Any

IDENTITIES_BY_COGNITO_SUB_INDEX = "userIdentitiesByCognitoSub"
ACTIVE_IDENTITY_STATUS = "active"
PROFILE_NAME_FIELDS = "displayName mergedIntoProfileId"


def profile_display_name(client: Any, cognito_sub: str) -> str | None:
    """The display name of the signed-in person's own profile, or None when they have no active identity or their profile has no display name."""
    identity = next((row for row in client.list_by_index(IDENTITIES_BY_COGNITO_SUB_INDEX, cognito_sub)
                     if row.get("cognitoSub") == cognito_sub and row.get("status") == ACTIVE_IDENTITY_STATUS), None)
    if identity is None:
        return None
    profile = client.get_record_with_fields("UserProfile", identity["userProfileId"], PROFILE_NAME_FIELDS)
    if profile and profile.get("mergedIntoProfileId"):
        profile = client.get_record_with_fields("UserProfile", profile["mergedIntoProfileId"], PROFILE_NAME_FIELDS) or profile
    name = str((profile or {}).get("displayName") or "").strip()
    return name or None
