from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any


def hash_stable(value: Any) -> str:
    if isinstance(value, str):
        payload = value
    else:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def hash_short(value: Any) -> str:
    return hash_stable(value)[:16]


def safe_id(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    normalized = normalized[:140] if normalized else ""
    return normalized or hash_short(value)


def knowledge_corpus_id(corpus: dict[str, Any], tenant_id: str | None = None) -> str:
    """The stored id of a corpus: ``knowledge-corpus-<key>``, ``<tenant>.knowledge-corpus-<key>`` on a shared stack (tenant_knowledge_keys)."""
    from .tenant_knowledge_keys import corpus_id_for_key
    key = corpus.get("key") or corpus.get("name") or corpus.get("corpus_uri") or "unknown"
    return corpus_id_for_key(safe_id(key), tenant_id)


def category_set_id_for(classifier_id: str, corpus_id: str) -> str:
    return f"category-set-{safe_id(corpus_id)}-{safe_id(classifier_id)}"


def category_lineage_id_for(category_set_id: str, category_key: str) -> str:
    return f"category-{safe_id(category_set_id)}-{safe_id(category_key)}"


def semantic_node_lineage_id_for(node_key: str, tenant_id: str | None = None) -> str:
    """A concept's lineage id. A node key is the same for every tenant, so on a shared stack the tenant is part of the id (``<tenant>.semantic-node-<key>``)."""
    from .tenant_knowledge_keys import tenant_unique_id
    return tenant_unique_id(f"semantic-node-{safe_id(node_key)}", tenant_id)


def reference_lineage_id_for(corpus_id: str, external_item_id: str) -> str:
    return f"reference-{safe_id(corpus_id)}-{safe_id(external_item_id)}"


def is_uuid_string(value: Any) -> bool:
    if not value:
        return False
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


def deterministic_uuid(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return str(uuid.UUID(bytes=digest[:16]))
