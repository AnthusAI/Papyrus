from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .catalog import catalog_items
from .corpus_storage_paths import default_corpus_path
from .options import (
    normalize_non_negative_integer,
    normalize_positive_integer,
    normalize_string,
    parse_options,
    resolve_mutation_apply,
)
from .steering import DEFAULT_STEERING_CONFIG, load_steering_config, require_corpus_config
from .env import PAPYRUS_ROOT
from .model_defaults import DEFAULT_LLM_MODEL

DEFAULT_INGESTION_RATIONALE = (
    "bulk-registration: register curated catalog entries in controlled batches via papyrus."
)


def register_catalog_batches(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "batch register-catalog")
    corpus_key = normalize_string(options.get("corpus-key"))
    if not corpus_key:
        raise ValueError("batch register-catalog requires --corpus-key <key>.")
    config_path = normalize_string(options.get("config")) or DEFAULT_STEERING_CONFIG
    steering_config = load_steering_config(config_path)
    corpus_config = require_corpus_config(steering_config, corpus_key)
    catalog_path = _resolve_path(
        normalize_string(options.get("catalog"))
        or str(Path(default_corpus_path(corpus_config)) / "metadata" / "catalog.json")
    )
    if not catalog_path.exists():
        raise ValueError(f"Catalog not found at {catalog_path}.")

    batch_size = normalize_positive_integer(options.get("batch-size"), "--batch-size") or 75
    start_batch = normalize_non_negative_integer(options.get("start-batch"), "--start-batch") or 0
    max_batches = normalize_non_negative_integer(options.get("max-batches"), "--max-batches") or 0
    dry_run = not apply
    rationale = normalize_string(options.get("ingestion-rationale")) or DEFAULT_INGESTION_RATIONALE

    run_dir = _resolve_path(normalize_string(options.get("run-dir")) or _default_run_dir("catalog-registration-bulk", corpus_key))
    run_dir.mkdir(parents=True, exist_ok=True)

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    items = catalog_items(catalog)
    total_batches = max(1, (len(items) + batch_size - 1) // batch_size)

    manifest_path = run_dir / "manifest.json"
    manifest = {
        "corpusKey": corpus_key,
        "config": config_path,
        "catalogPath": str(catalog_path),
        "batches": [],
        "startedAt": _utc_now(),
    }
    if manifest_path.exists():
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(prior, dict):
            manifest.update(prior)

    print(f"catalog-registration\tcorpus\t{corpus_key}")
    print(f"catalog-registration\tbatch-size\t{batch_size}")
    print(f"catalog-registration\ttotal-batches\t{total_batches}")
    print(f"catalog-registration\trun-dir\t{run_dir}")
    print(f"catalog-registration\tdry-run\t{str(dry_run).lower()}")

    processed = 0
    for batch_index in range(start_batch, total_batches):
        if max_batches and processed >= max_batches:
            break
        start = batch_index * batch_size
        batch_items = items[start : start + batch_size]
        batch_catalog = _build_batch_catalog(catalog, batch_items)
        batch_path = run_dir / f"catalog-batch-{batch_index:04d}.json"
        batch_path.write_text(json.dumps(batch_catalog, indent=2) + "\n", encoding="utf-8")

        args = [
            "poetry",
            "run",
            "papyrus",
            "references",
            "register-catalog",
            "--config",
            config_path,
            "--corpus-key",
            corpus_key,
            "--catalog",
            str(batch_path),
            "--status",
            "accepted",
            "--ingestion-rationale",
            rationale,
            "--title-subtitle-enrichment",
            "false",
        ]
        if dry_run:
            args.append("--dry-run")

        started_at = _utc_now()
        result = subprocess.run(args, cwd=PAPYRUS_ROOT, capture_output=True, text=True, check=False)
        ended_at = _utc_now()
        manifest["batches"] = [entry for entry in manifest.get("batches") or [] if entry.get("batchIndex") != batch_index]
        manifest["batches"].append(
            {
                "batchIndex": batch_index,
                "offset": start,
                "count": len(batch_items),
                "batchPath": str(batch_path),
                "exitCode": int(result.returncode or 0),
                "startedAt": started_at,
                "completedAt": ended_at,
            }
        )
        manifest["updatedAt"] = ended_at
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if result.returncode != 0:
            raise RuntimeError(f"Batch {batch_index} failed.\n{(result.stdout or '').strip()}\n{(result.stderr or '').strip()}")
        processed += 1
        print(f"catalog-registration\tbatch\t{batch_index + 1}/{total_batches}\tcount\t{len(batch_items)}")

    manifest["finishedAt"] = _utc_now()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"catalog-registration\tcomplete\tbatches-processed\t{processed}")


def run_post_ingestion_enrichment_batches(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "batch enrich-references")
    corpus_key = normalize_string(options.get("corpus-key"))
    if not corpus_key:
        raise ValueError("batch enrich-references requires --corpus-key <key>.")

    batch_size = normalize_positive_integer(options.get("batch-size"), "--batch-size") or 25
    start_batch = normalize_non_negative_integer(options.get("start-batch"), "--start-batch") or 0
    max_batches = normalize_non_negative_integer(options.get("max-batches"), "--max-batches") or 0
    scan_limit = normalize_positive_integer(options.get("scan-limit"), "--scan-limit") or 5000
    summary_max_tokens = normalize_positive_integer(options.get("summary-max-tokens"), "--summary-max-tokens") or 100
    model = normalize_string(options.get("model")) or DEFAULT_LLM_MODEL
    curate_all = not bool(options.get("recent-only"))

    run_dir = _resolve_path(normalize_string(options.get("run-dir")) or _default_run_dir("post-ingestion-enrichment-bulk", corpus_key))
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {"corpusKey": corpus_key, "batches": []}
    )

    batch_index = start_batch
    processed = 0
    while True:
        if max_batches and processed >= max_batches:
            break
        args = [
            "poetry",
            "run",
            "papyrus",
            "references",
            "curate-recent",
            "--corpus-key",
            corpus_key,
            "--max-count",
            str(batch_size),
            "--scan-limit",
            str(scan_limit),
            "--summary-max-tokens",
            str(summary_max_tokens),
            "--model",
            model,
            "--json",
        ]
        if not apply:
            args.append("--dry-run")
        if curate_all:
            args.append("--all")
        else:
            args.extend(["--since-hours", "48"])

        result = subprocess.run(args, cwd=PAPYRUS_ROOT, capture_output=True, text=True, check=False)
        payload = _extract_last_json(result.stdout or "")
        selected = (((payload or {}).get("summary") or {}).get("selectedCount")) or 0
        succeeded = (((payload or {}).get("summary") or {}).get("succeededCount")) or 0
        failed = (((payload or {}).get("summary") or {}).get("failedCount")) or 0
        manifest.setdefault("batches", []).append(
            {
                "batchIndex": batch_index,
                "selectedCount": selected,
                "succeededCount": succeeded,
                "failedCount": failed,
                "exitCode": int(result.returncode or 0),
                "completedAt": _utc_now(),
            }
        )
        manifest["updatedAt"] = _utc_now()
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        if result.returncode != 0:
            raise RuntimeError(f"Wave {batch_index + 1} failed.\n{(result.stdout or '').strip()}\n{(result.stderr or '').strip()}")

        print(f"post-ingestion-enrichment\twave\t{batch_index + 1}\tselected\t{selected}\tsucceeded\t{succeeded}")
        if selected <= 0:
            print("post-ingestion-enrichment\tcomplete\tno remaining references")
            break
        if succeeded <= 0 and failed > 0:
            print("post-ingestion-enrichment\tcomplete\tbatch failed without successes")
            break

        batch_index += 1
        processed += 1

    manifest["finishedAt"] = _utc_now()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"post-ingestion-enrichment\twaves-processed\t{processed}")


def _extract_last_json(stdout: str) -> dict[str, Any] | None:
    for line in reversed((stdout or "").splitlines()):
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _build_batch_catalog(catalog: dict[str, Any], batch_items: list[dict[str, Any]]) -> dict[str, Any]:
    source_items = catalog.get("items")
    if isinstance(source_items, dict):
        mapped: dict[str, Any] = {}
        for item in batch_items:
            key = item.get("item_id") or item.get("externalItemId") or item.get("id")
            if key:
                mapped[str(key)] = item
        return {
            "schema_version": catalog.get("schema_version") or 2,
            "generated_at": catalog.get("generated_at") or _utc_now(),
            "corpus_uri": catalog.get("corpus_uri"),
            "items": mapped,
        }
    return {
        "schema_version": catalog.get("schema_version") or 2,
        "generated_at": catalog.get("generated_at") or _utc_now(),
        "corpus_uri": catalog.get("corpus_uri"),
        "items": batch_items,
    }


def _default_run_dir(prefix: str, corpus_key: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in corpus_key).strip("-")
    ts = datetime.now(timezone.utc).isoformat().replace(":", "-")
    return str(PAPYRUS_ROOT / ".papyrus-runs" / f"{prefix}-{safe}-{ts}")


def _resolve_path(value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = PAPYRUS_ROOT / candidate
    return candidate.resolve()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
