"""Promote a monitor record to a normal item, and suggest which records to promote (docs/knowledge-cloud-run.md).

A monitor record (a delivered Hugging Face Hub model, say) counts in the Knowledge Map as data and is never a page. A person
who finds one worth a story promotes it: ``papyrus references promote <reference id> --section <section>`` saves a **draft**
article in that section. It carries the source link, the structured facts and the entities the Hub's fields name, and it says
in its body that it is a stub for an editor to write. Nothing is published, the Reference's curation state is not changed,
and promoting twice is a no-op, so the editor's text is never overwritten.

``suggest`` picks the records most worth a look for the weekly run's one soft review request: the newest records in the
window ranked by what the Hub itself shows (likes, then downloads), without any model. A record already promoted is not
suggested again.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

import yaml

from .knowledge_snapshot.monitor_records import MonitorRecord, record_entities, record_summary
from .knowledge_snapshot.weeks import parse_day
from .publishing import ItemFields, item_id_for, save_item
from .record_helpers import slugify

SECTION = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ITEM_TYPE = "article"
MONITOR_RECORD_KEY = "monitorRecord"
SUGGESTION_WEEKS = 4


def validate_section(value: Any) -> str:
    section = str(value or "").strip() if value is not True else ""
    if not SECTION.match(section):
        raise ValueError("references promote requires --section <section> (lowercase letters, digits and single hyphens).")
    return section


def promotion_slug(record: MonitorRecord) -> str:
    return slugify(record.model_id) or slugify(record.reference_id)


def promotion_item_id(record: MonitorRecord, section: str) -> str:
    return item_id_for(section, promotion_slug(record))


def front_matter(record: MonitorRecord) -> dict[str, Any]:
    """The draft's front matter: title and deck, the entities, the source link and the record's own facts. No ``date``: a
    published item takes its publication date when an editor publishes it, not the model's release date."""
    details = record.details
    facts = {
        name: details[name]
        for name in ("modelId", "author", "pipelineTag", "license", "libraryName", "likes", "downloads", "sha")
        if details.get(name) not in (None, "")
    }
    return {
        "title": record.model_id,
        "deck": record_summary(record),
        "entities": [{"kind": kind, "name": name} for kind, name in record_entities(record)],
        "sources": [{"title": record.model_id, "url": record.url, "provenance": record.provenance}],
        MONITOR_RECORD_KEY: {"referenceId": record.reference_id, "source": record.source, "released": record.created_at[:10], **facts, "baseModels": details.get("baseModels") or []},
    }


def body(record: MonitorRecord) -> str:
    details = record.details
    kind = f"{details['pipelineTag']} model" if details.get("pipelineTag") else "model"
    lines = [f"[{record.model_id}]({record.url}) is a {kind}" + (f" by {details['author']}" if details.get("author") else "") + f", released {record.created_at[:10]}."]
    if details.get("license"):
        lines[0] += f" Its licence is {details['license']}."
    bases = [base for base in details.get("baseModels") or [] if base.get("modelId")]
    if bases:
        lines.append("It is built on " + ", ".join(f"[{base['modelId']}](https://huggingface.co/{base['modelId']}) ({base.get('relation') or 'declared'})" for base in bases[:3]) + ".")
    lines.append(f"This is a draft stub made from a record {record.provenance}. An editor writes the story before anything is published.")
    return "\n\n".join(lines) + "\n"


def promote_record(client: Any, record: MonitorRecord, *, section: str, actor: str, now: str | None = None) -> dict[str, Any]:
    """Save the draft item for a record, or report the one already saved. Returns ``itemId``, ``slug`` and ``created``."""
    section = validate_section(section)
    slug, item_id = promotion_slug(record), promotion_item_id(record, section)
    if client.get_record("Item", item_id) is not None:
        return {"itemId": item_id, "slug": slug, "section": section, "created": False}
    fields = ItemFields(
        type=ITEM_TYPE, slug=slug, section=section, front_matter_yaml=yaml.safe_dump(front_matter(record), sort_keys=False, allow_unicode=True, width=1000),
        body_markus=body(record), aliases=[], id=item_id,
    )
    save_item(client, fields, actor=actor, now=now)
    return {"itemId": item_id, "slug": slug, "section": section, "created": True}


def promoted_reference_ids(client: Any, records: Iterable[MonitorRecord]) -> set[str]:
    """Reference ids of ``records`` that some item already carries in its front matter (``monitorRecord.referenceId``)."""
    wanted = {record.reference_id for record in records}
    found: set[str] = set()
    for row in client.list_records("Item"):
        metadata = row.get("metadata")
        text = str(metadata.get("frontMatterYaml") if isinstance(metadata, dict) else metadata or "")
        if MONITOR_RECORD_KEY in text:
            found.update(reference_id for reference_id in wanted if reference_id in text)
    return found


def suggest(records: Iterable[MonitorRecord], *, limit: int, as_of: date, promoted: set[str] = frozenset()) -> list[MonitorRecord]:
    """The ``limit`` records of the last ``SUGGESTION_WEEKS`` weeks that the Hub itself shows the most interest in, most liked first
    (downloads break a tie, then the model id), leaving out records already promoted (their reference ids in ``promoted``)."""
    since = as_of - timedelta(weeks=SUGGESTION_WEEKS)

    def interest(record: MonitorRecord) -> tuple[int, int, str]:
        return (-int(record.details.get("likes") or 0), -int(record.details.get("downloads") or 0), record.model_id)

    recent = [record for record in records if not record.routed and record.reference_id not in promoted and since <= parse_day(record.created_at) <= as_of + timedelta(days=6)]
    return sorted(recent, key=interest)[:limit]
