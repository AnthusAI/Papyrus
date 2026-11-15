"""Naming one concept in other languages: the concept's own text is the source, the label procedure makes the label (``translate.localize_label``)."""
from __future__ import annotations

from typing import Any

from .keys import CONCEPT
from .primary import lineage_of, preferred_name, primary_text
from .translate import LabelSource, Outcome, localize_label


def concept_source(node: dict[str, Any], language: str) -> LabelSource:
    text = primary_text(node)
    return LabelSource(CONCEPT, lineage_of(node), language, text["name"], description=text["description"], aliases=tuple(text["aliases"]),
                       summary=f"a concept of kind {node.get('nodeKind') or 'unknown'} the newsroom tracks")


def localize_concept(client: Any, concept: str, languages: list[str], *, dry_run: bool = False, models_for=None) -> list[dict[str, Any]]:
    """One row per language: ``{concept, language, state, name, description, equivalence, reasons, costUsd}``."""
    import humanus

    from ..editorial_checks import GraphQLEditorialStore, settings_from
    from ..editorial_languages import primary_language, site_language
    from ..guidelines import GuidelineStore
    from ..localize.checks import BlockChecker, starter_pack
    from ..localize.models import ResponsesModels, Spend
    from ..section_concepts import resolve_concept
    from ..translation_glossary import resolve_glossary

    node = resolve_concept(client, concept)
    if node is None:
        raise ValueError(f"No concept is named {concept!r}.")
    settings = settings_from(GraphQLEditorialStore(execute=client.graphql, tenant_id=getattr(client, "tenant_id", None)))
    primary = node.get("language") or primary_language(settings)
    source = concept_source(node, primary)
    report: list[dict[str, Any]] = []
    for language in dict.fromkeys(site_language(tag, settings) for tag in languages):
        if language == primary:
            raise ValueError(f"{language} is the language the concept is written in; give another language.")
        spend = Spend()
        models = (models_for or (lambda s: ResponsesModels(s)))(spend)
        glossary = resolve_glossary(GuidelineStore(client), language)
        checker = BlockChecker(source_language=primary, target_language=language, glossary=glossary, copy_edit_pack=starter_pack(language), judge=models.judge,
                               lanes={"rules": False, "classifier": False})
        names = {tag: humanus.resolve_language(tag).name for tag in (primary, language)}
        outcome: Outcome = localize_label(client, models, source, language, glossary=glossary, checker=checker, register_notes=[], language_names=names, dry_run=dry_run)
        report.append({"concept": preferred_name(node), "language": language, "state": outcome.state, "name": outcome.draft.name if outcome.draft else None,
                       "description": outcome.draft.description if outcome.draft else None, "equivalence": outcome.draft.equivalence if outcome.draft else None,
                       "reasons": outcome.reasons, "costUsd": outcome.cost_usd})
        if outcome.state == "held" and not dry_run:
            from ..section_labels import _raise_hold

            _raise_hold(client, source, language, outcome)
    return report
