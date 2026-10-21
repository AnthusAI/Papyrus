"""The publication a backend serves is data: its one canonical KnowledgeCorpus.

    papyrus publication init --key <key> --name <name>

creates that corpus on a fresh backend (idempotent), so the editorial and catalog commands
need no repo steering file. A deploy can create it too (``ensure_publication_from_environment``).
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from typing import Any, Callable

from .ids import knowledge_corpus_id

CANONICAL_CORPUS_KIND = "canonical"
PUBLICATION_KEY_ENVIRONMENT = "PAPYRUS_PUBLICATION_CORPUS_KEY"
PUBLICATION_NAME_ENVIRONMENT = "PAPYRUS_PUBLICATION_NAME"
INIT_HINT = "papyrus publication init --key <key> --name <name>"


def _canonical_corpora(client) -> list[dict[str, Any]]:
    return [row for row in client.list_by_index("knowledgeCorporaByRoleAndName", CANONICAL_CORPUS_KIND) if row.get("role") == CANONICAL_CORPUS_KIND]


def ensure_publication(client, key: str, name: str | None = None) -> dict[str, Any]:
    """Create the canonical publication corpus when the backend has none. Safe to repeat."""
    key = (key or "").strip()
    if not key:
        raise ValueError("A publication key is required.")
    corpus_id = knowledge_corpus_id({"key": key})
    canonical = _canonical_corpora(client)
    if len(canonical) > 1:
        raise ValueError("The backend has more than one canonical corpus; resolve that before initializing a publication.")
    if canonical:
        if canonical[0].get("id") != corpus_id:
            served = str(canonical[0].get("id") or "").removeprefix("knowledge-corpus-")
            raise ValueError(f"This backend already serves publication {served}; refusing to also create {key}.")
        return {"created": False, "key": key, "corpusId": corpus_id, "name": canonical[0].get("name")}
    current = client.get_record("KnowledgeCorpus", corpus_id)
    if current:
        raise ValueError(f"Corpus {corpus_id} already exists with role {current.get('role')!r}, not {CANONICAL_CORPUS_KIND!r}; it is not changed.")
    display_name = (name or "").strip() or key
    now = datetime.now(timezone.utc).isoformat()
    client.create_record("KnowledgeCorpus", {
        "id": corpus_id, "name": display_name, "role": CANONICAL_CORPUS_KIND, "itemCount": 0, "createdAt": now, "updatedAt": now,
    })
    return {"created": True, "key": key, "corpusId": corpus_id, "name": display_name}


def ensure_publication_from_environment(client, environment: dict[str, str] | None = None) -> dict[str, Any] | None:
    """Deploy-time: create the publication corpus from the brand's corpus key when the backend names one."""
    env = os.environ if environment is None else environment
    key = (env.get(PUBLICATION_KEY_ENVIRONMENT) or "").strip()
    if not key:
        return None
    try:
        return ensure_publication(client, key, env.get(PUBLICATION_NAME_ENVIRONMENT))
    except ValueError as conflict:
        # A backend that already has a different publication is not the deploy's to change.
        print(f"publication\tensure\tskipped\t{conflict}")
        return None


def publication_init_command(flags: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="papyrus publication init")
    parser.add_argument("--key", required=True, help="Publication (corpus) key, e.g. my-publication.")
    parser.add_argument("--name", required=True, help="Publication display name.")
    args = parser.parse_args(flags)
    from .graphql_authoring import create_authoring_client

    client, _ = create_authoring_client()
    result = ensure_publication(client, args.key, args.name)
    print(f"publication\tinit\t{'created' if result['created'] else 'exists'}\t{result['key']}\t{result['corpusId']}")


def resolve_catalog_corpus(
    client,
    options: dict[str, Any],
    load_steering: Callable[[str | None], dict[str, Any] | None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The corpus a catalog registers into, plus the steering config when one applies.

    With ``--corpus-key`` and a steering file, the file governs (unchanged). Otherwise the backend's single
    canonical corpus is the publication; a given ``--corpus-key`` is then only an assertion about it.
    """
    from .editorial_context import hosted_publication
    from .steering import load_steering_config, require_corpus_config

    load_steering = load_steering or load_steering_config

    corpus_key = options.get("corpus-key")
    steering = load_steering(options.get("config")) if corpus_key or options.get("config") else None
    if steering is not None and corpus_key:
        return require_corpus_config(steering, corpus_key, "--corpus-key"), steering
    publication = hosted_publication(client, corpus_key if isinstance(corpus_key, str) else None)
    return {"key": publication["key"], "name": publication["name"], "role": CANONICAL_CORPUS_KIND}, steering


def publication_corpus_key(client, explicit: str | None = None) -> str:
    """`--corpus-key` when given, else the key of the backend's canonical publication corpus."""
    if explicit:
        return explicit
    from .editorial_context import hosted_publication

    return hosted_publication(client)["key"]
