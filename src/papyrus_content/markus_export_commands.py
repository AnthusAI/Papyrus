"""CLI entry for ``papyrus content export-published`` (PPY-1d0f3d)."""

from __future__ import annotations

import json
from pathlib import Path

from .graphql_authoring import PapyrusGraphQLAuthoringClient, create_authoring_client
from .guest_auth import GuestSession, guest_auth_requested, resolve_guest_configuration
from .markus_export import EmptyExportError, ExportError, export_content
from .markus_import import AbsentMediaStore
from .media_store import S3MediaStore, configured_media_bucket
from .options import normalize_string, parse_options


def content_export_published(flags: list[str]) -> None:
    options = parse_options(flags)
    out_raw = normalize_string(options.get("out"))
    if not out_raw:
        raise ValueError("Pass --out <directory>.")
    explicit_bucket = normalize_string(options.get("bucket"))
    if guest_auth_requested(options.get("auth")):
        if options.get("drafts"):
            raise ValueError("--auth guest reads published content only; it cannot be combined with --drafts.")
        configuration = resolve_guest_configuration(explicit_bucket)
        session = GuestSession(configuration)
        client = PapyrusGraphQLAuthoringClient(
            endpoint=configuration.endpoint, auth_token="", header_factory=session.appsync_headers
        )
        store = (
            S3MediaStore(configuration.bucket, client=session.s3_client())
            if configuration.bucket
            else AbsentMediaStore()
        )
    else:
        client, _claims = create_authoring_client()
        bucket = configured_media_bucket(explicit_bucket)
        store = S3MediaStore(bucket) if bucket else AbsentMediaStore()
    try:
        report = export_content(
            client,
            store,
            Path(out_raw),
            drafts=bool(options.get("drafts")),
            clean=bool(options.get("clean")),
            allow_empty=bool(options.get("allow-empty")),
            site=normalize_string(options.get("site")),
        )
    except ExportError as error:
        label = "no items" if isinstance(error, EmptyExportError) else "export failed"
        payload = {"ok": False, "error": label, "errors": error.errors}
        print(json.dumps(payload, indent=2) if options.get("json") else f"{label}: " + "; ".join(error.errors))
        raise SystemExit(1)
    if options.get("json"):
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"Exported {len(report.items)} items ({report.mode}) to {report.out_dir}")
