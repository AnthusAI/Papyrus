"""The source's own publication date, read from HTML (Open Graph ``article:published_time``, JSON-LD ``datePublished``, ``<time datetime>``).

Standard library only, so the monitoring router can bundle it (``web_structured_metadata`` needs the Biblicus runner)."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any


_ISO_DATE_PREFIX = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?(?![\d])")
_PRECISIONS = {"day": 0, "month": 1, "year": 2}
_JSON_LD_DATE_KEY = "datePublished"


class _PublicationDateParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.open_graph_value = ""
        self.json_ld_blocks: list[str] = []
        self.time_values: list[str] = []
        self._json_ld_active = False
        self._json_ld_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        fields = {name.lower(): value or "" for name, value in attrs}
        if tag == "meta":
            key = (fields.get("property") or fields.get("name") or "").lower()
            if key == "article:published_time" and not self.open_graph_value:
                self.open_graph_value = fields.get("content", "").strip()
        elif tag == "time" and fields.get("datetime", "").strip():
            self.time_values.append(fields["datetime"].strip())
        elif tag == "script":
            self._json_ld_active = "ld+json" in fields.get("type", "").lower()
            self._json_ld_buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._json_ld_active:
            self.json_ld_blocks.append("".join(self._json_ld_buffer))
            self._json_ld_active = False

    def handle_data(self, data: str) -> None:
        if self._json_ld_active:
            self._json_ld_buffer.append(data)


def normalize_html_date(raw_value: Any) -> dict[str, str] | None:
    """Reduce an ISO 8601 date or date-time to ``{"value": YYYY-MM-DD, "precision": day|month|year}``; ``None`` when it is not a date."""
    match = _ISO_DATE_PREFIX.match(str(raw_value or "").strip())
    if not match:
        return None
    year, month, day = match.group(1), match.group(2), match.group(3)
    precision = "day" if day else "month" if month else "year"
    from datetime import date

    try:
        value = date(int(year), int(month or 1), int(day or 1))
    except ValueError:
        return None
    return {"value": value.isoformat(), "precision": precision}


def _json_ld_published_values(payload: Any) -> list[str]:
    if isinstance(payload, list):
        return [value for entry in payload for value in _json_ld_published_values(entry)]
    if not isinstance(payload, dict):
        return []
    values = [str(payload[_JSON_LD_DATE_KEY])] if isinstance(payload.get(_JSON_LD_DATE_KEY), (str, int)) else []
    for key, child in payload.items():
        if key != _JSON_LD_DATE_KEY and isinstance(child, (list, dict)):
            values.extend(_json_ld_published_values(child))
    return values


def publication_date_from_html(html: str) -> dict[str, str] | None:
    """The source's own publication date read from its HTML, with where it came from.

    Tries ``article:published_time``, then JSON-LD ``datePublished`` (including inside ``@graph``), then the first ``<time datetime>``.
    Returns ``{"value", "precision", "source"}`` or ``None`` when the page declares no readable date. Never raises.
    """
    parser = _PublicationDateParser()
    try:
        parser.feed(str(html or ""))
        parser.close()
    except Exception:  # noqa: BLE001 - a page that breaks the parser declares no date
        return None
    json_ld_values: list[str] = []
    for block in parser.json_ld_blocks:
        try:
            json_ld_values.extend(_json_ld_published_values(json.loads(block)))
        except ValueError:
            continue
    for source, candidates in (
        ("og:article:published_time", [parser.open_graph_value]),
        ("json-ld", json_ld_values),
        ("time-element", parser.time_values),
    ):
        for candidate in candidates:
            normalized = normalize_html_date(candidate)
            if normalized:
                return {**normalized, "source": source}
    return None


def publication_date_resolution_record(*, source: str, precision: str, resolved_at: str) -> dict[str, str]:
    """The ``Reference.metadata.publicationDateResolution`` shape: where the date came from, how precise it is, and when it was resolved."""
    return {"source": source, "precision": precision, "resolvedAt": resolved_at}
