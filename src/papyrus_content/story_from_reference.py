"""A story based on a Reference: the link, the story's own text, and the seeded image (docs/reference-curation-pipeline.md#stories-based-on-a-reference).

Two things are true of every story that is made from a Reference, whichever path made it (``papyrus references promote``, the
promotion of a ``story_draft`` Proposal, ``papyrus stories create --reference``, the copywriting assignment):

1. **The story is linked to the Reference.** One ``SemanticRelation`` (``uses_evidence``, role ``based_on``) from the story's
   lineage to the Reference's lineage, so the link survives new versions of either side (``story_reporting.link_reference_to_story``).
   The newsroom story view lists it and the Reference view lists the stories based on it.
2. **The story's text is its own.** The body is seeded from our words (the story draft's cited body, or a brief for the
   copywriter) and goes through the copywriting and copy-editing stages. It is never the Reference's captured or extracted text, and
   ``refuse_copied_body`` refuses a seeded body that shares a long verbatim span with that text. The one thing a story may take from
   the Reference is the preview image, and only for a ``post`` (``SEEDED_IMAGE_ITEM_TYPES``): see ``seeded_image_markus``.
   The editor's one-tap Create Story (``create_story_from_reference``) is the one path that seeds the image for any type, and starts the body from the Reference's
   generated summary (our words; the copy guard still applies).

Nothing here publishes. A story that already exists is never rewritten (the editor's text is never overwritten); only its link is
made sure of.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import urlsplit

import yaml

from .link_exploration import canonical_url
from .publishing import ItemFields, item_id_for, save_item
from .record_helpers import slugify
from .reference_images import PREVIEW_ROLE
from .story_types import type_for_new_story, require_story_type
from .story_reporting import BASED_ON, current_reference, latest_story_version, link_reference_to_story, stories_based_on_reference, story_references

#: The item types whose image is seeded from the Reference's preview image.
SEEDED_IMAGE_ITEM_TYPES = ("post",)
#: A seeded body that shares this many consecutive words with the Reference's text is refused.
COPIED_RUN_WORDS = 12
#: ReferenceAttachment roles that hold the Reference's captured text.
SOURCE_TEXT_ROLES = ("extracted_text", "extracted_text_raw")
REFERENCE_TARGET_PREFIX = "reference:"

SourceTextReader = Callable[[str], str]


class StoryCopiedFromReference(ValueError):
    """The seeded body repeats a long span of the Reference's own text."""

    def __init__(self, reference_id: str, span: str) -> None:
        super().__init__(
            f"The body shares {COPIED_RUN_WORDS} or more consecutive words with the text of {reference_id} "
            f"(\"{span}\"). A story is written in our own words; send it through copywriting instead of copying the source."
        )
        self.reference_id = reference_id
        self.span = span


# --- the copy guard -----------------------------------------------------------------------------------------------------------


_URL = re.compile(r"https?://\S+")
_WORD = re.compile(r"[a-z0-9]+")


def words_of(text: str) -> list[str]:
    """The words of a text, lower case, without addresses, so formatting and links never hide or fake a shared span."""
    return _WORD.findall(_URL.sub(" ", text or "").lower())


def shared_span(candidate: str, source: str, *, run: int = COPIED_RUN_WORDS) -> str | None:
    """The first ``run`` consecutive words of ``candidate`` that also appear, in the same order, in ``source``; None when there is none."""
    mine, theirs = words_of(candidate), words_of(source)
    if len(mine) < run or len(theirs) < run:
        return None
    known = {tuple(theirs[index:index + run]) for index in range(len(theirs) - run + 1)}
    for index in range(len(mine) - run + 1):
        window = tuple(mine[index:index + run])
        if window in known:
            return " ".join(window)
    return None


def refuse_copied_body(body: str, source_texts: Iterable[tuple[str, str]]) -> None:
    """Raises ``StoryCopiedFromReference`` when ``body`` repeats ``COPIED_RUN_WORDS`` words in a row from any ``(reference id, text)``."""
    for reference_id, text in source_texts:
        span = shared_span(body, text)
        if span:
            raise StoryCopiedFromReference(reference_id, span)


def default_source_text_reader() -> SourceTextReader | None:
    """Reads a captured text by its storage path through the corpus text provider, or None when this machine has none."""
    try:
        from papyrus_knowledge_query.services import build_environment_services

        provider = build_environment_services().corpus_text
        return provider.read_text if provider else None
    except Exception:  # noqa: BLE001 - no provider is a fact about this machine, reported as "unchecked"
        return None


def reference_source_texts(client: Any, reference: dict[str, Any], reader: SourceTextReader | None) -> tuple[list[tuple[str, str]], bool]:
    """The captured texts of one Reference and whether all of them could be read (a text that cannot be read leaves the check incomplete)."""
    texts: list[tuple[str, str]] = []
    complete = True
    lineage_id = reference.get("lineageId") or reference["id"]
    for attachment in client.list_reference_attachments_by_lineage(lineage_id):
        if attachment.get("role") not in SOURCE_TEXT_ROLES or not attachment.get("storagePath"):
            continue
        try:
            text = reader(str(attachment["storagePath"])) if reader else ""
        except Exception:  # noqa: BLE001 - an unreadable text leaves the check incomplete
            text = ""
        if text:
            texts.append((reference["id"], str(text)))
        else:
            complete = False
    return texts, complete


def check_body_against_references(client: Any, body: str, references: list[dict[str, Any]], source_text_reader: SourceTextReader | None = None) -> str:
    """Refuses (``StoryCopiedFromReference``) a body that repeats the captured text of any of the References; returns ``passed``, or
    ``unchecked`` when a captured text could not be read on this machine (the check then covers only the texts that could be)."""
    resolved: list[SourceTextReader | None] = []

    def reader(storage_path: str) -> str:  # looked up only when a Reference actually has captured text to compare with
        if not resolved:
            resolved.append(source_text_reader if source_text_reader is not None else default_source_text_reader())
        if resolved[0] is None:
            raise RuntimeError("no corpus text provider on this machine")
        return resolved[0](storage_path)

    texts: list[tuple[str, str]] = []
    status = "passed"
    for row in references:
        found, complete = reference_source_texts(client, row, reader)
        texts += found
        if not complete:
            status = "unchecked"
    refuse_copied_body(body, texts)
    return status


# --- the seeded image ---------------------------------------------------------------------------------------------------------


def preview_of(client: Any, reference: dict[str, Any]) -> dict[str, Any] | None:
    """The Reference's preview image (its ``preview`` ReferenceAttachment) as ``{url, site, title}``; None when the page declared none."""
    lineage_id = reference.get("lineageId") or reference["id"]
    for attachment in client.list_reference_attachments_by_lineage(lineage_id):
        address = attachment.get("sourceUri")
        if attachment.get("role") == PREVIEW_ROLE and isinstance(address, str) and address.lower().startswith(("http://", "https://")):
            metadata = attachment.get("metadata")
            metadata = json.loads(metadata) if isinstance(metadata, str) and metadata else (metadata or {})
            return {"url": address, "site": metadata.get("siteName") or attachment.get("filename") or urlsplit(str(reference.get("sourceUri") or "")).hostname}
    return None


def _attribute(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace('"', "'").replace("}", ")")).strip()


def seeded_image_markus(preview: dict[str, Any], reference: dict[str, Any]) -> str:
    """The ``::image`` line that seeds a post: the preview's own address (never copied to our media), alt text from the Reference title, and
    a credit naming the site. The remote address is referenced, not hosted: the illustration stage replaces it or hosts a licensed copy."""
    alt = _attribute(str(reference.get("title") or "Preview image"))
    credit = _attribute(f"Image: {preview['site']}") if preview.get("site") else ""
    credit_attribute = f' credit="{credit}"' if credit else ""
    return f'::image{{src="{preview["url"]}" alt="{alt}"{credit_attribute}}}'


# --- our own text -------------------------------------------------------------------------------------------------------------


def brief_body(title: str, references: list[dict[str, Any]]) -> str:
    """A brief for the copywriter, in our words: where the story comes from and what the writer must do. It carries none of the source's text."""
    sources = ", ".join(f"[{reference.get('title') or reference.get('sourceUri')}]({reference.get('sourceUri')})" for reference in references if reference.get("sourceUri"))
    return (
        f"Brief for the copywriter: {title}.\n\n"
        f"This story is based on {sources or 'a source in the newsroom'}. Write it in our own words: what happened, what is new "
        "about it and why it matters to our readers. Do not reuse the source's sentences. Link the source where the text relies on it.\n"
    )


# --- creating the story -------------------------------------------------------------------------------------------------------


def _dump(front_matter: dict[str, Any]) -> str:
    return yaml.safe_dump(front_matter, sort_keys=False, allow_unicode=True, width=1000)


def create_story_from_references(
    client: Any,
    *,
    references: list[dict[str, Any]],
    section: str,
    slug: str,
    title: str,
    actor: str,
    body_markus: str | None = None,
    item_type: str | None = None,
    front_matter: dict[str, Any] | None = None,
    item_id: str | None = None,
    source_text_reader: SourceTextReader | None = None,
    seed_image: bool = False,
    now: str | None = None,
) -> dict[str, Any]:
    """Saves the draft story for one or more References, links each to it as ``based_on``, and returns what happened.

    ``body_markus`` is our own text (a story draft's body); without it the body is a brief for the copywriter. A body that copies the
    Reference's text raises ``StoryCopiedFromReference`` before anything is written. A ``post`` also gets the first Reference's preview
    image. A story that already exists keeps its text; its links are still made sure of. Returns ``itemId``, ``lineageId``, ``created``,
    ``linked`` (reference lineage ids), ``image`` (``seeded``, ``none`` or ``not a post``; ``seed_image`` seeds any type, as the editor's Create Story action does) and ``copyCheck`` (``passed`` or ``unchecked``).
    """
    if not references:
        raise ValueError("A story based on a Reference needs at least one Reference.")
    item_type = item_type or type_for_new_story()
    rows = []
    for reference in references:
        row = current_reference(client, reference["id"]) or reference
        rows.append(row)
    story_id = item_id or item_id_for(section, slug)
    existing = client.get_record("Item", story_id)
    created = existing is None
    image = "not a post"
    copy_check = "passed"
    if created:
        body = body_markus if body_markus and body_markus.strip() else brief_body(title, rows)
        copy_check = check_body_against_references(client, body, rows, source_text_reader)
        meta = dict(front_matter or {})
        meta.setdefault("title", title)
        meta.setdefault("sources", [{"title": row.get("title") or row.get("sourceUri"), "url": row.get("sourceUri")} for row in rows if row.get("sourceUri")])
        if seed_image or item_type in SEEDED_IMAGE_ITEM_TYPES:
            preview = next((found for found in (preview_of(client, row) for row in rows) if found), None)
            if preview:
                body = seeded_image_markus(preview, rows[0]) + "\n\n" + body
                meta["seededImage"] = {
                    "url": preview["url"], "from": "reference-preview", "hosted": False,
                    "credit": f"Image: {preview['site']}" if preview.get("site") else None, "page": rows[0].get("sourceUri"),
                }
                image = "seeded"
            else:
                image = "none"
        save_item(
            client,
            ItemFields(type=item_type, slug=slug, section=section, front_matter_yaml=_dump(meta), body_markus=body, aliases=[], id=story_id),
            actor=actor,
            now=now,
        )
        existing = client.get_record("Item", story_id)
    lineage_id = existing.get("lineageId") or story_id
    linked = []
    for row in rows:
        result = link_reference_to_story(client, lineage_id, row["id"], role=BASED_ON, actor=actor, now=now)
        linked.append(result["referenceLineageId"])
    return {"itemId": story_id, "lineageId": lineage_id, "created": created, "linked": linked, "image": image if created else "kept", "copyCheck": copy_check if created else "not applicable"}


# --- a story draft becomes a story --------------------------------------------------------------------------------------------


def reference_lineages_of_targets(targets: Any) -> list[str]:
    """The Reference lineage ids a story draft Proposal names in its targets (``entity:reference:<lineage>``)."""
    parsed = json.loads(targets) if isinstance(targets, str) and targets else (targets or [])
    found = []
    for target in parsed:
        identifier = str(target.get("id") or "") if isinstance(target, dict) else ""
        if identifier.startswith(REFERENCE_TARGET_PREFIX) and identifier.removeprefix(REFERENCE_TARGET_PREFIX) not in found:
            found.append(identifier.removeprefix(REFERENCE_TARGET_PREFIX))
    return found


def section_of_draft_body(body: str) -> str | None:
    match = re.search(r"^Section: ([^.\n]+)\.", body or "", re.M)
    return match.group(1).strip() if match else None


def story_from_story_draft(
    client: Any,
    draft: dict[str, Any],
    *,
    actor: str,
    section: str | None = None,
    item_type: str | None = None,
    source_text_reader: SourceTextReader | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Turns an approved ``story_draft`` Proposal (``title``, ``summary``, ``body``, ``targets``) into a draft story at the copywriting stage.

    The body is the draft's own cited text (our words); the Reference lineages come from the draft's ``reference:`` targets and
    each is linked ``based_on``. The section is the one given, else the one the draft's body names. A draft that cites no Reference
    cannot be a story based on one: use ``create_story`` for it."""
    lineages = reference_lineages_of_targets(draft.get("targets"))
    if not lineages:
        raise ValueError("This story draft names no Reference in its targets; there is nothing to base the story on.")
    references = []
    for lineage in lineages:
        reference = current_reference(client, lineage)
        if reference is None:
            raise ValueError(f"Reference {lineage} named by the story draft was not found.")
        references.append(reference)
    chosen = section or section_of_draft_body(str(draft.get("body") or ""))
    if not chosen:
        raise ValueError("The story draft names no section; pass one.")
    title = str(draft.get("title") or "").strip()
    slug = slugify(title)[:80].strip("-")
    if not slug:
        raise ValueError("The story draft has no title to make an address from.")
    front = {"title": title}
    if draft.get("summary"):
        front["deck"] = str(draft["summary"])
    return create_story_from_references(
        client, references=references, section=chosen, slug=slug, title=title, actor=actor, body_markus=str(draft.get("body") or ""),
        item_type=item_type, front_matter=front, source_text_reader=source_text_reader, now=now,
    )


# --- stories that already exist -----------------------------------------------------------------------------------------------


_BODY_LINK = re.compile(r"https?://[^\s)\]>\"'}]+")


def url_key(url: str) -> str | None:
    """A match key for an address: no scheme, tracking parameters, fragment, ``www.`` or trailing slash, host in lower case."""
    try:
        parts = urlsplit(canonical_url(url.strip().rstrip(".,;")))
    except ValueError:
        return None
    host = (parts.hostname or "").removeprefix("www.")
    if not host:
        return None
    path = parts.path.rstrip("/")
    return f"{host}{path}" + (f"?{parts.query}" if parts.query else "")


def item_urls(item: dict[str, Any]) -> dict[str, str]:
    """The addresses a story links to (body links and the ``sources`` of its front matter), keyed by match key, first address kept."""
    found: dict[str, str] = {}
    text = str(item.get("bodyMarkus") or "")
    metadata = item.get("metadata")
    metadata = json.loads(metadata) if isinstance(metadata, str) and metadata else (metadata or {})
    try:
        front = yaml.safe_load(metadata.get("frontMatterYaml") or "") or {}
    except yaml.YAMLError:
        front = {}
    for source in front.get("sources") or [] if isinstance(front, dict) else []:
        if isinstance(source, dict) and isinstance(source.get("url"), str):
            text += "\n" + source["url"]
    for address in _BODY_LINK.findall(text):
        key = url_key(address)
        if key and key not in found:
            found[key] = address
    return found


def _current_versions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per lineage: the one marked current, else the highest version."""
    by_lineage: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_lineage.setdefault(str(row.get("lineageId") or row["id"]), []).append(row)
    chosen = []
    for versions in by_lineage.values():
        pool = [row for row in versions if row.get("versionState") == "current"] or versions
        chosen.append(max(pool, key=lambda row: int(row.get("versionNumber") or 0)))
    return chosen


def plan_reference_links(client: Any, *, role: str | None = None) -> list[dict[str, Any]]:
    """For each story (current version of an Item lineage) whose text links to the ``sourceUri`` of a Reference: the link to write.

    A story that matches exactly one Reference is ``based_on`` it; one that matches several cites them (``cited``). ``role`` overrides
    both. Each row says whether the link ``exists`` already."""
    references = _current_versions(client.list_records("Reference"))
    by_key: dict[str, dict[str, Any]] = {}
    for reference in references:
        if reference.get("curationStatus") == "rejected" or not reference.get("sourceUri"):
            continue
        key = url_key(str(reference["sourceUri"]))
        if key:
            by_key.setdefault(key, reference)
    plan = []
    for item in _current_versions(client.list_records("Item")):
        matches = [(by_key[key], address) for key, address in item_urls(item).items() if key in by_key]
        if not matches:
            continue
        lineage_id = str(item.get("lineageId") or item["id"])
        linked = {row["referenceLineageId"] for row in story_references(client, lineage_id)}
        chosen = role or (BASED_ON if len(matches) == 1 else "cited")
        for reference, address in matches:
            reference_lineage = str(reference.get("lineageId") or reference["id"])
            plan.append({
                "itemId": item["id"], "lineageId": lineage_id, "referenceId": reference["id"], "referenceLineageId": reference_lineage,
                "sourceUri": reference["sourceUri"], "linkedAddress": address, "role": chosen, "exists": reference_lineage in linked,
            })
    return plan


# --- the editor's one-tap "Create Story" ---------------------------------------------------------------------------------------

#: Front matter key that marks a story started by the Create Story action; the editor shows a plain note while it is there.
SEEDED_FROM_KEY = "seededFrom"


def host_of(url: Any) -> str | None:
    host = urlsplit(str(url or "")).hostname
    return host.removeprefix("www.") if host else None


def source_attribution(reference: dict[str, Any], preview: dict[str, Any] | None) -> str:
    """``Source: [title](address), site.`` The link and who it came from; never the source's own text."""
    title = _attribute(str(reference.get("title") or reference.get("sourceUri") or "the source")).replace("[", "(").replace("]", ")")
    site = (preview or {}).get("site") or host_of(reference.get("sourceUri"))
    address = str(reference.get("sourceUri") or "")
    link = f"[{title}]({address})" if address else title
    return f"Source: {link}" + (f", {site}." if site else ".")


def start_body(summary: str, attribution: str) -> str:
    """The body Create Story starts from: the Reference's generated summary, then the source link and attribution. Without a summary, the source line only."""
    return (f"{summary.strip()}\n\n" if summary.strip() else "") + attribution + "\n"


def obvious_section(client: Any) -> str | None:
    """The one enabled newsroom section, when the site has exactly one; else None (an editor chooses)."""
    try:
        enabled = [row for row in client.list_records("NewsroomSection") if row.get("enabled") is not False]
    except Exception:  # noqa: BLE001 - no section list is no obvious section
        return None
    return str(enabled[0]["id"]) if len(enabled) == 1 and enabled[0].get("id") else None


def unused_slug(client: Any, section: str | None, base: str, lineage: str) -> str:
    """``base``, or ``base-<n>`` when a story with that address exists already (a second story from the same Reference)."""
    candidate, number = base, 1
    while client.get_record("Item", item_id_for(section, candidate)) is not None:
        number += 1
        candidate = f"{base}-{number}"
        if number > 50:
            candidate = f"{base}-{lineage[-6:]}-{number}"
            break
    return candidate


def story_rows(client: Any, reference_lineage: str) -> list[dict[str, Any]]:
    """Stories already based on the Reference: ``itemId``, ``lineageId``, ``title``, ``stage``, newest first."""
    rows = []
    for link in stories_based_on_reference(client, reference_lineage):
        if link["role"] != BASED_ON:
            continue
        try:
            story = latest_story_version(client, str(link["storyLineageId"]))
        except Exception:  # noqa: BLE001 - a link whose story cannot be read is not offered
            continue
        rows.append({
            "itemId": story["id"], "lineageId": link["storyLineageId"], "title": story.get("title") or story.get("slug") or "", "stage": story.get("stage"),
            "updatedAt": story.get("updatedAt") or "",
        })
    return sorted(rows, key=lambda row: str(row["updatedAt"]), reverse=True)


def create_story_from_reference(
    client: Any,
    reference_id: str,
    *,
    actor: str,
    item_type: str | None = None,
    again: bool = False,
    summary_of: Callable[[str], str] | None = None,
    source_text_reader: SourceTextReader | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """The editor's one-tap Create Story: a draft story at the copywriting stage, started from this Reference, linked to it, ready to write.

    * type ``item_type`` (the site's default Story type when none is given, ``storyTypes.default`` in its ``projection.json``, else ``article``), stage ``copywriting``, a section only when the site has exactly one;
    * the title is the Reference's title; the body is the Reference's generated summary (``summary_of``, the summary chain of the idea pipeline) followed by the
      source link and attribution, or the source line alone when no summary exists. Nothing else is written, and no text is invented;
    * the Reference's preview image, if the page declared one, is the first line: a remote address (never copied to our media) with a credit to its site, recorded
      in the front matter with the page it came from. It is another site's picture: the editor checks the rights before publishing;
    * ``uses_evidence`` / ``based_on`` links the story to the Reference, so it is listed under "Stories based on this Reference".

    A Reference that already has a story is not given a second one silently: unless ``again`` is true the result is ``{"created": False, "existing": [...]}``.
    A summary that repeats ``COPIED_RUN_WORDS`` words of the captured text is left out (``summary: "withheld"``), the same copy guard as every other path.
    This never changes the Reference's curation status; the editor's Accept is a vote the caller records through the existing review path.
    """
    item_type = require_story_type(item_type) if item_type else type_for_new_story()
    reference = current_reference(client, reference_id)
    if reference is None:
        raise ValueError(f"Reference not found: {reference_id}")
    lineage = str(reference.get("lineageId") or reference["id"])
    existing = story_rows(client, lineage)
    if existing and not again:
        return {"created": False, "existing": existing, "referenceLineageId": lineage}
    preview = preview_of(client, reference)
    title = re.sub(r"\s+", " ", str(reference.get("title") or "")).strip() or host_of(reference.get("sourceUri")) or "Untitled story"
    section = obvious_section(client)
    slug = unused_slug(client, section, slugify(title)[:80].strip("-") or f"story-{lineage[-6:]}", lineage)
    try:
        summary = " ".join(str((summary_of(lineage) if summary_of else "") or "").split())
    except Exception:  # noqa: BLE001 - no summary is a source line only
        summary = ""
    attribution = source_attribution(reference, preview)

    def make(text: str, state: str) -> dict[str, Any]:
        front = {"title": title, SEEDED_FROM_KEY: {"kind": "reference", "referenceLineageId": lineage, "summary": state, "by": actor}}
        return create_story_from_references(
            client, references=[reference], section=section or "", slug=slug, title=title, actor=actor, body_markus=start_body(text, attribution),
            item_type=item_type, front_matter=front, source_text_reader=source_text_reader, seed_image=True, now=now, item_id=item_id_for(section, slug),
        )

    state = "included" if summary else "none"
    try:
        result = make(summary, state)
    except StoryCopiedFromReference:
        state = "withheld"
        result = make("", state)
    return {
        **result, "created": True, "title": title, "itemType": item_type, "stage": "copywriting", "summary": state, "section": section,
        "referenceLineageId": lineage, "imageCredit": f"Image: {preview['site']}" if preview and preview.get("site") else None,
    }
