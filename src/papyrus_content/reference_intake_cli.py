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
    created = existed = unknown = 0
    videos = 0
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
            reference_id, status = reference.get("id") or "-", reference.get("curationStatus") or "-"
            if reference.get("created") is True:
                created += 1
                print(f"references\tcreate-from-catalog\tcreated\t{label}\t{reference_id}\t{status}", flush=True)
            elif reference.get("created") is False:
                existed += 1   # a Reference already recorded keeps its status: the request never applies one to it
                print(f"references\tcreate-from-catalog\talready-existed\t{label}\t{reference_id}\t"
                      f"status={status} (existing; requested pending not applied)", flush=True)
            else:   # a backend older than this CLI does not say which; do not guess
                unknown += 1
                print(f"references\tcreate-from-catalog\toutcome-unknown\t{label}\t{reference_id}\tstatus={status} "
                      "(the backend predates this CLI and does not say whether this request created it or it already existed)", flush=True)
        prediction = result.get("prediction") or {}
        videos += int(prediction.get("videos") or 0)
        if prediction.get("ok") is False:   # the server could not queue it: the Reference exists and stays hidden until it has a prediction
            print(f"references\tcreate-from-catalog\tprediction\tNOT-REQUESTED\t{label}\t{prediction.get('error')}\t"
                  "queue it with `papyrus references queue-predictions` once the cause is fixed", flush=True)
    from .reference_prediction_queue import video_line
    line = video_line("references\tcreate-from-catalog", videos)   # a video's picture and transcript can only be read from a machine the platform answers
    if line:
        print(line, flush=True)
    print(f"references\tcreate-from-catalog\tsummary\tcreated={created}\talready-existed={existed}"
          + (f"\toutcome-unknown={unknown}" if unknown else "") + f"\tnot-confirmed={len(failed)}", flush=True)
    if failed:
        raise ValueError(
            f"{len(failed)} of {total} sources were not confirmed (a timeout leaves the outcome unknown). Run the same command again: "
            "a source already recorded is returned unchanged and is not recurated."
        )
