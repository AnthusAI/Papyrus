"""The standard knowledge blocks (``::include{kind="block" name="knowledge-..."}``) and the wiki directives, from the snapshot.

``trending-strip``, ``trending-list``, ``clusters``, ``concept-of-the-week``, ``topic-count``, ``entity`` and ``score`` are
rendered here, ahead of the site's ``block`` hook. A block whose data file is absent renders nothing, so the page keeps
its own placeholder. Nothing is computed that the snapshot does not hold.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from html import escape

from . import knowledge_components as parts
from .knowledge import KnowledgeSource

PREFIX = "knowledge-"
COMMON = {"kind", "name", "depends"}
BLOCKS: dict[str, set[str]] = {
    "knowledge-trending-strip": {"limit"},
    "knowledge-trending-list": {"limit", "entityKind"},
    "knowledge-clusters": {"limit"},
    "knowledge-concept-of-the-week": set(),
    "knowledge-topic-count": set(),
    "knowledge-entity": {"key", "part", "annotate", "annotateLabel"},
    "knowledge-score": {"value", "n", "threshold", "label"},
}
PARTS = ("trend", "neighbourhood", "related")
DEFAULT_LIMITS = {"knowledge-trending-strip": 5, "knowledge-trending-list": 6, "knowledge-clusters": 3}
CLUSTER_LABELS = {"new": "New", "growing": "▲ Growing", "cooling": "▼ Cooling"}
PLACEHOLDER = '<div class="papyrus-dynamic" data-papyrus-dynamic="{name}"></div>'


def is_knowledge_block(attributes: Mapping) -> bool:
    return attributes.get("kind") == "block" and str(attributes.get("name", "")).startswith(PREFIX)


def _whole(attributes: Mapping, name: str, source: str) -> int | None:
    if name not in attributes:
        return None
    try:
        value = int(attributes[name])
    except ValueError:
        value = -1
    if value < 0:
        raise ValueError(f"{source}: ::include {attributes.get('name')} {name} must be a whole number, got {attributes[name]!r}")
    return value


def _number(attributes: Mapping, name: str, source: str) -> float | None:
    if name not in attributes:
        return None
    try:
        return float(attributes[name])
    except ValueError:
        raise ValueError(f"{source}: ::include {attributes.get('name')} {name} must be a number, got {attributes[name]!r}") from None


def check(attributes: Mapping, source: str) -> None:
    """Validate one knowledge block include; a build error names the file."""
    name = attributes.get("name", "")
    if name not in BLOCKS:
        raise ValueError(f"{source}: unknown knowledge block {name!r}; the blocks are {', '.join(sorted(BLOCKS))}")
    unknown = set(attributes) - COMMON - BLOCKS[name]
    if unknown:
        raise ValueError(f"{source}: ::include {name} has unknown attributes: {', '.join(sorted(unknown))}")
    _whole(attributes, "limit", source)
    if name == "knowledge-entity":
        if not attributes.get("key"):
            raise ValueError(f"{source}: ::include knowledge-entity needs key")
        if attributes.get("part") not in PARTS:
            raise ValueError(f"{source}: ::include knowledge-entity needs part to be one of {', '.join(PARTS)}")
    if name == "knowledge-score":
        if "value" not in attributes:
            raise ValueError(f"{source}: ::include knowledge-score needs value")
        _number(attributes, "value", source)
        _number(attributes, "threshold", source)
        _whole(attributes, "n", source)


def entity_keys(found: list[dict]) -> list[str]:
    return [attributes["key"] for attributes in found if attributes.get("name") == "knowledge-entity" and attributes.get("key")]


def _kinds(index: Mapping) -> dict[str, str]:
    return {str(kind.get("key")): str(kind.get("label") or kind.get("key")) for kind in index.get("kinds") or []}


def _links(index: Mapping) -> dict[str, str]:
    return {str(e.get("key")): e["href"] for e in index.get("entities") or [] if e.get("href")}


def _by_key(index: Mapping) -> dict[str, Mapping]:
    return {str(e.get("key")): e for e in index.get("entities") or []}


def _chip(entity: Mapping, kinds: Mapping[str, str], proposed: bool = False) -> str:
    kind = str(entity.get("kind") or "")
    return parts.entity_chip(kinds.get(kind, kind), entity.get("name"), kind=kind, href=entity.get("href"), proposed=proposed)


def _item_count(count) -> str:
    count = int(count or 0)
    return f"{count} item" + ("" if count == 1 else "s")


def _strip(index: Mapping, limit: int) -> str:
    by_key = _by_key(index)
    chosen = [by_key[key] for key in index.get("trending") or [] if key in by_key and not by_key[key].get("isNew")][:limit]
    if not chosen:
        return ""
    kinds = _kinds(index)
    rows = "".join(f'<li class="papyrus-knowledge-trending-item">{_chip(e, kinds)}{parts.trend(e)}</li>' for e in chosen)
    return f'<ul class="papyrus-knowledge-trending-strip">{rows}</ul>'


def _filter_nav(identifier: str, kinds_present: list[tuple[str, str]]) -> str:
    links = [f'<li><a href="#{identifier}">All</a></li>']
    rules = []
    for key, label in kinds_present:
        anchor = f"{identifier}-{key}"
        links.append(f'<li><a href="#{anchor}">{escape(label)}</a></li>')
        rules.append(f'#{anchor}:target~ol>li:not([data-kind="{key}"]){{display:none}}')
    anchors = "".join(f'<span id="{identifier}-{key}" class="papyrus-knowledge-anchor"></span>' for key, _label in kinds_present)
    return (
        f'<nav class="papyrus-knowledge-kindfilter" aria-label="Filter by kind"><ul>{"".join(links)}</ul></nav>'
        f'{anchors}<style>{"".join(rules)}</style>'
    )


def _list(index: Mapping, limit: int, entity_kind: str) -> str:
    by_key = _by_key(index)
    ranked = [by_key[key] for key in index.get("trending") or [] if key in by_key and not by_key[key].get("isNew")]
    if entity_kind:
        ranked = [e for e in ranked if e.get("kind") == entity_kind]
    chosen = ranked[:limit]
    if not chosen:
        return ""
    kinds = _kinds(index)
    rows = []
    for entity in chosen:
        last4 = (entity.get("change") or {}).get("last4")
        recent = f'<span class="papyrus-knowledge-recent">{int(last4)} in the last 4 weeks</span>' if last4 is not None else ""
        rows.append(
            f'<li class="papyrus-knowledge-trending-item" data-kind="{escape(parts.token(entity.get("kind")))}">{_chip(entity, kinds)}'
            f'{parts.trend(entity)}<span class="papyrus-knowledge-count-text">{_item_count(entity.get("itemCount"))}</span>{recent}</li>'
        )
    nav = ""
    if not entity_kind:
        present = []
        for entity in ranked:
            key = parts.token(entity.get("kind"))
            if key and key not in [k for k, _ in present]:
                present.append((key, kinds.get(str(entity.get("kind")), str(entity.get("kind")))))
        if len(present) > 1:
            identifier = "papyrus-knowledge-trending-" + hashlib.sha256("|".join(str(e.get("key")) for e in chosen).encode("utf-8")).hexdigest()[:8]
            nav = _filter_nav(identifier, present)
    return f'<div class="papyrus-knowledge-trending-list">{nav}<ol>{"".join(rows)}</ol></div>'


def _clusters(clusters: Mapping, limit: int) -> str:
    show_unnamed = clusters.get("unacceptedClusters") == "unnamed"
    cards = []
    for cluster in clusters.get("clusters") or []:
        named = bool(cluster.get("name"))
        if not named and not show_unnamed:
            continue
        if len(cards) >= limit:
            break
        weeks = int(cluster.get("weeksOfData") or 0)
        count = f'<span class="papyrus-knowledge-count-text">{_item_count(cluster.get("itemCount"))}</span>'
        if not named:
            cards.append(f'<li class="papyrus-knowledge-cluster" data-state="unnamed"><p class="papyrus-knowledge-cluster-name">Unnamed theme</p>{count}</li>')
            continue
        name = escape(str(cluster["name"]))
        link = parts.safe_href(cluster.get("href"))
        title = f'<a href="{escape(link)}">{name}</a>' if link else name
        label = CLUSTER_LABELS.get(str(cluster.get("state"))) if weeks >= parts.NEW_BELOW else None
        badge = f'<span class="papyrus-knowledge-cluster-label">{label}</span>' if label else ""
        terms = ", ".join(escape(str(term)) for term in cluster.get("topTerms") or [])
        terms_html = f'<span class="papyrus-knowledge-terms">{terms}</span>' if terms else ""
        series = list(cluster.get("series8") or [])
        spark = parts.sparkline(series[-min(len(series), weeks):]) if weeks >= parts.NEW_BELOW else ""
        state = escape(str(cluster.get("state") or "")) if label else ""
        cards.append(
            f'<li class="papyrus-knowledge-cluster"{f" data-state={chr(34)}{state}{chr(34)}" if state else ""}>'
            f'<p class="papyrus-knowledge-cluster-name">{title}</p>{badge}{count}{terms_html}{spark}</li>'
        )
    return f'<ul class="papyrus-knowledge-clusters">{"".join(cards)}</ul>' if cards else ""


def _concept_of_the_week(index: Mapping) -> str:
    chosen = index.get("conceptOfTheWeek")
    if not chosen or not chosen.get("name"):
        return ""
    link = parts.safe_href(chosen.get("href"))
    name = escape(str(chosen["name"]))
    title = f'<a href="{escape(link)}">{name}</a>' if link else name
    lede = f'<p class="papyrus-knowledge-cotw-lede">{escape(str(chosen["lede"]))}</p>' if chosen.get("lede") else ""
    facts = []
    if chosen.get("itemCount") is not None:
        facts.append(_item_count(chosen["itemCount"]))
    if chosen.get("makerCount") is not None:
        facts.append(f'{int(chosen["makerCount"])} makers')
    meta = f'<p class="papyrus-knowledge-cotw-meta">{", ".join(facts)}</p>' if facts else ""
    return f'<article class="papyrus-knowledge-cotw"><p class="papyrus-knowledge-cotw-name">{title}</p>{lede}{meta}</article>'


def _entity(knowledge: KnowledgeSource, index: Mapping | None, attributes: Mapping) -> str:
    entity = knowledge.entity(attributes["key"])
    if entity is None:
        return ""
    kinds = _kinds(index) if index else {}
    part = attributes["part"]
    if part == "trend":
        body = parts.trend(entity)
        as_of = (index or {}).get("asOf") or ""
        chart = parts.trend_chart(
            entity.get("series26") or [], entity.get("weeksOfHistory"), as_of,
            annotate=attributes.get("annotate", ""), annotate_label=attributes.get("annotateLabel", ""),
        ) if as_of else ""
        return f'<div class="papyrus-knowledge-entity-trend">{body}{chart}</div>' if body or chart else ""
    if part == "neighbourhood":
        return parts.neighbourhood(entity.get("neighbours") or [], kinds, _links(index) if index else {})
    related = []
    for item in entity.get("relatedItems") or []:
        link = parts.safe_href(item.get("url"))
        title = escape(str(item.get("title") or ""))
        when = str(item.get("publishedAt") or "")[:10]
        stamp = f' <time datetime="{escape(when)}">{escape(when)}</time>' if when else ""
        related.append(f'<li>{f"<a href={chr(34)}{escape(link)}{chr(34)}>{title}</a>" if link else title}{stamp}</li>')
    return f'<ul class="papyrus-knowledge-related">{"".join(related)}</ul>' if related else ""


def render_block(attributes: Mapping, knowledge: KnowledgeSource, source: str) -> str:
    """The markup of one knowledge block; empty when the data it reads is absent."""
    check(attributes, source)
    name = attributes["name"]
    limit = _whole(attributes, "limit", source)
    limit = DEFAULT_LIMITS.get(name, 0) if limit is None else limit
    if name == "knowledge-score":
        threshold = _number(attributes, "threshold", source)
        count = _whole(attributes, "n", source)
        return parts.score_readout(_number(attributes, "value", source) or 0.0, count, threshold=0.5 if threshold is None else threshold, label=attributes.get("label", ""))
    if name == "knowledge-clusters":
        clusters = knowledge.clusters()
        return _clusters(clusters, limit) if clusters else ""
    index = knowledge.index()
    if name == "knowledge-entity":
        return _entity(knowledge, index, attributes)
    if not index:
        return ""
    if name == "knowledge-trending-strip":
        return _strip(index, limit)
    if name == "knowledge-trending-list":
        return _list(index, limit, attributes.get("entityKind", ""))
    if name == "knowledge-concept-of-the-week":
        return _concept_of_the_week(index)
    return f'<span class="papyrus-knowledge-count">{int(index.get("topicCount") or 0)}</span>'


def render_directive(directive: str, attributes: Mapping, knowledge: KnowledgeSource) -> str:
    """The static rendering of ``recent-concepts``, ``concept-list`` and ``concept-count``.

    Without ``index.json`` the empty ``papyrus-dynamic`` placeholder stays, as before."""
    index = knowledge.index()
    placeholder = PLACEHOLDER.format(name=escape(directive))
    if not index:
        return placeholder
    kind = attributes.get("kind")
    entities = [e for e in index.get("entities") or [] if not kind or e.get("kind") == kind]
    if directive == "concept-count":
        if not kind:
            total = int(index.get("entityCount") or 0)
        else:
            total = sum(int(k.get("count") or 0) for k in index.get("kinds") or [] if k.get("key") == kind)
        return f'<span class="papyrus-knowledge-count">{total}</span>'
    if directive == "recent-concepts":
        entities.sort(key=lambda e: (int(e.get("weeksOfHistory") or 0), -int(e.get("itemCount") or 0), str(e.get("key"))))
        limit = attributes.get("limit", 10)
    else:
        entities.sort(key=lambda e: (str(e.get("name") or "").casefold(), str(e.get("key"))))
        limit = attributes.get("limit")
    entities = entities if limit is None else entities[: int(limit)]
    if not entities:
        return ""
    kinds = _kinds(index)
    rows = "".join(
        f'<li>{_chip(e, kinds)}<span class="papyrus-knowledge-count-text">{_item_count(e.get("itemCount"))}</span></li>' for e in entities
    )
    return f'<ul class="papyrus-knowledge-concepts" data-directive="{escape(directive)}">{rows}</ul>'
