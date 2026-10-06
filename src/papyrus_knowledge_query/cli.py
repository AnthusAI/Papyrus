from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

from papyrus_content.graphql_http import aws_credentials_available, iam_signed_graphql_headers

from .engine import run_knowledge_query
from .services import build_environment_services
from .uris import parse_papyrus_uri
from .vector_index import VectorIndexOptions, index_reference_passages


def add_knowledge_query_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "knowledge-query",
        help="Run the shared Papyrus knowledge query engine",
    )
    parser.add_argument("--input", default="", help="JSON input file, or '-' for stdin")
    parser.add_argument("--query", default="", help="Semantic query text")
    parser.add_argument("--anchor", action="append", default=[], help="Anchor as kind:id or papyrus://kind/id")
    parser.add_argument(
        "--profile",
        default="researcher",
        choices=["researcher", "reporter", "reporting", "editor", "reviewer", "chat"],
    )
    parser.add_argument("--format", default="structured", choices=["structured", "markdown", "both"])
    parser.add_argument("--max-tokens", type=int, default=0)
    parser.add_argument("--depth", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument(
        "--include-kind",
        action="append",
        default=[],
        help="Include related records of specific kinds (repeatable), e.g. reference,message,assignment,item",
    )
    parser.add_argument(
        "--exclude-kind",
        action="append",
        default=[],
        help="Exclude related records of specific kinds (repeatable)",
    )
    parser.add_argument(
        "--include-message-kind",
        action="append",
        default=[],
        help="Include message records only for these messageKind values (repeatable)",
    )
    parser.add_argument(
        "--exclude-message-kind",
        action="append",
        default=[],
        help="Exclude message records for these messageKind values (repeatable)",
    )
    parser.add_argument(
        "--include-assignment-type",
        action="append",
        default=[],
        help="Include assignment records only for these assignmentTypeKey values (repeatable)",
    )
    parser.add_argument(
        "--exclude-assignment-type",
        action="append",
        default=[],
        help="Exclude assignment records for these assignmentTypeKey values (repeatable)",
    )
    parser.add_argument(
        "--execution",
        default="remote",
        choices=["auto", "remote", "local"],
        help="Run through AppSync/Lambda by default, or force local shared-engine execution for development",
    )


def add_knowledge_vector_index_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "knowledge-vector-index",
        help="Index accepted reference extracted-text passages into the configured S3 vector index",
    )
    parser.add_argument("--action", default="sync", choices=["audit", "sync", "rebuild"])
    parser.add_argument("--corpus-id", default="")
    parser.add_argument("--category-set-id", default="")
    parser.add_argument("--reference-id", action="append", default=[], help="Reference id, lineageId, or externalItemId to index")
    parser.add_argument("--max-references", type=int, default=0)
    parser.add_argument("--max-chunks-per-reference", type=int, default=8)
    parser.add_argument("--chunk-words", type=int, default=180)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--no-source-vectors", action="store_true", help="Do not write one source-level vector per reference")
    parser.add_argument("--no-passage-vectors", action="store_true", help="Do not write extracted-text passage vectors")
    parser.add_argument("--no-ontology-vectors", action="store_true", help="Do not write ontology relation/profile vectors")
    parser.add_argument("--include-ontology-vectors", action="store_true", help="Explicitly include ontology relation/profile vectors")
    parser.add_argument("--force", action="store_true", help="Re-embed and upsert vectors even when deterministic keys already exist")
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--workers", type=int, default=8, help="Parallel workers for GraphQL attachment lookup and S3 text reads")
    parser.add_argument("--dry-run", action="store_true")


def run_knowledge_query_cli(args: argparse.Namespace) -> dict[str, Any]:
    payload = _load_input(args.input) if args.input else _input_from_args(args)
    if _should_run_remote(args):
        result = _run_remote_knowledge_query(payload)
        _annotate_cli_execution(result, "remote")
        return result
    result = run_knowledge_query(payload, build_environment_services())
    _annotate_cli_execution(result, "local")
    return result


def run_knowledge_vector_index_cli(args: argparse.Namespace) -> dict[str, Any]:
    options = VectorIndexOptions(
        action=args.action,
        corpus_id=args.corpus_id,
        category_set_id=args.category_set_id,
        reference_ids=tuple(args.reference_id or ()),
        max_references=args.max_references or None,
        max_chunks_per_reference=max(1, args.max_chunks_per_reference),
        chunk_words=max(80, args.chunk_words),
        batch_size=max(1, min(args.batch_size, 500)),
        include_source_vectors=not bool(args.no_source_vectors),
        include_passage_vectors=not bool(args.no_passage_vectors),
        include_ontology_vectors=not bool(args.no_ontology_vectors),
        force=bool(args.force),
        dry_run=bool(args.dry_run),
        progress_every=max(0, int(args.progress_every or 0)),
        worker_count=max(1, int(args.workers or 1)),
    )
    return index_reference_passages(build_environment_services(), options)


def _load_input(path: str) -> dict[str, Any]:
    if path == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(path).read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise TypeError("knowledge-query input file must contain a JSON object")
    return payload


def _should_run_remote(args: argparse.Namespace) -> bool:
    execution = getattr(args, "execution", "auto")
    if execution == "local":
        return False
    endpoint = os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT", "").strip()
    if execution == "remote":
        if not endpoint or not aws_credentials_available():
            raise RuntimeError(
                "remote knowledge-query execution requires PAPYRUS_GRAPHQL_ENDPOINT and AWS credentials (set AWS_PROFILE)"
            )
        return True
    return bool(endpoint and aws_credentials_available())


def _run_remote_knowledge_query(payload: dict[str, Any]) -> dict[str, Any]:
    endpoint = os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT", "").strip()
    input_json = json.dumps(payload, separators=(",", ":"))
    body = json.dumps(
        {
            "query": "query KnowledgeQuery($input: AWSJSON!) { knowledgeQuery(input: $input) }",
            "variables": {"input": input_json},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers=iam_signed_graphql_headers(endpoint, body),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=330) as response:  # nosec B310 - configured AppSync endpoint
        response_payload = json.loads(response.read().decode("utf-8"))
    if response_payload.get("errors"):
        raise RuntimeError(json.dumps(response_payload["errors"]))
    result = (response_payload.get("data") or {}).get("knowledgeQuery")
    if isinstance(result, str):
        parsed = json.loads(result)
        if isinstance(parsed, dict):
            return parsed
    if isinstance(result, dict):
        return result
    raise RuntimeError("knowledgeQuery remote response did not contain a JSON object")


def _annotate_cli_execution(result: dict[str, Any], execution: str) -> None:
    if not isinstance(result, dict):
        return
    debug = result.setdefault("debug", {})
    if isinstance(debug, dict):
        debug["cliExecution"] = execution
    provenance = result.setdefault("provenance", {})
    if isinstance(provenance, dict):
        provenance["cliExecution"] = execution


def _input_from_args(args: argparse.Namespace) -> dict[str, Any]:
    scope: dict[str, Any] = {}
    if args.depth is not None:
        scope["depth"] = args.depth
    if args.top_k is not None:
        scope["topK"] = args.top_k
    if args.include_kind:
        scope["includeObjectKinds"] = [str(value) for value in args.include_kind if str(value).strip()]
    if args.exclude_kind:
        scope["excludeObjectKinds"] = [str(value) for value in args.exclude_kind if str(value).strip()]
    if args.include_message_kind:
        scope["includeMessageKinds"] = [str(value) for value in args.include_message_kind if str(value).strip()]
    if args.exclude_message_kind:
        scope["excludeMessageKinds"] = [str(value) for value in args.exclude_message_kind if str(value).strip()]
    if args.include_assignment_type:
        scope["includeAssignmentTypeKeys"] = [str(value) for value in args.include_assignment_type if str(value).strip()]
    if args.exclude_assignment_type:
        scope["excludeAssignmentTypeKeys"] = [str(value) for value in args.exclude_assignment_type if str(value).strip()]
    output: dict[str, Any] = {"format": args.format}
    if args.max_tokens:
        output["maxTokens"] = args.max_tokens
    return {
        "anchors": [_parse_anchor(value) for value in args.anchor],
        "semanticQuery": args.query,
        "scope": scope,
        "profile": args.profile,
        "output": output,
    }


def _parse_anchor(value: str) -> dict[str, Any]:
    if value.startswith("papyrus://"):
        return parse_papyrus_uri(value)
    if ":" not in value:
        raise ValueError("--anchor must use kind:id or papyrus://kind/id")
    kind, object_id = value.split(":", 1)
    kind = kind.strip()
    object_id = object_id.strip()
    if not kind or not object_id:
        raise ValueError("--anchor must use kind:id or papyrus://kind/id")
    return {"kind": kind, "id": object_id, "lineageId": object_id}
