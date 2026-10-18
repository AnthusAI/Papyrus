from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .env import PAPYRUS_ROOT
from .graphql_authoring import create_authoring_client
from .ids import hash_short, knowledge_corpus_id
from .options import normalize_non_negative_integer, normalize_positive_integer, normalize_string, parse_options, parse_repeated_option
from .steering import default_corpus_key, load_steering_config, require_corpus_config


def _default_query_terms() -> list[str]:
    return [
        "computer vision",
        "multimodal",
        "model eval",
        "retrieval",
        "alignment",
    ]


def run_citation_led_discovery(flags: list[str]) -> None:
    options = parse_options(flags)
    steering_config = load_steering_config(options.get("config"))
    anchor_corpus_key = (
        options.get("anchor-corpus-key")
        or options.get("corpus-key")
        or (steering_config.get("canonicalTopicSet") or {}).get("corpusKey")
        or default_corpus_key()
    )
    anchor_corpus = require_corpus_config(steering_config, anchor_corpus_key, "--anchor-corpus-key")
    query_terms = parse_repeated_option(flags, "query") or _default_query_terms()
    run_id = normalize_string(options.get("run-id")) or f"citation-led-{hash_short([anchor_corpus_key, _utc_now()])}"
    run_dir = PAPYRUS_ROOT / ".papyrus-runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    from_year = normalize_non_negative_integer(options.get("from-year"), "--from-year") or 2023
    to_year = normalize_non_negative_integer(options.get("to-year"), "--to-year") or datetime.now(timezone.utc).year
    anchor_limit = normalize_positive_integer(options.get("anchor-limit"), "--anchor-limit") or 40
    feed_limit = normalize_positive_integer(options.get("feed-limit"), "--feed-limit") or 20

    client, _ = create_authoring_client()
    corpus_id = knowledge_corpus_id(anchor_corpus)
    references = [
        reference
        for reference in client.safe_list_records("Reference")
        if (reference.get("corpusId") == corpus_id and (reference.get("versionState") in {None, "current"}))
    ]
    references.sort(
        key=lambda row: (
            str(row.get("sourcePublishedAt") or row.get("createdAt") or ""),
            str(row.get("id") or ""),
        ),
        reverse=True,
    )
    anchors = [reference for reference in references if _year_in_range(reference.get("sourcePublishedAt"), from_year, to_year)][
        :anchor_limit
    ]

    scored: list[dict[str, Any]] = []
    for anchor in anchors:
        metadata = _json_object(anchor.get("metadata"))
        title_text = f"{anchor.get('title') or ''} {anchor.get('summary') or ''}".lower()
        signal = sum(1 for term in query_terms if term.lower() in title_text)
        citations = int(metadata.get("citation_count") or 0)
        score = float(signal * 10 + min(citations, 20))
        scored.append(
            {
                "item_id": anchor.get("externalItemId") or anchor.get("id"),
                "referenceId": anchor.get("id"),
                "title": anchor.get("title"),
                "source_uri": anchor.get("sourceUri"),
                "published_at": anchor.get("sourcePublishedAt"),
                "route_corpus": anchor_corpus_key,
                "confidence_tier": "high" if score >= 20 else "medium" if score >= 8 else "low",
                "score": score,
            }
        )
    ranked = sorted(scored, key=lambda row: (row["score"], str(row.get("published_at") or "")), reverse=True)[:feed_limit]

    anchors_path = run_dir / "anchors.json"
    raw_path = run_dir / "raw.json"
    scored_path = run_dir / "scored.json"
    ranked_path = run_dir / "ranked-catalog.json"
    report_path = run_dir / "report.json"

    anchors_path.write_text(json.dumps(anchors, indent=2) + "\n", encoding="utf-8")
    raw_path.write_text(json.dumps(anchors, indent=2) + "\n", encoding="utf-8")
    scored_path.write_text(json.dumps(scored, indent=2) + "\n", encoding="utf-8")
    ranked_payload = {
        "schema_version": 2,
        "generated_at": _utc_now(),
        "corpus_uri": anchor_corpus.get("s3Prefix") or anchor_corpus.get("path"),
        "items": ranked,
    }
    ranked_path.write_text(json.dumps(ranked_payload, indent=2) + "\n", encoding="utf-8")

    counts_by_confidence = {
        "high": sum(1 for row in ranked if row.get("confidence_tier") == "high"),
        "medium": sum(1 for row in ranked if row.get("confidence_tier") == "medium"),
        "low": sum(1 for row in ranked if row.get("confidence_tier") == "low"),
    }
    report = {
        "runId": run_id,
        "totals": {"errors": 0},
        "counts_by_route_corpus": {anchor_corpus_key: len(ranked)},
        "counts_by_confidence_tier": counts_by_confidence,
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if options.get("output"):
        output_path = Path(str(options["output"]))
        if not output_path.is_absolute():
            output_path = (PAPYRUS_ROOT / output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(ranked_path.read_text(encoding="utf-8"), encoding="utf-8")

    print(f"references\tdiscover-citation-led\trun-id\t{run_id}")
    print(f"references\tdiscover-citation-led\tanchors\t{len(anchors)}")
    print(f"references\tdiscover-citation-led\traw\t{len(anchors)}")
    print(f"references\tdiscover-citation-led\tscored\t{len(scored)}")
    print(f"references\tdiscover-citation-led\tranked\t{len(ranked)}")
    print(f"references\tdiscover-citation-led\tresearch\t{len(ranked)}")
    print("references\tdiscover-citation-led\tjournalism\t0")
    print(f"references\tdiscover-citation-led\thigh\t{counts_by_confidence['high']}")
    print(f"references\tdiscover-citation-led\tmedium\t{counts_by_confidence['medium']}")
    print(f"references\tdiscover-citation-led\tlow\t{counts_by_confidence['low']}")
    print("references\tdiscover-citation-led\terrors\t0")
    print(f"references\tdiscover-citation-led\tanchors-file\t{anchors_path}")
    print(f"references\tdiscover-citation-led\traw-file\t{raw_path}")
    print(f"references\tdiscover-citation-led\tscored-file\t{scored_path}")
    print(f"references\tdiscover-citation-led\tranked-file\t{ranked_path}")
    print(f"references\tdiscover-citation-led\treport-file\t{report_path}")
    if options.get("output"):
        print(f"references\tdiscover-citation-led\toutput\t{options['output']}")


def _year_in_range(value: Any, start_year: int, end_year: int) -> bool:
    text = str(value or "").strip()
    if len(text) < 4:
        return False
    try:
        year = int(text[:4])
    except ValueError:
        return False
    return start_year <= year <= end_year


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
