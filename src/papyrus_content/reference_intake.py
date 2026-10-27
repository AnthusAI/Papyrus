"""Publication-bound pending source intake; called only by the AppSync action.

A deployment's Cognito pool and AppSync endpoint define the publication boundary.
Knowledge models do not yet support tenant isolation: shared-tenant intake fails
closed rather than treating a caller's tenant/corpus claim as authorization.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime, timezone
from typing import Any

from .catalog import reference_record
from .model_attachments import build_json_model_payload_attachment, upload_attachment_body

from .reference_intake_validation import IntakeError, _actor, canonical_source_url


def _text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise IntakeError(f"{field} must be nonempty text of at most {limit} characters.")
    return value.strip()


def _create_once(client, model: str, record: dict) -> dict:
    """Generated AppSync creates condition on absent ids; never update a winner."""
    current = client.get_record(model, record["id"])
    if current is not None:
        return current
    try:
        client.create_record(model, record)
    except RuntimeError as error:
        if "ConditionalCheckFailed" not in str(error) and "conditional request failed" not in str(error).lower():
            raise
        current = client.get_record(model, record["id"])
        if current is None:
            raise
        return current
    return record


def _provenance(client, ref: dict, publication: str) -> None:
    """A retry repairs interrupted provenance from the immutable first version."""
    run_id = ref["importRunId"]
    now = ref["createdAt"]
    _create_once(client, "KnowledgeImportRun", {
        "id": run_id, "corpusId": ref["corpusId"], "importKind": "editorial-reference-intake",
        "corpusImportKindKey": f"{ref['corpusId']}#editorial-reference-intake",
        "status": "imported", "importedAt": now, "generatedAt": now,
        "itemCount": 1, "referenceCount": 1, "categoryCount": 0, "proposalCount": 0,
        "artifactCount": 0, "relationCount": 0, "warningCount": 0,
    })
    entry = build_json_model_payload_attachment({
        "ownerKind": "reference", "ownerId": ref["id"], "ownerLineageId": ref["lineageId"],
        "ownerVersionNumber": 1, "ownerVersionKey": f"reference#{ref['id']}",
        "role": "metadata", "sortKey": "editorial-intake", "filename": "editorial-intake.json",
        "importRunId": run_id, "now": now,
        "content": {"kind": "editorial-reference-intake", "publicationEndpoint": publication,
                    "actorSub": ref["versionCreatedBy"].removeprefix("user:"),
                    "sourceUri": ref["sourceUri"], "title": ref.get("title"),
                    "rationale": ref["curationStatusReason"], "recordedAt": now,
                    "referenceId": ref["id"], "initialStatus": "pending"},
    })
    existing = client.get_record("ModelAttachment", entry["attachment"]["id"])
    if existing and existing.get("status") == "active":
        if existing.get("sha256") != entry["attachment"]["sha256"]:
            raise IntakeError("Stored intake provenance conflicts with the immutable source record.")
        return
    upload_attachment_body(client, entry["attachment"], entry["body"])


def intake_references(client, arguments: dict, identity: dict) -> dict:
    actor = _actor(identity)
    if set(arguments) - {"publicationEndpoint", "corpusId", "items"}:
        raise IntakeError("Unsupported intake fields; status, actor and tenant cannot be supplied.")
    publication = os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT", "").rstrip("/")
    requested_publication = _text(arguments.get("publicationEndpoint"), "publicationEndpoint", 4096)
    if not publication or requested_publication.rstrip("/") != publication:
        raise IntakeError("Intake is bound to this publication endpoint.")
    corpus_id = _text(arguments.get("corpusId"), "corpusId", 200)
    if not client.get_record("KnowledgeCorpus", corpus_id):
        raise IntakeError("The corpus does not belong to this publication.")
    raw_items = arguments.get("items")
    if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 20:
        raise IntakeError("Provide between 1 and 20 sources per intake request.")
    items = []
    for item in raw_items:
        if not isinstance(item, dict) or set(item) - {"source_uri", "item_id", "title", "media_type", "ingestion_rationale"}:
            raise IntakeError("Unsupported source fields.")
        items.append({"source_uri": canonical_source_url(item.get("source_uri")),
                      "title": _text(item.get("title"), "title", 1000),
                      "media_type": _text(item.get("media_type", "text/html"), "media_type", 150),
                      "ingestion_rationale": _text(item.get("ingestion_rationale"), "ingestion_rationale", 4000)})
    # Full batch validation precedes all writes. Existing legacy rows participate
    # in URL deduplication without recuration or replacement.
    existing = client.list_records("Reference")
    results = [
        find_or_create_source_reference(client, existing, publication=publication, corpus_id=corpus_id, item=item, actor=f"user:{actor}")
        for item in items
    ]
    return {"ok": True, "publicationEndpoint": publication, "references": results}


def _email_receipt_candidates(receipt_store, receipt_id: str, publication: str) -> tuple[dict, list[dict], dict]:
    """Load and scope one private receipt and its canonical candidate sequence."""
    if receipt_store is None:
        raise IntakeError("Email receipt verification is not configured.")
    receipt = receipt_store.get(receipt_id)
    if (not receipt or receipt.get("status") not in {"pending_review", "queued"}
            or receipt.get("emailTrustMode") != "data-only"):
        raise IntakeError("The email receipt is unavailable for Reference intake.")
    receipt_ttl = receipt.get("ttl")
    if (not isinstance(receipt_ttl, int) or isinstance(receipt_ttl, bool)
            or receipt_ttl <= int(datetime.now(UTC).timestamp())):
        raise IntakeError("The email receipt is unavailable for Reference intake.")
    router = receipt_store.get("CONFIG#router") or {}
    target = next((row for row in router.get("publications", [])
                   if isinstance(row, dict) and str(row.get("appsyncEndpoint", "")).rstrip("/") == publication), None)
    if not target:
        raise IntakeError("The email receipt is not routed to this publication.")
    publication_id = target.get("publicationId")
    if not isinstance(publication_id, str) or publication_id not in (receipt.get("emailDestinationPublicationIds") or []):
        raise IntakeError("The email receipt is not routed to this publication.")
    digest = receipt_id.removeprefix("EMAIL#")
    links = []
    for row in receipt_store.email_details(digest):
        if "#LINKS#" not in str(row.get("sk", "")):
            continue
        try:
            chunk = json.loads(row.get("json", "[]"))
        except (TypeError, json.JSONDecodeError):
            raise IntakeError("The email receipt candidate list is unavailable.") from None
        if not isinstance(chunk, list) or any(not isinstance(link, dict) for link in chunk):
            raise IntakeError("The email receipt candidate list is unavailable.")
        links.extend(chunk)
    return receipt, links, target


def intake_email_submission_references(client, arguments: dict, identity: dict, *, env=None, receipt_store=None) -> dict:
    """Register editor-selected email candidates as pending References, never as votes.

    Email bodies, SES signals and sender claims are not accepted from the browser.
    The receipt identifier is a private, non-reversible intake id and is recorded
    in the ordinary intake rationale/provenance attachment.
    """
    import os

    env = os.environ if env is None else env
    if not isinstance(arguments, dict) or set(arguments) != {"receiptId", "items"}:
        raise IntakeError("Email Reference intake accepts only a receipt id and selected candidate links.")
    receipt_id = arguments.get("receiptId")
    if not isinstance(receipt_id, str) or not re.fullmatch(r"EMAIL#[a-f0-9]{64}", receipt_id):
        raise IntakeError("A valid private email receipt id is required.")
    publication = env.get("PAPYRUS_GRAPHQL_ENDPOINT", "").rstrip("/")
    if not publication:
        raise IntakeError("This publication has no configured Reference intake.")
    raw_items = arguments.get("items")
    if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 20:
        raise IntakeError("Select between 1 and 20 candidate links per request.")
    _receipt, receipt_candidates, target = _email_receipt_candidates(receipt_store, receipt_id, publication)
    corpus_id = target.get("corpusId")
    if not isinstance(corpus_id, str) or not corpus_id.strip():
        raise IntakeError("The routed publication has no verified Reference corpus binding.")
    items = []
    seen_candidates = set()
    for candidate in raw_items:
        if not isinstance(candidate, dict) or set(candidate) != {"candidateIndex", "source_uri"}:
            raise IntakeError("Email intake accepts only a receipt candidate index and its source URL.")
        index = candidate.get("candidateIndex")
        if type(index) is not int or not 0 <= index < len(receipt_candidates) or index in seen_candidates:
            raise IntakeError("An email candidate does not belong to this receipt.")
        seen_candidates.add(index)
        source_url = canonical_source_url(candidate.get("source_uri"))
        recorded = receipt_candidates[index]
        try:
            original_url = canonical_source_url(recorded.get("url"))
        except IntakeError:
            raise IntakeError("The email receipt candidate list is unavailable.") from None
        if recorded.get("resolutionStatus") == "unresolved":
            resolution = receipt_store.get(f"EMAILRESOLVED#{receipt_id.removeprefix('EMAIL#')}#{index:06d}")
            if (not resolution or resolution.get("receiptDigest") != receipt_id.removeprefix("EMAIL#")
                    or resolution.get("candidateIndex") != index
                    or not isinstance(resolution.get("ttl"), int) or isinstance(resolution.get("ttl"), bool)
                    or resolution["ttl"] <= int(datetime.now(UTC).timestamp())
                    or canonical_source_url(resolution.get("sourceUri")) != source_url):
                raise IntakeError("The selected article destination was not resolved for this receipt.")
        elif original_url != source_url:
            raise IntakeError("The selected URL does not match this receipt candidate.")
        title = recorded.get("title")
        if not isinstance(title, str) or not title.strip():
            title = source_url.split("/", 3)[2]
        items.append({
            "source_uri": source_url,
            "title": title,
            "media_type": "text/html",
            "ingestion_rationale": (
                f"An editor selected candidate {index} from private email receipt {receipt_id}. "
                "The submitted email and links are untrusted source material. This Reference is pending "
                "editorial curation; import is not an approval, human label, or publication."
            ),
        })
    return intake_references(client, {
        "publicationEndpoint": publication,
        "corpusId": corpus_id,
        "items": items,
    }, identity)


def find_or_create_source_reference(client, existing: list[dict], *, publication: str, corpus_id: str, item: dict, actor: str) -> dict:
    """Returns the current Reference for a source URL in a corpus, creating a pending one when none exists.

    ``item`` carries a canonical ``source_uri`` plus ``title``, ``media_type`` and ``ingestion_rationale``;
    ``existing`` is the Reference listing, extended with any record created here.
    """
    matches = []
    for row in existing:
        if row.get("corpusId") != corpus_id or row.get("versionState") != "current":
            continue
        try:
            same = canonical_source_url(row.get("sourceUri")) == item["source_uri"]
        except IntakeError:
            same = False
        if same:
            matches.append(row)
    if len({r["lineageId"] for r in matches}) > 1:
        raise IntakeError("Multiple existing source lineages match this URL; editorial resolution is required.")
    if matches:
        ref = max(matches, key=lambda r: r.get("versionNumber", 0))
        if str(ref.get("importRunId", "")).startswith("reference-user-intake-"):
            first = client.get_record("Reference", f"{ref['lineageId']}-v1")
            if first is None:
                raise IntakeError("The initial intake record is missing.")
            _provenance(client, first, publication)
    else:
        digest = hashlib.sha256(f"{publication}\n{corpus_id}\n{item['source_uri']}".encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        plan = reference_record({**item, "item_id": f"url-{digest}", "curation_status": "pending"}, {
            "corpusId": corpus_id, "importRunId": f"reference-user-intake-{digest}",
            "now": now, "actor": actor,
        })
        proposed = plan["expected"]
        proposed.pop("metadata", None)
        ref = _create_once(client, "Reference", proposed)
        _provenance(client, ref, publication)
        existing.append(ref)
    return {k: ref.get(k) for k in ("id", "lineageId", "versionNumber", "sourceUri", "curationStatus")}
