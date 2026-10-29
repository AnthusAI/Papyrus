"""``papyrus references enrich-images``: give each Reference the preview its source page declares, for the References feed.

The feed shows an image, a one-line dek and the site name on every card. They come from the source page's own link-preview
metadata (``og:image`` / ``twitter:image``, ``og:description``, ``og:site_name``), read with link exploration. They are stored as one
``ReferenceAttachment`` per Reference with role ``preview`` and sort key ``002-preview``; no schema change. ``sourceUri`` is the
image address (nothing is downloaded or copied: the browser loads it straight from the source with no referrer), and ``metadata``
holds ``{description, siteName, title, imageUrl, fetchedAt}``. The newsroom already loads every attachment with the References,
so cards need no extra request.

New References get this automatically when they are created (``attach_preview``, called by the monitoring router after delivery, by
the user/agent URL intake and by email-submission registration); this command is the backfill and refresh tool.

Idempotent: a Reference that already has a preview attachment is skipped unless ``--refresh``. A page that declares no image and no
description is recorded as checked (an attachment with only ``checkedAt``) so it is not fetched again on every run.
"""

from __future__ import annotations

import json
import mimetypes
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Callable

from .ids import hash_short
from .link_exploration import Exploration, PageMetadata, explore
from .options import normalize_string, parse_options, resolve_mutation_apply

PREVIEW_ROLE = "preview"
PREVIEW_SORT_KEY = "002-preview"


def _iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _http_address(value: Any) -> str | None:
    text = normalize_string(value)
    return text if text and text.lower().startswith(("http://", "https://")) else None


def preview_attachment_id(reference: dict[str, Any]) -> str:
    version_key = "reference#" + str(reference["id"])
    return f"reference-attachment-{hash_short([version_key, PREVIEW_ROLE, PREVIEW_SORT_KEY])}"


def preview_attachment(reference: dict[str, Any], exploration: Exploration, now: datetime) -> dict[str, Any]:
    """The ``ReferenceAttachment`` row for one Reference's preview. A page with no metadata still yields a "checked" row."""
    version_key = f"reference#{reference['id']}"
    metadata = exploration.metadata.as_dict() if exploration.metadata else {}
    image = metadata.get("imageUrl")
    guessed = mimetypes.guess_type(urllib.parse.urlsplit(image).path)[0] if image else None
    stamp = _iso(now)
    return {
        "id": preview_attachment_id(reference),
        "referenceId": reference["id"],
        "referenceLineageId": reference.get("lineageId") or reference["id"],
        "referenceVersionNumber": reference.get("versionNumber"),
        "referenceVersionKey": version_key,
        "role": PREVIEW_ROLE,
        "sortKey": PREVIEW_SORT_KEY,
        "sourceUri": image,
        "filename": metadata.get("siteName") or urllib.parse.urlsplit(str(reference.get("sourceUri") or "")).hostname,
        "mediaType": guessed if guessed and guessed.startswith("image/") else ("image/*" if image else None),
        "importedAt": stamp,
        "metadata": json.dumps({**metadata, "checkedAt": stamp, "via": "link_exploration"}, sort_keys=True),
    }


def exploration_from_preview(url: str, preview: dict[str, Any]) -> Exploration:
    """An ``Exploration`` rebuilt from page metadata an earlier capture already read (``Capture.preview``), so no second fetch is needed."""
    return Exploration(True, url, via="direct", metadata=PageMetadata(
        image_url=preview.get("imageUrl"), description=preview.get("description"),
        site_name=preview.get("siteName"), title=preview.get("title")))


def attach_preview(
    client: Any,
    reference: dict[str, Any],
    *,
    exploration: Exploration | None = None,
    explorer: Callable[..., Exploration] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    log: Callable[[str], None] = print,
) -> str:
    """Write the preview attachment for one newly created Reference. Idempotent, and NEVER raises.

    Skips when the Reference version already has a preview. Uses ``exploration`` when the caller already read the page (curation's
    capture), else fetches once. A page with no image still gets its "checked" row. Logs one JSON line and returns
    ``written``, ``exists`` or ``failed``; creating the Reference must never depend on this.
    """
    reference_id = reference.get("id") if isinstance(reference, dict) else None
    try:
        if client.get_record("ReferenceAttachment", preview_attachment_id(reference)):
            return "exists"
        found = exploration
        if found is None:
            address = _http_address(reference.get("sourceUri"))
            if address is None:
                raise ValueError("no web address")
            found = (explorer or explore)(address, want_text=False, use_search=False)
        if not found.ok and not (found.metadata and found.metadata.as_dict()):
            raise RuntimeError(f"page not readable: {found.failure or 'unknown'}")
        row = preview_attachment(reference, found, now())
        client.upsert("ReferenceAttachment", row)
        log(json.dumps({"referencePreview": "written", "referenceId": reference_id, "withImage": bool(row["sourceUri"]),
                        "reused": exploration is not None}, sort_keys=True))
        return "written"
    except Exception as error:  # noqa: BLE001 - a preview is decoration; it must never block or fail the Reference
        try:
            log(json.dumps({"referencePreview": "failed", "referenceId": reference_id,
                            "reason": f"{type(error).__name__}: {str(error)[:200]}"}, sort_keys=True))
        except Exception:  # noqa: BLE001
            pass
        return "failed"


def enrich_reference_previews(
    client: Any,
    *,
    corpus: str | None = None,
    limit: int | None = None,
    refresh: bool = False,
    dry_run: bool = False,
    explorer: Callable[..., Exploration] = explore,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, Any]:
    """Fetch and store previews for current References. Returns counts; never raises for one bad page."""
    references = [
        row for row in client.list_records("Reference")
        if (row.get("versionState") in (None, "current")) and _http_address(row.get("sourceUri"))
        and (corpus is None or row.get("corpusId") == corpus)
    ]
    existing = {row.get("referenceVersionKey") for row in client.list_records("ReferenceAttachment") if row.get("role") == PREVIEW_ROLE}
    counts = {"considered": len(references), "alreadyHave": 0, "withImage": 0, "withoutImage": 0, "failed": 0, "written": 0}
    attempted = 0
    for reference in references:
        if f"reference#{reference['id']}" in existing and not refresh:
            counts["alreadyHave"] += 1
            continue
        if limit is not None and attempted >= limit:
            break
        attempted += 1
        found = explorer(str(reference["sourceUri"]), want_text=False, use_search=False)
        if not found.ok and not (found.metadata and found.metadata.as_dict()):
            counts["failed"] += 1
            continue
        row = preview_attachment(reference, found, now())
        counts["withImage" if row["sourceUri"] else "withoutImage"] += 1
        if not dry_run:
            client.upsert("ReferenceAttachment", row)
            counts["written"] += 1
    return counts


def references_enrich_images(flags: list[str]) -> None:
    """papyrus references enrich-images [--corpus <id>] [--limit N] [--refresh] [--dry-run]

    Reads each current Reference's source page and stores its link-preview image, description and site name as a ``preview``
    attachment (see this module). Writes by default; ``--dry-run`` fetches and counts without writing.
    """
    from .graphql_authoring import create_authoring_client

    options = parse_options(flags)
    for flag in ("corpus", "limit"):
        if options.get(flag) is True:
            raise ValueError(f"--{flag} needs a value.")
    apply = resolve_mutation_apply(options, "references enrich-images")
    client, _ = create_authoring_client()
    counts = enrich_reference_previews(
        client,
        corpus=normalize_string(options.get("corpus")),
        limit=int(options["limit"]) if options.get("limit") else None,
        refresh=bool(options.get("refresh")),
        dry_run=not apply,
    )
    print("references\tenrich-images\t" + "\t".join(f"{key}={value}" for key, value in counts.items()) + ("\tdry-run" if not apply else ""))
