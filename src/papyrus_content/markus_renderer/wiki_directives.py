"""Dynamic wiki components: leaf directives whose content the CMS computes when a wiki page is shown.

The directives validate and survive into bodyIr as ordinary directive nodes. The CMS wiki view replaces each
one with a live list; a static build renders only an empty placeholder because the data is not in the page.
"""

from __future__ import annotations

from html import escape
from typing import Any

from markusmd.ast import Directive
from markusmd.registry import DirectiveSpec, Registry, _Strict

WIKI_DYNAMIC_DIRECTIVE_NAMES = ("recent-concepts", "concept-list", "concept-count")


class RecentConceptsAttrs(_Strict):
    limit: int = 10
    kind: str | None = None


class ConceptListAttrs(_Strict):
    kind: str | None = None
    limit: int | None = None


class ConceptCountAttrs(_Strict):
    kind: str | None = None


def _render_dynamic_placeholder(directive: Directive, inner: str, attrs: dict[str, Any]) -> str:
    return f'<div class="papyrus-dynamic" data-papyrus-dynamic="{escape(directive.name)}"></div>'


def wiki_directive_specs() -> list[DirectiveSpec]:
    return [
        DirectiveSpec(name="recent-concepts", schema=RecentConceptsAttrs, renderer=_render_dynamic_placeholder, leaf=True),
        DirectiveSpec(name="concept-list", schema=ConceptListAttrs, renderer=_render_dynamic_placeholder, leaf=True),
        DirectiveSpec(name="concept-count", schema=ConceptCountAttrs, renderer=_render_dynamic_placeholder, leaf=True),
    ]


def papyrus_registry() -> Registry:
    registry = Registry.default()
    for spec in wiki_directive_specs():
        registry.register(spec)
    return registry
