"""Independently authored companions, not translations (PPY-219a24).

Each companion has its own sources, structure and editorial checklist. Its language
family is only a navigation relationship; no alignment, model or translation request
is manufactured. All entry points that generate translations must respect ownership.
"""

from __future__ import annotations
import hashlib
import json
from typing import Any


def metadata(row):
    value = (row or {}).get("metadata") or {}
    return json.loads(value) if isinstance(value, str) else value


def is_authored(row):
    return metadata(row).get("authoredEdition", {}).get("kind") == "independent"


def current_companion(client, story, language):
    from .item_language import localization_lineage_id
    from .story_reporting import story_versions

    rows = story_versions(client, localization_lineage_id(story, language))
    return next((r for r in rows if r.get("versionState") == "current"), rows[0] if rows else None)


def require_translation_owned(client, story, language):
    if is_authored(current_companion(client, story, language)):
        raise ValueError(f"{story} has an independently authored {language} edition; translation cannot replace it.")


def import_edition(
    client,
    *,
    story: str,
    language: str,
    body: str,
    front_matter: str,
    written_by: str,
    author_kind: str,
    applied_by: str,
    reason: str,
    apply: bool = True,
) -> dict[str, Any]:
    from .editorial_checks import GraphQLEditorialStore, settings_from
    from .editorial_languages import site_language
    from .language_serving import serving_languages
    from .item_language import localization_lineage_id, item_language, bare_group_id
    from .localize import desired_state
    from .publishing import (
        _load_front_matter,
        _derive_or_raise,
        columns_from_front_matter,
        ItemFields,
        _source_content_hash,
        _status_keys,
        utc_now_iso,
    )
    from .story_reporting import published_story_version, story_versions, _carry_media_forward
    from .story_checklist import sync_checklist
    from .record_helpers import to_aws_json, compact_dict
    from .language_serving import localized_slug, unique_slug
    from .content_item_lifecycle import head_stage_fields

    if author_kind not in ("agent", "person") or not written_by.strip() or not reason.strip():
        raise ValueError("Name the writer, author-kind agent|person, and reason.")
    primary = published_story_version(client, story)
    if not primary:
        raise ValueError("The original Story must be published first.")
    tenant = getattr(client, "tenant_id", None)
    if tenant and primary.get("tenantId") not in (None, tenant):
        raise ValueError("The original belongs to another tenant.")
    group = bare_group_id(primary.get("languageGroupId"), tenant)
    lineage = primary.get("lineageId")
    if group != lineage:
        raise ValueError("Name the original Story, not a companion.")
    settings = settings_from(GraphQLEditorialStore(execute=client.graphql, tenant_id=tenant))
    serving = serving_languages(settings)
    target = site_language(language, settings)
    if item_language(primary) != serving.primary or target == serving.primary:
        raise ValueError("A companion needs a different enabled language of the primary Story.")
    locale = localization_lineage_id(lineage, target)
    front = _load_front_matter(front_matter)
    if not isinstance(front.get("title"), str) or not front["title"].strip() or not body.strip():
        raise ValueError("The independently authored copy needs its own title and nonempty body.")
    if author_kind == "agent" and (front.get("drafting") or {}).get("by") != "AI":
        raise ValueError("Agent-authored copy must truthfully declare drafting.by: AI.")
    envelope = _derive_or_raise(front_matter, body)
    digest = hashlib.sha256(json.dumps([front_matter, body, written_by, author_kind], ensure_ascii=False).encode()).hexdigest()
    request = desired_state.current(client, lineage, target)
    if request and request.get("state") in ("wanted", "started"):
        raise ValueError("A translation is queued or in flight; resolve it before importing an authored edition.")
    rows = story_versions(client, locale)
    if rows:
        existing = next((r for r in rows if r.get("versionState") == "current"), rows[0])
        if (
            is_authored(existing)
            and metadata(existing)["authoredEdition"].get("inputHash") == digest
            and existing.get("bodyMarkus") == body
            and metadata(existing).get("frontMatterYaml") == front_matter
        ):
            return {"lineage": locale, "language": target, "unchanged": True, "record": existing, "published": False}
        raise ValueError(f"{locale} already exists; an authored import never replaces another edition.")

    # Use the edition's own title for its stable address, not the primary's title.
    def taken(value):
        return any(
            r.get("language") == target and r.get("section") == primary.get("section") for r in client.list_by_index("itemBySlug", value)
        )

    slug = unique_slug(localized_slug(front["title"], serving.slugs[target], primary_slug=primary["slug"]), taken)
    if not slug:
        raise ValueError("The edition title cannot form an address.")
    now = utc_now_iso()
    record_id = f"{locale}-v1"
    fields = ItemFields(
        type=primary["type"], slug=slug, section=primary.get("section"), front_matter_yaml=front_matter, body_markus=body, aliases=[]
    )
    provenance = {
        "kind": "independent",
        "writtenBy": written_by,
        "authorKind": author_kind,
        "appliedBy": applied_by,
        "reason": reason,
        "inputHash": digest,
        "createdAt": now,
        "originalLineage": lineage,
    }
    row = {
        "id": record_id,
        "lineageId": locale,
        "versionNumber": 1,
        "versionState": "current",
        "versionCreatedAt": now,
        "versionCreatedBy": written_by,
        "changeReason": reason,
        "type": primary["type"],
        "section": primary.get("section"),
        "slug": slug,
        "aliases": [],
        "stage": "copywriting",
        "status": "draft",
        **_status_keys(primary["type"], primary.get("section"), "draft"),
        **columns_from_front_matter(front),
        "body": [],
        "bodyMarkus": body,
        "bodyIr": to_aws_json(envelope),
        "metadata": to_aws_json({"frontMatterYaml": front_matter, "authoredEdition": provenance}),
        "contentHash": _source_content_hash(fields),
        "language": target,
        "languageGroupId": lineage,
    }
    row.update(head_stage_fields(row))
    result = {
        "lineage": locale,
        "language": target,
        "unchanged": False,
        "record": None,
        "published": False,
        "bodyHash": hashlib.sha256(body.encode()).hexdigest(),
    }
    if not apply:
        return result
    client.create_record("Item", compact_dict(row))
    _carry_media_forward(client, record_id, envelope, front_matter, [primary])
    sync_checklist(client, locale)
    result["record"] = row
    return result
