"""Translate the words of one figure for a language variant (``papyrus figures localize``; docs/figures.md, "Figures in other languages").

The words are the figure's text segments (``figures.text.text_segments``), its alt text and its caption. They are translated with the same client, the same
glossary entries and the same register notes as the Story's translation run (``record.collect``), then checked with the same Humanus checks: the language's
copy-edit pack on every result and the bilingual judge on every pair. The checks are advice. This module returns the translations and the findings, and
the caller shows both; it never refuses a translation because of a finding, and it saves nothing.
"""
from __future__ import annotations

from typing import Any, Callable

from .engine import _language_name
from .models import LocalizeModels, ResponsesModels, Spend
from .record import NothingToDo, collect

LABEL_KIND = "figure-label"
NOTE = ("Blocks of kind figure-label are short labels drawn inside a picture: translate each as a label of about the same length (it has to fit the same "
        "space), plain text, no added punctuation. The kind caption is the figure's one-sentence caption and field:imageAlt its alt text.")


def translate_figure_words(client, *, story: str, language: str, labels: list[str], alt: str, caption: str,
                           models: Callable[[Spend], LocalizeModels] | None = None) -> dict[str, Any]:
    """``{"labels": {source: translation}, "alt", "caption", "findings": [...], "costUsd"}`` for a figure of the published Story ``story``.
    Raises ``ValueError`` when the Story cannot be translated (not published, marked do not localize, already in that language)."""
    from .run import procedure_version

    spend = Spend()
    model = (models or (lambda s: ResponsesModels(s)))(spend)
    try:
        request = collect(client, story=story, language=language, judge=model.judge, procedure_version=procedure_version())
    except NothingToDo as reason:
        raise ValueError(str(reason)) from reason
    blocks = [{"id": f"L{number}", "kind": LABEL_KIND, "text": text} for number, text in enumerate(labels, start=1)]
    if alt:
        blocks.append({"id": "ALT", "kind": "field:imageAlt", "text": alt})
    if caption:
        blocks.append({"id": "CAP", "kind": "caption", "text": caption})
    sources = [block["text"] for block in blocks]
    languages = {"source": request.source.language, "target": request.language,
                 "source_name": _language_name(request.source.language), "target_name": _language_name(request.language)}
    entries = request.glossary.entries_in(sources, request.source.language)
    answer = model.translate({"languages": languages, "registerNotes": request.register_notes, "blocks": blocks, "context": [], "notes": NOTE,
                              "glossary": request.glossary.prompt_lines(entries)})
    by_id = {entry["id"]: entry["text"].strip() for entry in answer["blocks"]}
    missing = [block["id"] for block in blocks if not by_id.get(block["id"])]
    if missing:
        raise ValueError(f"the model did not translate {', '.join(missing)}; nothing was made.")
    findings: list[dict[str, Any]] = []
    for block in blocks:
        target = by_id[block["id"]]
        for found in request.checker.copy_edit(target)[0]:
            findings.append({"block": block["text"], **found.payload()})
        for found in request.checker.faithfulness(block["text"], target)[0]:
            findings.append({"block": block["text"], **found.payload()})
    return {"labels": {block["text"]: by_id[block["id"]] for block in blocks if block["kind"] == LABEL_KIND},
            "alt": by_id.get("ALT", ""), "caption": by_id.get("CAP", ""), "findings": findings, "costUsd": round(spend.cost_usd, 6),
            "language": request.language, "originalLineage": request.source.lineage_id}
