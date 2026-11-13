"""The per-language glossary and do-not-translate list (PPY-795b4b; docs/plans/multilingual-publishing.md, "Terminology memory").

A publication decides how its terms are translated. The glossary is guideline data, the kind ``glossary``, layered like every guideline kind:
the publication's document (entries every language shares: the do-not-translate list), a section's, then each language overlay (``es`` then
``es-419``), then the section's overlays. Laying over is by term: a later layer's entry for a term replaces an earlier one unless the publication
locks ``entries``. Per Ryan (2026-11-13) the glossary is also where a target locale's naming conventions live (``Paris`` is ``París`` in Spanish).

An entry::

    {"term": "Justice Department", "translations": ["Departamento de Justicia"], "note": "...", "caseSensitive": false,
     "originalOnFirstMention": false}
    {"term": "abliteration", "doNotTranslate": true}

``translations`` lists the approved renderings, the first preferred; ``doNotTranslate`` keeps the term exactly as the source writes it. One of the
two is required. Names of people, organisations and products need no entry: Humanus's ``names`` parity check keeps every name unchanged unless the
glossary gives an approved local form.

Two uses, both from this module, so the translator and the check read the same entries:

* :meth:`Glossary.entries_in`: the entries whose source term occurs in the blocks being translated (the translator is told only what it will meet);
* :meth:`Glossary.humanus` : the ``glossary`` of a Humanus check request (the ``glossary`` parity check verifies each one, as a faithfulness finding).

Learning offers, never applies: nothing here writes a glossary. Starter documents for a language are data (``data/glossary/<tag>.json``); an admin
saves one with ``papyrus guidelines save --kind glossary``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import Any, Iterable

from .guidelines.document import GLOSSARY_KIND as KIND, digest, translation_glossary_entries as entries_problem

@dataclass(frozen=True)
class Glossary:
    """The resolved glossary for one language (and section): its entries and the version that identifies exactly what was used."""

    language: str
    entries: tuple[dict[str, Any], ...]
    version: str          # sha256 over the entries and the layers they came from; part of a translation's provenance and run key
    layers: tuple[dict[str, Any], ...] = ()

    @classmethod
    def of(cls, language: str, entries: Iterable[dict[str, Any]], layers: Iterable[dict[str, Any]] = ()) -> "Glossary":
        entries, layers = tuple(entries), tuple(layers)
        problem = entries_problem(list(entries))
        if problem:
            raise ValueError(f"The {language} glossary is not valid: {problem}.")
        return cls(language, entries, digest({"language": language, "entries": list(entries), "layers": list(layers)}), layers)

    def entries_in(self, texts: Iterable[str], source_language: str = "en") -> list[dict[str, Any]]:
        """The entries whose term occurs in ``texts`` (matched the source language's way, on word boundaries), in glossary order."""
        import humanus

        reader = humanus.resolve_language(source_language)
        joined = "\n\n".join(texts)
        return [entry for entry in self.entries if reader.phrase_pattern((entry["term"],), bool(entry.get("caseSensitive"))).search(joined)]

    def humanus(self, entries: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
        """The ``glossary`` of a Humanus check request: every entry (or the given ones), a do-not-translate term with no translations (Humanus keeps it unchanged)."""
        chosen = self.entries if entries is None else tuple(entries)
        return {"language": self.language, "entries": [
            {"term": entry["term"], **({"translations": list(entry["translations"])} if entry.get("translations") else {"doNotTranslate": True}),
             "caseSensitive": bool(entry.get("caseSensitive"))}
            for entry in chosen]}

    def prompt_lines(self, entries: Iterable[dict[str, Any]]) -> list[str]:
        """The entries as lines for a translator's prompt."""
        lines = []
        for entry in entries:
            if entry.get("doNotTranslate"):
                line = f"- {entry['term']}: keep exactly as written (do not translate)"
            else:
                line = f"- {entry['term']}: {entry['translations'][0]}" + (f" (also acceptable: {', '.join(entry['translations'][1:])})" if len(entry["translations"]) > 1 else "")
                if entry.get("originalOnFirstMention"):
                    line += f"; on first mention follow it with the original in brackets ({entry['term']})"
            if entry.get("note"):
                line += f". Note: {entry['note']}"
            lines.append(line)
        return lines


def resolve_glossary(store: Any, language: str, section: str | None = None) -> Glossary:
    """The glossary for text in ``language`` (and ``section``), from the publication's guideline documents. A publication with no glossary has an
    empty one (names still stay unchanged by Humanus's names check)."""
    from .guidelines.layering import resolve_guidelines

    resolved = resolve_guidelines(store, KIND, section, language)
    return Glossary.of(language, resolved["document"].get("entries") or [], resolved["layers"])


def starter_document(language: str | None = None) -> dict[str, Any]:
    """The starter glossary document for a language overlay (``es-419``, ``zh-Hans``), or the publication's shared document when ``language`` is None."""
    name = f"{language}.json" if language else "publication.json"
    path = resources.files("papyrus_content").joinpath("data", "glossary", name)
    if not path.is_file():
        raise ValueError(f"There is no starter glossary for {language or 'the publication'}.")
    document = json.loads(path.read_text(encoding="utf-8"))
    problem = entries_problem(document.get("entries"))
    if problem:
        raise ValueError(f"The starter glossary {name} is not valid: {problem}.")
    return document


def starter_glossary(language: str) -> Glossary:
    """The glossary a publication would have with only the starter documents saved: the shared one, then each language overlay (``es``, ``es-419``)."""
    from .editorial_languages import languages_served
    from .guidelines.layering import lay_over

    overlays = []
    for tag in languages_served(language)[1:]:
        try:
            overlays.append((starter_document(tag), {"layer": "language", "language": tag, "version": 0}))
        except ValueError:
            continue
    document, _, _ = lay_over(KIND, starter_document(None), 0, overlays)
    return Glossary.of(language, document.get("entries") or [], ({"starter": True, "language": language},))
