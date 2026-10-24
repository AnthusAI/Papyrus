"""Trend stories: a weekly knowledge snapshot turned into cited story drafts (PPY-fb4dfa, docs/idea-pipeline.md).

The flow is snapshot, signals, one model call, a deterministic citation check, then a ``story_draft`` Proposal in state ``draft``.

* A **signal** is one fact-bearing row of the snapshot: a rising (or cooling) cluster or entity, with its weekly counts. Signals
  are built without a model, so the same snapshot gives the same signals.
* The model writes headline, dek and paragraphs as single sentences, each with the signal handles (S1, S2, ...) it rests on.
* The **citation check** keeps a draft only when every sentence cites at least one signal that exists in the snapshot, every
  number in a sentence appears in the signals that sentence cites, and the figure names signals the draft cites. A failing draft is
  not filed; the run record says which sentence failed and why.
* The **figure** is a small chart spec (``evidence.figure``) built by code from the cited signals' weekly counts. The model only
  picks which cited signals to chart and writes the title and caption; it never supplies a number.

Nothing here publishes or transitions a Proposal. Approving the copy and the figure is an editor's decision.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from . import dedupe, synthesis
from .digest import iso
from .pipeline import DEFAULT_MAXIMUM_COST_USD, RunRefused, comparison_documents
from .review import request_human_review
from .store import JsonStore, ProposalStore

DEFAULT_MAXIMUM_DRAFTS = 3
MAXIMUM_ENTITY_SIGNALS = 8
MAXIMUM_NEW_ENTITY_SIGNALS = 3
MAXIMUM_CLUSTER_SIGNALS = 6
MAXIMUM_CITED_SIGNALS = 10  # a story_draft Proposal names at most ten targets
MAXIMUM_FIGURE_SIGNALS = 3
MINIMUM_SENTENCES = 3
MAXIMUM_PARAGRAPHS = 5
MAXIMUM_SENTENCE = 400
FETCH_LIMIT_BYTES = 8_000_000
STATE_ORDER = {"growing": 0, "new": 1, "cooling": 2}
Fetch = Callable[[str], Any]

SYSTEM_PROMPT = """You draft short trend stories for a publication from its weekly knowledge snapshot. You are given the publication's mission and policy, its allowed sections, the week's signals (rising or cooling clusters and entities, each with weekly item counts), its recent and in-flight stories and earlier drafts.

A trend story says what moved this week and what moved with it, using only the signals. Write two to four short paragraphs.

Rules:
- Every headline, dek and body sentence is its own entry with the handles (S1, S2, ...) of the signals it rests on, in "cites". A sentence with no handle, or a handle that is not a signal you were given, makes the whole draft unusable.
- One sentence per entry. Do not put handles in the text; refer to a signal by its name. Write dates as ISO dates (2026-10-19), exactly as they appear in the signals.
- Use only what the signal fields say. Do not invent facts, causes, quotes, dates or names, and do not explain why something grew. Do not do arithmetic: write a number only if it appears in the fields of a signal that sentence cites (write digits, not number words). A sentence that mentions two signals cites both.
- Where "percent" is null the base is small or the history short: describe the counts, never a percentage. Where "is_new" is true, say the entity is new to the map.
- Items are the publication's own published items; counts are items per week. The stories are proposals for an editor, not finished reporting.
- Make no present-tense statement about the publisher's own production systems or results.
- Choose the section from the allowed list, exactly as written.
- figure_signals are one to three cited handles whose weekly counts make the chart; figure_title and figure_caption describe it using only those signals' numbers.
- Skip a trend that recent or in-flight stories or earlier drafts already cover. Propose as many distinct stories as the signals support, up to maximum_drafts, each built from different signals; fewer is better than weak. Never use the word "desk".
"""

_SENTENCE = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}}},
    "required": ["text", "cites"],
    "additionalProperties": False,
}
SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "name": "trend_story_drafts",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "drafts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "headline": _SENTENCE,
                        "dek": _SENTENCE,
                        "section": {"type": "string"},
                        "paragraphs": {
                            "type": "array",
                            "items": {"type": "object", "properties": {"sentences": {"type": "array", "items": _SENTENCE}}, "required": ["sentences"], "additionalProperties": False},
                        },
                        "figure_signals": {"type": "array", "items": {"type": "string"}},
                        "figure_title": {"type": "string"},
                        "figure_caption": {"type": "string"},
                    },
                    "required": ["headline", "dek", "section", "paragraphs", "figure_signals", "figure_title", "figure_caption"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["drafts"],
        "additionalProperties": False,
    },
}


# --- the snapshot -------------------------------------------------------------------------------------------------------


def read_location(location: str) -> Any:
    """JSON from a path or an http(s) address."""
    if re.match(r"https?://", location):
        request = urllib.request.Request(location, headers={"Accept": "application/json", "User-Agent": "papyrus-ideas-trends"})
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - http(s) only, checked above
            raw = response.read(FETCH_LIMIT_BYTES + 1)
        if len(raw) > FETCH_LIMIT_BYTES:
            raise ValueError(f"{location} is larger than {FETCH_LIMIT_BYTES} bytes.")
        return json.loads(raw.decode("utf-8"))
    return json.loads(Path(location).expanduser().read_text(encoding="utf-8"))


def _join(base: str, relative: str) -> str:
    return base.rstrip("/") + "/" + relative if re.match(r"https?://", base) else str(Path(base).expanduser() / relative)


def load_snapshot(source: str, fetch: Fetch = read_location) -> dict[str, Any]:
    """A knowledge snapshot from ``source``: a weekly archive entry (``history/<asOf>.json``, self-contained), an ``index.json``,
    or the ``_data/knowledge/`` directory or address that holds ``index.json``, ``clusters.json`` and ``entities/``."""
    location = source.strip()
    previous: dict[str, Any] | None = None
    if location.endswith(".json"):
        document = fetch(location)
        if isinstance(document, dict) and isinstance(document.get("snapshot"), dict):
            held = document["snapshot"]
            index, clusters, entities = held.get("index"), held.get("clusters"), held.get("entities") or {}
            entity_file: Callable[[str], dict[str, Any] | None] = lambda key: entities.get(key)  # noqa: E731
        else:
            if not isinstance(document, dict) or not isinstance(document.get("entities"), list):
                raise ValueError(f"{source} is not a knowledge snapshot (no index with asOf and entities, no archived snapshot).")
            index, base = document, location.rsplit("/", 1)[0] if "/" in location else "."
            clusters = fetch(_join(base, "clusters.json"))
            entity_file = _entity_reader(fetch, base)
            previous = _previous_clusters(fetch, base, index.get("asOf") if isinstance(index, dict) else None)
    else:
        index, clusters = fetch(_join(location, "index.json")), fetch(_join(location, "clusters.json"))
        entity_file = _entity_reader(fetch, location)
        previous = _previous_clusters(fetch, location, index.get("asOf") if isinstance(index, dict) else None)
    if not isinstance(index, dict) or not index.get("asOf") or not isinstance(index.get("entities"), list):
        raise ValueError(f"{source} is not a knowledge snapshot (no index with asOf and entities).")
    try:
        date.fromisoformat(index["asOf"])
    except ValueError as error:
        raise ValueError(f"The snapshot asOf {index['asOf']!r} is not a date.") from error
    return {
        "source": source, "asOf": index["asOf"], "index": index,
        "clusters": (clusters or {}).get("clusters", []) if isinstance(clusters, dict) else [],
        "entityFile": entity_file, "previous": previous,
    }


def _entity_reader(fetch: Fetch, base: str) -> Callable[[str], dict[str, Any] | None]:
    def read(key: str) -> dict[str, Any] | None:
        try:
            return fetch(_join(base, f"entities/{key}.json"))
        except Exception:  # noqa: BLE001 - an entity file is colour for the model; its absence never stops a run
            return None

    return read


def _previous_clusters(fetch: Fetch, base: str, as_of: str | None) -> dict[str, Any] | None:
    """The cluster item counts of the last archived week before ``as_of``, from the history archive; None when there is none."""
    try:
        entries = [entry for entry in fetch(_join(base, "history/index.json")).get("entries", []) if entry.get("asOf") and entry["asOf"] < (as_of or "")]
        if not entries:
            return None
        latest = max(entries, key=lambda entry: entry["asOf"])
        archived = fetch(_join(base, f"history/{latest['file']}"))
        return {"asOf": latest["asOf"], "counts": {cluster["uid"]: cluster.get("itemCount") for cluster in archived.get("clusters", [])}}
    except Exception:  # noqa: BLE001 - the archive is optional
        return None


# --- signals --------------------------------------------------------------------------------------------------------------


def week_labels(as_of: str, count: int) -> list[str]:
    """Monday dates of the ``count`` ISO weeks ending with the week that contains ``as_of`` (oldest first)."""
    end = date.fromisoformat(as_of)
    end -= timedelta(days=end.weekday())
    return [(end - timedelta(weeks=count - 1 - position)).isoformat() for position in range(count)]


def _series(values: Any) -> list[int | float]:
    return [value for value in values or [] if isinstance(value, (int, float)) and not isinstance(value, bool)]


def build_signals(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """The week's signals, clusters first (growing, new, cooling, then the rest), then entities (trending order, then new ones)."""
    as_of, signals = snapshot["asOf"], []
    previous = snapshot.get("previous") or {}
    clusters = [cluster for cluster in snapshot["clusters"] if cluster.get("name") and cluster.get("uid") and cluster.get("itemCount")]
    clusters.sort(key=lambda cluster: (STATE_ORDER.get(cluster.get("state"), 3), -int(cluster["itemCount"]), cluster["uid"]))
    for cluster in clusters[:MAXIMUM_CLUSTER_SIGNALS]:
        series = _series(cluster.get("series8"))
        signal = {
            "id": f"cluster:{cluster['uid']}", "asOf": as_of, "kind": "cluster", "name": cluster["name"], "targetType": "cluster", "targetId": cluster["uid"],
            "state": cluster.get("state"), "itemCount": cluster["itemCount"], "weeksOfData": cluster.get("weeksOfData"),
            "topTerms": (cluster.get("topTerms") or [])[:6], "series": series, "weeks": week_labels(as_of, len(series)), "href": cluster.get("href"),
        }
        if (previous.get("counts") or {}).get(cluster["uid"]) is not None:
            signal["itemCountInPreviousArchive"] = previous["counts"][cluster["uid"]]
            signal["previousArchiveWeek"] = previous["asOf"]
        signals.append(signal)
    by_key = {entity["key"]: entity for entity in snapshot["index"]["entities"] if entity.get("key")}
    keys = [key for key in snapshot["index"].get("trending") or [] if key in by_key][:MAXIMUM_ENTITY_SIGNALS]
    new = sorted((e for e in by_key.values() if e.get("isNew") and (e.get("change") or {}).get("last4", 0) >= 3 and e["key"] not in keys), key=lambda e: (-e["change"]["last4"], e["key"]))
    keys += [entity["key"] for entity in new[:MAXIMUM_NEW_ENTITY_SIGNALS]]
    for key in keys:
        entity, change = by_key[key], by_key[key].get("change") or {}
        series = _series(entity.get("series8"))
        signal = {
            "id": f"entity:{key}", "asOf": as_of, "kind": "entity", "name": entity["name"], "entityKind": entity.get("kind"), "targetType": "entity", "targetId": key,
            "itemCount": entity.get("itemCount"), "weeksOfHistory": entity.get("weeksOfHistory"), "isNew": bool(entity.get("isNew")),
            "last4": change.get("last4"), "prior4": change.get("prior4"), "percent": change.get("percent"),
            "series": series, "weeks": week_labels(as_of, len(series)), "href": entity.get("href"),
        }
        detail = snapshot["entityFile"](key) or {}
        if detail.get("neighbours"):
            signal["neighbours"] = [{k: n.get(k) for k in ("name", "relation", "weight")} for n in detail["neighbours"][:3]]
        if detail.get("relatedItems"):
            signal["relatedItems"] = [{k: i.get(k) for k in ("title", "url", "publishedAt")} for i in detail["relatedItems"][:3]]
        signals.append(signal)
    return signals


def handles_for(signals: list[dict[str, Any]]) -> dict[str, str]:
    """Handle (S1, S2, ...) to signal id, in signal order."""
    return {f"S{number}": signal["id"] for number, signal in enumerate(signals, start=1)}


def signal_view(handle: str, signal: dict[str, Any], as_of: str) -> dict[str, Any]:
    """What the model sees, and the only numbers a sentence citing it may use."""
    view: dict[str, Any] = {"handle": handle, "kind": signal["kind"], "name": signal["name"], "week_of": as_of}
    if signal["kind"] == "cluster":
        view.update(state=signal.get("state"), items_in_cluster=signal["itemCount"], weeks_of_data=signal.get("weeksOfData"), top_terms=signal.get("topTerms"))
        if "itemCountInPreviousArchive" in signal:
            view.update(items_in_cluster_in_previous_archive=signal["itemCountInPreviousArchive"], previous_archive_week=signal["previousArchiveWeek"])
    else:
        view.update(
            entity_kind=signal.get("entityKind"), items_total=signal.get("itemCount"), weeks_of_history=signal.get("weeksOfHistory"), is_new=signal.get("isNew"),
            items_last_4_weeks=signal.get("last4"), items_prior_4_weeks=signal.get("prior4"), percent=signal.get("percent"),
            neighbours=signal.get("neighbours"), related_items=signal.get("relatedItems"),
        )
    view["items_per_week"] = dict(zip(signal["weeks"], signal["series"]))
    return {key: value for key, value in view.items() if key == "percent" or value not in (None, [], {})}  # a null percent is information


def build_input(snapshot: dict[str, Any], signals: list[dict[str, Any]], context: dict[str, Any], maximum: int) -> dict[str, Any]:
    handles = handles_for(signals)
    by_id = {signal["id"]: signal for signal in signals}
    return {
        "mission": context.get("mission"), "policy": context.get("policy"),
        "allowed_sections": [section["title"] for section in context.get("sections", [])],
        "maximum_drafts": maximum, "snapshot_week_of": snapshot["asOf"],
        "signals": [signal_view(handle, by_id[identifier], by_id[identifier]["asOf"]) for handle, identifier in handles.items()],
        "recent_and_in_flight_stories": [{key: story.get(key) for key in ("title", "section", "state", "date", "summary") if story.get(key)} for story in context.get("stories", [])],
        "earlier_drafts": [{key: draft.get(key) for key in ("title", "state", "angle") if draft.get(key)} for draft in context.get("drafts", [])],
    }


# --- the model call -------------------------------------------------------------------------------------------------------


def call_model(transport: synthesis.Transport, model: str, model_input: dict[str, Any]) -> tuple[list[Any], synthesis.Usage]:
    payload = synthesis.request_payload(model, model_input) | {"instructions": SYSTEM_PROMPT, "text": {"format": SCHEMA}}
    body = transport(synthesis.RESPONSES_URL, {"Content-Type": "application/json"}, payload)
    text = synthesis.response_text(body)
    if body.get("status") == "incomplete" or text is None:
        raise synthesis.SynthesisError("The model returned no complete answer.")
    try:
        drafts = json.loads(text)["drafts"]
    except (ValueError, KeyError, TypeError) as error:
        raise synthesis.SynthesisError("The model did not answer with the trend story drafts format.") from error
    if not isinstance(drafts, list):
        raise synthesis.SynthesisError("The model did not answer with a list of drafts.")
    return drafts, synthesis.usage_of(body, model)


# --- the citation check ---------------------------------------------------------------------------------------------------


DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def _normal(token: str) -> str:
    return format(Decimal(token).normalize(), "f")


def facts_in(value: Any) -> tuple[set[str], set[str]]:
    """(numbers, ISO dates) written in a string, or held anywhere in a JSON value. Dates are kept apart from numbers so that the
    month and day of a week label never make small numbers look grounded; ``07``, ``7.0`` and ``7`` are one number."""
    numbers: set[str] = set()
    dates: set[str] = set()
    if isinstance(value, bool) or value is None:
        return numbers, dates
    if isinstance(value, (int, float)):
        return {_normal(repr(value))}, dates
    if isinstance(value, dict):
        parts = [*value.keys(), *value.values()]
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        text = str(value)
        dates.update(DATE.findall(text))
        numbers.update(_normal(token) for token in re.findall(r"\d+(?:\.\d+)?", DATE.sub(" ", text).replace(",", "")))
        return numbers, dates
    for part in parts:
        found_numbers, found_dates = facts_in(part)
        numbers |= found_numbers
        dates |= found_dates
    return numbers, dates


def _problem(where: str, text: str, reason: str) -> dict[str, str]:
    return {"where": where, "reason": reason, "text": text[:160]}


def ungrounded(text: str, allowed: list[tuple[set[str], set[str]]]) -> list[str]:
    """The numbers and dates in ``text`` that none of the ``allowed`` (numbers, dates) sets holds, numbers first."""
    numbers, dates = facts_in(text)
    held_numbers, held_dates = set().union(*(n for n, _ in allowed)), set().union(*(d for _, d in allowed))
    return sorted(numbers - held_numbers, key=float) + sorted(dates - held_dates)


def check_sentence(where: str, entry: Any, handles: dict[str, str], views: dict[str, tuple[set[str], set[str]]]) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """(the sentence with real signal ids, its problems). Problems are reported together so a person sees all of them."""
    if not isinstance(entry, dict) or not isinstance(entry.get("text"), str) or not entry["text"].strip():
        return None, [_problem(where, "", "missing_text")]
    text, cites = entry["text"].strip(), [str(handle).strip() for handle in entry.get("cites") or []]
    problems: list[dict[str, str]] = []
    unknown = sorted({handle for handle in cites if handle not in handles})
    if not cites:
        problems.append(_problem(where, text, "no_citation"))
    if unknown:
        problems.append(_problem(where, text, f"unknown_signal:{','.join(unknown)}"))
    if len(text) > MAXIMUM_SENTENCE:
        problems.append(_problem(where, text, "sentence_too_long"))
    if len(re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])", text)) > 1:
        problems.append(_problem(where, text, "several_sentences_in_one_entry"))
    if re.search(r"\[[A-Z]\d+\]", text):
        problems.append(_problem(where, text, "handle_written_in_text"))
    if re.search(r"\bdesk\b", text, re.IGNORECASE):
        problems.append(_problem(where, text, "banned_word"))
    if cites and not unknown:
        loose = ungrounded(text, [views[handles[handle]] for handle in cites])
        if loose:
            problems.append(_problem(where, text, f"number_not_in_cited_signals:{','.join(loose)}"))
    return ({"text": text, "signalIds": list(dict.fromkeys(handles[h] for h in cites if h in handles))} if not problems else None), problems


def check_draft(item: Any, handles: dict[str, str], signals: dict[str, dict[str, Any]], views: dict[str, tuple[set[str], set[str]]], allowed_sections: list[str]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """(the checked draft or None, the citation check record). The record is kept for failing and passing drafts alike."""
    record: dict[str, Any] = {"status": "failed", "sentences": 0, "problems": []}
    if not isinstance(item, dict):
        record["problems"].append(_problem("draft", "", "not_an_object"))
        return None, record
    problems: list[dict[str, str]] = record["problems"]
    headline, headline_problems = check_sentence("headline", item.get("headline"), handles, views)
    dek, dek_problems = check_sentence("dek", item.get("dek"), handles, views)
    problems += headline_problems + dek_problems
    paragraphs, sentences, attempted = [], [], 0
    raw_paragraphs = item.get("paragraphs")
    if not isinstance(raw_paragraphs, list) or not raw_paragraphs or len(raw_paragraphs) > MAXIMUM_PARAGRAPHS:
        problems.append(_problem("body", "", "paragraphs_missing_or_too_many"))
        raw_paragraphs = []
    for number, paragraph in enumerate(raw_paragraphs, start=1):
        entries = paragraph.get("sentences") if isinstance(paragraph, dict) else None
        checked_paragraph = []
        for position, entry in enumerate(entries if isinstance(entries, list) else [], start=1):
            attempted += 1
            checked, found = check_sentence(f"paragraph {number} sentence {position}", entry, handles, views)
            problems += found
            if checked:
                checked_paragraph.append(checked)
                sentences.append(checked)
        if not checked_paragraph and not any(p["where"].startswith(f"paragraph {number} ") for p in problems):
            problems.append(_problem(f"paragraph {number}", "", "empty_paragraph"))
        paragraphs.append(checked_paragraph)
    record["sentences"] = len(sentences) + (headline is not None) + (dek is not None)
    if attempted < MINIMUM_SENTENCES:
        problems.append(_problem("body", "", "fewer_than_three_body_sentences"))
    cited = list(dict.fromkeys(i for entry in [headline, dek, *sentences] if entry for i in entry["signalIds"]))
    if len(cited) < 2:
        problems.append(_problem("draft", "", "fewer_than_two_signals_cited"))
    if len(cited) > MAXIMUM_CITED_SIGNALS:
        problems.append(_problem("draft", "", "cites_more_than_ten_signals"))
    sections = {name.strip().lower(): name for name in allowed_sections}
    section = str(item.get("section") or "").strip()
    if sections and section.lower() not in sections:
        problems.append(_problem("section", section, "unknown_section"))
    figure_handles = [str(handle).strip() for handle in item.get("figure_signals") or []]
    figure_ids = [handles.get(handle) for handle in figure_handles]
    title, caption = str(item.get("figure_title") or "").strip(), str(item.get("figure_caption") or "").strip()
    if not 1 <= len(figure_ids) <= MAXIMUM_FIGURE_SIGNALS or any(i is None or i not in cited for i in figure_ids):
        problems.append(_problem("figure", ", ".join(figure_handles), "figure_signals_must_be_one_to_three_cited_signals"))
    elif not title or not caption or len(title) > 200 or len(caption) > 300:
        problems.append(_problem("figure", caption, "figure_title_or_caption_missing_or_too_long"))
    elif len({len(signals[i]["series"]) for i in figure_ids}) != 1 or len(signals[figure_ids[0]]["series"]) < 2:
        problems.append(_problem("figure", ", ".join(figure_ids), "figure_series_unusable"))
    else:
        loose = ungrounded(f"{title} {caption}", [views[i] for i in figure_ids])
        if loose or re.search(r"\bdesk\b", f"{title} {caption}", re.IGNORECASE):
            problems.append(_problem("figure", caption, f"number_not_in_cited_signals:{','.join(loose)}" if loose else "banned_word"))
    if problems or headline is None or dek is None:
        return None, record
    record.update(status="passed", signalsCited=cited)
    return {
        "headline": headline, "dek": dek, "section": sections.get(section.lower(), section), "paragraphs": paragraphs, "citedSignalIds": cited,
        "figureSignalIds": figure_ids, "figureTitle": title, "figureCaption": caption,
    }, record


def validate_drafts(raw: list[Any], handles: dict[str, str], signals: dict[str, dict[str, Any]], allowed_sections: list[str], maximum: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(passing drafts, failing drafts with the citation check that failed them). The first ``maximum`` passing drafts are kept."""
    views = {identifier: facts_in(_grounding(signals[identifier])) for identifier in signals}
    valid, invalid = [], []
    for item in raw:
        draft, record = check_draft(item, handles, signals, views, allowed_sections)
        if draft is None:
            title = str(((item.get("headline") or {}).get("text")) if isinstance(item, dict) and isinstance(item.get("headline"), dict) else "")[:200]
            invalid.append({"title": title, "reason": "citation_check_failed", "citationCheck": record})
        else:
            draft["citationCheck"] = record
            valid.append(draft)
    for extra in valid[maximum:]:
        invalid.append({"title": extra["headline"]["text"], "reason": "over_the_maximum"})
    return valid[:maximum], invalid


def _grounding(signal: dict[str, Any]) -> dict[str, Any]:
    # The numbers a sentence may use are exactly the numbers the model was shown for that signal (week_of included).
    return signal_view("S0", signal, signal["asOf"])


# --- figure, body, record -------------------------------------------------------------------------------------------------


def figure_spec(draft: dict[str, Any], signals: dict[str, dict[str, Any]], as_of: str) -> dict[str, Any]:
    chosen = [signals[identifier] for identifier in draft["figureSignalIds"]]
    return {
        "type": "line", "title": draft["figureTitle"], "caption": draft["figureCaption"], "unit": "items per week",
        "source": f"knowledge snapshot {as_of}", "x": chosen[0]["weeks"],
        "series": [{"signal": signal["id"], "label": signal["name"], "values": signal["series"]} for signal in chosen],
    }


def describe_signal(signal: dict[str, Any]) -> str:
    if signal["kind"] == "cluster":
        parts = [f"cluster, {signal.get('state') or 'steady'}, {signal['itemCount']} items"]
    else:
        change = f"{signal['last4']} items in the last four weeks against {signal['prior4']} before" if signal.get("last4") is not None else f"{signal.get('itemCount')} items"
        percent = f" ({signal['percent']:+d}%)" if isinstance(signal.get("percent"), int) else ""
        parts = [f"{signal.get('entityKind') or 'entity'}, {change}{percent}" + (", new to the map" if signal.get("isNew") else "")]
    return f"{signal['name']}: " + "; ".join(parts)


def draft_body(draft: dict[str, Any], signals: dict[str, dict[str, Any]], figure: dict[str, Any]) -> str:
    numbers = {identifier: number for number, identifier in enumerate(draft["citedSignalIds"], start=1)}

    def marked(sentence: dict[str, Any]) -> str:
        return sentence["text"] + " " + "".join(f"[{numbers[i]}]" for i in sentence["signalIds"])

    lines = [marked(draft["dek"]), ""]
    for paragraph in draft["paragraphs"]:
        lines += [" ".join(marked(sentence) for sentence in paragraph), ""]
    lines += [f"## Figure: {figure['title']}", "", f"{figure['caption']} Line chart, {figure['unit']}, weeks beginning {figure['x'][0]} to {figure['x'][-1]}. Source: {figure['source']}.", ""]
    lines += [f"- {entry['label']}: {', '.join(str(value) for value in entry['values'])}" for entry in figure["series"]]
    lines += ["", "## Signals cited", ""]
    for identifier, number in numbers.items():
        signal = signals[identifier]
        link = f" ({signal['href']})" if signal.get("href") else ""
        lines.append(f"{number}. {describe_signal(signal)}{link} `{identifier}`")
    lines += ["", f"Section: {draft['section']}. Drafted by AI from the knowledge snapshot; an editor approves the copy and the figure before anything is published.", ""]
    return "\n".join(lines)


def run_id_for(source: str, now: datetime) -> str:
    return f"trends-run-{now.strftime('%Y%m%dT%H%M%SZ')}-{hashlib.sha256((source + iso(now)).encode()).hexdigest()[:6]}"


def draft_record(draft: dict[str, Any], *, run: dict[str, Any], signals: dict[str, dict[str, Any]], snapshot: dict[str, Any], now: datetime) -> dict[str, Any]:
    figure = figure_spec(draft, signals, snapshot["asOf"])
    cited = [signals[identifier] for identifier in draft["citedSignalIds"]]
    return {
        "ideaId": "idea-" + hashlib.sha256(f"{run['runId']}|{draft['headline']['text']}".encode()).hexdigest()[:10],
        "kind": "story_draft", "origin": "trend", "state": "draft", "proposer": "ai", "proposedBy": "AI", "private": True,
        "publication": run["publication"], "runId": run["runId"], "createdAt": iso(now),
        "snapshot": {"source": snapshot["source"], "asOf": snapshot["asOf"]},
        "title": draft["headline"]["text"][:200], "angle": draft["dek"]["text"][:300], "section": draft["section"],
        "body": draft_body(draft, signals, figure),
        "targets": [{"type": signal["targetType"], "id": signal["targetId"]} for signal in cited],
        "evidence": {"signals": len(cited), "source": f"knowledge snapshot {snapshot['asOf']} ({run['publication']}), papyrus ideas trends"[:200], "figure": figure},
        "citedSignalIds": draft["citedSignalIds"], "citationCheck": draft["citationCheck"],
        "sentences": [{"role": role, **sentence} for role, sentence in [("headline", draft["headline"]), ("dek", draft["dek"])]]
        + [{"role": "body", **sentence} for paragraph in draft["paragraphs"] for sentence in paragraph],
    }


def target_key(targets: Any) -> frozenset[tuple[str, str]]:
    if isinstance(targets, str):
        try:
            targets = json.loads(targets)
        except ValueError:
            targets = []
    return frozenset((str(t.get("type")), str(t.get("id"))) for t in targets or [] if isinstance(t, dict))


def split_same_targets(drafts: list[dict[str, Any]], existing: list[tuple[str, str, frozenset[tuple[str, str]]]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Drops a draft whose cited targets are exactly those of an earlier non-declined story draft (``existing``: kind, id, targets)."""
    kept, dropped, known = [], [], list(existing)
    for draft in drafts:
        wanted = target_key(draft["targets"])
        match = next((entry for entry in known if entry[2] == wanted), None)
        if match:
            dropped.append({"title": draft["title"], "reason": "same_targets", "sameTargetsAs": {"kind": match[0], "id": match[1]}})
            continue
        kept.append(draft)
        known.append(("draft", draft["ideaId"], wanted))
    return kept, dropped


def estimate_inputs(snapshot: dict[str, Any], signals: list[dict[str, Any]], context: dict[str, Any], documents: list[dedupe.Document]) -> dict[str, Any]:
    return {
        "signals": len(signals), "clusterSignals": sum(s["kind"] == "cluster" for s in signals), "entitySignals": sum(s["kind"] == "entity" for s in signals),
        "snapshotAsOf": snapshot["asOf"], "archivePreviousWeek": (snapshot.get("previous") or {}).get("asOf"),
        "stories": len(context.get("stories", [])), "earlierDrafts": sum(1 for d in documents if d.kind in {"draft", "proposal"}),
        "sections": len(context.get("sections", [])), "mission": bool(context.get("mission")), "policy": bool(context.get("policy")),
    }


def draft_trends(
    *,
    snapshot: dict[str, Any],
    site: str,
    context: dict[str, Any],
    json_store: JsonStore | None,
    transport: synthesis.Transport,
    proposal_store: ProposalStore | None = None,
    review_client: Any = None,
    model: str = synthesis.DEFAULT_MODEL,
    maximum: int = DEFAULT_MAXIMUM_DRAFTS,
    threshold: float = dedupe.DEFAULT_THRESHOLD,
    maximum_cost_usd: float = DEFAULT_MAXIMUM_COST_USD,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Drafts trend stories and returns the run ledger. A dry run reads, asks the model and checks, but files, stores and requests nothing."""
    moment = now or datetime.now(timezone.utc)
    run: dict[str, Any] = {
        "runId": run_id_for(snapshot["source"], moment), "kind": "trends-run", "publication": site, "startedAt": iso(moment), "model": model,
        "store": "dry-run" if dry_run else ("proposals" if proposal_store else "json"), "dryRun": dry_run, "private": True,
        "snapshot": {"source": snapshot["source"], "asOf": snapshot["asOf"]},
    }
    stored = json_store.ideas() if json_store else []
    proposals = proposal_store.story_drafts() if proposal_store else []
    if proposal_store is not None and proposal_store.dedupe_unavailable:
        run["proposalDedupe"] = proposal_store.dedupe_unavailable
    documents = comparison_documents(context, stored, proposals, [])
    signals_list = build_signals(snapshot)
    signals = {signal["id"]: signal for signal in signals_list}
    handles = handles_for(signals_list)
    run["inputs"] = estimate_inputs(snapshot, signals_list, context, documents)
    run.update(proposed=0, invalid=[], duplicates=[], drafts=[], usage=None)
    if len(signals_list) < 2:
        run["noCall"] = f"The snapshot yields {len(signals_list)} signal(s); a trend story needs at least 2."
    else:
        model_input = build_input(snapshot, signals_list, context, maximum)
        size = len(SYSTEM_PROMPT) + len(str(model_input))
        if size > synthesis.MAXIMUM_INPUT_CHARACTERS:
            raise RunRefused(f"The input is {size} characters (limit {synthesis.MAXIMUM_INPUT_CHARACTERS}).")
        estimate = synthesis.estimate_cost_usd(model, size)
        run["estimatedCostUsd"] = estimate
        if estimate is not None and estimate > maximum_cost_usd:
            raise RunRefused(f"Estimated cost ${estimate:.4f} is over --max-cost-usd ${maximum_cost_usd:.2f}.")
        raw, usage = call_model(transport, model, model_input)
        run["usage"] = usage.as_dict()
        run["proposed"] = len(raw)
        valid, run["invalid"] = validate_drafts(raw, handles, signals, [s["title"] for s in context.get("sections", [])], maximum)
        records = [draft_record(draft, run=run, signals=signals, snapshot=snapshot, now=moment) for draft in valid]
        similar, run["duplicates"] = dedupe.split_duplicates(records, documents, threshold)
        existing = [("proposal", row["id"], target_key(row.get("targets"))) for row in proposals if row.get("state") != "declined"]
        existing += [("draft", idea["ideaId"], target_key(idea.get("targets"))) for idea in stored if idea.get("origin") == "trend" and idea.get("state") != "declined"]
        kept, same = split_same_targets(similar, [entry for entry in existing if entry[2]])
        run["duplicates"] += same
        for record in kept:
            if not dry_run:
                if proposal_store:
                    record["proposalId"] = proposal_store.file_trend_draft(record)
                if json_store:
                    json_store.save_idea(record)
            run["drafts"].append(record)
    run["ideasCreated"] = 0 if dry_run else len(run["drafts"])
    if dry_run:
        run["review"] = {"status": "skipped", "requested": False, "ideas": len(run["drafts"]), "note": "Dry run: nothing was filed, so no review was requested."}
    else:
        request_human_review(review_client, run, run["drafts"], noun="trend story draft")
    run["finishedAt"] = iso(datetime.now(timezone.utc))
    if json_store and not dry_run:
        json_store.save_run(run)
    return run


def render_report(run: dict[str, Any]) -> str:
    """The markdown a person reads: each draft with its body and figure data, then the drafts that failed the check and why."""
    usage = run.get("usage") or {}
    lines = [
        f"# Trend story drafts: {run['publication']}",
        "",
        f"Run `{run['runId']}` on the snapshot of {run['snapshot']['asOf']} ({run['snapshot']['source']}). Proposed by AI." + (" Dry run: nothing was filed." if run["dryRun"] else " Private drafts for review; nothing here is published."),
        "",
        f"- Signals read: {run['inputs']['signals']}; drafts proposed: {run['proposed']}; passed the citation check and kept: {len(run['drafts'])}; failed the check: {len(run['invalid'])}; duplicates dropped: {len(run['duplicates'])}",
        f"- Model {run['model']}: {usage.get('inputTokens', 0)} input and {usage.get('outputTokens', 0)} output tokens, cost ${usage.get('costUsd') if usage.get('costUsd') is not None else 'unknown'}",
        "",
    ]
    for number, draft in enumerate(run["drafts"], start=1):
        figure = draft["evidence"]["figure"]
        lines += [f"## {number}. {draft['title']}", "", f"Citation check: passed ({draft['citationCheck']['sentences']} sentences, {len(draft['citedSignalIds'])} signals). Targets: " + ", ".join(f"{t['type']}:{t['id']}" for t in draft["targets"]) + f". Figure: {figure['type']}, {len(figure['series'])} series.", "", draft["body"].rstrip(), ""]
    for heading, rows, describe in (
        ("Failed the citation check or were invalid", run["invalid"], lambda r: f"{r['title'] or '(untitled)'}: {r['reason']}" + "".join(f"\n  - {p['where']}: {p['reason']}" + (f" ({p['text']})" if p["text"] else "") for p in (r.get("citationCheck") or {}).get("problems", []))),
        ("Dropped as duplicates", run["duplicates"], lambda r: f"{r['title']}: {r['reason']}"),
    ):
        if rows:
            lines += [f"## {heading}", ""] + [f"- {describe(row)}" for row in rows] + [""]
    if run.get("noCall"):
        lines += [f"No model call was made: {run['noCall']}", ""]
    return "\n".join(lines)
