"""The translation run against a Papyrus backend: collect its inputs, keep its stages, save its result (PPY-843a7c).

* :func:`collect` reads the published primary version, the previous localization and its alignment, the glossary, the language's pack and
  register notes and the measured spend of earlier runs, and builds the run key.
* :class:`AttachmentStageStore` keeps each stage's result as a JSON ModelAttachment on the source version (role ``localize_stage``), so a run
  interrupted by an outage continues from its finished stages.
* :func:`save` records the translation as a new version of the sibling lineage ``{primary}--{language}``: author AI, unpublished, with no board
  stage (translations stay off the board and the English listings until the listing keys carry the language), the source version it came from,
  and its provenance as a ModelAttachment (role ``localization_provenance``). It never publishes and never writes the English Story, except the
  advice of :func:`report_back`.
* :func:`hold` raises a flag review request naming why the translation is held.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..item_language import localization_lineage_id
from ..publishing import utc_now_iso
from ..record_helpers import compact_dict, to_aws_json
from .engine import AlignedBlock, LocalizeRequest, SourceVersion, stage_key
from .models import PROMPT_VERSION

ACTOR = "AI"
STAGE_ROLE = "localize_stage"
PROVENANCE_ROLE = "localization_provenance"
ADVICE_KEY = "translationAdvice"
RAISED_BY = "papyrus.story.localize"


class NothingToDo(Exception):
    """The run has nothing to do; the message says why (not published, do not localize, already the newest translation)."""


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("metadata")
    if isinstance(value, str) and value.strip():
        return json.loads(value)
    return dict(value or {})


class AttachmentStageStore:
    """Stage results as JSON attachments of one source version: one ModelAttachment per stage key, found by its owner, role and sort key."""

    def __init__(self, client, owner: dict[str, Any]):
        self.client, self.owner = client, owner

    def _attachment(self, key: str) -> dict[str, Any]:
        from ..model_attachments import model_attachment_id

        return {"id": model_attachment_id("item", self.owner["id"], STAGE_ROLE, key)}

    def get(self, key: str) -> dict[str, Any] | None:
        from ..model_attachments import download_attachment_buffer

        row = self.client.get_record("ModelAttachment", self._attachment(key)["id"])
        if row is None:
            return None
        body = download_attachment_buffer(self.client, row)
        return json.loads(body) if body else None

    def put(self, key: str, value: dict[str, Any]) -> None:
        from ..model_attachments import build_json_model_payload_attachment, upload_attachment_body

        entry = build_json_model_payload_attachment({"ownerKind": "item", "ownerId": self.owner["id"], "ownerLineageId": self.owner["lineageId"],
                                                     "ownerVersionNumber": self.owner.get("versionNumber"), "role": STAGE_ROLE, "sortKey": key,
                                                     "filename": f"{hashlib.sha256(key.encode()).hexdigest()[:24]}.json", "content": value,
                                                     "now": utc_now_iso()})
        upload_attachment_body(self.client, entry["attachment"], entry["body"])


def source_version(row: dict[str, Any], language: str) -> SourceVersion:
    return SourceVersion(lineage_id=row["lineageId"], version_id=row["id"], version_number=int(row.get("versionNumber") or 0),
                         content_hash=str(row.get("contentHash") or ""), language=language, title=row.get("title") or row.get("headline") or "",
                         deck=row.get("deck") or "", body=row.get("bodyMarkus") or "", section=row.get("section"))


def run_key(source: SourceVersion, language: str, *, procedure_version: str, checker_versions: dict[str, str]) -> str:
    """Same key, same run: the group, the language, the exact source text, the procedure, the language packs, the policies and the glossary."""
    parts = [source.lineage_id, language, source.content_hash, procedure_version, PROMPT_VERSION, checker_versions]
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:32]


def previous_alignment(client, lineage: str) -> tuple[dict[str, Any] | None, list[AlignedBlock] | None]:
    """The localization's current version and its alignment (from its provenance), or (None, None) before the first translation."""
    from ..model_attachments import download_attachment_buffer, model_attachment_id
    from ..story_reporting import story_versions

    versions = story_versions(client, lineage)
    if not versions:
        return None, None
    current = next((row for row in versions if row.get("versionState") == "current"), versions[0])
    row = client.get_record("ModelAttachment", model_attachment_id("item", current["id"], PROVENANCE_ROLE, PROVENANCE_ROLE))
    if row is None:
        raise ValueError(f"Localization version {current['id']} has no provenance record; its alignment cannot be read.")
    provenance = json.loads(download_attachment_buffer(client, row))
    return current, [AlignedBlock(entry.get("sourceBlock"), entry["text"], entry.get("owner", "machine"), bool(entry.get("pinned")))
                     for entry in provenance["alignment"]]


def register_notes(writing: dict[str, Any]) -> list[str]:
    """The writing guidelines' fields that a language overlay set (register, words to prefer and avoid), as lines for the translator."""
    notes: list[str] = []
    for key, sources in (writing.get("fieldSources") or {}).items():
        if not any(source.get("layer") in ("language", "section-language") for source in sources):
            continue
        value = (writing.get("document") or {}).get(key)
        if isinstance(value, str):
            notes.append(f"{key}: {value}")
        elif isinstance(value, list):
            notes += [f"{key}: {item}" if isinstance(item, str) else f"{key}: {json.dumps(item, ensure_ascii=False)}" for item in value]
        elif isinstance(value, dict):
            notes.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    return notes


def spend_history(client, procedure_key: str) -> list[dict[str, Any]]:
    """Earlier runs' measured cost and size by language, from the run records the runner keeps (newest page)."""
    history = []
    for run in client.recent_procedure_runs(procedure_key):
        output = run.get("output")
        output = json.loads(output) if isinstance(output, str) else (output or {})
        if run.get("runStatus") == "completed" and output.get("sourceCharacters") and output.get("costUsd") is not None:
            history.append({"language": output.get("language"), "sourceCharacters": output["sourceCharacters"], "costUsd": output["costUsd"]})
    return history


def collect(client, *, story: str, language: str, judge, procedure_version: str, ceiling_usd: float | None = None,
            decision_model: Any = None) -> LocalizeRequest:
    """Stage 1: everything the run needs, read through indexes. Refuses a Story that is not published or is marked do-not-localize."""
    from ..editorial_checks import GraphQLEditorialStore, settings_from
    from ..editorial_languages import site_language, starter_packs_for, story_language
    from ..editorial_model_context import editing_pack_and_context
    from ..guidelines import GuidelineStore
    from ..guidelines.layering import resolve_guidelines
    from ..story_reporting import published_story_version
    from ..translation_glossary import resolve_glossary
    from .budget import predict
    from .checks import BlockChecker
    from .blocks import blocks_of
    from .engine import PROCEDURE_KEY

    store = GraphQLEditorialStore(execute=client.graphql, tenant_id=getattr(client, "tenant_id", None))
    settings = settings_from(store)
    row = published_story_version(client, story)
    if row is None:
        raise NothingToDo(f"Story {story} is not published; a Story is translated from its published version.")
    if _metadata(row).get("doNotLocalize"):
        raise NothingToDo(f"Story {story} is marked do not localize.")
    source_language = story_language(row, settings)
    target = site_language(language, settings)
    if target == source_language:
        raise ValueError(f"Story {story} is already written in {target}.")
    source = source_version(row, source_language)
    lineage = localization_lineage_id(story, target)
    current, previous = previous_alignment(client, lineage)
    guidelines = GuidelineStore(client)
    glossary = resolve_glossary(guidelines, target, source.section)
    pack, _ = editing_pack_and_context(store, source.section, settings, target)
    pack["papyrusStarterPacks"] = list(starter_packs_for(target))
    source_pack, _ = editing_pack_and_context(store, source.section, settings, source_language)
    source_pack["papyrusStarterPacks"] = list(starter_packs_for(source_language))
    lanes = {"rules": bool(settings["lanes"].get("rules", True)), "classifier": bool(settings["lanes"].get("classifier", False))}
    checker = BlockChecker(source_language=source_language, target_language=target, glossary=glossary, copy_edit_pack=pack, judge=judge,
                           lanes=lanes, decision_model=decision_model)
    english = BlockChecker(source_language=source_language, target_language=source_language, glossary=glossary, copy_edit_pack=source_pack,
                           judge=None, lanes={"rules": True, "classifier": False})
    key = run_key(source, target, procedure_version=procedure_version, checker_versions=checker.versions)
    characters = sum(len(block.text) for block in blocks_of(source.body, title=source.title, deck=source.deck) if block.translated)
    return LocalizeRequest(
        source=source, language=target, localization_lineage=lineage, run_key=key, glossary=glossary, checker=checker,
        register_notes=register_notes(resolve_guidelines(guidelines, "writing", source.section, target)),
        previous=previous, previous_source_hash=_metadata(current).get("localization", {}).get("sourceContentHash") if current else None,
        prediction=predict(target, characters, spend_history(client, PROCEDURE_KEY)), ceiling_usd=ceiling_usd,
        procedure_version=procedure_version, source_checker=lambda text: english.copy_edit(text)[0])


def _front_matter(primary: dict[str, Any], title: str, deck: str) -> str | None:
    """The primary version's front matter with the reader-facing text replaced by the translation's."""
    import yaml

    from ..publishing import _load_front_matter

    loaded = _load_front_matter(_metadata(primary).get("frontMatterYaml"))
    if not loaded:
        return None
    if title:
        loaded["title"] = title
    for key in ("deck", "standfirst", "description"):
        if key in loaded and deck:
            loaded[key] = deck
    return yaml.safe_dump(loaded, allow_unicode=True, sort_keys=False)


def save(client, request: LocalizeRequest, outcome: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    """Records the translation as the next version of the localization lineage (version 1 the first time) and its provenance. Unpublished,
    no board stage, author AI. Refuses when a newer source was translated meanwhile (an older run never replaces newer work)."""
    from ..model_attachments import build_json_model_payload_attachment, upload_attachment_body
    from ..publishing import ItemFields, _derive_or_raise, _source_content_hash, _status_keys, _without_server_fields
    from ..story_reporting import next_version_record_id, story_versions, superseding_update

    now = now or utc_now_iso()
    primary = client.get_record("Item", request.source.version_id)
    versions = story_versions(client, request.localization_lineage)
    latest = next((row for row in versions if row.get("versionState") == "current"), versions[0] if versions else None)
    if latest is not None and int(latest.get("sourceVersionNumber") or 0) > request.source.version_number:
        raise ValueError(f"{request.localization_lineage} already holds a translation of source version {latest['sourceVersionNumber']}; "
                         f"this run translated version {request.source.version_number} and saves nothing.")
    translation = outcome["translation"]
    front_matter = _front_matter(primary, translation["title"], translation["deck"])
    fields = ItemFields(type=primary["type"], slug=primary["slug"], section=primary.get("section"), front_matter_yaml=front_matter,
                        body_markus=translation["body"], aliases=[])
    envelope = _derive_or_raise(front_matter, translation["body"])
    number = (max(int(row.get("versionNumber") or 0) for row in versions) + 1) if versions else 1
    record_id = next_version_record_id(request.localization_lineage, number, {row["id"] for row in versions})
    metadata = {"frontMatterYaml": front_matter,
                "localization": {"runKey": request.run_key, "outcome": outcome["outcome"], "reason": outcome["reason"], "translation": "machine",
                                 "reviewed": False, "sourceContentHash": request.source.content_hash, "rounds": outcome["rounds"],
                                 "revertedBlocks": outcome["revertedBlocks"], "costUsd": outcome["costUsd"]}}
    base = {name: value for name, value in _without_server_fields(primary).items()
            if name not in ("starRating", "starRatedAt", "starRatedBy", "headStageKey", "scheduledPublishAt", "scheduledBy", "scheduledAt",
                            "scheduleState", "scheduleName", "tenantSlug", "shortSlug")}
    record = {
        **base,
        "id": record_id, "lineageId": request.localization_lineage, "versionNumber": number,
        "previousVersionId": latest["id"] if latest else None, "versionState": "current", "versionCreatedAt": now, "versionCreatedBy": ACTOR,
        "changeReason": f"translation of version {request.source.version_number} into {request.language}",
        "stage": None, "headStageKey": None, "status": "draft", **_status_keys(fields.type, fields.section, "draft"),
        "title": translation["title"] or None, "headline": translation["title"] or None, "sortTitle": translation["title"] or None,
        "deck": translation["deck"] or None, "body": [], "bodyMarkus": fields.body_markus, "bodyIr": to_aws_json(envelope),
        "metadata": to_aws_json(metadata), "contentHash": _source_content_hash(fields),
        "publishedAt": None, "versionPublishedAt": None, "versionPublishedBy": None,
        "language": request.language, "languageGroupId": request.source.lineage_id, "sourceLineageId": request.source.lineage_id,
        "sourceVersionNumber": request.source.version_number, "sourceContentHash": request.source.content_hash, "syncState": "current",
    }
    client.create_record("Item", compact_dict(record))
    alignment = [{**entry, "text": text} for entry, text in zip(outcome["provenance"]["alignment"], outcome["translation"]["blocks"])]
    provenance = {**outcome["provenance"], "alignment": alignment, "target": {**outcome["provenance"]["target"], "versionId": record_id}}
    entry = build_json_model_payload_attachment({"ownerKind": "item", "ownerId": record_id, "ownerLineageId": request.localization_lineage,
                                                 "ownerVersionNumber": number, "role": PROVENANCE_ROLE, "sortKey": PROVENANCE_ROLE,
                                                 "filename": "provenance.json", "content": provenance, "now": now})
    upload_attachment_body(client, entry["attachment"], entry["body"])
    for row in versions:
        if row.get("versionState") != "superseded":
            client.update_record("Item", superseding_update(row))
    return record


def report_back(client, request: LocalizeRequest, advice: list[dict[str, Any]]) -> None:
    """Stock phrasing found in the translation that the English block has too, as advice on the English version (Item.metadata.translationAdvice,
    per language). The only write this procedure makes to the English Story."""
    if not advice:
        return
    row = client.get_record("Item", request.source.version_id)
    metadata = _metadata(row)
    metadata.setdefault(ADVICE_KEY, {})[request.language] = {"runKey": request.run_key, "at": utc_now_iso(), "phrases": advice}
    client.update_record("Item", {"id": row["id"], "metadata": to_aws_json(metadata), **({"updatedAt": row["updatedAt"]} if row.get("updatedAt") else {})})


def hold(client, request: LocalizeRequest, reason: str) -> dict[str, Any]:
    """A flag review request on the localization, saying why it is held. Idempotent per run key."""
    from ..review_requests import raise_review

    return raise_review(client, subject={"type": "story", "id": request.localization_lineage}, mode="flag",
                        reason=f"The {request.language} translation is held: {reason}"[:1900], raised_by=RAISED_BY,
                        request_id=f"localize-{request.run_key[:24]}")


def stage_store_for(client, request: LocalizeRequest) -> AttachmentStageStore:
    return AttachmentStageStore(client, {"id": request.source.version_id, "lineageId": request.source.lineage_id,
                                         "versionNumber": request.source.version_number})


__all__ = ["AttachmentStageStore", "NothingToDo", "collect", "hold", "report_back", "save", "stage_key", "stage_store_for"]
