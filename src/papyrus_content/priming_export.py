"""``papyrus cyclotron export-priming``: a publication's editor labels as JSON Lines for a Cyclotron's priming import.

Read-only. Two sources, one row per item, in the lab's priming import shape (docs/cyclotron-priming.md, "Exporting a
publication's labels"):

1. **References** of the publication's corpus. An editor's curation decision is the label for classifier
   ``distinctive-relevance``: accepted is ``include``, rejected is ``exclude``. A Reference still pending has no label.
2. **Drafts an automation made from TTAB decisions** (``ttab-automation``). The monitor automations of the publication on
   the ``ttab`` monitor name a procedure. Each completed ProcedureRun of that procedure names a story (its output
   ``story``). The story's stage says what an editor did with the draft, and that is the label for classifier
   ``distinctive-draft-accept``: published is ``include``; held and spiked are ``exclude``; any earlier stage is still
   pending and has no label. A TTAB item never gets ``distinctive-relevance`` from here: only a curation decision on its
   Reference is a judgement of relevance, and that arrives through source 1.

``labeledBy`` is a role (``editor`` or ``automation``), never an address or an account subject. ``modelMade`` is true when the
actor that set the state is a machine and no editor confirmed it. For curation that is the router's rule (``human_actor`` in
``monitoring_router``); for a story stage a machine is an automation, agent or worker actor, while the operator's own CLI is
an editor's hand.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from .graphql_authoring import create_authoring_client
from .monitoring_router import WORKER_ACTOR, human_actor
from .options import normalize_string, parse_options
from .reference_curation_store import TEXT_SORT_KEY, AttachmentStore, read_card

RELEVANCE = "distinctive-relevance"
DRAFT_ACCEPT = "distinctive-draft-accept"
SOURCE_CORPUS = "corpus"
SOURCE_TTAB = "ttab-automation"
TTAB_MONITOR = "ttab"
EDITOR, AUTOMATION = "editor", "automation"
CURATION_LABELS = {"accepted": "include", "rejected": "exclude"}
STAGE_LABELS = {"published": "include", "held": "exclude", "spiked": "exclude"}
MACHINE_PREFIXES = ("automation:", "agent:", "system:", "worker:", "papyrus-monitoring", "behave-")
EMAIL = re.compile(r"[^@\s:]+@[^@\s:]+\.[^@\s:]+")
FRONT_MATTER_DATE = re.compile(r"^date:\s*[\"']?(\d{4}-\d{2}-\d{2})", re.MULTILINE)

BodyReader = Callable[[Mapping[str, Any], list[dict[str, Any]]], str]


def scrubbed(text: Any) -> str:
    """Editor words with any address replaced, so an export can never carry one."""
    return EMAIL.sub("[address removed]", str(text or "")).strip()


def machine_story_actor(actor: str) -> bool:
    """A story stage was set by a machine: an automation, agent or worker. The operator's CLI and any person are editors."""
    actor = actor.strip()
    return not actor or actor == WORKER_ACTOR or actor.startswith(MACHINE_PREFIXES) or actor.endswith("(Tactus)")


def compose_text(title: str, url: str, summary: str, body: str) -> str:
    return f"{title}\n{url}\n\n{summary}\n\n{body}"


def iso_day(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def row(item_id: str, occurred_at: str, values: Mapping[str, str], labels: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
    title, url = str(values.get("title") or ""), str(values.get("url") or "")
    summary, body = str(values.get("summary") or ""), str(values.get("body") or "")
    return {"id": item_id, "occurred_at": occurred_at,
            "values": {"title": title, "url": url, "summary": summary, "body": body, "text": compose_text(title, url, summary, body)},
            "labels": labels, "provenance": provenance}


# --- source 1: the corpus ----------------------------------------------------------------------------------------------


def reference_content(client, reference: Mapping[str, Any], read_extracted: BodyReader | None) -> dict[str, str]:
    """Summary and body: the curation card's summary and `curation-text` body, else the extracted text, else empty."""
    summary = body = ""
    card = read_card(client, dict(reference))
    if card:
        summary = str((card.get("summary") or {}).get("text") or "")
        sort_key = (card.get("current") or {}).get("textSortKey") or TEXT_SORT_KEY
        try:
            body = AttachmentStore(client).read_text(dict(reference), sort_key) or ""
        except Exception:  # noqa: BLE001 - a body that cannot be read is an empty body, not a failed export
            body = ""
    if not body and read_extracted is not None:
        try:
            body = read_extracted(reference, client.list_reference_attachments_by_lineage(reference["lineageId"])) or ""
        except Exception:  # noqa: BLE001
            body = ""
    return {"title": str(reference.get("title") or ""), "url": str(reference.get("sourceUri") or ""), "summary": summary, "body": body}


def reference_row(client, reference: Mapping[str, Any], read_extracted: BodyReader | None, *, include_unlabeled: bool) -> dict[str, Any] | None:
    status = str(reference.get("curationStatus") or "")
    label = CURATION_LABELS.get(status)
    if label is None and not include_unlabeled:
        return None
    actor = str(reference.get("curationStatusUpdatedBy") or "")
    human = human_actor(actor)
    labels: dict[str, Any] = {}
    provenance = {"source": SOURCE_CORPUS, "state": status or "pending"}
    if label is not None:
        labels[RELEVANCE] = {"label": label, "explanation": scrubbed(reference.get("curationStatusReason")) if human else ""}
        provenance.update(labeledBy=EDITOR if human else AUTOMATION,
                          labeledAt=iso_day(reference.get("curationStatusUpdatedAt") or reference.get("updatedAt")),
                          modelMade=not human)
    else:
        provenance.update(labeledBy="", labeledAt="", modelMade=not human)
    occurred = iso_day(reference.get("sourcePublishedAt") or reference.get("importedAt") or reference.get("createdAt"))
    return row(f"ref-{reference['lineageId']}", occurred, reference_content(client, reference, read_extracted), labels, provenance)


# --- source 2: drafts an automation made from TTAB decisions ----------------------------------------------------------


def ttab_procedure_keys(client, publication: str) -> list[str]:
    keys = []
    for automation in client.list_records("Automation"):
        trigger = _json(automation.get("trigger")) or {}
        config = trigger.get("config") or {}
        if trigger.get("kind") == "monitor" and config.get("monitorId") == TTAB_MONITOR and config.get("publicationId") == publication:
            keys.append(str(automation.get("procedureKey") or ""))
    return sorted({key for key in keys if key})


def story_decision(client, lineage_id: str) -> dict[str, Any] | None:
    """The story's current version, and the version that put it in that stage (who moved it, when, why). None if it is gone."""
    versions = sorted(client.list_by_index("itemsByLineageAndVersion", lineage_id), key=lambda version: int(version.get("versionNumber") or 0))
    if not versions:
        return None
    current = next((version for version in reversed(versions) if version.get("versionState") == "current"), versions[-1])
    stage = current.get("stage")
    entered = current
    for version in reversed([version for version in versions if int(version.get("versionNumber") or 0) <= int(current.get("versionNumber") or 0)]):
        if version.get("stage") != stage:
            break
        entered = version
    return {"current": current, "entered": entered}


def opinion_date(story: Mapping[str, Any], reference: Mapping[str, Any] | None, run: Mapping[str, Any]) -> str:
    front = _json(story.get("metadata")) or {}
    found = FRONT_MATTER_DATE.search(str(front.get("frontMatterYaml") or "")) if isinstance(front, dict) else None
    if found:
        return f"{found.group(1)}T00:00:00Z"
    return iso_day((reference or {}).get("sourcePublishedAt") or run.get("requestedAt"))


def reference_for_proceeding(references: Iterable[Mapping[str, Any]], proceeding: str) -> Mapping[str, Any] | None:
    pattern = re.compile(rf"(?<!\d){re.escape(proceeding)}(?!\d)")
    matches = [reference for reference in references if pattern.search(str(reference.get("sourceUri") or ""))]
    return min(matches, key=lambda reference: str(reference.get("lineageId")), default=None)


def ttab_rows(client, publication: str, references: list[Mapping[str, Any]], read_extracted: BodyReader | None, *,
              include_unlabeled: bool, skipped: dict[str, int]) -> list[dict[str, Any]]:
    keys = set(ttab_procedure_keys(client, publication))
    runs = sorted((run for run in client.list_records("ProcedureRun") if run.get("procedureKey") in keys and run.get("runStatus") == "completed"),
                  key=lambda run: str(run.get("requestedAt") or ""))
    latest_run_of_story: dict[str, Mapping[str, Any]] = {}
    for run in runs:
        story = (_json(run.get("output")) or {}).get("story")
        if isinstance(story, str) and story:
            latest_run_of_story[story] = run
    rows = []
    for story_id, run in sorted(latest_run_of_story.items()):
        decision = story_decision(client, story_id)
        proceeding = str((_json(run.get("input")) or {}).get("proceeding") or "")
        if decision is None or not proceeding:
            skipped["story gone or proceeding unknown"] += 1
            continue
        story, entered = decision["current"], decision["entered"]
        stage = str(story.get("stage") or "")
        label = STAGE_LABELS.get(stage)
        if label is None and not include_unlabeled:
            continue
        reference = reference_for_proceeding(references, proceeding)
        content = (reference_content(client, reference, read_extracted) if reference else {"title": str(story.get("title") or ""), "url": "", "summary": "", "body": ""})
        content["url"] = str((_json(run.get("input")) or {}).get("opinion_url") or content["url"])
        occurred = opinion_date(story, reference, run)
        actor = str(entered.get("versionCreatedBy") or "")
        machine = machine_story_actor(actor)
        labels: dict[str, Any] = {}
        provenance = {"source": SOURCE_TTAB, "state": stage or "unknown"}
        if label is not None:
            labels[DRAFT_ACCEPT] = {"label": label, "explanation": "" if machine else scrubbed(entered.get("changeReason"))}
            provenance.update(labeledBy=AUTOMATION if machine else EDITOR, labeledAt=iso_day(entered.get("versionCreatedAt")), modelMade=machine)
        else:
            provenance.update(labeledBy="", labeledAt="", modelMade=True)
        rows.append(row(f"ttab-{proceeding}-{occurred[:10]}", occurred, content, labels, provenance))
    return rows


# --- the export ---------------------------------------------------------------------------------------------------------


def export_priming(client, publication: str, corpus_key: str, *, include_unlabeled: bool = False,
                   read_extracted: BodyReader | None = None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    skipped = {"story gone or proceeding unknown": 0}
    references = [reference for reference in client.list_records("Reference")
                  if reference.get("corpusId") == corpus_key and reference.get("versionState") == "current"]
    rows = [built for built in (reference_row(client, reference, read_extracted, include_unlabeled=include_unlabeled)
                                for reference in sorted(references, key=lambda reference: str(reference["lineageId"]))) if built]
    rows += ttab_rows(client, publication, references, read_extracted, include_unlabeled=include_unlabeled, skipped=skipped)
    return rows, skipped


def encode_lines(rows: Iterable[Mapping[str, Any]]) -> str:
    return "".join(json.dumps(item, ensure_ascii=False, sort_keys=False) + "\n" for item in rows)


def summary_of(rows: list[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in rows:
        labels = item["labels"] or {"unlabeled": {"label": "-"}}
        for classifier, entry in labels.items():
            key = f"{classifier}\t{entry['label']}\tmodelMade={str(item['provenance']['modelMade']).lower()}"
            counts[key] = counts.get(key, 0) + 1
    return counts


def s3_extracted_text_reader() -> BodyReader:
    """Reads a Reference's `extracted_text` attachment from the storage bucket (read-only)."""
    from .source_readiness import select_extracted_text_attachment
    from .reference_url_text import resolve_storage_bucket_name

    state: dict[str, Any] = {}

    def read(reference: Mapping[str, Any], attachments: list[dict[str, Any]]) -> str:
        attachment = select_extracted_text_attachment(dict(reference), attachments)
        path = str((attachment or {}).get("storagePath") or "").strip()
        if not path:
            return ""
        if "s3" not in state:
            import boto3
            state["s3"], state["bucket"] = boto3.client("s3"), resolve_storage_bucket_name()
        return state["s3"].get_object(Bucket=state["bucket"], Key=path)["Body"].read().decode("utf-8", errors="replace").strip()

    return read


def cyclotron_export_priming(flags: list[str]) -> None:
    """papyrus cyclotron export-priming --publication <id> --corpus-key <key> [--include-unlabeled] [--out FILE]"""
    options = parse_options(flags)
    publication, corpus_key = normalize_string(options.get("publication")), normalize_string(options.get("corpus-key"))
    if not publication or not corpus_key:
        raise ValueError("Usage: papyrus cyclotron export-priming --publication <id> --corpus-key <key> [--include-unlabeled] [--out FILE]")
    out = normalize_string(options.get("out"))
    client, _ = create_authoring_client()
    rows, skipped = export_priming(client, publication, corpus_key, include_unlabeled=bool(options.get("include-unlabeled")),
                                   read_extracted=s3_extracted_text_reader())
    text = encode_lines(rows)
    if out:
        with open(out, "w", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    print(f"cyclotron\texport-priming\t{len(rows)}\t{out or 'stdout'}", file=sys.stderr)
    for key, count in sorted(summary_of(rows).items()):
        print(f"  {key}\t{count}", file=sys.stderr)
    for reason, count in skipped.items():
        if count:
            print(f"  skipped\t{reason}\t{count}", file=sys.stderr)
