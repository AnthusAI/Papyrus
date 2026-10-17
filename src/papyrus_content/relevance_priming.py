"""Priming the running relevance cyclotron from a URL an editor pasted.

The Newsroom writes one ``KnowledgeRawPayload`` per request (kind
``cyclotron-priming-request``, JSON in a ``raw_payload`` attachment), the same
channel as the manual review rate. The next decide-relevance sweep extracts the
page, adds it to the running cyclotron with ``add_priming_examples`` and records
an outcome (``applied`` with the new version, or ``failed`` with a reason) in a
``priming_outcome`` attachment on the same payload. No new store and no new
model: a request with an outcome is finished and is never extracted again.
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse, urlunparse

from .ids import safe_id
from .model_attachments import attachment_record, build_json_model_payload_attachment

PRIMING_REQUEST_KIND = "cyclotron-priming-request"
PRIMING_REQUEST_ROLE = "raw_payload"
PRIMING_OUTCOME_ROLE = "priming_outcome"
PRIMING_ITEM_PREFIX = "priming:"

ExtractUrl = Callable[[str], Mapping[str, Any]]


def priming_request_payload_id(cyclotron_id: str, request_id: str) -> str:
    """The KnowledgeRawPayload an editor writes to ask for one priming example."""
    return f"knowledge-raw-payload-cyclotron-priming-request-{safe_id(cyclotron_id)}-{safe_id(request_id)}"


def normalize_priming_url(value: Any) -> str:
    """The https URL a priming request names, without its fragment; ValueError when it is not one."""
    raw = str(value or "").strip()
    try:
        parsed = urlparse(raw)
    except ValueError:
        parsed = None
    if parsed is None or parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ValueError("A priming example needs an https URL.")
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.params, parsed.query, ""))


def priming_item_id(url: str) -> str:
    """The cyclotron item id of a primed URL; it can never equal a Reference lineage id."""
    return PRIMING_ITEM_PREFIX + hashlib.sha256(normalize_priming_url(url).encode("utf-8")).hexdigest()[:16]


def priming_label(request: Mapping[str, Any], labels: Sequence[str]) -> str:
    label = str(request.get("label") or "")
    if label not in labels:
        raise ValueError(f"The label {label!r} is not one of this cyclotron's labels: {', '.join(labels)}.")
    return label


def readable_engine_refusal(error: ValueError) -> str:
    message = str(error)
    if "different content" in message:
        return "This URL already primed the cyclotron with a different label, explanation or page text."
    if "disjoint" in message:
        return "This page is already one of the references the cyclotron decided, so it cannot also be a priming example."
    return message


def priming_outcome_record(payload_id: str, outcome: Mapping[str, Any], *, now: str) -> dict[str, Any]:
    """The ModelAttachment record that finishes a request."""
    return attachment_record(build_json_model_payload_attachment({
        "ownerKind": "knowledgeRawPayload",
        "ownerId": payload_id,
        "ownerLineageId": payload_id,
        "role": PRIMING_OUTCOME_ROLE,
        "sortKey": "outcome",
        "filename": "priming-outcome.json",
        "content": dict(outcome),
        "now": now,
    }))


def default_url_extractor(steering_config: Mapping[str, Any], corpus: Mapping[str, Any]) -> ExtractUrl:
    """Extract a page with the existing Papyrus priming curation (needs Biblicus, network and OpenAI)."""
    def extract(url: str) -> Mapping[str, Any]:
        from .priming_curation import PapyrusPrimingCuration

        curation = PapyrusPrimingCuration(
            corpus=dict(corpus), classifier_id=steering_config["canonicalTopicSet"]["classifierId"],
            publication_name=(steering_config.get("publication") or {}).get("name") or "")
        prepared = curation.prepare({"url": url}, None, "")
        if prepared.get("status") != "complete":
            raise ValueError(prepared.get("message") or "Processing needs a complete title and abstract.")
        return prepared["candidate"]["values"]
    return extract
