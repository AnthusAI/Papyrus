"""Server-rendered knowledge components: entity chip, sparkline and trend, trend chart, graph neighbourhood, score readout.

Each is a pure function returning markup that works with no JavaScript. Marks carry meaning, never colour alone: a proposed
entity has a dashed outline and the text "proposed", a rise or fall has ▲ or ▼ and a sign, a score has its number. SVG is
decorative (``aria-hidden``) and the figure it draws is always present as text. Classes are ``papyrus-knowledge-*``; a site
themes them with the custom properties listed in ``assets/papyrus-knowledge.css``.

Cold-start rules (the snapshot contract): under 4 weeks of history there is no sparkline and no percent, only the word
"new"; from 4 to 7 weeks a sparkline without a percent; from 8 weeks the sparkline and the percent when the snapshot has one.
The 26-week chart appears only after 12 weeks of history.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from collections.abc import Mapping, Sequence

NEW_BELOW = 4
FULL_FROM = 8
CHART_FROM = 12
SAFE_HREF = re.compile(r"^(https?://|/(?!/)|#)", re.I)
TOKEN = re.compile(r"[^A-Za-z0-9_-]+")


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def safe_href(value) -> str:
    return value if isinstance(value, str) and SAFE_HREF.match(value) else ""


def token(value) -> str:
    return TOKEN.sub("-", str(value or "")).strip("-")


def humanise(relation: str) -> str:
    text = re.sub(r"[_-]+", " ", str(relation)).strip()
    return text[:1].upper() + text[1:]


def trend_state(weeks_of_history) -> str:
    weeks = int(weeks_of_history or 0)
    return "new" if weeks < NEW_BELOW else "building" if weeks < FULL_FROM else "full"


def entity_chip(kind_label: str, name: str, *, kind: str = "", href: str | None = None, proposed: bool = False) -> str:
    """The kind and the name of an entity; a proposed one is dashed and says "proposed" to assistive technology."""
    classes = "papyrus-knowledge-chip" + (" papyrus-knowledge-chip--proposed" if proposed else "")
    state = ' data-state="proposed"' if proposed else ""
    marker = '<span class="papyrus-knowledge-sr"> (proposed)</span>' if proposed else ""
    inner = (
        f'<span class="papyrus-knowledge-chip-kind">{esc(kind_label)}</span>'
        f'<span class="papyrus-knowledge-chip-name">{esc(name)}</span>{marker}'
    )
    attributes = f'class="{classes}" data-kind="{esc(token(kind or kind_label))}"{state}'
    link = safe_href(href)
    return f'<a {attributes} href="{esc(link)}">{inner}</a>' if link else f"<span {attributes}>{inner}</span>"


def attribution_text(actor, verb: str) -> str:
    """Who did it, as reader text: ``Accepted by AI``, ``Accepted by Ada``, ``Edited by AI on 2026-10-21``, ``Reviewed by Ada on 2026-10-21``.

    ``verb`` is ``accepted`` or ``description``; a person's description edit reads "Reviewed", an AI agent's "Edited"."""
    if not isinstance(actor, Mapping) or actor.get("actor") not in ("ai", "human"):
        return ""
    human = actor["actor"] == "human"
    name = str(actor.get("name") or "").strip() or "an editor"
    day = str(actor.get("on") or "")[:10]
    on = f" on {day}" if day else ""
    if verb == "accepted":
        return f"Accepted by {name if human else 'AI'}"
    return f"Reviewed by {name}{on}" if human else f"Edited by AI{on}"


def attribution(actor, verb: str) -> str:
    text = attribution_text(actor, verb)
    return f'<p class="papyrus-knowledge-attribution" data-actor="{esc(actor["actor"])}">{esc(text)}</p>' if text else ""


def sparkline(values: Sequence[int]) -> str:
    """Inline SVG polyline of the values, oldest first, with the newest point marked. Decorative: the figure is text beside it."""
    points = [max(0, int(value)) for value in values]
    if len(points) < 2:
        return ""
    width, height, pad = 80, 24, 2
    top = max(max(points), 1)
    step = (width - 2 * pad) / (len(points) - 1)
    coordinates = [(pad + index * step, height - pad - (value / top) * (height - 2 * pad)) for index, value in enumerate(points)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coordinates)
    last_x, last_y = coordinates[-1]
    return (
        f'<svg class="papyrus-knowledge-sparkline" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'aria-hidden="true" focusable="false"><polyline class="papyrus-knowledge-sparkline-line" points="{line}" fill="none"/>'
        f'<circle class="papyrus-knowledge-sparkline-end" cx="{last_x:.1f}" cy="{last_y:.1f}" r="2"/></svg>'
    )


def change_figure(percent: int) -> str:
    """``▲ +40%``: a mark, a sign and the number; the mark is read as a word by assistive technology."""
    if percent > 0:
        mark, word, sign = "▲", "up", "+"
    elif percent < 0:
        mark, word, sign = "▼", "down", "−"
    else:
        mark, word, sign = "▬", "unchanged", ""
    return (
        f'<span class="papyrus-knowledge-change" data-direction="{word}">'
        f'<span aria-hidden="true">{mark}</span><span class="papyrus-knowledge-sr">{word} </span>{sign}{abs(percent)}%</span>'
    )


def trend(entity: Mapping) -> str:
    """The sparkline and the percent change of an entity, or just "new", following the cold-start rules."""
    weeks = int(entity.get("weeksOfHistory") or 0)
    state = trend_state(weeks)
    if state == "new":
        return '<span class="papyrus-knowledge-trend" data-state="new"><span class="papyrus-knowledge-new">new</span></span>'
    series = list(entity.get("series8") or [])
    drawn = sparkline(series[-min(len(series), weeks):])
    percent = (entity.get("change") or {}).get("percent")
    figure = change_figure(int(percent)) if percent is not None else ""
    if not (drawn or figure):
        return ""
    return f'<span class="papyrus-knowledge-trend" data-state="{state}">{drawn}{figure}</span>'


def _week_starts(as_of: str, count: int) -> list[dt.date]:
    end = dt.date.fromisoformat(as_of[:10])
    return [end - dt.timedelta(weeks=count - 1 - index) for index in range(count)]


def trend_chart(series: Sequence[int], weeks_of_history, as_of: str, *, annotate: str = "", annotate_label: str = "", unit: str = "items") -> str:
    """Two-series weekly chart: bars for the weekly count and a dashed line for its trailing four-week average.

    Only after 12 weeks of history; the weeks before the entity's first link are not drawn. ``annotate`` is a date: the week
    that holds it gets a vertical marker, labelled with ``annotate_label``."""
    weeks = int(weeks_of_history or 0)
    values = [max(0, int(value)) for value in series]
    if weeks < CHART_FROM or len(values) < CHART_FROM:
        return ""
    values = values[-min(len(values), weeks):]
    try:
        starts = _week_starts(as_of, len(values))
    except ValueError:
        return ""
    width, height, left, bottom, top_pad = 320, 132, 4, 22, 14
    plot_height = height - bottom - top_pad
    slot = (width - 2 * left) / len(values)
    peak = max(max(values), 1)

    def y_of(value: float) -> float:
        return top_pad + plot_height - (value / peak) * plot_height

    bars = "".join(
        f'<rect class="papyrus-knowledge-chart-bar" x="{left + index * slot + 1:.1f}" y="{y_of(value):.1f}" '
        f'width="{max(slot - 2, 1):.1f}" height="{top_pad + plot_height - y_of(value):.1f}"/>'
        for index, value in enumerate(values)
    )
    averages = [sum(values[max(0, index - 3): index + 1]) / len(values[max(0, index - 3): index + 1]) for index in range(len(values))]
    line = " ".join(f"{left + (index + 0.5) * slot:.1f},{y_of(value):.1f}" for index, value in enumerate(averages))
    marker = ""
    note = ""
    if annotate:
        try:
            day = dt.date.fromisoformat(annotate[:10])
        except ValueError:
            day = None
        found = next((index for index, start in enumerate(starts) if day is not None and start <= day < start + dt.timedelta(weeks=1)), None)
        if found is not None:
            x = left + (found + 0.5) * slot
            anchor = "end" if found > len(values) / 2 else "start"
            text_x = x - 3 if anchor == "end" else x + 3
            label = f'<text class="papyrus-knowledge-chart-note" x="{text_x:.1f}" y="10" text-anchor="{anchor}">{esc(annotate_label)}</text>' if annotate_label else ""
            marker = f'<line class="papyrus-knowledge-chart-marker" x1="{x:.1f}" x2="{x:.1f}" y1="{top_pad}" y2="{top_pad + plot_height}"/>{label}'
            note = f" Marked: {annotate_label or starts[found].isoformat()}."
    summary = f"{unit.capitalize()} per week for {len(values)} weeks to {starts[-1].isoformat()}; peak {max(values)}; latest week {values[-1]}.{note}"
    peak_label = "" if (marker and annotate_label) else f'<text class="papyrus-knowledge-chart-label" x="{left}" y="10">{peak}</text>'
    axis = (
        f'<line class="papyrus-knowledge-chart-axis" x1="{left}" x2="{width - left}" y1="{top_pad + plot_height}" y2="{top_pad + plot_height}"/>'
        f'<text class="papyrus-knowledge-chart-label" x="{left}" y="{height - 6}">{esc(starts[0].isoformat())}</text>'
        f'<text class="papyrus-knowledge-chart-label" x="{width - left}" y="{height - 6}" text-anchor="end">{esc(starts[-1].isoformat())}</text>'
        f"{peak_label}"
    )
    return (
        '<figure class="papyrus-knowledge-chart">'
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{esc(summary)}" focusable="false">'
        f'{bars}<polyline class="papyrus-knowledge-chart-average" points="{line}" fill="none"/>{marker}{axis}</svg>'
        f'<figcaption class="papyrus-knowledge-chart-caption">{esc(summary)} Bars: {esc(unit)} per week. Dashed line: four-week average.</figcaption>'
        "</figure>"
    )


def _weight_bar(weight: int, peak: int) -> str:
    share = round(100 * weight / peak) if peak else 0
    return (
        '<svg class="papyrus-knowledge-weightbar" viewBox="0 0 100 6" width="60" height="6" aria-hidden="true" focusable="false">'
        f'<rect class="papyrus-knowledge-weightbar-track" width="100" height="6"/>'
        f'<rect class="papyrus-knowledge-weightbar-fill" width="{share}" height="6"/></svg>'
    )


def neighbourhood(neighbours: Sequence[Mapping], kinds: Mapping[str, str], links: Mapping[str, str]) -> str:
    """One column per relation type, entries by weight (items linking both ends) with a bar and the number.

    ``kinds`` maps a kind key to its label, ``links`` an entity key to its page."""
    groups: dict[str, list[Mapping]] = {}
    for neighbour in neighbours:
        groups.setdefault(str(neighbour.get("relation") or ""), []).append(neighbour)
    if not groups:
        return ""
    peak = max(int(neighbour.get("weight") or 0) for neighbour in neighbours)
    ordered = sorted(groups.items(), key=lambda pair: (-sum(int(n.get("weight") or 0) for n in pair[1]), pair[0]))
    columns = []
    for relation, members in ordered:
        members = sorted(members, key=lambda n: (-int(n.get("weight") or 0), str(n.get("name") or ""), str(n.get("key") or "")))
        entries = "".join(
            "<li>"
            + entity_chip(kinds.get(str(n.get("kind")), str(n.get("kind") or "")), n.get("name"), kind=str(n.get("kind") or ""), href=links.get(str(n.get("key"))))
            + _weight_bar(int(n.get("weight") or 0), peak)
            + f'<span class="papyrus-knowledge-weight">{int(n.get("weight") or 0)}</span></li>'
            for n in members
        )
        columns.append(
            f'<div class="papyrus-knowledge-neighbourhood-column" data-relation="{esc(token(relation))}">'
            f'<h3 class="papyrus-knowledge-neighbourhood-heading">{esc(humanise(relation))}</h3><ul>{entries}</ul></div>'
        )
    return f'<div class="papyrus-knowledge-neighbourhood">{"".join(columns)}</div>'


def score_readout(value: float, n: int | None = None, *, threshold: float = 0.5, label: str = "") -> str:
    """A 5-segment meter for a score from 0 to 1, with the value and ``n`` as text; dimmed below ``threshold``."""
    clamped = min(max(float(value), 0.0), 1.0)
    filled = int(clamped * 5 + 0.5)
    low = clamped < threshold
    segments = "".join(
        f'<rect class="papyrus-knowledge-score-segment{" papyrus-knowledge-score-segment--filled" if index < filled else ""}" '
        f'x="{index * 14}" y="0" width="12" height="8"/>'
        for index in range(5)
    )
    meter = f'<svg class="papyrus-knowledge-score-meter" viewBox="0 0 68 8" width="68" height="8" aria-hidden="true" focusable="false">{segments}</svg>'
    name = f'<span class="papyrus-knowledge-score-label">{esc(label)}</span>' if label else ""
    count = f'<span class="papyrus-knowledge-score-n">n=<span>{int(n)}</span></span>' if n is not None else ""
    note = '<span class="papyrus-knowledge-sr"> (below threshold)</span>' if low else ""
    classes = "papyrus-knowledge-score" + (" papyrus-knowledge-score--dimmed" if low else "")
    return (
        f'<span class="{classes}" data-level="{"low" if low else "ok"}">{name}{meter}'
        f'<span class="papyrus-knowledge-score-value">{clamped:.2f}</span>{count}{note}</span>'
    )
