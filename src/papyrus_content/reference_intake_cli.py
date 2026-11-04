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
    # One source per request: the server takes up to 20, but one source takes 6 to 12 seconds, so a batch can
    # outlast the client's read timeout and leave the outcome unknown (PPY-856536). The server derives each
    # Reference id from the canonical URL, so repeating any request returns the same record.
    failed = []
    total = len(items)
    for number, item in enumerate(items, start=1):
        label = f"{number}/{total}\t{item['source_uri']}"
        try:
            result = client.graphql(MUTATION, {"input": json.dumps({
                "publicationEndpoint": client.endpoint, "corpusId": knowledge_corpus_id(corpus), "items": [item],
            })}).get("intakePendingReferences")
            if isinstance(result, str):
                result = json.loads(result)
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise ValueError(f"rejected: {json.dumps(result)}")
        except Exception as error:  # noqa: BLE001 - every failure is reported per item, then the run continues
            failed.append(item["source_uri"])
            print(f"references\tcreate-from-catalog\tfailed\t{label}\t{' '.join(str(error).split())[:300]}", flush=True)
            continue
        for reference in result.get("references") or [{}]:
            print(f"references\tcreate-from-catalog\trecorded\t{label}\t{reference.get('id') or '-'}\t{reference.get('curationStatus') or '-'}", flush=True)
    print(f"references\tcreate-from-catalog\tsummary\tconfirmed={total - len(failed)}\tnot-confirmed={len(failed)}", flush=True)
    if failed:
        raise ValueError(
            f"{len(failed)} of {total} sources were not confirmed (a timeout leaves the outcome unknown). Run the same command again: "
            "a source already recorded is returned unchanged and is not recurated."
        )
