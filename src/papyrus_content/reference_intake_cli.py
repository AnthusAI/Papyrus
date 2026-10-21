"""User-session catalog intake uses a scoped action, never raw model writes."""
from __future__ import annotations

import json
from pathlib import Path

from .ids import knowledge_corpus_id
from .reference_intake import canonical_source_url
from .steering import load_steering_config, require_steering_config
from .publication import resolve_catalog_corpus

MUTATION = "mutation IntakePendingReferences($input: AWSJSON!) { intakePendingReferences(input: $input) }"


def register_pending_catalog(client, options: dict, *, apply: bool) -> None:
    if options.get("status", "pending") != "pending":
        raise ValueError("User-session catalog intake supports --status pending only; use editorial review for decisions.")
    if options.get("actor") or options.get("reason-code"):
        raise ValueError("Pending intake derives its actor from the signed-in publication session.")
    corpus, _ = resolve_catalog_corpus(
        client, options, lambda path: require_steering_config(path) if path else load_steering_config(None)
    )
    catalog = json.loads(Path(options["catalog"]).read_text(encoding="utf-8"))
    if not isinstance(catalog, dict) or not isinstance(catalog.get("items"), list):
        raise ValueError("The catalog must contain an items array.")
    items = []
    for source in catalog["items"]:
        if not isinstance(source, dict) or set(source) - {"source_uri", "item_id", "title", "media_type", "ingestion_rationale"}:
            raise ValueError("User-session intake accepts source_uri, item_id, title, media_type and ingestion_rationale only.")
        item = {**source, "source_uri": canonical_source_url(source.get("source_uri"))}
        item["ingestion_rationale"] = source.get("ingestion_rationale") or options.get("ingestion-rationale")
        if not item.get("title") or not item.get("ingestion_rationale"):
            raise ValueError("Every source needs a title and ingestion rationale.")
        items.append(item)
    if not items:
        raise ValueError("The catalog is empty.")
    print(f"references\tcreate-from-catalog\tintake\tuser-session\titems={len(items)}\tstatus=pending")
    if not apply:
        print("references\tcreate-from-catalog\tapply\tno (preview only; server authorization and deduplication not executed)")
        return
    for offset in range(0, len(items), 20):
        result = client.graphql(MUTATION, {"input": json.dumps({
            "publicationEndpoint": client.endpoint, "corpusId": knowledge_corpus_id(corpus),
            "items": items[offset:offset + 20],
        })}).get("intakePendingReferences")
        if isinstance(result, str):
            result = json.loads(result)
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise ValueError(f"Pending Reference intake rejected: {json.dumps(result)}")
        print(json.dumps(result, sort_keys=True))
