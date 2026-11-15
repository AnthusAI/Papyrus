"""`papyrus sections labels`: the names of the site's sections in each language it writes in (docs/multilingual-labels.md).

A section's name is its ``title`` and its short description comes from the site's sections file (``--descriptions-file web/sections.json``: a list of
``{"id", "label", "description"}``, where it already is for the home page). Each is translated by the label procedure (``entity_labels.translate``), checked
and, when clean, saved as a current ``EntityLabel`` that the projection reads: the section's name on the language's pages comes from it. A held label (a
collision, an error-severity finding, no equivalent term) is saved held and raises a review request; nothing is published from it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .entity_labels.keys import SECTION, entity_key
from .entity_labels.translate import LabelSource, Outcome, localize_label


def read_descriptions(path: str | None) -> dict[str, dict[str, str]]:
    if not path:
        return {}
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = loaded["sections"] if isinstance(loaded, dict) else loaded
    return {str(row["id"]): {"label": str(row.get("label") or ""), "description": str(row.get("description") or "")} for row in rows}


def section_sources(client: Any, primary: str, descriptions: dict[str, dict[str, str]], only: set[str] | None = None) -> list[LabelSource]:
    """One source per enabled section (or the named ones): its title and, when the sections file has it, its description. The section list is a dozen rows."""
    from . import request_meter

    with request_meter.sweep("section-labels"):
        rows = client.list_records("NewsroomSection")
    sources = []
    for row in sorted(rows, key=lambda r: r["id"]):
        if (only and row["id"] not in only) or (not only and row.get("enabled") is False):
            continue
        described = descriptions.get(row["id"], {})
        sources.append(LabelSource(SECTION, row["id"], primary, (described.get("label") or row.get("title") or row["id"]).strip(),
                                   description=described.get("description", "").strip(), summary=str(row.get("editorialMission") or "")[:400]))
    return sources


def localize_sections(client: Any, languages: list[str], *, descriptions: dict[str, dict[str, str]], only: set[str] | None = None, dry_run: bool = False,
                      models_for=None) -> list[dict[str, Any]]:
    """Translate every section's label into each language. One row per (section, language): ``{section, language, state, name, description, reasons, costUsd}``."""
    import humanus

    from .editorial_checks import GraphQLEditorialStore, settings_from
    from .editorial_languages import primary_language, site_language
    from .guidelines import GuidelineStore
    from .localize.checks import BlockChecker, starter_pack
    from .localize.models import ResponsesModels, Spend
    from .translation_glossary import resolve_glossary

    settings = settings_from(GraphQLEditorialStore(execute=client.graphql, tenant_id=getattr(client, "tenant_id", None)))
    primary = primary_language(settings)
    sources = section_sources(client, primary, descriptions, only)
    keys = tuple(entity_key(SECTION, source.entity_id) for source in sources)
    names = {tag: humanus.resolve_language(tag).name for tag in {primary, *languages}}
    report: list[dict[str, Any]] = []
    for language in dict.fromkeys(site_language(tag, settings) for tag in languages):
        spend = Spend()
        models = (models_for or (lambda s: ResponsesModels(s)))(spend)
        glossary = resolve_glossary(GuidelineStore(client), language)
        checker = BlockChecker(source_language=primary, target_language=language, glossary=glossary, copy_edit_pack=starter_pack(language), judge=models.judge,
                               lanes={"rules": False, "classifier": False})
        for source in sources:
            outcome: Outcome = localize_label(client, models, source, language, glossary=glossary, checker=checker, register_notes=[], language_names=names,
                                              neighbour_keys=keys, dry_run=dry_run)
            report.append({"section": source.entity_id, "language": language, "state": outcome.state, "name": outcome.draft.name if outcome.draft else None,
                           "description": outcome.draft.description if outcome.draft else None, "equivalence": outcome.draft.equivalence if outcome.draft else None,
                           "reasons": outcome.reasons, "costUsd": outcome.cost_usd})
            if outcome.state == "held" and not dry_run:
                _raise_hold(client, source, language, outcome)
    return report


def _raise_hold(client: Any, source: LabelSource, language: str, outcome: Outcome) -> None:
    from .review_requests import raise_review

    raise_review(client, subject={"type": "label", "id": entity_key(source.kind, source.entity_id)}, mode="flag",
                 reason=f"The {language} name of the {source.kind} {source.name!r} is held: " + "; ".join(outcome.reasons)[:1700],
                 raised_by="papyrus.label.localize", request_id=f"label-{source.kind}-{source.entity_id}-{language}".lower().replace("#", "-"))


def sections_labels(flags: list[str], *, client: Any = None) -> None:
    """papyrus sections labels --language TAG [--language TAG ...] [--descriptions-file FILE] [--section ID ...] [--dry-run] [--json]

    Translate the name and short description of each enabled section into each language and save them as that language's section labels (clean ones are
    current and the next projection reads them; a held one raises a review request and is never published). Needs a model key (OPENAI_API_KEY) and the
    operator lane (`papyrus --auth iam`). A label made from the current words is skipped, a person's wording is never overwritten, and --dry-run
    makes the labels (and pays for them) without saving anything."""
    parser = argparse.ArgumentParser(prog="papyrus sections labels", description=sections_labels.__doc__)
    parser.add_argument("--language", action="append", required=True)
    parser.add_argument("--descriptions-file")
    parser.add_argument("--section", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(flags)
    if client is None:
        from .graphql_authoring import create_authoring_client

        client, _ = create_authoring_client()
    report = localize_sections(client, args.language, descriptions=read_descriptions(args.descriptions_file), only=set(args.section) or None, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return
    for row in report:
        print("\t".join([row["section"], row["language"], row["state"], row["name"] or "", f"${row['costUsd']:.4f}", "; ".join(row["reasons"])]))
    print(f"total\t${sum(row['costUsd'] for row in report):.4f}" + ("\tdry run: nothing saved" if args.dry_run else ""), file=sys.stderr)
