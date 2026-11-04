"""Dependency-free validation shared by editor intake and its cloud handoff."""
import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .staff_groups import claim_groups, has_editor_rights

# Set (exactly "true") on a backend that carries a PAPYRUS_TENANT_ID but serves one publication only: its knowledge data
# is then that publication's, so the tenant does not mean the data is shared. Remove it if a second publication is ever added.
SINGLE_PUBLICATION_FLAG = "PAPYRUS_SINGLE_PUBLICATION_BACKEND"


class IntakeError(ValueError):
    pass


def canonical_source_url(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) <= 32 for c in value):
        raise IntakeError("source_uri must be an HTTP(S) URL without whitespace.")
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"https", "http"} or not parts.hostname or parts.username or parts.password:
            raise ValueError()
        host = parts.hostname.encode("idna").decode("ascii").lower()
        if ":" in host:
            host = f"[{host}]"
        port = parts.port
        if port is not None and port != {"http": 80, "https": 443}[parts.scheme.lower()]:
            host += f":{port}"
        # Preserve path/query semantics; fragments never identify a fetched resource.
        return urlunsplit((parts.scheme.lower(), host, parts.path or "/", parts.query, ""))
    except (ValueError, UnicodeError) as error:
        raise IntakeError("source_uri must be a valid HTTP(S) URL without credentials.") from error


def _actor(identity: dict[str, Any]) -> str:
    if not isinstance(identity, dict):
        raise IntakeError("A validated publication identity is required.")
    claims = identity.get("claims") or {}
    if not isinstance(claims, dict):
        raise IntakeError("Validated publication claims are required.")
    issuer = os.environ.get("PAPYRUS_USER_POOL_ISSUER", "")
    subject = identity.get("sub")
    groups = claim_groups(claims.get("cognito:groups"))  # AppSync can expose this claim as a string
    if (not issuer or identity.get("issuer") != issuer or claims.get("iss") != issuer
            or not isinstance(subject, str) or not subject or claims.get("sub") != subject
            or not has_editor_rights(groups)):
        raise IntakeError(
            "A validated editor of this publication is required. Operators without an editor session can run "
            "`papyrus references create-from-catalog --status pending` with IAM credentials "
            "(PAPYRUS_GRAPHQL_AUTH=iam), then curate the pending references through delegated curation."
        )
    if claims.get("tenantId") or claims.get("custom:tenantId"):
        raise IntakeError(
            "Reference intake is refused for a session that carries a tenant: knowledge data has no tenant isolation."
        )
    if os.environ.get("PAPYRUS_TENANT_ID") and os.environ.get(SINGLE_PUBLICATION_FLAG) != "true":
        raise IntakeError(
            "This backend is configured with a tenant, so Reference intake is refused unless the backend serves exactly "
            f"one publication. If it does, set {SINGLE_PUBLICATION_FLAG}=true in the site's cms.environment and redeploy; "
            "an operator can instead run `papyrus references create-from-catalog --status pending` with IAM credentials "
            "(PAPYRUS_GRAPHQL_AUTH=iam)."
        )
    return subject

