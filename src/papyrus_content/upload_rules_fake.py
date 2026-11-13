"""The upload function's acceptance rules, for the in-memory fakes of the S3 side.

The real upload function (amplify/functions/model-attachment-upload) refuses an attachment whose role is not in its ``ALLOWED_ROLES`` or whose media type its rules do not allow
for that role. A fake that accepted any attachment hid that a role the Python side writes (``doctrine_document``) was never allowed on a deployed backend. The fakes call
``assert_upload_accepted`` so they refuse exactly what the function refuses: the lists are read from the function's own source, not copied here.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

FUNCTION = Path(__file__).resolve().parents[2] / "amplify/functions/model-attachment-upload"


def _block(text: str, name: str) -> str:
    found = re.search(rf"const {name}\b[^=]*=\s*new Set\(\[(.*?)\]\)", text, re.DOTALL)
    assert found, f"{name} not found in the upload function's source"
    return found.group(1)


@lru_cache(maxsize=1)
def _rules() -> dict:
    handler = (FUNCTION / "handler.ts").read_text()
    rules = (FUNCTION / "rules.ts").read_text()
    quoted = lambda text: set(re.findall(r'"([^"]+)"', text))
    pictures = re.search(r"VISUAL_MEDIA_TYPES[^=]*=\s*\{(.*?)\}", rules, re.DOTALL)
    return {
        "roles": quoted(_block(handler, "ALLOWED_ROLES")),
        "general": quoted(_block(handler, "ALLOWED_MEDIA_TYPES")),
        "picture_types": set(re.findall(r'"(image/[a-z]+)"', pictures.group(1))),
        "picture_roles": quoted(_block(rules, "VISUAL_ROLES")) | {re.search(r'CANDIDATE_PICTURE_ROLE = "([a-z_]+)"', rules).group(1)},
        "octet_roles": quoted(_block(rules, "OCTET_STREAM_ROLES").replace("DOCTRINE_ASSET_ROLE", '"doctrine_asset"')),
    }


def allowed_roles() -> set[str]:
    return set(_rules()["roles"])


def assert_upload_accepted(attachment: dict) -> None:
    """Raise what the upload function raises when it would refuse this attachment's role or media type."""
    rules = _rules()
    role, media_type = attachment["role"], str(attachment["mediaType"]).lower()
    if role not in rules["roles"]:
        raise RuntimeError(f"GraphQL request failed: Unsupported ModelAttachment role {role}.")
    allowed = ({"application/octet-stream"} if role in rules["octet_roles"] else rules["picture_types"] if role in rules["picture_roles"] else rules["general"])
    if media_type not in allowed:
        raise RuntimeError(f"GraphQL request failed: Unsupported ModelAttachment mediaType {media_type} for role {role}.")


def assert_owner_exists(attachment: dict, items: list[dict]) -> None:
    """Raise what the upload function raises when the Item an attachment is for does not exist yet (the fakes hold only Item owners).

    The function looks the owner up by id before it hands out an upload slot, so the row must be created first. The visual style profile's example pictures are owned by the
    lineage, not by one version: their owner exists when the profile has any version."""
    if attachment["ownerKind"] != "item":
        return
    rules = (FUNCTION / "rules.ts").read_text()
    lineage_owner = re.search(r'VISUAL_STYLE_OWNER_ID = "([^"]+)"', rules).group(1)
    lineage_slug = re.search(r'VISUAL_STYLE_SLUG = "([^"]+)"', rules).group(1)
    if attachment["ownerId"] == lineage_owner:
        if not any(row.get("slug") == lineage_slug for row in items):
            raise RuntimeError("GraphQL request failed: Cannot attach an example picture before the publication has a visual style profile. Save a profile first.")
        return
    if not any(row["id"] == attachment["ownerId"] for row in items):
        raise RuntimeError(f"GraphQL request failed: Cannot attach payload to missing Item {attachment['ownerId']}.")
