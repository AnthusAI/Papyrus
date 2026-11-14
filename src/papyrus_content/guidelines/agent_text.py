"""A resolved guidelines document as plain text for an agent, and the lookup an agent's context uses to find it.

The headings here are only the names of the document's own fields. Every sentence an agent reads comes from the saved document, so the
wording of a site's voice is data and never code (``images/prompt_lint.py`` keeps this module and the role texts free of site wording).
"""
from __future__ import annotations

from typing import Any

from .layering import resolve_guidelines
from .store import GuidelineStore

BINDING_FIELDS = ("voice", "audience")
PROSE_FIELDS = (("editorialAim", "Editorial aim"), ("tone", "Tone"), ("sentenceStyle", "Sentence style"), ("voicePatterns", "Voice patterns"),
                ("structure", "Structure"), ("evidenceRules", "Evidence rules"))


def _list(label: str, items: Any) -> list[str]:
    if not items:
        return []
    return [f"{label}:", *(f"- {item}" for item in items)]


def _voice_lines(document: dict) -> list[str]:
    voice = document.get("voice") or {}
    lines = [f"Voice: {voice['name']}"] if voice.get("name") else []
    lines += [f"{key.title()}: {value}" for key, value in voice.items() if key != "name" and isinstance(value, str) and value.strip()]
    return lines


def _constraint_lines(document: dict) -> list[str]:
    rules = [f"- {rule['text']}" for rule in document.get("constraints") or [] if rule.get("text")]
    return ["Binding rules:", *rules] if rules else []


def writing_text(document: dict, *, binding_only: bool = False) -> str:
    """The writing guidelines for an agent. ``binding_only`` keeps the voice, the audience and the binding rules, for an agent that only chooses what to commission."""
    lines = _voice_lines(document)
    if document.get("audience"):
        lines.append(f"Audience: {document['audience']}")
    if not binding_only:
        for key, label in PROSE_FIELDS:
            value = document.get(key)
            lines += _list(label, value) if isinstance(value, list) else ([f"{label}: {value}"] if value else [])
        lexicon = document.get("lexicon") or {}
        lines += _list("Prefer", lexicon.get("prefer")) + _list("Avoid", lexicon.get("avoid"))
        glossary = [f"- {entry['term']}" + (f": {entry['use']}" if entry.get("use") else "") + (f" (not: {', '.join(entry['avoid'])})" if entry.get("avoid") else "")
                    for entry in document.get("glossary") or []]
        lines += ["Glossary:", *glossary] if glossary else []
        if document.get("bodyMarkus"):
            lines += ["", document["bodyMarkus"].strip()]
    constraints = _constraint_lines(document)
    if constraints:
        lines += ["", *constraints] if lines else constraints
    return "\n".join(lines).strip()


def guidelines_for_agent(store: Any, kind: str, section: str | None, guideline_store: GuidelineStore | None = None, *, language: str) -> dict:
    """The resolved guidelines of ``kind`` for the section (or the publication when there is none) and the Story's ``language``, with where each field came from
    and which versions were used."""
    return resolve_guidelines(guideline_store or GuidelineStore(store), kind, section, language)


def layer_sources(resolved: dict) -> dict:
    """What an entry records so a draft can be traced to the exact guidelines: each layer's slug, version and hash, and where every field came from."""
    return {"layers": resolved["layers"], "fieldSources": resolved["fieldSources"]}
