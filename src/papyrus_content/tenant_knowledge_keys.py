"""The one builder of the keys the knowledge models carry their tenant in (PPY-ce6207).

Which keys get the tenant depends on the stack's tenancy mode (``tenancy.is_shared_stack``):

* A DEDICATED stack never changes a key, even when it has a fixed tenant id. Every key is byte for byte what it was.
* A SHARED stack puts the tenant in front of a global key value (``<tenant>#references``) and makes a corpus id
  ``<tenant>.<corpus>``; every key that starts with a corpus id (the feed, star, medium, content-needed and public keys,
  the corpus indexes) is tenant-safe from there with no change. A key built with no tenant raises ``TenantKeyError``;
  nothing defaults to a tenant, and there is no fallback to the unprefixed key.

Writers and readers both build through these functions; no caller writes a global key or a corpus id by hand. The
tenant is the argument, else the one configured for the process (``PAPYRUS_TENANT_ID`` or the signed-in site's). A
function that serves several tenants (a shared stack's Lambda) always passes the tenant of its TenantContext.

TypeScript twin: ``lib/tenant-knowledge-keys.ts``. Both are tested against the ``tenant`` cases of
``scripts/fixtures/reference-feed-key-vectors.json``.
"""
from __future__ import annotations

import re

from .tenancy import TENANT_KEY_SEPARATOR, TenantError, configured_tenant_id, is_shared_stack, validate_tenant_id

CORPUS_SEPARATOR = "."
KNOWLEDGE_CORPUS_PREFIX = "knowledge-corpus-"
_TENANT_CORPUS = re.compile(r"^([a-z0-9][a-z0-9-]{0,62})\.(?=knowledge-corpus-)")

#: The global feed keys of the knowledge models (the stored value of ``newsroomFeedKey`` / ``reviewedFeedKey``).
REFERENCE_FEED_KEY = "references"
REFERENCE_REVIEWED_FEED_KEY = "references#reviewed"
SEMANTIC_NODE_FEED_KEY = "semanticNodes"
SEMANTIC_RELATION_FEED_KEY = "semanticRelations"
REFERENCE_LINK_FEED_KEY = "reference-links"


class TenantKeyError(TenantError):
    """A shared stack was asked for a key and no tenant was named."""


def key_tenant(tenant_id: str | None = None) -> str | None:
    """The tenant that prefixes keys on this stack: None on a dedicated stack (keys never change), the validated tenant on a shared one.

    A shared stack with no tenant raises; it never falls back to an unprefixed key."""
    if not is_shared_stack():
        return None
    tenant = tenant_id or configured_tenant_id()
    if not tenant:
        raise TenantKeyError("A shared stack builds no knowledge key without a tenant: name the tenant (--tenant, PAPYRUS_TENANT_ID, or the call's tenant context).")
    return validate_tenant_id(tenant)


def global_key(value: str, tenant_id: str | None = None) -> str:
    """A key value that is the same for every tenant today (a feed name), as this stack stores it: ``<tenant>#<value>`` on a shared stack."""
    tenant = key_tenant(tenant_id)
    if tenant is None:
        return value
    prefix = f"{tenant}{TENANT_KEY_SEPARATOR}"
    return value if value.startswith(prefix) else f"{prefix}{value}"


def tenant_corpus_id(corpus_id: str, tenant_id: str | None = None) -> str:
    """A corpus id as this stack stores it: unchanged on a dedicated stack, ``<tenant>.<corpus id>`` on a shared one."""
    tenant = key_tenant(tenant_id)
    if tenant is None:
        return corpus_id
    prefix = f"{tenant}{CORPUS_SEPARATOR}"
    return corpus_id if corpus_id.startswith(prefix) else f"{prefix}{corpus_id}"


def tenant_unique_id(record_id: str, tenant_id: str | None = None) -> str:
    """A record id that is built from a key the same for every tenant (a concept's lineage id from its node key), as this stack stores it:
    unchanged on a dedicated stack, ``<tenant>.<record id>`` on a shared one, so two tenants' concepts never share an id."""
    return tenant_corpus_id(record_id, tenant_id)


def corpus_key_of(corpus_id: str) -> str:
    """The corpus key a stored corpus id names (``knowledge-corpus-<key>`` with the tenant and the prefix removed). Pure: needs no mode."""
    bare = _TENANT_CORPUS.sub("", corpus_id, count=1)
    return bare.removeprefix(KNOWLEDGE_CORPUS_PREFIX)


def corpus_id_for_key(corpus_key: str, tenant_id: str | None = None) -> str:
    """The stored corpus id of a corpus key: ``knowledge-corpus-<key>``, tenant-prefixed on a shared stack."""
    return tenant_corpus_id(f"{KNOWLEDGE_CORPUS_PREFIX}{corpus_key}", tenant_id)


def is_corpus_id(value: str) -> bool:
    """True for a stored corpus id in either form (so a command can tell an id from a key)."""
    return _TENANT_CORPUS.sub("", value, count=1).startswith(KNOWLEDGE_CORPUS_PREFIX)


def own_corpora(rows, tenant_id: str | None = None) -> list:
    """The corpus rows that belong to this stack's tenant: every row on a dedicated stack, only ``<tenant>.<corpus id>`` rows on a shared one
    (the role index lists every tenant's canonical corpus, so a publication lookup keeps its own)."""
    tenant = key_tenant(tenant_id)
    if tenant is None:
        return list(rows)
    prefix = f"{tenant}{CORPUS_SEPARATOR}"
    return [row for row in rows if str(row.get("id") or "").startswith(prefix)]
