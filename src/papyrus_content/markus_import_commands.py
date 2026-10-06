"""CLI entry for ``papyrus content import-markus`` (PPY-22a3b4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .media_store import S3MediaStore, configured_media_bucket
from .graphql_authoring import create_authoring_client
from .markus_import import (
    AbsentMediaStore,
    ImportOptions,
    plan_import,
    run_import,
)
from .options import normalize_string, parse_comma_list, parse_options, resolve_mutation_apply


def parse_draft_dirs(value: str | None) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for entry in parse_comma_list(value) if value else []:
        source, separator, target = entry.partition("=")
        if not separator or not source.strip() or not target.strip():
            raise ValueError("--draft-dirs entries must look like drafts=articles.")
        mapping[source.strip()] = target.strip()
    return mapping


def import_options_from_flags(options: dict[str, Any]) -> ImportOptions:
    content_dir = normalize_string(options.get("content-dir"))
    if not content_dir:
        raise ValueError("--content-dir is required.")
    article_dirs = parse_comma_list(normalize_string(options.get("article-dirs"))) or ["articles"]
    aliases_file = normalize_string(options.get("aliases-file"))
    image_source_dir = normalize_string(options.get("image-source-dir"))
    return ImportOptions(
        content_dir=Path(content_dir),
        article_dirs=tuple(article_dirs),
        draft_dirs=parse_draft_dirs(normalize_string(options.get("draft-dirs"))),
        aliases_file=Path(aliases_file) if aliases_file else None,
        publish=not options.get("no-publish"),
        force=bool(options.get("force")),
        image_source_dir=Path(image_source_dir) if image_source_dir else None,
    )


def content_import_markus(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "content import-markus")
    import_options = import_options_from_flags(options)
    client, _claims = create_authoring_client()
    bucket = configured_media_bucket(normalize_string(options.get("bucket")))
    if bucket:
        store = S3MediaStore(bucket)
    elif apply:
        raise ValueError("Pass --bucket or provide amplify_outputs.json with a storage bucket.")
    else:
        store = AbsentMediaStore()
    plan = plan_import(import_options, client, store)
    report = run_import(plan, client, store, apply=apply)
    payload = report.to_dict()
    if options.get("json"):
        print(json.dumps(payload, indent=2))
    else:
        mode = "dry run" if not apply else "applied"
        print(f"content import-markus ({mode}): ok={payload['ok']}")
        for key in (
            "created", "updated", "unchanged", "skippedEditedInCms", "published",
            "mediaUploaded", "mediaUnchanged", "readerOwnedAssets", "notInSource",
        ):
            print(f"  {key}: {payload[key]}")
        for message in payload["errors"]:
            print(f"  error: {message}")
    if not report.ok:
        raise SystemExit(1)
