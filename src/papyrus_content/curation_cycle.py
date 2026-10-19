from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .categories_steering import load_json_file, write_json_file
from .biblicus_runner import BiblicusCommandError, BiblicusRunner, resolve_biblicus_workdir
from .ids import knowledge_corpus_id
from .steering import require_corpus_config


def timestamp_run_id(value: datetime | None = None) -> str:
    date = value or datetime.now(timezone.utc)
    return date.isoformat().replace("-", "").replace(":", "").replace(".000", "").replace("+00:00", "Z")


def build_curation_cycle_plan(config: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    if not config:
        raise ValueError("A steering config is required to run the curation cycle.")
    run_id = options.get("runId") or timestamp_run_id()
    run_dir = Path(options.get("outputDir") or Path(".papyrus-runs") / run_id).resolve()
    biblicus_workdir = resolve_biblicus_workdir(options.get("biblicusWorkdir"))
    canonical_corpus = require_corpus_config(config, config["canonicalTopicSet"]["corpusKey"], "canonicalTopicSet.corpusKey")
    canonical_classifier_id = config["canonicalTopicSet"]["classifierId"]
    source_projections = []
    for corpus in config.get("corpora") or []:
        if corpus.get("key") == canonical_corpus.get("key"):
            continue
        projection = corpus.get("canonicalProjection") or {}
        if projection.get("authorityCorpusKey") != canonical_corpus.get("key"):
            continue
        source_projections.append(
            {
                "targetCorpus": corpus,
                "targetCorpusId": knowledge_corpus_id(corpus),
                "authorityCorpus": canonical_corpus,
                "authorityCorpusId": knowledge_corpus_id(canonical_corpus),
                "classifierId": projection.get("classifierId"),
                "projectionPath": str(run_dir / f"{corpus['key']}-projection.json"),
                "targetSteeringPath": str(run_dir / f"{corpus['key']}-steering-export.json"),
            }
        )
    return {
        "runId": run_id,
        "runDir": str(run_dir),
        "biblicusWorkdir": str(biblicus_workdir),
        "configPath": config.get("configPath"),
        "canonical": {
            "corpus": canonical_corpus,
            "corpusId": knowledge_corpus_id(canonical_corpus),
            "classifierId": canonical_classifier_id,
            "steeringPath": str(run_dir / f"{canonical_corpus['key']}-steering-export.json"),
            "categorySetPath": str(run_dir / f"{canonical_corpus['key']}-accepted-category-set.json"),
            "categoryTreePath": str(run_dir / f"{canonical_corpus['key']}-accepted-category-tree.json"),
            "steeringFeedbackPath": str(run_dir / f"{canonical_corpus['key']}-steering-feedback.json"),
            "lexicalSteeringPath": str(run_dir / f"{canonical_corpus['key']}-lexical-steering.json"),
            "taxonomyDiscoveryPath": str(run_dir / f"{canonical_corpus['key']}-taxonomy-discovery.json"),
            "seedManifestPath": str(
                biblicus_workdir
                / (canonical_corpus.get("path") or "")
                / "metadata"
                / "topic-classifiers"
                / canonical_classifier_id
                / "seed-manifest.json"
            ),
        },
        "sourceProjections": source_projections,
        "verificationPath": str(run_dir / "verification.json"),
    }


def validate_cycle_corpus_paths(plan: dict[str, Any]) -> None:
    corpora = [plan["canonical"]["corpus"], *[projection["targetCorpus"] for projection in plan.get("sourceProjections") or []]]
    for corpus in corpora:
        if not corpus.get("path"):
            raise ValueError(f"Corpus {corpus.get('key')} does not define a local path in steering config.")
        resolved = resolve_biblicus_corpus_path(plan, corpus)
        if not resolved.exists():
            raise ValueError(f"Corpus path for {corpus.get('key')} was not found: {resolved}")


def resolve_biblicus_corpus_path(plan: dict[str, Any], corpus: dict[str, Any]) -> Path:
    path_value = corpus.get("path") or ""
    if Path(path_value).is_absolute():
        return Path(path_value)
    return Path(plan["biblicusWorkdir"]) / path_value


def latest_pipeline_snapshot(bundle: dict[str, Any]) -> str | None:
    artifacts = [
        artifact
        for artifact in bundle.get("artifacts") or []
        if artifact.get("kind") == "extraction"
        and str(artifact.get("artifact_id") or "").startswith("pipeline:")
        and artifact.get("snapshot_id")
    ]
    artifacts.sort(key=lambda artifact: str(artifact.get("created_at") or ""), reverse=True)
    return f"pipeline:{artifacts[0]['snapshot_id']}" if artifacts else None


def run_biblicus(plan: dict[str, Any], args: list[str], label: str) -> str:
    log_prefix = Path(plan["runDir"]) / re.sub(r"[^A-Za-z0-9_.-]", "-", label)
    print(f"Biblicus: {label}")
    runner = BiblicusRunner.from_environment(workdir=plan["biblicusWorkdir"])
    try:
        output = runner.run(args)
    except BiblicusCommandError as error:
        log_prefix.with_suffix(".stdout.log").write_text(error.stdout, encoding="utf-8")
        log_prefix.with_suffix(".stderr.log").write_text(error.stderr, encoding="utf-8")
        raise RuntimeError(f"Biblicus {label} failed. See {log_prefix}.stderr.log") from error
    log_prefix.with_suffix(".stdout.log").write_text(output.stdout, encoding="utf-8")
    log_prefix.with_suffix(".stderr.log").write_text(output.stderr, encoding="utf-8")
    return output.stdout


def run_biblicus_json(plan: dict[str, Any], args: list[str], label: str, output_path: str) -> None:
    stdout = run_biblicus(plan, [*args, "--format", "json"], label)
    write_json_file(output_path, json.loads(stdout))


def record_proposal_bundle_if_present(plan: dict[str, Any], bundle_path: str, corpus_path: str, label: str) -> None:
    path = Path(bundle_path)
    if not path.exists():
        print(f"skip\t{label}\tno proposal bundle at {bundle_path}")
        return
    bundle = load_json_file(path)
    proposals = bundle.get("proposals") or []
    print(f"record\t{label}\t{len(proposals)} proposals\t{bundle_path}\tcorpus={corpus_path}")
