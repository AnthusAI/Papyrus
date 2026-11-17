"""Finished copy attached as a Story's translation (``papyrus stories import-translation``, PPY-b64b0b).

The translation procedure writes a translation with a model, and ``correct-translation`` lets a person fix one. Neither takes copy that was written
separately, by people or by other agents, and is already finished. This does: it saves that copy as the next version of the sibling lineage
``<story>--<language>`` through the same record-writing path the procedure uses (:func:`record.save`), so the version is paired with the published English
version it translates, carries the original's pictures, gets its address from the language's slug policy, and stays unpublished.

What is different from a machine translation, and nothing else:

* **Authorship.** The version's author is the person or agent that wrote it (``--written-by``); its front matter ``author`` is that name and has
  ``drafting: {by: AI}`` only when the caller says bots helped (``--drafting-by-ai``), so the site's standard byline reads "By NAME" or "By various bots
  and NAME", and the language edition translates it like every byline; ``metadata.localization.translation`` is ``imported``, not ``machine``, as a record
  (the page says nothing of AI for it); the provenance has an ``authorship`` entry (written by, imported by, why, ``machineGenerated: false``). No model wrote or rewrote it.
* **Every block is the writer's.** In the version's alignment every block is ``owner: human`` and ``pinned: true``, so a later translation run keeps the
  copy exactly: a changed or deleted English block under it is a conflict, never an overwrite (``engine.plan_slots``).
* **No model is called.** The checks are the translation run's own, minus the bilingual judge: the parity rules and the glossary (numbers, links,
  citations, code, directives, structure, house terms) against the English, block by block and for the whole body, and the language's own copy-edit
  policies. An error-severity faithfulness finding holds the version exactly as it holds a machine translation: ``outcome: held`` and a flag review request
  that a person answers before the version publishes. Other findings are advice and are printed.
* **It must line up with the English.** The copy has the same blocks in the same order (the title, the dek, the front matter texts, then the body's blocks,
  separated by blank lines), each block of the same kind. Everything a translator never sees (``blocks.protect``: link targets, web addresses, citations,
  inline code, a figure's ``src`` and ``credit`` and its other settings) and every code block, comment and rule must be the English's, as written.
  Anything else is refused, saving nothing, with the position and what to change.

The desired-state record (``desired_state.settled``) is written finished (``saved``, or ``held``) and names this source text, so
``papyrus stories localize --all`` counts the language of the Story as up to date and does not run over it.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ..item_front_matter import DEK_KEYS
from ..item_language import localization_lineage_id
from ..publishing import utc_now_iso
from . import desired_state
from .blocks import FIELD_PREFIX, FRONT_MATTER_FIELDS, Block, blocks_of, join_body, normalized, protect
from .checks import Finding
from .record import NothingToDo, collect, hold, run_key, save

PROCEDURE_KEY = "papyrus.story.import-translation"
TRANSLATION_KIND = "imported"
FRONT_MATTER_KEYS = ("title", *DEK_KEYS, *FRONT_MATTER_FIELDS)
_EMBEDDED_FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_EXCERPT = 60


class CopyRefused(ValueError):
    """The copy cannot be paired with the English block for block; the message says where and what to change. Nothing was saved."""


@dataclass
class Copy:
    """The finished copy's reader-facing front matter texts and its body."""

    title: str
    deck: str
    fields: dict[str, str]
    body: str


@dataclass
class Imported:
    """What an import does (or did): the alignment, the findings, whether it holds, and the saved version."""

    lineage: str
    language: str
    run_key: str
    pairs: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    held: bool = False
    reason: str = ""
    replaces: dict[str, Any] | None = None
    unchanged: bool = False
    record: dict[str, Any] | None = None
    review_request: str | None = None


def _excerpt(text: str) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= _EXCERPT else flat[:_EXCERPT - 1] + "…"


def read_copy(body_text: str, front_matter_text: str | None, source_fields: tuple[tuple[str, str], ...], source_has_deck: bool) -> Copy:
    """The copy's front matter and body from the files' text. The front matter is YAML with the Story's reader-facing texts (``title``, the dek under any of
    ``DEK_KEYS``, and the fields the English has: ``blurb``, ``imageAlt``), either in its own file or as a leading ``---`` block of the body file."""
    import yaml

    embedded = _EMBEDDED_FRONT_MATTER.match(body_text)
    if embedded and front_matter_text is not None:
        raise CopyRefused("The body file starts with its own front matter and a front matter file was given too: give the front matter once.")
    if embedded:
        front_matter_text, body_text = embedded.group(1), body_text[embedded.end():]
    if front_matter_text is None:
        raise CopyRefused("The copy has no front matter: give --front-matter-file (or start the body file with a --- block) with the title"
                          + (", the dek" if source_has_deck else "") + "".join(f" and {key}" if i else f", {key}" for i, (key, _) in enumerate(source_fields)) + ".")
    try:
        loaded = yaml.safe_load(front_matter_text)
    except yaml.YAMLError as error:
        raise CopyRefused(f"The front matter is not valid YAML: {error}") from error
    if not isinstance(loaded, dict):
        raise CopyRefused("The front matter is a YAML mapping of the Story's texts (title, dek, blurb, imageAlt).")
    unknown = sorted(set(loaded) - set(FRONT_MATTER_KEYS))
    if unknown:
        raise CopyRefused(f"The front matter has {', '.join(unknown)}; only {', '.join(FRONT_MATTER_KEYS)} are the copy's own texts. Everything else of the "
                          "Story (tags, sources, pictures, section) stays the English's.")
    for key, value in loaded.items():
        if not isinstance(value, str) or not value.strip():
            raise CopyRefused(f"The front matter's {key} must be text.")
    problems = []
    if "title" not in loaded:
        problems.append("title")
    deck_keys = [key for key in DEK_KEYS if key in loaded]
    if len(deck_keys) > 1:
        raise CopyRefused(f"The front matter gives the dek twice ({', '.join(deck_keys)}); keep one.")
    if source_has_deck and not deck_keys:
        problems.append("a dek (dek or deck)")
    needed = {key for key, _ in source_fields}
    problems += [key for key, _ in source_fields if key not in loaded]
    if problems:
        raise CopyRefused(f"The front matter lacks {', '.join(problems)}; the English has {'it' if len(problems) == 1 else 'them'}, so the copy needs "
                          f"{'it' if len(problems) == 1 else 'them'} too.")
    if deck_keys and not source_has_deck:
        raise CopyRefused(f"The front matter has a dek ({deck_keys[0]}) and the English has none.")
    extra = [key for key in FRONT_MATTER_FIELDS if key in loaded and key not in needed]
    if extra:
        raise CopyRefused(f"The front matter has {', '.join(extra)} and the English has none.")
    return Copy(title=loaded["title"].strip(), deck=loaded[deck_keys[0]].strip() if deck_keys else "",
                fields={key: loaded[key].strip() for key, _ in source_fields}, body=body_text)


def _is_front(block: Block) -> bool:
    return block.kind in ("title", "deck") or block.kind.startswith(FIELD_PREFIX)


def _parts(block: Block) -> Counter:
    return Counter(protect(block.text).parts)


def _where(number: int, block: Block) -> str:
    return f"{number} ({block.kind}: {_excerpt(block.text)})"


def align(source: list[Block], copy: list[Block]) -> list[tuple[Block, Block]]:
    """The copy's blocks paired with the English's, one to one in order. Raises :class:`CopyRefused` naming every problem found: blocks that do not line up
    (with the first position where they stop matching), a changed code block, comment or rule, and a link target, web address, citation, credit or other
    fixed part that the copy changed. The front matter texts are paired by name, the body's blocks by position."""
    source_front, copy_front = [b for b in source if _is_front(b)], [b for b in copy if _is_front(b)]
    source_body, copy_body = [b for b in source if not _is_front(b)], [b for b in copy if not _is_front(b)]
    problems: list[str] = []
    if len(source_body) != len(copy_body) or any(s.kind != c.kind for s, c in zip(source_body, copy_body)):
        problems.append(_misaligned(source_body, copy_body))
    if problems:
        raise CopyRefused("The copy's blocks cannot be paired with the English's. " + " ".join(problems))
    pairs = list(zip(source_front, copy_front)) + list(zip(source_body, copy_body))
    for number, (s, c) in enumerate(pairs, start=1):
        label = "the " + s.kind if _is_front(s) else f"body block {number - len(source_front)} ({s.kind})"
        if not s.translated:
            if normalized(s.text) != normalized(c.text):
                problems.append(f"{label[0].upper() + label[1:]} was changed: code blocks, comments and rules are copied from the English as they are.")
            continue
        lost, added = _parts(s) - _parts(c), _parts(c) - _parts(s)
        if lost or added:
            detail = "; ".join(part for part in (f"missing {', '.join(repr(p) for p in sorted(lost))}" if lost else "",
                                                  f"changed or added {', '.join(repr(p) for p in sorted(added))}" if added else "") if part)
            problems.append(f"In {label} a link target, web address, citation, credit or other fixed part is not the English's ({detail}). "
                            "Write the same targets and settings as the English, and translate only the words around them (a figure's alt text and caption "
                            "are the copy's own; its src, credit and layout are not).")
    if problems:
        raise CopyRefused(" ".join(problems))
    return pairs


def _misaligned(source: list[Block], copy: list[Block]) -> str:
    """Why the body blocks do not pair, and the first place they stop matching."""
    said = (f"The English body has {len(source)} blocks and the copy has {len(copy)}. Blocks are separated by blank lines; a ::: container, a fenced code "
            "block and a figure directive are one block each, however many lines they span, and the copy needs the same blocks in the same order.")
    for index, (s, c) in enumerate(zip(source, copy), start=1):
        if s.kind != c.kind:
            return f"{said} They first differ at block {index}: the English has a {s.kind} ({_excerpt(s.text)}) and the copy a {c.kind} ({_excerpt(c.text)})."
        if _parts(s) != _parts(c):
            return (f"{said} They first stop matching at block {index}: its links, addresses and fixed parts differ from the English's ({_excerpt(s.text)}). "
                    "A paragraph was probably split or joined at or before this block.")
    if len(copy) < len(source):
        return f"{said} The copy ends after block {len(copy)}; the English goes on with block {len(copy) + 1} ({_excerpt(source[len(copy)].text)})."
    return f"{said} The copy has {len(copy) - len(source)} more from block {len(source) + 1} ({_excerpt(copy[len(source)].text)})."


def _front_of(copy: Copy, source_fields: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    return tuple((key, copy.fields[key]) for key, _ in source_fields)


def _finding_row(block: int | None, kind: str, finding: Finding) -> dict[str, Any]:
    return {"block": block, "kind": kind, **finding.payload()}


def import_translation(client, *, story: str, language: str, body: str, front_matter: str | None, written_by: str, applied_by: str, reason: str,
                       drafting_by_ai: bool = False, apply: bool = True, now: str | None = None) -> Imported:
    """Saves finished copy as the next version of ``<story>--<language>``, paired with the published English version. ``apply`` False only works out the
    alignment and the findings and writes nothing. Every refusal raises with its reason and saves nothing."""
    if not written_by or not reason:
        raise ValueError("An import names who wrote the copy (--written-by) and why it is attached (--reason).")
    try:
        request = collect(client, story=story, language=language, judge=None, procedure_version=PROCEDURE_KEY)
    except NothingToDo as error:
        raise ValueError(f"{error} Finished copy is attached to a Story's published version: publish the English Story first.") from error
    source = request.source
    lineage = localization_lineage_id(story, request.language)
    copy = read_copy(body, front_matter, source.fields, bool(source.deck))
    source_blocks = blocks_of(source.body, title=source.title, deck=source.deck, fields=source.fields)
    copy_blocks = blocks_of(copy.body, title=copy.title, deck=copy.deck or None, fields=_front_of(copy, source.fields))
    pairs = align(source_blocks, copy_blocks)

    checker = request.checker
    findings: list[dict[str, Any]] = []
    for number, (s, c) in enumerate(pairs, start=1):
        if not s.translated:
            continue
        parity, _ = checker.parity(s.text, c.text)
        edit, _ = checker.copy_edit(c.text)
        findings += [_finding_row(number, s.kind, f) for f in parity + edit]
    texts = [c.text for _, c in pairs]
    body_texts = [c.text for s, c in pairs if not _is_front(s)]
    body_markus = join_body(body_texts)
    document, _ = checker.faithfulness_document(source.body, body_markus)
    seen = {(row["policy"], row["message"], row["excerpt"]) for row in findings}
    findings += [_finding_row(None, "body", f) for f in document if (f.policy, f.message, f.excerpt) not in seen]
    remaining = [row for row in findings if row["category"] == "faithfulness" and row["severity"] == "error" and row["status"] == "violation"]
    reasons = ["faithfulness: " + "; ".join(f"{row['policy']}: {row['message']}" for row in remaining[:5])] if remaining else []

    key = run_key(source, request.language, procedure_version=PROCEDURE_KEY,
                  checker_versions={**checker.versions, "copy": hashlib.sha256(json.dumps(texts, ensure_ascii=False).encode("utf-8")).hexdigest()[:32],
                                    "writtenBy": written_by, "draftingByAi": drafting_by_ai})
    request.run_key = key   # the version, its hold and the request all carry the import's own key
    versions = _versions(client, lineage)
    current = next((row for row in versions if row.get("versionState") == "current"), versions[0] if versions else None)
    result = Imported(
        lineage=lineage, language=request.language, run_key=key, findings=findings, held=bool(reasons), reason="; ".join(reasons),
        pairs=[{"block": number, "kind": s.kind, "english": s.text, "copy": c.text} for number, (s, c) in enumerate(pairs, start=1)],
        replaces=_replaces(current), review_request=_review_id(key) if reasons else None)
    existing = desired_state.current(client, source.lineage_id, request.language)
    if existing is not None and existing.get("state") == "started":
        raise ValueError(f"A translation run for {story} in {request.language} is in progress (its request is started). Wait for it to finish, then import.")
    if not apply:
        return result
    now = now or utc_now_iso()
    source_row = {"id": source.version_id, "lineageId": source.lineage_id, "versionNumber": source.version_number, "contentHash": source.content_hash}
    state = "held" if result.held else "saved"
    if current is not None and _localization(current).get("runKey") == key:   # the same copy again: nothing new to save, the request is written again so it is right
        result.unchanged, result.record = True, current
        desired_state.settled(client, source=source_row, language=request.language, requested_by=applied_by, state=_localization(current).get("outcome") or state,
                              run_key=key, reason=result.reason, now=now)
        return result
    title = next(c.text for s, c in pairs if s.kind == "title")
    deck = next((c.text for s, c in pairs if s.kind == "deck"), "")
    fields = {s.kind[len(FIELD_PREFIX):]: c.text for s, c in pairs if s.kind.startswith(FIELD_PREFIX)}
    alignment = [{"sourceBlock": s.id, "owner": "human", "pinned": True} for s, _ in pairs]
    outcome = {"outcome": state, "reason": result.reason, "rounds": 0, "revertedBlocks": 0, "costUsd": 0.0, "hold": result.held,
               "translation": {"title": title, "deck": deck, "fields": fields, "body": body_markus, "blocks": texts},
               "provenance": _provenance(request, key, pairs, findings, remaining, alignment, state, result.reason, written_by, applied_by, reason, now,
                                         current, lineage)}
    result.record = save(client, request, outcome, now=now, author=written_by,
                         change_reason=f"imported copy written by {written_by}: {reason}",
                         byline={"author": written_by, "draftingByAi": drafting_by_ai},
                         localization={"translation": TRANSLATION_KIND, "writtenBy": written_by, "draftingByAi": drafting_by_ai, "importedBy": applied_by, "reason": result.reason,
                                       "outcome": state})
    if result.held:
        hold(client, request, result.reason, raised_by=PROCEDURE_KEY)
    desired_state.settled(client, source=source_row, language=request.language, requested_by=applied_by, state=state, run_key=key, reason=result.reason, now=now)
    return result


def _review_id(key: str) -> str:
    from ..localization_publish import hold_request_id

    return hold_request_id(key)


def _versions(client, lineage: str) -> list[dict[str, Any]]:
    from ..story_reporting import story_versions

    return story_versions(client, lineage)


def _localization(row: dict[str, Any]) -> dict[str, Any]:
    from .record import _metadata

    return _metadata(row).get("localization") or {}


def _replaces(current: dict[str, Any] | None) -> dict[str, Any] | None:
    """The version the import supersedes, and whose wording it was: a machine's, or an earlier import or correction (a person's, kept in its history)."""
    if current is None:
        return None
    localization = _localization(current)
    return {"versionId": current["id"], "versionNumber": current.get("versionNumber"), "translation": localization.get("translation") or "machine",
            "status": current.get("status"), "createdBy": current.get("versionCreatedBy")}


def _provenance(request, key, pairs, findings, remaining, alignment, state, reason_held, written_by, applied_by, reason, now, current, lineage) -> dict[str, Any]:
    source = request.source
    clean = not remaining
    counts: dict[str, dict[str, int]] = {}
    for row in findings:
        counts.setdefault(row["category"], {}).setdefault(row["severity"], 0)
        counts[row["category"]][row["severity"]] += 1
    return {
        "schemaVersion": 1,
        "procedure": {"key": PROCEDURE_KEY, "version": request.procedure_version},
        "runKey": key,
        "authorship": {"kind": "written", "machineGenerated": False, "writtenBy": written_by, "importedBy": applied_by, "reason": reason, "at": now,
                       **({"replaces": _replaces(current)} if current is not None else {})},
        "source": {"lineageId": source.lineage_id, "versionId": source.version_id, "versionNumber": source.version_number, "contentHash": source.content_hash,
                   "language": source.language},
        "target": {"language": request.language, "lineageId": lineage},
        "blocks": {"translated": 0, "reused": 0, "pinned": len(alignment), "conflicted": 0, "copied": sum(1 for s, _ in pairs if not s.translated),
                   "sourceCharactersTranslated": 0},
        "models": None, "versions": request.checker.versions, "rounds": [], "revertedBlocks": 0,
        "findings": counts,
        "remaining": [row for row in findings if row["category"] == "faithfulness" or row["severity"] in ("error", "warn")][:200],
        "reportBack": [],
        "cost": {"totalUsd": 0.0, "byPurpose": {}, "prediction": None, "ceilingUsd": None},
        "outcome": state, "reason": reason_held,
        "alignment": alignment,
        "checklist": {
            "translate": {"done": True, "proof": f"finished copy written by {written_by}, imported by {applied_by}"},
            "faithfulness": {"done": clean, "proof": "the parity and glossary rules on every block and on the whole body; no bilingual judge ran, no model was called"},
            "copy_edit": {"done": True, "proof": "the language's copy-edit policies on every block"},
            "publish": {"done": False, "proof": "importing never publishes"},
            "corrector_review": {"done": False, "optional": True, "proof": "a corrector's correction or Looks right"},
        },
    }


__all__ = ["Copy", "CopyRefused", "Imported", "align", "import_translation", "read_copy"]
