"""Dynamic wiki components: leaf directives whose content the CMS computes when a wiki page is shown.

The directives validate and survive into bodyIr as ordinary directive nodes. The CMS wiki view replaces each
one with a live list; a static build renders only an empty placeholder because the data is not in the page.
"""

from __future__ import annotations

from collections.abc import Callable
from html import escape
from typing import Any

from pydantic import ConfigDict

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


class IncludeAttrs(_Strict):
    """``::include{kind="block" name="knowledge-entity" key="x" part="trend"}``: the attributes belong to the include's
    kind and are checked when the site is projected (see ``projection/standard/includes.py``)."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)


class VideoAttrs(_Strict):
    """``::video{...}`` as Papyrus documents it (docs/markus-content-markup.md, "Videos"). Markus's built-in spec only knows
    ``src``/``title``/``poster``; the rest is read by Papyrus's own video markup when a site's ``embeds.providers`` is on, and
    otherwise ignored by the built-in renderer. Which attributes are *named* must not depend on the site setting, so this
    one spec is shared by every path that parses Story Markus."""

    src: str
    title: str | None = None
    poster: str | None = None
    credit: str | None = None
    caption: str | None = None
    start: str | int | None = None


def video_directive_spec() -> DirectiveSpec:
    """The ``video`` directive with Papyrus's attribute names and Markus's own renderer (so output is unchanged)."""
    builtin = Registry.default().resolve("video")
    assert builtin is not None
    return DirectiveSpec(name="video", schema=VideoAttrs, renderer=builtin.renderer, leaf=True)


def base_registry() -> Registry:
    """Markus's default directives plus Papyrus's wider ``video``; no wiki directives."""
    registry = Registry.default()
    registry.register(video_directive_spec())
    return registry


def _render_dynamic_placeholder(directive: Directive, inner: str, attrs: dict[str, Any]) -> str:
    return f'<div class="papyrus-dynamic" data-papyrus-dynamic="{escape(directive.name)}"></div>'


def wiki_directive_specs(render: Callable[[str, dict[str, Any]], str] | None = None) -> list[DirectiveSpec]:
    """The wiki directives. ``render(name, attributes)`` fills them in a static build; without it each is an empty placeholder."""

    def renderer(directive: Directive, inner: str, attrs: dict[str, Any]) -> str:
        return render(directive.name, attrs) if render is not None else _render_dynamic_placeholder(directive, inner, attrs)

    return [
        DirectiveSpec(name="recent-concepts", schema=RecentConceptsAttrs, renderer=renderer, leaf=True),
        DirectiveSpec(name="concept-list", schema=ConceptListAttrs, renderer=renderer, leaf=True),
        DirectiveSpec(name="concept-count", schema=ConceptCountAttrs, renderer=renderer, leaf=True),
        DirectiveSpec(name="include", schema=IncludeAttrs, renderer=lambda directive, inner, attrs: "", leaf=True),
    ]


def papyrus_registry(render: Callable[[str, dict[str, Any]], str] | None = None) -> Registry:
    registry = base_registry()
    for spec in wiki_directive_specs(render):
        registry.register(spec)
    return registry
