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

from copy import deepcopy
from dataclasses import replace

import hashlib
import json
from typing import Any

from ..item_front_matter import DEK_KEYS
from ..item_language import localization_lineage_id, translation_original
from ..localization_publish import hold_request_id
from ..publishing import utc_now_iso
from ..record_helpers import compact_dict, to_aws_json
from .blocks import FRONT_MATTER_FIELDS
from .engine import AlignedBlock, LocalizeRequest, SourceVersion, stage_key
from .image_variants import carry_forward, images_with_text, normalize, read_variants, revert_body
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


def figure_facts(client, version_id: str) -> dict[str, dict[str, Any]]:
    """What `papyrus figures render` recorded about each stored picture of a version (``MediaAsset.metadata.figure``), by normalized stored path."""
    facts: dict[str, dict[str, Any]] = {}
    for media in client.list_by_index("mediaAssetsByItemAndSortKey", version_id):
        metadata = _metadata(media)
        path = normalize(metadata.get("srcPath"))
        if path and isinstance(metadata.get("figure"), dict):
            facts[path] = metadata["figure"]
    return facts


def with_image_variants(client, row: dict[str, Any], source: SourceVersion, current: dict[str, Any] | None,
                        previous: list[AlignedBlock] | None) -> tuple[SourceVersion, list[AlignedBlock] | None, list[Any]]:
    """What a run needs to know about pictures. The source with the figures and cover that hold words listed (advice for an editor, ``images_with_text``);
    the translation's language variants (``image_variants``); and the previous alignment with those variants put back to the original's pictures, because the
    run compares texts that name the original's pictures and :func:`save` applies the variants again."""
    variants = read_variants(_metadata(current).get("frontMatterYaml")) if current else []
    if variants and previous:
        previous = [replace(block, text=revert_body(block.text, variants)) for block in previous]
    found = images_with_text(source.body, _metadata(row).get("frontMatterYaml"), figure_facts(client, row["id"]), variants)
    return replace(source, images_with_text=tuple(found)), previous, variants


def _source_fields(row: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """The reader-facing front matter texts the Story has, in the order of ``FRONT_MATTER_FIELDS``."""
    from ..item_front_matter import front_matter

    loaded = front_matter(row)
    return tuple((key, loaded[key]) for key in FRONT_MATTER_FIELDS if isinstance(loaded.get(key), str) and loaded[key].strip())


def source_version(row: dict[str, Any], language: str) -> SourceVersion:
    return SourceVersion(lineage_id=row["lineageId"], version_id=row["id"], version_number=int(row.get("versionNumber") or 0),
                         content_hash=str(row.get("contentHash") or ""), language=language, title=row.get("title") or row.get("headline") or "",
                         deck=row.get("deck") or "", body=row.get("bodyMarkus") or "", section=row.get("section"), fields=_source_fields(row))


def run_key(source: SourceVersion, language: str, *, procedure_version: str, checker_versions: dict[str, str]) -> str:
    """Same key, same run: the group, the language, the exact source text, the procedure, the language packs, the policies and the glossary."""
    parts = [source.lineage_id, language, source.content_hash, procedure_version, PROMPT_VERSION, checker_versions]
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:32]


def read_provenance(client, version: dict[str, Any]) -> dict[str, Any]:
    """The provenance record of one localization version (its alignment included). Raises when the version has none."""
    from ..model_attachments import download_attachment_buffer, model_attachment_id

    row = client.get_record("ModelAttachment", model_attachment_id("item", version["id"], PROVENANCE_ROLE, PROVENANCE_ROLE))
    if row is None:
        raise ValueError(f"Localization version {version['id']} has no provenance record; its alignment cannot be read.")
    return json.loads(download_attachment_buffer(client, row))


def previous_alignment(client, lineage: str) -> tuple[dict[str, Any] | None, list[AlignedBlock] | None]:
    """The localization's current version and its alignment (from its provenance), or (None, None) before the first translation."""
    from ..story_reporting import story_versions

    versions = story_versions(client, lineage)
    if not versions:
        return None, None
    current = next((row for row in versions if row.get("versionState") == "current"), versions[0])
    from ..authored_editions import is_authored
    if is_authored(current):
        raise ValueError(f"{lineage} is independently authored; translation cannot replace it.")
    provenance = read_provenance(client, current)
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


def automation_procedure_key(client, automation_id: str | None) -> str | None:
    """The key the site registered the translation procedure under: the procedureKey of the automation that runs it (a site names its keys,
    `SITE.story-localize`). None when no automation is named (a plan), so there is no measured history to read."""
    if not automation_id:
        return None
    row = client.get_record("Automation", automation_id)
    if not row or not row.get("procedureKey"):
        raise ValueError(f"The automation {automation_id} does not exist, or names no procedure. Create it first (docs/automations.md).")
    return str(row["procedureKey"])


def collect(client, *, story: str, language: str, judge, procedure_version: str, ceiling_usd: float | None = None,
            decision_model: Any = None, automation_id: str | None = None, procedure_key: str | None = None,
            history: list[dict[str, Any]] | None = None, shared: dict[Any, Any] | None = None) -> LocalizeRequest:
    """Stage 1: everything the run needs, read through indexes. Refuses a Story that is not published or is marked do-not-localize.
    ``procedure_key`` (or the procedure of ``automation_id``) names the registered procedure whose earlier runs give the cost prediction; a caller that
    plans many Stories reads those runs once and passes them as ``history``, and one ``shared`` dict, in which what depends only on the site, the section and
    the language (the settings, the editing packs, the glossary, the register guidelines) is read once for the whole plan instead of once per Story."""
    def once(key, read):
        if shared is None:
            return read()
        if key not in shared:
            shared[key] = read()
        return shared[key]

    from ..editorial_checks import GraphQLEditorialStore, settings_from
    from ..editorial_languages import register_packs_for, site_language, starter_packs_for, story_language
    from ..editorial_model_context import editing_pack_and_context
    from ..guidelines import GuidelineStore
    from ..guidelines.layering import resolve_guidelines
    from ..language_serving import serving_languages
    from ..story_reporting import published_story_version
    from ..translation_glossary import resolve_glossary
    from .budget import predict
    from .checks import BlockChecker
    from .blocks import blocks_of

    row = published_story_version(client, story)
    if row is None:
        raise NothingToDo(f"Story {story} is not published; a Story is translated from its published version.")
    original = translation_original(row, getattr(client, "tenant_id", None))
    if original is not None:
        raise ValueError(f"Story {story} is itself a translation of {original}; translate the original, not its translation.")
    if _metadata(row).get("doNotLocalize"):
        raise NothingToDo(f"Story {story} is marked do not localize.")
    store = GraphQLEditorialStore(execute=client.graphql, tenant_id=getattr(client, "tenant_id", None))
    settings = once("settings", lambda: settings_from(store))
    source_language = story_language(row, settings)
    target = site_language(language, settings)
    if target == source_language:
        raise ValueError(f"Story {story} is already written in {target}.")
    source = source_version(row, source_language)
    lineage = localization_lineage_id(story, target)
    current, previous = previous_alignment(client, lineage)
    source, previous, variants = with_image_variants(client, row, source, current, previous)
    guidelines = GuidelineStore(client)
    glossary = once(("glossary", target, source.section), lambda: resolve_glossary(guidelines, target, source.section))
    pack = deepcopy(once(("pack", source.section, target), lambda: editing_pack_and_context(store, source.section, settings, target))[0])
    pack["papyrusStarterPacks"] = [*starter_packs_for(target), *register_packs_for(target)]   # names the category of each finding; the policies come from the site
    source_pack = deepcopy(once(("pack", source.section, source_language), lambda: editing_pack_and_context(store, source.section, settings, source_language))[0])
    source_pack["papyrusStarterPacks"] = list(starter_packs_for(source_language))
    lanes = {"rules": bool(settings["lanes"].get("rules", True)), "classifier": bool(settings["lanes"].get("classifier", False))}
    notes = once(("register", source.section, target), lambda: register_notes(resolve_guidelines(guidelines, "writing", source.section, target)))
    checker = BlockChecker(source_language=source_language, target_language=target, glossary=glossary, copy_edit_pack=pack, judge=judge,
                           lanes=lanes, decision_model=decision_model, notes=notes)   # the judge reads the notes the translator does
    english = BlockChecker(source_language=source_language, target_language=source_language, glossary=glossary, copy_edit_pack=source_pack,
                           judge=None, lanes={"rules": True, "classifier": False})
    procedure_key = procedure_key or (automation_procedure_key(client, automation_id) if history is None else None)
    history = history if history is not None else (spend_history(client, procedure_key) if procedure_key else [])
    key = run_key(source, target, procedure_version=procedure_version, checker_versions=checker.versions)
    characters = sum(len(block.text) for block in blocks_of(source.body, title=source.title, deck=source.deck, fields=source.fields) if block.translated)
    return LocalizeRequest(
        source=source, language=target, localization_lineage=lineage, run_key=key, glossary=glossary, checker=checker,
        slug_policy=serving_languages(settings).slugs[target],
        register_notes=notes,
        previous=previous, previous_source_hash=_metadata(current).get("localization", {}).get("sourceContentHash") if current else None,
        prediction=predict(target, characters, history), ceiling_usd=ceiling_usd,
        procedure_version=procedure_version, source_checker=lambda text: english.copy_edit(text)[0], image_variants=variants)


def _front_matter(primary: dict[str, Any], title: str, deck: str, fields: dict[str, str] | None = None) -> str | None:
    """The primary version's front matter with the reader-facing text replaced by the translation's."""
    import yaml

    from ..publishing import _load_front_matter

    loaded = _load_front_matter(_metadata(primary).get("frontMatterYaml"))
    if not loaded:
        return None
    if title:
        loaded["title"] = title
    for key in DEK_KEYS:
        if key in loaded and deck:
            loaded[key] = deck
    for key, text in (fields or {}).items():
        if key in loaded and text:
            loaded[key] = text
    return yaml.safe_dump(loaded, allow_unicode=True, sort_keys=False)


def _first_slug(client, request: LocalizeRequest, primary: dict[str, Any], title: str) -> str:
    """The localization's own address, drafted once at its first version by the language's slug policy, unique among the Stories of its language in the
    section. Every later version keeps it (the slug lock); ``papyrus stories set-slug`` changes it before the first publish."""
    from ..language_serving import localized_slug, unique_slug

    def taken(slug: str) -> bool:
        return any((row.get("lineageId") or row["id"]) != request.localization_lineage and row.get("language") == request.language
                   and row.get("section") == primary.get("section") for row in client.list_by_index("itemBySlug", slug))

    return unique_slug(localized_slug(title, request.slug_policy, primary_slug=primary["slug"]), taken)


def save(client, request: LocalizeRequest, outcome: dict[str, Any], *, now: str | None = None, author: str = ACTOR, change_reason: str | None = None,
         localization: dict[str, Any] | None = None) -> dict[str, Any]:
    """Records the translation as the next version of the localization lineage (version 1 the first time) and its provenance. Unpublished,
    no board stage, author AI. Refuses when a newer source was translated meanwhile (an older run never replaces newer work).

    Finished copy that a person or another agent wrote (``import_copy``, ``papyrus stories import-translation``) is saved by this same path: it names its
    ``author`` and ``change_reason``, and its ``localization`` entries (``translation``, who wrote it) are written over the machine's."""
    from ..model_attachments import build_json_model_payload_attachment, upload_attachment_body
    from ..publishing import ItemFields, _derive_or_raise, _load_front_matter, columns_from_front_matter, _source_content_hash, _status_keys, _without_server_fields
    from ..story_reporting import _carry_media_forward, next_version_record_id, story_versions, superseding_update

    now = now or utc_now_iso()
    primary = client.get_record("Item", request.source.version_id)
    versions = story_versions(client, request.localization_lineage)
    latest = next((row for row in versions if row.get("versionState") == "current"), versions[0] if versions else None)
    from ..authored_editions import is_authored
    if is_authored(latest):
        raise ValueError("An independently authored edition now exists; this translation saves nothing.")
    if latest is not None and int(latest.get("sourceVersionNumber") or 0) > request.source.version_number:
        raise ValueError(f"{request.localization_lineage} already holds a translation of source version {latest['sourceVersionNumber']}; "
                         f"this run translated version {request.source.version_number} and saves nothing.")
    translation = outcome["translation"]
    front_matter = _front_matter(primary, translation["title"], translation["deck"], translation.get("fields"))
    body_markus = translation["body"]
    if request.image_variants:   # a localized figure survives a re-translation: the new text keeps naming the language's own picture
        front_matter, body_markus = carry_forward(front_matter, body_markus, request.image_variants)
    slug = latest["slug"] if latest is not None else _first_slug(client, request, primary, translation["title"])
    fields = ItemFields(type=primary["type"], slug=slug, section=primary.get("section"), front_matter_yaml=front_matter,
                        body_markus=body_markus, aliases=[])
    envelope = _derive_or_raise(front_matter, body_markus)
    number = (max(int(row.get("versionNumber") or 0) for row in versions) + 1) if versions else 1
    record_id = next_version_record_id(request.localization_lineage, number, {row["id"] for row in versions})
    metadata = {"frontMatterYaml": front_matter,
                "localization": {"runKey": request.run_key, "outcome": outcome["outcome"], "reason": outcome["reason"], "translation": "machine",
                                 "reviewed": False, "sourceContentHash": request.source.content_hash, "rounds": outcome["rounds"],
                                 "revertedBlocks": outcome["revertedBlocks"], "costUsd": outcome["costUsd"],
                                 **({"imagesWithText": list(request.source.images_with_text)} if request.source.images_with_text else {}),
                                 **(localization or {})}}
    base = {name: value for name, value in _without_server_fields(primary).items()
            if name not in ("starRating", "starRatedAt", "starRatedBy", "headStageKey", "scheduledPublishAt", "scheduledBy", "scheduledAt",
                            "scheduleState", "scheduleName", "tenantSlug", "shortSlug")}
    record = {
        **base,
        "id": record_id, "lineageId": request.localization_lineage, "versionNumber": number, "slug": slug, "aliases": [],
        "previousVersionId": latest["id"] if latest else None, "versionState": "current", "versionCreatedAt": now, "versionCreatedBy": author,
        "changeReason": change_reason or f"translation of version {request.source.version_number} into {request.language}",
        "stage": None, "headStageKey": None, "status": "draft", **_status_keys(fields.type, fields.section, "draft"),
        "title": translation["title"] or None, "headline": translation["title"] or None, "sortTitle": translation["title"] or None,
        "deck": (columns_from_front_matter(_load_front_matter(front_matter))["deck"] if front_matter else translation["deck"] or None), "body": [], "bodyMarkus": fields.body_markus, "bodyIr": to_aws_json(envelope),
        "metadata": to_aws_json(metadata), "contentHash": _source_content_hash(fields),
        "publishedAt": None, "versionPublishedAt": None, "versionPublishedBy": None,
        "language": request.language, "languageGroupId": request.source.lineage_id, "sourceLineageId": request.source.lineage_id,
        "sourceVersionNumber": request.source.version_number, "sourceContentHash": request.source.content_hash, "syncState": "current",
    }
    client.create_record("Item", compact_dict(record))
    _carry_media_forward(client, record_id, envelope, front_matter, [primary, *versions])   # the original's pictures and the translation's own variants: a translation is published with them (publish checks each)
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


def carry_provenance(client, previous: dict[str, Any], record: dict[str, Any]) -> None:
    """Gives ``record`` (a person's new version of a localization, for example one that points at a localized figure) the provenance of the version it
    follows, unchanged except for the version it names, so the next translation run still finds its alignment: the text is the machine's and a
    picture changed, not a block."""
    from ..model_attachments import build_json_model_payload_attachment, download_attachment_buffer, model_attachment_id, upload_attachment_body

    row = client.get_record("ModelAttachment", model_attachment_id("item", previous["id"], PROVENANCE_ROLE, PROVENANCE_ROLE))
    if row is None:
        return
    provenance = json.loads(download_attachment_buffer(client, row))
    provenance["target"] = {**provenance.get("target", {}), "versionId": record["id"]}
    entry = build_json_model_payload_attachment({"ownerKind": "item", "ownerId": record["id"], "ownerLineageId": record["lineageId"],
                                                 "ownerVersionNumber": record.get("versionNumber"), "role": PROVENANCE_ROLE, "sortKey": PROVENANCE_ROLE,
                                                 "filename": "provenance.json", "content": provenance, "now": utc_now_iso()})
    upload_attachment_body(client, entry["attachment"], entry["body"])


def report_back(client, request: LocalizeRequest, advice: list[dict[str, Any]]) -> None:
    """Stock phrasing found in the translation that the English block has too, as advice on the English version (Item.metadata.translationAdvice,
    per language). The only write this procedure makes to the English Story."""
    if not advice:
        return
    row = client.get_record("Item", request.source.version_id)
    metadata = _metadata(row)
    metadata.setdefault(ADVICE_KEY, {})[request.language] = {"runKey": request.run_key, "at": utc_now_iso(), "phrases": advice}
    client.update_record("Item", {"id": row["id"], "metadata": to_aws_json(metadata), **({"updatedAt": row["updatedAt"]} if row.get("updatedAt") else {})})


def hold(client, request: LocalizeRequest, reason: str, *, raised_by: str = RAISED_BY) -> dict[str, Any]:
    """A flag review request on the localization, saying why it is held. Idempotent per run key."""
    from ..review_requests import raise_review

    return raise_review(client, subject={"type": "story", "id": request.localization_lineage}, mode="flag",
                        reason=f"The {request.language} translation is held: {reason}"[:1900], raised_by=raised_by,
                        request_id=hold_request_id(request.run_key))


def stage_store_for(client, request: LocalizeRequest) -> AttachmentStageStore:
    return AttachmentStageStore(client, {"id": request.source.version_id, "lineageId": request.source.lineage_id,
                                         "versionNumber": request.source.version_number})


__all__ = ["AttachmentStageStore", "NothingToDo", "carry_provenance", "collect", "hold", "report_back", "save", "stage_key", "stage_store_for"]
