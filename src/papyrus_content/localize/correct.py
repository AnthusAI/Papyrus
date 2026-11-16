"""A person's correction of a translation (``papyrus stories correct-translation``, PPY-ef71cd).

A correction is a new version of the translation lineage (``<story>--<language>``), saved like any person's save (``save_story_version``), whose edited
blocks are the person's: in the version's alignment each is ``owner: human`` and ``pinned: true``, so a later translation run keeps it exactly
(``engine.plan_slots``: a changed or deleted source block under a pinned block is a conflict, never an overwrite).

What is recorded, and where. The version's author is the person (``--edited-by``). The provenance record of the new version is the previous one with the
changed blocks' text, owner and pin updated, and a ``corrections`` entry appended: who edited, who applied the edit (the signed-in session), the reason,
each changed block's text before and after and, when given, who approved it. The approver is metadata only: it is never written into the Story's text,
a credit or a caption, and not into the version's change reason. A correction never changes a link target, a credit or any other part a translator
never sees (``blocks.protect``): the correction is refused if it would.

Every failure raises with its reason; a correction that matches nothing, or matches more than it names, saves nothing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..item_language import localization_lineage_id
from ..publishing import utc_now_iso
from .blocks import FIELD_PREFIX, Block, blocks_of, join_body, normalized, protect
from .record import PROVENANCE_ROLE, _front_matter, _metadata, _source_fields, read_provenance


@dataclass(frozen=True)
class Edit:
    """Replace ``old`` by ``new`` in the translation's text. Without ``every`` the text must occur exactly once."""

    old: str
    new: str
    every: bool = False


@dataclass
class Correction:
    """What a correction does (or did): the blocks it changes with their text before and after, and the saved version when it was written."""

    lineage: str
    changed: list[dict[str, Any]] = field(default_factory=list)
    record: dict[str, Any] | None = None


def edits_from(payload: Any) -> list[Edit]:
    """The edits of a JSON list ``[{"from": "...", "to": "...", "every": false}]``."""
    if not isinstance(payload, list) or not payload:
        raise ValueError("The edits are a JSON list with at least one entry: [{\"from\": \"old wording\", \"to\": \"new wording\"}].")
    edits = []
    for index, entry in enumerate(payload, start=1):
        if not isinstance(entry, dict) or not isinstance(entry.get("from"), str) or not isinstance(entry.get("to"), str) or not entry["from"]:
            raise ValueError(f"Edit {index} needs a non-empty \"from\" and a \"to\" (both text).")
        unknown = set(entry) - {"from", "to", "every"}
        if unknown:
            raise ValueError(f"Edit {index} has unknown field(s) {', '.join(sorted(unknown))}; the fields are from, to and every.")
        if entry["from"] == entry["to"]:
            raise ValueError(f"Edit {index} changes nothing: \"from\" and \"to\" are the same.")
        edits.append(Edit(entry["from"], entry["to"], bool(entry.get("every", False))))
    return edits


def _aligned_blocks(current: dict[str, Any], provenance: dict[str, Any]) -> list[Block]:
    """The stored translation's blocks (title, dek, reader-facing fields, body), checked against the alignment of its provenance."""
    blocks = blocks_of(current.get("bodyMarkus") or "", title=current.get("title") or current.get("headline"), deck=current.get("deck"),
                       fields=_source_fields(current))
    alignment = provenance["alignment"]
    if len(blocks) != len(alignment) or any(normalized(block.text) != normalized(entry["text"]) for block, entry in zip(blocks, alignment)):
        raise ValueError(f"The stored text of {current['id']} does not match its alignment (blocks: text {len(blocks)}, alignment {len(alignment)}); "
                         "it was changed outside the translation procedure, so a correction cannot say which blocks it pins. Translate it again first.")
    return blocks


def apply_edits(blocks: list[Block], edits: list[Edit]) -> dict[int, str]:
    """The new text of each block the edits change, by position. Each edit applies to the text the earlier edits left. Code, comments and rules are
    never edited; a replacement that changes a link target, a credit or another fixed part of its block is refused."""
    texts = [block.text for block in blocks]
    for number, edit in enumerate(edits, start=1):
        editable = [i for i, block in enumerate(blocks) if block.translated and edit.old in texts[i]]
        found = sum(texts[i].count(edit.old) for i in editable)
        if not found:
            raise ValueError(f"Edit {number}: \"{edit.old}\" is not in the translation's text.")
        if found > 1 and not edit.every:
            raise ValueError(f"Edit {number}: \"{edit.old}\" occurs {found} times. Name more of the surrounding words so it occurs once, or set \"every\": true to change all of them.")
        for i in editable:
            texts[i] = texts[i].replace(edit.old, edit.new)
    changed = {i: text for i, text in enumerate(texts) if text != blocks[i].text}
    if not changed:
        raise ValueError("The edits change nothing in the translation.")
    for i, text in changed.items():
        if protect(blocks[i].text).parts != protect(text).parts:
            raise ValueError(f"The edit of block {i + 1} would change a link, a citation, a credit or another fixed part of it. A correction changes wording only.")
    return changed


def correct_translation(client, *, story: str, language: str, edits: list[Edit], edited_by: str, applied_by: str, reason: str,
                        approved_by: str | None = None, apply: bool = True, now: str | None = None) -> Correction:
    """Saves the edits as the next version of the translation, the changed blocks pinned to ``edited_by``. ``apply`` False only works out the blocks."""
    from ..model_attachments import build_json_model_payload_attachment, upload_attachment_body
    from ..story_reporting import current_story_version, save_story_version

    if not edited_by or not reason:
        raise ValueError("A correction names the person who edited (--edited-by) and the reason (--reason).")
    lineage = localization_lineage_id(story, language)
    try:
        current = current_story_version(client, lineage)
    except Exception as error:  # noqa: BLE001 - say what is missing instead of the lookup's own words
        raise ValueError(f"{story} has no {language} translation yet ({lineage}); there is nothing to correct.") from error
    provenance = read_provenance(client, current)
    blocks = _aligned_blocks(current, provenance)
    changed = apply_edits(blocks, edits)
    correction = Correction(lineage, [{"block": i + 1, "kind": blocks[i].kind, "before": blocks[i].text, "after": text} for i, text in changed.items()])
    if not apply:
        return correction
    now = now or utc_now_iso()
    texts = [changed.get(i, block.text) for i, block in enumerate(blocks)]
    title = next((text for block, text in zip(blocks, texts) if block.kind == "title"), "")
    deck = next((text for block, text in zip(blocks, texts) if block.kind == "deck"), "")
    fields = {block.kind[len(FIELD_PREFIX):]: text for block, text in zip(blocks, texts) if block.kind.startswith(FIELD_PREFIX)}
    body = join_body([text for block, text in zip(blocks, texts) if block.kind not in ("title", "deck") and not block.kind.startswith(FIELD_PREFIX)])
    front_matter = _front_matter(current, title, deck, fields)
    if front_matter is None and any(blocks[i].kind == "title" or blocks[i].kind == "deck" or blocks[i].kind.startswith(FIELD_PREFIX) for i in changed):
        raise ValueError(f"{current['id']} has no front matter to carry a corrected title, dek or field; correct its body, or save a front matter first.")
    record = save_story_version(client, lineage, front_matter_yaml=front_matter if front_matter is not None else _metadata(current).get("frontMatterYaml"),
                                body_markus=body, actor=edited_by, change_reason=f"correction by {edited_by}: {reason}", now=now)
    alignment = [{**entry, "text": texts[i], **({"owner": "human", "pinned": True} if i in changed else {})} for i, entry in enumerate(provenance["alignment"])]
    entry_of = {
        "versionId": record["id"], "versionNumber": record["versionNumber"], "at": now, "editedBy": edited_by, "appliedBy": applied_by, "reason": reason,
        **({"approvedBy": approved_by} if approved_by else {}),
        "blocks": [{"block": item["block"], "kind": item["kind"], "before": item["before"], "after": item["after"]} for item in correction.changed],
    }
    provenance = {**provenance, "alignment": alignment, "target": {**provenance.get("target", {}), "versionId": record["id"]},
                  "blocks": {**provenance.get("blocks", {}), "pinned": sum(1 for item in alignment if item.get("owner") == "human")},
                  "corrections": [*provenance.get("corrections", []), entry_of],
                  "checklist": {**provenance.get("checklist", {}), "corrector_review": {"done": True, "optional": True,
                                                                                         "proof": f"a correction by {edited_by}, version {record['versionNumber']}"}}}
    attachment = build_json_model_payload_attachment({"ownerKind": "item", "ownerId": record["id"], "ownerLineageId": lineage,
                                                      "ownerVersionNumber": record["versionNumber"], "role": PROVENANCE_ROLE, "sortKey": PROVENANCE_ROLE,
                                                      "filename": "provenance.json", "content": provenance, "now": now})
    upload_attachment_body(client, attachment["attachment"], attachment["body"])
    correction.record = record
    return correction


__all__ = ["Correction", "Edit", "apply_edits", "correct_translation", "edits_from"]
