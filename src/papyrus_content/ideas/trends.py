"""Trend stories: a weekly knowledge snapshot turned into cited story drafts (PPY-fb4dfa, docs/idea-pipeline.md).

The flow is snapshot, signals, one model call, a deterministic citation check, then a ``story_draft`` Proposal in state ``draft``.

* A **signal** is one fact-bearing row of the snapshot: a rising (or cooling) cluster or entity, with its weekly counts. Signals
  are built without a model, so the same snapshot gives the same signals.
* **Which entities are signals** is a deterministic ranking (``select_entities``): the most surprising recent window (1, 2, 4, 8, ... weeks, chosen per
  entity and corrected for having tried several) against the entity's own earlier history and the whole corpus's growth, not raw counts; broad kinds (licence, task, platform) never anchor a draft and are only offered as context; a maker anchors
  a draft only when it is notable (watchlisted, or several models with real likes or downloads). Thresholds are ``TrendConfig``.
* An **item** is a release or story behind an entity signal in the snapshot window (its title, one-line summary, date and site URL, at
  most five most recent per signal). The model is shown them so the story is about what shipped, not only the counts.
* The model writes headline, dek and paragraphs as single sentences, each with the signal handles (S1, S2, ...) and item handles
  (I1, I2, ...) it rests on.
* The **citation check** keeps a draft only when every sentence cites at least one signal or item that exists in the input, every
  number and ISO date in a sentence appears in the signals and items that sentence cites, the draft cites at least two different
  signals, and the figure names signals the draft cites. A failing draft is not filed; the run record says which sentence failed and why.
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
from collections.abc import Iterable
from typing import Any, Callable

from ..knowledge_snapshot.trends import SERIES_SHORT, TrendConfig, corpus_volume, exceeds_report, scan_window
from . import dedupe, synthesis
from .digest import iso
from .excluded_hosts import is_excluded, normalize_hosts
from .pipeline import DEFAULT_MAXIMUM_COST_USD, RunRefused, comparison_documents
from .review import request_human_review
from .items import IdeaRefused
from .items import ItemStore
from .store import JsonStore

DEFAULT_MAXIMUM_DRAFTS = 3
MAXIMUM_ENTITY_SIGNALS = 8
MAXIMUM_CONTEXT_SIGNALS = 2  # broad-kind entities (licence, task, platform) offered beside the anchors; they may be cited, never lead a story
MAXIMUM_CLUSTER_SIGNALS = 6
MAXIMUM_CITED_SIGNALS = 10  # a story_draft Proposal names at most ten targets
MAXIMUM_FIGURE_SIGNALS = 3
MINIMUM_SENTENCES = 3
MAXIMUM_PARAGRAPHS = 5
MAXIMUM_SENTENCE = 400
FETCH_LIMIT_BYTES = 8_000_000
MAXIMUM_ITEMS_PER_SIGNAL = 5
MAXIMUM_RECORDS_PER_SIGNAL = 3  # monitor records (a Hub model) beside the site's own items; they are cited as releases, not as stories
MAXIMUM_ITEMS = 40  # distinct items in one model input; each is a title, a summary and a date
SUMMARY_LIMIT = 300
ITEM_FETCH_LIMIT_BYTES = 200_000
MAXIMUM_OUTPUT_TOKENS = 12_000  # reasoning plus up to three cited drafts; the shared 6,000 ran out when the model wrote three
EXCLUDED_REPORT_LIMIT = 25
ENGAGEMENT = re.compile(r"(\d[\d,]*)\s+likes?,\s*(\d[\d,]*)\s+downloads?")
STATE_ORDER = {"growing": 0, "new": 1, "cooling": 2}
Fetch = Callable[[str], Any]
FetchText = Callable[[str], str]

SYSTEM_PROMPT = """You draft short trend stories for a publication from its weekly knowledge snapshot. You are given the publication's mission and policy, its allowed sections, the week's signals (rising or cooling clusters and entities, each with weekly item counts), the items behind those signals (each a release or story with a title, a one-line summary, a publication date and a site URL), its recent and in-flight stories and earlier drafts.

Write a story an informed reader would find new, not a readout of counts. Say what shipped, who made it, what is different about it, and what the pattern across the releases suggests. Lead with the releases: name them, say what each one is from its title and summary, and bring in counts only as support for the pattern. Counts are support: cite a signal for a release by the signals in its "behind_signals" and use its four-week change or total, never a single week's count on its own, and leave the counts out of a sentence when they add nothing. Each item already has its own published page, so do not retell one release: the story is what two or more of the releases show together, with each named and cited. Plain, specific prose; no hype and no filler adjectives. Write two to four short paragraphs. The headline names the concrete thing (a release, a maker, a model, a licence) and not a count or the word "trend". The dek says what is new about it in one specific sentence; it does not restate the headline. The signals have no items of their own where "items" is missing; then say only what the counts show.

Rules:
- Every headline, dek and body sentence is its own entry with the handles it rests on, in "cites": signal handles (S1, S2, ...) and item handles (I1, I2, ...). A sentence about a release cites that release's item handle; a sentence that uses a signal's counts or state cites the signal handle too. A sentence with no handle, or a handle that is not one you were given, makes the whole draft unusable.
- One sentence per entry. Do not put handles in the text; refer to a signal or an item by its name. Write dates as ISO dates (2026-10-19), exactly as they appear in the signals and items.
- Use only what the signal and item fields say. Do not invent facts, causes, quotes, dates or names, and do not explain why something grew or why a maker did something. A reading of the pattern is allowed only if it is framed with "suggests" (or "points to") and rests on the cited items. Do not do arithmetic: write a number only if it appears in the fields of a signal or item that sentence cites (write digits, not number words). A sentence that mentions two signals or items cites both.
- A signal with "role": "context" is a broad category (a licence, a task or a platform) offered only so a sentence can say where the releases sit. Cite it for context, but never make it the subject of the headline or the dek, and never build a story around it. The anchors are the signals without that role.
- An entity signal says over which window it is rising: "window_weeks" weeks, with "items_in_window" items in it against "items_before_window" in the "weeks_before_window" weeks before. Say the span as it is ("over the last 4 weeks"), describe the counts and never work out a percentage. Where "is_new" is true, say the entity is new to the map.
- Items are the publication's own published items, except an item with a "from" field: that is a release recorded from a monitored source (for example a model on the Hugging Face Hub). It has no page on the site, so call it a release or a model, say where it is from, never that the publication published or reported it, and use only the facts in its title and summary. Counts are items and recorded releases per week. The stories are proposals for an editor, not finished reporting.
- Make no present-tense statement about the publisher's own production systems or results.
- Choose the section from the allowed list, exactly as written.
- figure_signals are one to three cited signal handles (S) whose weekly counts make the chart; figure_title and figure_caption describe it using only those signals' numbers.
- Hard requirements, checked by code; a draft that misses any of them is discarded whole: (1) at least three body sentences in total, across the paragraphs, not counting the headline and dek; (2) at least two different signals cited across the draft (citing items does not count), so every story compares or connects two or more signals (for example a cluster and an entity that moved together, or two entities); a story about one signal alone is not allowed; (3) every sentence has its own non-empty "cites"; (4) figure_signals are signal handles the draft cites.
- Skip a trend that recent or in-flight stories or earlier drafts already cover, but only when the same signals are covered. Return maximum_drafts drafts whenever the signals and items allow it, each about a different group of two or more releases (give every draft a different lead set; three drafts are expected when there are twelve items) and built from a different pairing or grouping of signals (the same release is not the lead of two drafts), and never fewer than one. Prefer a plain, well-grounded draft that meets the requirements over a clever one. Never use the word "desk".
"""

SENTENCE_SCHEMA = {
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
                        "headline": SENTENCE_SCHEMA,
                        "dek": SENTENCE_SCHEMA,
                        "section": {"type": "string"},
                        "paragraphs": {
                            "type": "array",
                            "items": {"type": "object", "properties": {"sentences": {"type": "array", "items": SENTENCE_SCHEMA}}, "required": ["sentences"], "additionalProperties": False},
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


def read_item_summary(url: str) -> str:
    """The Markdown of a published item (``<item url>.md``) as text; the caller keeps only its one-line summary."""
    request = urllib.request.Request(url, headers={"Accept": "text/markdown", "User-Agent": "papyrus-ideas-trends"})
    with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - http(s) only, built from the snapshot address
        return response.read(ITEM_FETCH_LIMIT_BYTES).decode("utf-8", errors="replace")


def summary_of(markdown: str) -> str | None:
    """The one-line summary of an item: the first block quote line of its Markdown, trimmed."""
    for line in markdown.splitlines():
        if line.startswith(">"):
            text = re.sub(r"\s+", " ", line.lstrip("> ").strip())
            return text[:SUMMARY_LIMIT].rstrip() if text else None
    return None


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
    origin = re.match(r"https?://[^/]+", location)
    return {
        "source": source, "asOf": index["asOf"], "index": index, "siteBase": origin.group(0) if origin else None,
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


def window_start(as_of: str, weeks: int) -> date:
    """The Monday that starts the window: the week of ``as_of`` and the ``weeks - 1`` before it."""
    end = date.fromisoformat(as_of)
    return (end - timedelta(days=end.weekday())) - timedelta(weeks=weeks - 1)


def window_records(related: Any, as_of: str, weeks: int) -> list[dict[str, Any]]:
    """The newest ``relatedRecords`` of an entity file in the snapshot window: releases recorded from a monitored source, each with its
    title, date, address (the source's own card), the one-line summary of its structured facts and where it is from. At most
    ``MAXIMUM_RECORDS_PER_SIGNAL``, newest first. They carry their summary, so no page is fetched for them."""
    start = window_start(as_of, weeks)
    records: dict[str, dict[str, Any]] = {}
    for row in related or []:
        if not isinstance(row, dict) or not row.get("title") or not row.get("url") or not isinstance(row.get("publishedAt"), str) or not row.get("summary"):
            continue
        if not re.match(r"https?://", str(row["url"])):
            continue
        try:
            published = date.fromisoformat(row["publishedAt"][:10])
        except ValueError:
            continue
        if published < start:
            continue
        url = str(row["url"])
        records.setdefault(
            f"item:{url}",
            {
                "id": f"item:{url}", "title": str(row["title"]).strip(), "date": published.isoformat(), "path": url, "url": url,
                "summary": str(row["summary"]).strip(), "from": str(row.get("provenance") or "from a monitored source"),
            },
        )
    return sorted(records.values(), key=lambda item: (item["date"], item["id"]), reverse=True)[:MAXIMUM_RECORDS_PER_SIGNAL]


def window_items(related: Any, as_of: str, site_base: str | None, weeks: int) -> list[dict[str, Any]]:
    """The most recent items of an entity file's ``relatedItems`` that fall in the snapshot window (the ``weeks`` to the end of the
    snapshot's week, plus anything published since), newest first, at most ``MAXIMUM_ITEMS_PER_SIGNAL``. Each is its title, date, path and site URL."""
    start = window_start(as_of, weeks)
    items: dict[str, dict[str, Any]] = {}
    for row in related or []:
        if not isinstance(row, dict) or not row.get("title") or not row.get("url") or not isinstance(row.get("publishedAt"), str):
            continue
        try:
            published = date.fromisoformat(row["publishedAt"][:10])
        except ValueError:
            continue
        if published < start:
            continue
        path = str(row["url"])
        site_url = path if re.match(r"https?://", path) else (site_base + path if site_base and path.startswith("/") else None)
        items.setdefault(f"item:{path}", {"id": f"item:{path}", "title": str(row["title"]).strip(), "date": published.isoformat(), "path": path, "url": site_url})
    return sorted(items.values(), key=lambda item: (item["date"], item["id"]), reverse=True)[:MAXIMUM_ITEMS_PER_SIGNAL]


def attach_summaries(signals: list[dict[str, Any]], fetch_text: FetchText | None) -> None:
    """Adds ``summary`` (the one-line summary of the published item) to every distinct item, when the item has a site URL and the text can be
    read. Items beyond ``MAXIMUM_ITEMS`` distinct ones are dropped, later signals first. A page that cannot be read is only a missing summary."""
    known: dict[str, dict[str, Any]] = {}
    for signal in signals:
        kept = []
        for item in signal.get("items", []):
            if item["id"] in known:
                kept.append(known[item["id"]])
            elif len(known) < MAXIMUM_ITEMS:
                known[item["id"]] = item
                kept.append(item)
        if kept:
            signal["items"] = kept
        else:
            signal.pop("items", None)
    for item in known.values():
        if fetch_text is None or not item.get("url") or item.get("from"):  # a recorded release states its facts itself
            continue
        try:
            summary = summary_of(fetch_text(item["url"].rstrip("/") + ".md"))
        except Exception:  # noqa: BLE001 - the summary is colour for the model; its absence never stops a run
            summary = None
        if summary:
            item["summary"] = summary


def window_engagement(related: Any, as_of: str, weeks: int) -> dict[str, int]:
    """How much the Hub's own numbers say about the releases in the window: distinct models and the likes and downloads their summaries state.
    It reads every record the entity file lists (the newest ``related_limit`` of them), not only the few the model is shown."""
    start = window_start(as_of, weeks)
    models: dict[str, tuple[int, int]] = {}
    for row in related or []:
        if not isinstance(row, dict) or not row.get("title") or not isinstance(row.get("publishedAt"), str):
            continue
        try:
            if date.fromisoformat(row["publishedAt"][:10]) < start:
                continue
        except ValueError:
            continue
        found = ENGAGEMENT.search(str(row.get("summary") or ""))
        likes, downloads = (int(found.group(1).replace(",", "")), int(found.group(2).replace(",", ""))) if found else (0, 0)
        models.setdefault(str(row["title"]).strip(), (likes, downloads))
    return {"models": len(models), "likes": sum(m[0] for m in models.values()), "downloads": sum(m[1] for m in models.values())}


def maker_notability(entity: dict[str, Any], detail: dict[str, Any] | None, as_of: str, weeks: int, config: TrendConfig) -> tuple[bool, str]:
    """(notable, why), over the last ``weeks`` weeks (the entity's own trend window). A maker is notable when it is on the watchlist, when the site has
    its own item about it in the window, or when at least ``minimum_models`` of its models were recorded in the window with likes adding up to
    ``minimum_likes`` or downloads to ``minimum_downloads`` (and in either case at least ``likes_floor`` likes: downloads alone are not notability).
    A single account with a handful of likes is below the bar and cannot anchor a draft."""
    names = {str(entity.get("key") or "").lower(), str(entity.get("name") or "").lower()}
    if names & config.watchlist:
        return True, "watchlisted"
    detail = detail or {}
    if window_items(detail.get("relatedItems"), as_of, None, weeks):
        return True, "the site has its own item about it in the window"
    engagement = window_engagement(detail.get("relatedRecords"), as_of, weeks)
    summary = f"{engagement['models']} model(s), {engagement['likes']} likes, {engagement['downloads']} downloads in the window"
    reached = engagement["likes"] >= config.minimum_likes or engagement["downloads"] >= config.minimum_downloads
    if engagement["models"] >= config.minimum_models and engagement["likes"] >= config.likes_floor and reached:
        return True, summary
    return False, summary


def history_of(entity: dict[str, Any]) -> list[int | float]:
    """The weekly counts an entity is scanned over: its full history (``seriesWeekly``, from its first week) when the snapshot has it, else the
    26 weeks (``series26``), else the 8 (``series8``). The windows tried (1, 2, 4, 8, ... weeks) grow with the history, up to the longest one that
    still leaves ``minimum_baseline_weeks`` of baseline."""
    return _series(entity.get("seriesWeekly")) or _series(entity.get("series26")) or _series(entity.get("series8"))


def _filed_date(row: dict[str, Any]) -> date | None:
    try:
        return datetime.fromisoformat(str(row.get("createdAt")).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _stored_window(row: dict[str, Any], key: str) -> dict[str, Any] | None:
    """The window a stored trend draft reported for an entity (``evidence.windows``), when the row carries it."""
    evidence = row.get("evidence")
    if isinstance(evidence, str):
        try:
            evidence = json.loads(evidence)
        except ValueError:
            return None
    for window in (evidence.get("windows") if isinstance(evidence, dict) else None) or []:
        if isinstance(window, dict) and window.get("signal") == f"entity:{key}" and window.get("windowWeeks") and window.get("count") is not None:
            return window
    return None


def _rate(report: dict[str, Any], config: TrendConfig) -> float:
    return (report["count"] + config.baseline_smoothing) / report["windowWeeks"]


def previous_report(key: str, rows: list[dict[str, Any]], history: list[int | float], volume: list[float], as_of: str, config: TrendConfig) -> dict[str, Any] | None:
    """What the earlier story drafts (``rows``: Proposals or stored trend drafts, in any state, declined included) that anchored on entity ``key``
    reported for it, as ``{filed, state, windowWeeks, count}``; the strongest report (highest weekly rate) when several drafts anchored on it.

    A draft reports the window the scan chose at the time. A stored draft carries it (``evidence.windows``); otherwise it is found again from the
    data, by scanning the entity's series and the corpus volume cut off at the week the draft was made (its snapshot's week, else its filing week),
    which is the same deterministic scan that run made. A draft made before the history reaches back far enough to scan has no report and counts
    for nothing. A broad kind never anchors, so a draft that only cites one as context says nothing about it."""
    if key.split("--", 1)[0] in config.broad_kinds:
        return None
    current = date.fromisoformat(as_of)
    current -= timedelta(days=current.weekday())
    best: dict[str, Any] | None = None
    for row in rows:
        if ("entity", key) not in target_key(row.get("targets")):
            continue
        filed = _filed_date(row)
        if filed is None:
            continue
        report = _stored_window(row, key)
        if report is None:
            made = (row.get("snapshot") or {}).get("asOf") if isinstance(row.get("snapshot"), dict) else None
            try:
                week = date.fromisoformat(str(made)) if made else filed
            except ValueError:
                week = filed
            week -= timedelta(days=week.weekday())
            cut = max(0, (current - week).days // 7)
            report = scan_window(history[: len(history) - cut], volume[: len(volume) - cut], config) if cut < len(volume) else None
        if report is None:
            continue
        report = {"filed": filed.isoformat(), "state": row.get("state"), "windowWeeks": report["windowWeeks"], "count": report["count"]}
        if best is None or _rate(report, config) > _rate(best, config):
            best = report
    return best


def select_entities(snapshot: dict[str, Any], config: TrendConfig | None = None, earlier: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Which entities become signals, deterministically, from the index's weekly series (the published ``trending`` order is not used).

    * **Ranked**: each entity's most surprising recent window (``scan_window``: 1, 2, 4, 8, ... weeks against everything before, Bonferroni-corrected for the
      number of windows tried), scored by the z-score of that corrected p-value, times a weight by kind (broad kinds are demoted). The entity needs
      at least ``minimum_recent`` mentions in its chosen window.
    * **Anchors**: the best ``MAXIMUM_ENTITY_SIGNALS`` of the ranked entities whose kind may anchor a draft (``anchor_kinds``), whose corrected p-value is
      within ``significance`` and whose score reaches ``minimum_score``; a maker must also be notable. Entities passed over are listed with the reason.
    * **Evidence, not days**: an entity that already anchored a draft in ``earlier`` (any state, declined included) anchors another only when its window
      now holds significantly more than that draft reported (``exceeds_report``); otherwise it is passed over, whatever the time since.
    * **Context**: up to ``MAXIMUM_CONTEXT_SIGNALS`` broad-kind entities that sit beside the anchors (their neighbours), most connected first. They
      carry ``role: "context"``; the prompt forbids a story about them.
    """
    config = config or TrendConfig()
    as_of = snapshot["asOf"]
    entities = [entity for entity in snapshot["index"]["entities"] if entity.get("key")]
    histories = {entity["key"]: history_of(entity) for entity in entities}
    volume = corpus_volume(histories.values(), max([SERIES_SHORT, *(len(values) for values in histories.values())]))
    scored = []
    for entity in entities:
        window = scan_window(histories[entity["key"]], volume, config)
        if window and window["count"] >= config.minimum_recent:
            score = round(window["surprise"] * config.kind_weight(entity.get("kind")), 3)
            scored.append({"key": entity["key"], "name": entity.get("name"), "kind": entity.get("kind"), "isNew": bool(entity.get("isNew")), "score": score, "window": window})
    scored.sort(key=lambda row: (-row["score"], -row["window"]["count"], row["key"]))
    by_key = {entity["key"]: entity for entity in entities}
    anchors, excluded, prior, details = [], [], [], {}

    def detail_of(key: str) -> dict[str, Any]:
        if key not in details:
            details[key] = snapshot["entityFile"](key) or {}
        return details[key]

    for row in scored:
        window = row["window"]
        if row["score"] < config.minimum_score or window["correctedPValue"] > config.significance:
            continue
        if row["kind"] not in config.anchor_kinds:
            excluded.append({"key": row["key"], "reason": f"{row['kind']} cannot anchor a draft", "score": row["score"]})
            continue
        report = previous_report(row["key"], earlier or [], histories[row["key"]], volume, as_of, config)
        if report:
            more, p_value = exceeds_report(window, report, config)
            prior.append({
                "key": row["key"], "filed": report["filed"], "state": report["state"], "reported": {"windowWeeks": report["windowWeeks"], "count": report["count"]},
                "now": {"windowWeeks": window["windowWeeks"], "count": window["count"]}, "pValue": p_value, "renewed": more,
            })
            if not more:
                excluded.append({
                    "key": row["key"], "score": row["score"],
                    "reason": f"no new evidence: the draft filed {report['filed']} ({report['state']}) reported {report['count']} in {report['windowWeeks']} week(s); "
                    f"now {window['count']} in {window['windowWeeks']} (p={p_value}, needs <= {config.significance})",
                })
                continue
            row = {**row, "renewal": prior[-1]}
        if len(anchors) >= MAXIMUM_ENTITY_SIGNALS:
            continue
        if row["kind"] == "maker":
            notable, why = maker_notability(by_key[row["key"]], detail_of(row["key"]), as_of, window["windowWeeks"], config)
            if not notable:
                excluded.append({"key": row["key"], "reason": f"maker below the notability bar: {why}", "score": row["score"]})
                continue
            row = {**row, "notability": why}
        anchors.append(row)
    anchor_keys = {row["key"] for row in anchors}
    broad = {row["key"]: row for row in scored if row["kind"] in config.broad_kinds and row["key"] not in anchor_keys}
    connection: dict[str, int] = {}
    for row in anchors:
        for neighbour in detail_of(row["key"]).get("neighbours") or []:
            if neighbour.get("key") in broad:
                connection[neighbour["key"]] = connection.get(neighbour["key"], 0) + int(neighbour.get("weight") or 0)
    context = sorted(connection, key=lambda key: (-connection[key], -broad[key]["window"]["surprise"], key))[:MAXIMUM_CONTEXT_SIGNALS]
    return {
        "anchors": anchors, "context": [broad[key] for key in context], "excluded": excluded[:EXCLUDED_REPORT_LIMIT], "priorDrafts": prior,
        "candidatesRanked": len(scored), "thresholds": {
            "minimumRecent": config.minimum_recent, "minimumScore": config.minimum_score, "minimumModels": config.minimum_models,
            "minimumLikes": config.minimum_likes, "minimumDownloads": config.minimum_downloads, "watchlist": sorted(config.watchlist),
            "significance": config.significance, "minimumBaselineWeeks": config.minimum_baseline_weeks,
        },
    }


def build_signals(
    snapshot: dict[str, Any], fetch_text: FetchText | None = None, config: TrendConfig | None = None, selection: dict[str, Any] | None = None,
    excluded_hosts: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """The week's signals, clusters first (growing, new, cooling, then the rest), then the anchor entities by score, then context entities.
    Entity signals carry ``items``: the releases behind them in the window, with a one-line summary where ``fetch_text`` can read the item page.
    The snapshot publishes no member list for a cluster, so a cluster signal has no items. An item whose address is on one of ``excluded_hosts``
    (or a subdomain) is left out of ``items`` and listed in the signal's ``excludedItemIds``: the signal's counts and history still include it."""
    excluded_hosts = normalize_hosts(excluded_hosts)
    config = config or TrendConfig()
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
    selection = selection or select_entities(snapshot, config)
    chosen = [(row, "anchor") for row in selection["anchors"]] + [(row, "context") for row in selection["context"]]
    for row, role in chosen:
        key = row["key"]
        entity = by_key[key]
        history = history_of(entity)
        series = _series(entity.get("series8")) or history[-SERIES_SHORT:]  # the chart shows the last eight weeks, as every signal's does
        window = row["window"]
        signal = {
            "id": f"entity:{key}", "asOf": as_of, "kind": "entity", "name": entity["name"], "entityKind": entity.get("kind"), "targetType": "entity", "targetId": key,
            "itemCount": entity.get("itemCount"), "weeksOfHistory": entity.get("weeksOfHistory"), "isNew": bool(entity.get("isNew")),
            "windowWeeks": window["windowWeeks"], "windowCount": window["count"], "baselineWeeks": window["baselineWeeks"], "baselineCount": window["baselineCount"],
            "window": window, "history": history, "historyWeeks": week_labels(as_of, len(history)),
            "series": series, "weeks": week_labels(as_of, len(series)), "href": entity.get("href"), "role": role,
        }
        detail = snapshot["entityFile"](key) or {}
        if detail.get("neighbours"):
            signal["neighbours"] = [{k: n.get(k) for k in ("name", "relation", "weight")} for n in detail["neighbours"][:3]]
        weeks = window["windowWeeks"]
        items = [*window_items(detail.get("relatedItems"), as_of, snapshot.get("siteBase"), weeks), *window_records(detail.get("relatedRecords"), as_of, weeks)]
        kept = [item for item in items if not item_is_excluded(item, excluded_hosts)]
        if len(kept) != len(items):
            signal["excludedItemIds"] = [item["id"] for item in items if item_is_excluded(item, excluded_hosts)]
        if kept:
            signal["items"] = kept
        signals.append(signal)
    attach_summaries(signals, fetch_text)
    return signals


def item_is_excluded(item: dict[str, Any], excluded_hosts: Iterable[str]) -> bool:
    """True when the item's address (its site URL or its source card; a bare site path has no host) is on an excluded host."""
    return any(is_excluded(address, excluded_hosts) for address in (item.get("url"), item.get("path"), str(item.get("id") or "").removeprefix("item:")))


def collect_items(signals: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Distinct items of the signals by id, in order of first appearance."""
    items: dict[str, dict[str, Any]] = {}
    for signal in signals:
        for item in signal.get("items", []):
            items.setdefault(item["id"], item)
    return items


def handles_for(signals: list[dict[str, Any]]) -> dict[str, str]:
    """Handle to id: S1, S2, ... for the signals in signal order, then I1, I2, ... for their distinct items in order of first appearance."""
    handles = {f"S{number}": signal["id"] for number, signal in enumerate(signals, start=1)}
    handles.update({f"I{number}": identifier for number, identifier in enumerate(collect_items(signals), start=1)})
    return handles


def item_view(handle: str, item: dict[str, Any], signal_handles: list[str] | None = None) -> dict[str, Any]:
    """What the model sees of an item, and the only numbers and dates a sentence citing it may use (title, summary, date)."""
    view = {"handle": handle, "title": item["title"], "summary": item.get("summary"), "published": item["date"], "from": item.get("from")}
    if signal_handles is not None:
        view.update(url=item.get("url") or item["path"], behind_signals=signal_handles)
    return {key: value for key, value in view.items() if value not in (None, [], "")}


def signal_view(handle: str, signal: dict[str, Any], as_of: str, item_handles: dict[str, str] | None = None) -> dict[str, Any]:
    """What the model sees, and the only numbers a sentence citing it may use."""
    view: dict[str, Any] = {"handle": handle, "kind": signal["kind"], "name": signal["name"], "week_of": as_of}
    if signal["kind"] == "cluster":
        view.update(state=signal.get("state"), items_in_cluster=signal["itemCount"], weeks_of_data=signal.get("weeksOfData"), top_terms=signal.get("topTerms"))
        if "itemCountInPreviousArchive" in signal:
            view.update(items_in_cluster_in_previous_archive=signal["itemCountInPreviousArchive"], previous_archive_week=signal["previousArchiveWeek"])
    else:
        view.update(
            entity_kind=signal.get("entityKind"), items_total=signal.get("itemCount"), weeks_of_history=signal.get("weeksOfHistory"), is_new=signal.get("isNew"),
            neighbours=signal.get("neighbours"), role="context" if signal.get("role") == "context" else None,
        )
        view.update(
            window_weeks=signal.get("windowWeeks"), items_in_window=signal.get("windowCount"),
            weeks_before_window=signal.get("baselineWeeks"), items_before_window=signal.get("baselineCount"),
        )
    if item_handles:
        view["items"] = [item_handles[item["id"]] for item in signal.get("items", []) if item["id"] in item_handles]
    view["items_per_week"] = dict(zip(signal.get("historyWeeks") or signal["weeks"], signal.get("history") or signal["series"]))
    return {key: value for key, value in view.items() if value not in (None, [], {})}


def build_input(snapshot: dict[str, Any], signals: list[dict[str, Any]], context: dict[str, Any], maximum: int) -> dict[str, Any]:
    handles = handles_for(signals)
    by_id = {signal["id"]: signal for signal in signals}
    signal_handles = {identifier: handle for handle, identifier in handles.items() if handle.startswith("S")}
    item_handles = {identifier: handle for handle, identifier in handles.items() if handle.startswith("I")}
    items = collect_items(signals)
    behind = {identifier: [signal_handles[signal["id"]] for signal in signals if any(i["id"] == identifier for i in signal.get("items", []))] for identifier in items}
    return {
        "mission": context.get("mission"), "policy": context.get("policy"),
        "allowed_sections": [section["title"] for section in context.get("sections", [])],
        "maximum_drafts": maximum, "snapshot_week_of": snapshot["asOf"],
        "signals": [signal_view(handle, by_id[identifier], by_id[identifier]["asOf"], item_handles) for handle, identifier in handles.items() if handle.startswith("S")],
        "items": [item_view(item_handles[identifier], item, behind[identifier]) for identifier, item in items.items()],
        "recent_and_in_flight_stories": [{key: story.get(key) for key in ("title", "section", "state", "date", "summary") if story.get(key)} for story in context.get("stories", [])],
        "earlier_drafts": [{key: draft.get(key) for key in ("title", "state", "angle") if draft.get(key)} for draft in context.get("drafts", [])],
    }


# --- the model call -------------------------------------------------------------------------------------------------------


def call_model(transport: synthesis.Transport, model: str, model_input: dict[str, Any]) -> tuple[list[Any], synthesis.Usage]:
    payload = synthesis.request_payload(model, model_input) | {"instructions": SYSTEM_PROMPT, "text": {"format": SCHEMA}, "max_output_tokens": MAXIMUM_OUTPUT_TOKENS}
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


def check_sentence(
    where: str, entry: Any, handles: dict[str, str], views: dict[str, tuple[set[str], set[str]]], excluded_ids: frozenset[str] = frozenset(),
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """(the sentence with real signal ids, its problems). Problems are reported together so a person sees all of them."""
    if not isinstance(entry, dict) or not isinstance(entry.get("text"), str) or not entry["text"].strip():
        return None, [_problem(where, "", "missing_text")]
    text, cites = entry["text"].strip(), [str(handle).strip() for handle in entry.get("cites") or []]
    problems: list[dict[str, str]] = []
    unknown = sorted({handle for handle in cites if handle not in handles})  # a signal (S) or an item (I) handle from the input
    if not cites:
        problems.append(_problem(where, text, "no_citation"))
    forbidden = sorted({handle for handle in cites if handles.get(handle) in excluded_ids})  # defence in depth: an excluded item is never offered, so never cited
    if forbidden:
        problems.append(_problem(where, text, f"cites_excluded_source_host:{','.join(forbidden)}"))
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
    if problems:
        return None, problems
    cited = list(dict.fromkeys(handles[h] for h in cites if h in handles))
    return {"text": text, "signalIds": [i for i in cited if not i.startswith("item:")], "itemIds": [i for i in cited if i.startswith("item:")]}, problems


def check_draft(item: Any, handles: dict[str, str], signals: dict[str, dict[str, Any]], views: dict[str, tuple[set[str], set[str]]], allowed_sections: list[str], excluded_ids: frozenset[str] = frozenset()) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """(the checked draft or None, the citation check record). The record is kept for failing and passing drafts alike."""
    record: dict[str, Any] = {"status": "failed", "sentences": 0, "problems": []}
    if not isinstance(item, dict):
        record["problems"].append(_problem("draft", "", "not_an_object"))
        return None, record
    problems: list[dict[str, str]] = record["problems"]
    headline, headline_problems = check_sentence("headline", item.get("headline"), handles, views, excluded_ids)
    dek, dek_problems = check_sentence("dek", item.get("dek"), handles, views, excluded_ids)
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
            checked, found = check_sentence(f"paragraph {number} sentence {position}", entry, handles, views, excluded_ids)
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
    cited_items = list(dict.fromkeys(i for entry in [headline, dek, *sentences] if entry for i in entry["itemIds"]))
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
    record.update(status="passed", signalsCited=cited, itemsCited=cited_items)
    return {
        "headline": headline, "dek": dek, "section": sections.get(section.lower(), section), "paragraphs": paragraphs, "citedSignalIds": cited, "citedItemIds": cited_items,
        "figureSignalIds": figure_ids, "figureTitle": title, "figureCaption": caption,
    }, record


def validate_drafts(raw: list[Any], handles: dict[str, str], signals: dict[str, dict[str, Any]], allowed_sections: list[str], maximum: int, excluded_hosts: Iterable[str] = ()) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(passing drafts, failing drafts with the citation check that failed them). The first ``maximum`` passing drafts are kept.
    A sentence that cites an item on one of ``excluded_hosts`` fails the check, even though such an item is never offered."""
    excluded_hosts = normalize_hosts(excluded_hosts)
    known = collect_items(list(signals.values()))
    excluded_ids = frozenset(identifier for identifier in set(handles.values()) if identifier.startswith("item:") and item_is_excluded(known.get(identifier) or {"id": identifier}, excluded_hosts))
    views = {identifier: facts_in(_grounding(signals[identifier])) for identifier in signals}
    views |= {identifier: facts_in({k: v for k, v in item_view("I0", item).items() if k != "handle"}) for identifier, item in collect_items(list(signals.values())).items()}
    valid, invalid = [], []
    for item in raw:
        draft, record = check_draft(item, handles, signals, views, allowed_sections, excluded_ids)
        if draft is None:
            title = str(((item.get("headline") or {}).get("text")) if isinstance(item, dict) and isinstance(item.get("headline"), dict) else "")[:200]
            invalid.append({"title": title, "reason": "citation_check_failed", "citationCheck": record, "draft": item})
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
        weeks = signal["windowWeeks"]
        span = "week" if weeks == 1 else f"{weeks} weeks"
        window = signal["window"]
        change = (
            f"{signal['windowCount']} items in the last {span} against {signal['baselineCount']} in the {signal['baselineWeeks']} weeks before "
            f"(about {window['expected']:g} expected; p={window['correctedPValue']:g} after correcting for {window['tested']} windows tried)"
        )
        parts = [f"{signal.get('entityKind') or 'entity'}, {change}" + (", new to the map" if signal.get("isNew") else "")]
    return f"{signal['name']}: " + "; ".join(parts)


def draft_body(draft: dict[str, Any], signals: dict[str, dict[str, Any]], figure: dict[str, Any]) -> str:
    """The marks number the cited signals first, then the cited items (the sources), so ``[3]`` may be a release."""
    numbers = {identifier: number for number, identifier in enumerate([*draft["citedSignalIds"], *draft.get("citedItemIds", [])], start=1)}
    items = collect_items(list(signals.values()))

    def marked(sentence: dict[str, Any]) -> str:
        return sentence["text"] + " " + "".join(f"[{numbers[i]}]" for i in [*sentence["signalIds"], *sentence.get("itemIds", [])])

    lines = [marked(draft["dek"]), ""]
    for paragraph in draft["paragraphs"]:
        lines += [" ".join(marked(sentence) for sentence in paragraph), ""]
    lines += [f"## Figure: {figure['title']}", "", f"{figure['caption']} Line chart, {figure['unit']}, weeks beginning {figure['x'][0]} to {figure['x'][-1]}. Source: {figure['source']}.", ""]
    lines += [f"- {entry['label']}: {', '.join(str(value) for value in entry['values'])}" for entry in figure["series"]]
    lines += ["", "## Signals cited", ""]
    for identifier in draft["citedSignalIds"]:
        signal = signals[identifier]
        link = f" ({signal['href']})" if signal.get("href") else ""
        lines.append(f"{numbers[identifier]}. {describe_signal(signal)}{link} `{identifier}`")
    if draft.get("citedItemIds"):
        lines += ["", "## Sources", ""]
        for identifier in draft["citedItemIds"]:
            item = items[identifier]
            lines.append(f"{numbers[identifier]}. {item['title']} ({item['date']}) {item.get('url') or item['path']}")
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
        "evidence": {
            "signals": len(cited), "source": f"knowledge snapshot {snapshot['asOf']} ({run['publication']}), papyrus ideas trends"[:200], "figure": figure,
            "windows": [{"signal": signal["id"], **signal["window"]} for signal in cited if signal["kind"] == "entity"],
        },
        "citedSignalIds": draft["citedSignalIds"], "citedItemIds": draft.get("citedItemIds", []),
        "citedItems": [{key: item.get(key) for key in ("id", "title", "date", "url")} for item in (collect_items(list(signals.values()))[i] for i in draft.get("citedItemIds", []))],
        "citationCheck": draft["citationCheck"],
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


def split_same_targets(
    drafts: list[dict[str, Any]], existing: list[tuple[str, str, frozenset[tuple[str, str]]]], renewed: frozenset[str] = frozenset()
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Drops a draft whose cited targets are exactly those of an earlier non-declined story draft (``existing``: kind, id, targets), unless it rests on
    an entity in ``renewed``: one the evidence test (``select_entities``) found materially stronger than its earlier draft reported."""
    kept, dropped, known = [], [], list(existing)
    for draft in drafts:
        wanted = target_key(draft["targets"])
        match = None if any(("entity", key) in wanted for key in renewed) else next((entry for entry in known if entry[2] == wanted), None)
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
        "items": len(collect_items(signals)), "itemsWithSummary": sum(1 for item in collect_items(signals).values() if item.get("summary")),
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
    idea_store: ItemStore | None = None,
    review_client: Any = None,
    model: str = synthesis.DEFAULT_MODEL,
    maximum: int = DEFAULT_MAXIMUM_DRAFTS,
    threshold: float = dedupe.DEFAULT_THRESHOLD,
    maximum_cost_usd: float = DEFAULT_MAXIMUM_COST_USD,
    dry_run: bool = False,
    now: datetime | None = None,
    fetch_text: FetchText | None = None,
    config: TrendConfig | None = None,
    excluded_hosts: Iterable[str] = (),
) -> dict[str, Any]:
    """Drafts trend stories and returns the run ledger. A dry run reads, asks the model and checks, but files, stores and requests nothing."""
    moment = now or datetime.now(timezone.utc)
    run: dict[str, Any] = {
        "runId": run_id_for(snapshot["source"], moment), "kind": "trends-run", "publication": site, "startedAt": iso(moment), "model": model,
        "store": "dry-run" if dry_run else (idea_store.kind if idea_store else "json"), "dryRun": dry_run, "private": True,
        "snapshot": {"source": snapshot["source"], "asOf": snapshot["asOf"]},
    }
    stored = json_store.ideas() if json_store else []
    proposals = idea_store.story_drafts() if idea_store else []
    documents = comparison_documents(context, stored, proposals, [])
    config = config or TrendConfig()
    earlier = [*proposals, *(idea for idea in stored if idea.get("origin") == "trend")]
    selection = select_entities(snapshot, config, earlier)
    run["selection"] = selection
    run["priorDrafts"] = selection["priorDrafts"]
    excluded_hosts = normalize_hosts(excluded_hosts)
    signals_list = build_signals(snapshot, fetch_text, config, selection, excluded_hosts)
    signals = {signal["id"]: signal for signal in signals_list}
    handles = handles_for(signals_list)
    run["inputs"] = estimate_inputs(snapshot, signals_list, context, documents)
    run["excludedSourceHosts"] = list(excluded_hosts)
    run["inputs"]["itemsExcludedByHost"] = len({i for signal in signals_list for i in signal.get("excludedItemIds", [])})
    run.update(proposed=0, invalid=[], duplicates=[], drafts=[], usage=None)
    if len(signals_list) < 2:
        run["noCall"] = f"The snapshot yields {len(signals_list)} signal(s); a trend story needs at least 2."
    else:
        model_input = build_input(snapshot, signals_list, context, maximum)
        size = len(SYSTEM_PROMPT) + len(str(model_input))
        if size > synthesis.MAXIMUM_INPUT_CHARACTERS:
            raise RunRefused(f"The input is {size} characters (limit {synthesis.MAXIMUM_INPUT_CHARACTERS}).")
        estimate = synthesis.estimate_cost_usd(model, size, MAXIMUM_OUTPUT_TOKENS)
        run["estimatedCostUsd"] = estimate
        if estimate is not None and estimate > maximum_cost_usd:
            raise RunRefused(f"Estimated cost ${estimate:.4f} is over --max-cost-usd ${maximum_cost_usd:.2f}.")
        raw, usage = call_model(transport, model, model_input)
        run["usage"] = usage.as_dict()
        run["proposed"] = len(raw)
        valid, run["invalid"] = validate_drafts(raw, handles, signals, [s["title"] for s in context.get("sections", [])], maximum, excluded_hosts)
        records = [draft_record(draft, run=run, signals=signals, snapshot=snapshot, now=moment) for draft in valid]
        similar, run["duplicates"] = dedupe.split_duplicates(records, documents, threshold)
        existing = [("proposal", row["id"], target_key(row.get("targets"))) for row in proposals if row.get("state") != "declined"]
        existing += [("draft", idea["ideaId"], target_key(idea.get("targets"))) for idea in stored if idea.get("origin") == "trend" and idea.get("state") != "declined"]
        kept, same = split_same_targets(similar, [entry for entry in existing if entry[2]], frozenset(row["key"] for row in selection["anchors"] if row.get("renewal")))
        run["duplicates"] += same
        for record in kept:
            if not dry_run:
                if idea_store:
                    try:
                        idea_store.mark(record, idea_store.file_story_draft(record))
                    except IdeaRefused as refusal:   # the editorial check found an error-severity violation: not filed
                        run["invalid"].append(refusal.as_invalid(record))
                        continue
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
        f"- Signals read: {run['inputs']['signals']}; items behind them: {run['inputs'].get('items', 0)} ({run['inputs'].get('itemsWithSummary', 0)} with a summary); left out as items from excluded source hosts (still counted in the statistics): {run['inputs'].get('itemsExcludedByHost', 0)}; drafts proposed: {run['proposed']}; passed the citation check and kept: {len(run['drafts'])}; failed the check: {len(run['invalid'])}; duplicates dropped: {len(run['duplicates'])}",
        f"- Model {run['model']}: {usage.get('inputTokens', 0)} input and {usage.get('outputTokens', 0)} output tokens, cost ${usage.get('costUsd') if usage.get('costUsd') is not None else 'unknown'}",
        "",
    ]
    for number, draft in enumerate(run["drafts"], start=1):
        figure = draft["evidence"]["figure"]
        lines += [f"## {number}. {draft['title']}", "", f"Citation check: passed ({draft['citationCheck']['sentences']} sentences, {len(draft['citedSignalIds'])} signals, {len(draft.get('citedItemIds', []))} sources). Targets: " + ", ".join(f"{t['type']}:{t['id']}" for t in draft["targets"]) + f". Figure: {figure['type']}, {len(figure['series'])} series.", "", draft["body"].rstrip(), ""]
    for heading, rows, describe in (
        ("Failed the citation check or were invalid", run["invalid"], lambda r: f"{r['title'] or '(untitled)'}: {r['reason']}" + "".join(f"\n  - {p['where']}: {p['reason']}" + (f" ({p['text']})" if p["text"] else "") for p in (r.get("citationCheck") or {}).get("problems", []))),
        ("Dropped as duplicates", run["duplicates"], lambda r: f"{r['title']}: {r['reason']}"),
    ):
        if rows:
            lines += [f"## {heading}", ""] + [f"- {describe(row)}" for row in rows] + [""]
    if run.get("noCall"):
        lines += [f"No model call was made: {run['noCall']}", ""]
    return "\n".join(lines)
