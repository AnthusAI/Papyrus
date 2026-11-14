"""The entity step of the knowledge run: a plain text pass finds candidate names, Jev decides which are real and what kind they are.

1. ``find_candidates`` reads the extracted texts with no model: capitalised sequences, mixed-case and versioned names, and
   lower-case words and phrases that appear in two documents or three times. Reference lists and bibliographies are not read, a
   citation number stuck to a name is cut off, a name is never joined across ``and`` (unless the whole is one proper name), a name that
   only ever appears as a whole section heading, at any level (a document's title, ``Materials and Methods``), is not a candidate, and
   neither is a date or a quantity (``October 22 and 23``, ``10 Hz``, ``3.5``). Each distinct name keeps up to three passages from
   different documents.
2. ``decide`` asks Jev three questions per distinct name (not per mention) in one request: is it a real thing (a yes/no answer that
   files it or drops it), which of the vocabulary's kinds is it, and does a reader of the publication need a page of its own for it
   (a second yes/no answer). Answers are cached by name, passages, the question text, the publication and the model, so a rerun
   pays only for what is new.
3. ``build_output`` writes the file ``publish-run --entities`` reads: every mention of a real name is a ``proposed`` entity whose
   ``score`` is Jev's confidence that it is real, with the page answer beside it (``page_score``, ``page_answer``), and every mention
   of a name the registry already holds is a ``resolved`` entity with its ``entity_key``. A name in only one document outside the
   reference lists has page score 0 whatever Jev said: that is decided here in code, not asked in the prompt. Jev does not propose
   relations, so ``relations`` is empty.

Nothing here cuts entities off by confidence: ``publish-run``'s filter and the AI review decide what is kept.
"""

from __future__ import annotations

import hashlib
import calendar
import json
import re
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .registry import alias_identity

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-1.13.0"
PUBLICATION_PURPOSE = "building a wiki of concepts"
PASSAGES = 3  # passages from different documents that show how a name is used
PASSAGE_MARGIN = 200  # characters on each side of the first mention in a document
FILED_AT = 0.5  # the boundary of a yes/no answer: a name Jev does not call real is dropped; the confidence itself is never cut off
SCHEMA_VERSION = 1

# A name is on one line: its words are joined by spaces or tabs, never by a line break. An apostrophe directly before a capital is
# inside the name (O'Connell); a possessive 's is not. ``and`` joins words here, and ``_pieces`` takes the joined text apart again.
TOKEN = r"[A-Z](?:[\w+.\-]|['\u2019](?=[A-Z]))*[\w+]"
TOKEN_OR_NUMBER = r"[A-Z0-9](?:[\w+.\-]|['\u2019](?=[A-Z]))*[\w+]"
NAMED = re.compile(r"\b" + TOKEN + r"(?:(?:[ \t]+(?:of|for|and|the|in|on))?[ \t]+" + TOKEN_OR_NUMBER + r"){0,5}")
MIXED = re.compile(r"\b[a-z]+[A-Z][\w\-]*\b|\b[A-Za-z]+-\d[\w.\-]*\b")
# A lower-case word starts and ends at a word edge: never inside a capitalised word (``ganization`` of ``Organization``).
WORD = re.compile(r"(?<![A-Za-z0-9_\-])[a-z][a-z\-]*[a-z](?![A-Za-z0-9_])")
PHRASE = re.compile(r"[a-z\-]+(?: [a-z\-]+)*")
CONNECTORS = frozenset({"of", "for", "and", "the", "in", "on"})
# One proper name that contains ``and``: a head noun and a connector, then words, then ``and`` and a single capitalised word
# (Center for Democracy and Technology). Two names joined by ``and`` (Facebook and Instagram, University of Zurich and ETH Zurich)
# have no connector before the ``and`` or more than one plain word after it.
ONE_NAME_WITH_AND = re.compile(r"[A-Z]\S*(?:[ \t]+(?!and\b)\S+)*?[ \t]+(?:of|for|on|in)(?:[ \t]+(?!and\b)\S+)+?[ \t]+and[ \t]+[A-Z][a-z]+")
REFERENCE_HEADING = re.compile(r"(?im)^[ \t]*(#{1,6})?[ \t]*(references|bibliography|works cited|literature cited)[ \t]*:?[ \t]*$")
HEADING = re.compile(r"(?m)^(#{1,6})[ \t]+\S")
STUCK_NUMBER = re.compile(r"^(.*[A-Za-z])(\d{2,3})$")
GLUED_WORD = re.compile(r"\b[A-Za-z][\w\-]*[A-Za-z]\d{2,3}\b")


# A date or a quantity is not a name: every word of it is a number, a month or weekday, a connector or a unit, and at least one is a number.
# The calendar's own names are used (not a list kept here); a unit is a base unit with an optional SI prefix, so ``kHz`` and ``GB`` are units and
# ``GPT`` is not (``GPT 4`` is a name). A bare unit or month with no number beside it (``May``, ``ML``) is left to the other filters.
NUMBER = re.compile(r"[+\-\u00b1~]?\d[\d.,:/\u2013\-]*(?:%|(?:st|nd|rd|th))?")
UNIT = re.compile(r"[YZEPTGMkhdcmµunpfa]?(?:Hz|B|W|V|A|J|N|K|Pa|s|m|g|l|\u03a9)|[%\u00b0]")
AFTER_NUMBER = re.compile(r"(?:^|\s)" + NUMBER.pattern + r"\s*$")
CALENDAR_WORDS = frozenset(word.casefold() for word in (*calendar.month_name, *calendar.month_abbr, *calendar.day_name, *calendar.day_abbr) if word)


def is_quantity(text: str) -> bool:
    """A date (``October 22 and 23``), a number (``3.5``, ``2020-2024``) or a number with units (``10 Hz and 10``), and nothing else."""
    words = [word.strip(",;:.()") for word in text.split()]
    words = [word for word in words if word]
    if not words or not any(NUMBER.fullmatch(word) for word in words):
        return False
    return all(NUMBER.fullmatch(word) or UNIT.fullmatch(word) or word.casefold() in CALENDAR_WORDS or word.casefold() in CONNECTORS or word.casefold() == "to" for word in words)


class ExtractionError(ValueError):
    pass


# -- 1. candidates ----------------------------------------------------------------------------------------------------
def reference_spans(text: str) -> list[tuple[int, int]]:
    """Where the reference lists are: from a References or Bibliography heading to the next heading of the same or a higher level, or
    the end of the text. Names in them are citations, not uses of the name."""
    spans = []
    for match in REFERENCE_HEADING.finditer(text):
        level = len(match.group(1) or "") or 7
        end = next((heading.start() for heading in HEADING.finditer(text, match.end()) if len(heading.group(1)) <= level), len(text))
        spans.append((match.start(), end))
    return spans


def _pieces(written: str, *, citations: int, glued: Counter) -> list[tuple[int, int]]:
    """The names inside one match of the name patterns, as offsets into it. ``and`` ends a name unless the whole is one proper name,
    and a citation number stuck to a word ends the name there: two or three digits after a letter, no larger than the number of entries
    in the document's reference lists, and a glued form seen at most twice in the document (``Qwen3`` repeats, a citation does not)."""
    keep_and = bool(ONE_NAME_WITH_AND.fullmatch(written))
    pieces: list[tuple[int, int]] = []
    current: list[tuple[str, int, int]] = []

    def close() -> None:
        while current and current[0][0] in CONNECTORS:
            current.pop(0)
        while current and current[-1][0] in CONNECTORS:
            current.pop()
        if current:
            pieces.append((current[0][1], current[-1][2]))
        current.clear()

    for token in re.finditer(r"\S+", written):
        word = token.group()
        stuck = STUCK_NUMBER.match(word) if citations else None
        if word == "and" and not keep_and:
            close()
        elif stuck and 10 <= int(stuck.group(2)) <= citations and glued[word] <= 2 and len(stuck.group(1)) >= 2:
            current.append((stuck.group(1), token.start(), token.start() + len(stuck.group(1))))
            close()
        else:
            current.append((word, token.start(), token.end()))
    close()
    return pieces


def scan_mentions(documents: Mapping[str, str], stop_words: Iterable[str]) -> tuple[dict[str, list[tuple[str, int, int, str]]], Counter]:
    """The finder: every place in the texts a name could be, by its shape, with no model, outside the reference lists. ``({case-folded
    name: [(item_id, start, end, text)]}, count of each lower-case word)``. Deciding which of them are worth asking about is
    ``find_candidates``'s job."""
    stop = frozenset(stop_words)
    seen: dict[str, list[tuple[str, int, int, str]]] = defaultdict(list)
    lower_words: Counter = Counter()
    for item_id, text in documents.items():
        references = reference_spans(text)
        counted = sum(sum(1 for line in text[a:b].splitlines() if line.strip()) - 1 for a, b in references)
        glued = Counter(GLUED_WORD.findall(text)) if counted else Counter()

        def outside(at: int) -> bool:
            return not any(a <= at < b for a, b in references)

        words = [(m.group(), m.start(), m.end()) for m in WORD.finditer(text) if outside(m.start())]
        lower_words.update(word for word, _a, _b in words)
        for pattern in (NAMED, MIXED):
            for match in pattern.finditer(text):
                pieces = _pieces(match.group(), citations=counted, glued=glued)
                written = [match.group()[a:b] for a, b in pieces]
                quantity = [is_quantity(piece) for piece in written]
                for (a, b), piece, number, at in zip(pieces, written, quantity, range(len(pieces))):
                    # ``Hz`` in ``Hz and 10`` or ``10 Hz``, ``June`` in ``12th June``: a unit or a calendar word that belongs to a number
                    unit_of_a_number = (bool(UNIT.fullmatch(piece)) or piece.casefold() in CALENDAR_WORDS) and (
                        any(quantity[max(at - 1, 0):at + 2]) or (at == 0 and bool(AFTER_NUMBER.search(text[max(match.start() + a - 24, 0):match.start() + a])))
                    )
                    if number or unit_of_a_number:
                        continue
                    if outside(match.start() + a):
                        seen[match.group()[a:b].casefold()].append((item_id, match.start() + a, match.start() + b, match.group()[a:b]))
        for size in (1, 2, 3):  # lower-case words and phrases, unbroken by punctuation and with no stop word at either edge
            for at in range(len(words) - size + 1):
                group = words[at:at + size]
                start, end = group[0][1], group[-1][2]
                phrase = text[start:end]
                if size > 1 and not PHRASE.fullmatch(phrase):
                    continue
                if group[0][0] in stop or group[-1][0] in stop or (size == 1 and len(phrase) < 6):
                    continue
                seen[phrase.casefold()].append((item_id, start, end, phrase))
    return seen, lower_words


def _is_section_heading(text: str, start: int, end: int) -> bool:
    """The mention is the whole of a heading line, or one of the parts of a heading that lists them (``Materials and Methods``), at any level: the
    name of a section, which is not a thing to file."""
    begin = text.rfind("\n", 0, start) + 1
    stop = text.find("\n", end)
    line = text[begin:len(text) if stop < 0 else stop]
    heading = re.match(r"#{1,6}[ \t]+(.*)$", line)
    if not heading:
        return False
    written = text[start:end].casefold()
    parts = re.split(r"\s*(?:,|&|\band\b)\s*", heading.group(1).strip().rstrip(".:").casefold())
    return written in [part.strip() for part in parts if part.strip()]


def find_candidates(documents: Mapping[str, str], stop_words: Iterable[str]) -> dict[str, dict]:
    """``{key: {name, contexts, mentions}}`` for every distinct name (key: the case-folded name). A mention is
    ``(item_id, start, end, text)``; ``contexts`` are up to ``PASSAGES`` passages from different documents."""
    stop = frozenset(stop_words)
    seen, lower_words = scan_mentions(documents, stop)
    found: dict[str, dict] = {}
    for key, mentions in seen.items():
        if key.isdigit() or len(key) < 2:
            continue
        words = key.split()
        documents_seen = {mention[0] for mention in mentions}
        lower = all(mention[3].islower() for mention in mentions)
        if lower and len(documents_seen) < 2 and len(mentions) < 3:  # a once-off lower-case phrase is no name
            continue
        if len(words) == 1 and key in stop:
            continue
        capitalised = sum(1 for mention in mentions if not mention[3].islower())
        if not lower and len(words) == 1 and key.isalpha() and lower_words[key] > capitalised:  # a word capitalised only at a sentence start
            continue
        mentions = sorted(set(mentions), key=lambda mention: (mention[0], mention[1]))
        if all(_is_section_heading(documents[item_id], start, end) for item_id, start, end, _text in mentions):
            continue
        if all(is_quantity(mention[3]) for mention in mentions):
            continue
        found[key] = {"name": Counter(mention[3] for mention in mentions).most_common(1)[0][0], "contexts": _passages(documents, mentions), "mentions": mentions}
    return found


def _passages(documents: Mapping[str, str], mentions: list[tuple[str, int, int, str]]) -> list[str]:
    passages: list[str] = []
    used: set[str] = set()
    for item_id, start, end, _text in mentions:
        if item_id in used:
            continue
        used.add(item_id)
        text = documents[item_id]
        begin = max(text.rfind(". ", 0, start), text.rfind("\n", 0, start)) + 1
        stop = min(at for at in (text.find(". ", end), text.find("\n", end), len(text)) if at >= 0)
        passages.append(text[max(begin, start - PASSAGE_MARGIN):min(stop + 1, end + PASSAGE_MARGIN)].strip())
        if len(passages) == PASSAGES:
            break
    return passages


# -- the registry -----------------------------------------------------------------------------------------------------
class RegistryMatcher:
    """Finds the names the registry already holds, so their mentions resolve to the accepted entity without asking Jev.

    Names compare as ``registry.alias_identity`` does (case folded, punctuation and spacing ignored), so ``GPT 4`` is ``GPT-4``. A
    single alphabetic word must match its written case, so an entity named ``Go`` does not take every ``go``."""

    def __init__(self, registry: Iterable[Mapping[str, Any]]) -> None:
        self.entries: dict[str, tuple[str, str]] = {}  # identity -> (entity key, kind)
        exact: list[str] = []
        loose: list[str] = []
        for entry in registry:
            for alias in entry.get("aliases") or ():
                identity = alias_identity(alias)
                if not identity or identity in self.entries:
                    continue
                self.entries[identity] = (str(entry["key"]), str(entry["kind"]))
                if alias.isalpha():
                    exact.append(re.escape(alias))
                else:
                    loose.append(r"[\W_]+".join(re.escape(word) for word in identity.split()))
        edge = r"(?<![A-Za-z0-9])(?:{})(?![A-Za-z0-9])"
        self._exact = re.compile(edge.format("|".join(sorted(exact, key=len, reverse=True)))) if exact else None
        self._loose = re.compile(edge.format("|".join(sorted(loose, key=len, reverse=True))), re.IGNORECASE) if loose else None

    def find(self, text: str) -> list[tuple[int, int, str, str, str]]:
        """``(start, end, text, entity key, kind)`` of every mention of a registry name, without overlaps (the longer name wins)."""
        matches = []
        for pattern in (self._exact, self._loose):
            for match in pattern.finditer(text) if pattern else ():
                entity = self.entries.get(alias_identity(match.group()))
                if entity:
                    matches.append((match.start(), match.end(), match.group(), *entity))
        matches.sort(key=lambda found: (found[0], -(found[1] - found[0])))
        kept: list[tuple[int, int, str, str, str]] = []
        for found in matches:
            if not kept or found[0] >= kept[-1][1]:
                kept.append(found)
        return kept

    def knows(self, name: str) -> bool:
        return alias_identity(name) in self.entries


# -- 2. Jev -----------------------------------------------------------------------------------------------------------
KIND_INSTRUCTIONS = "As the name is used in these passages, which kind of wiki concept is it?"
REAL_QUESTION = {
    "type": "noul",
    "instructions": "Is this name a specific, established thing, such as a named person, organisation, model, dataset, method or tool, or a recognised research concept, as it is used in the passages?",
    "criteria": {
        "true": "It names one particular thing or an established concept that people refer to by this name.",
        "false": "It is an ordinary word or phrase, a code identifier, a heading, a citation string, a sentence fragment, or a generic description.",
    },
}
PAGE_QUESTION = {
    "type": "noul",
    "instructions": "Would a reader of this publication look this name up, so that it deserves a wiki page of its own?",
    "criteria": {
        "true": "It is a subject the publication explains or returns to, or a well-known thing a reader would want explained, and the passages say what it is or does. A common word counts only when the documents discuss it as a specific concept.",
        "false": "It is mentioned in passing or as one example among several, is a person or paper cited once, is a minor detail, is not a real thing, or is a common word or generic phrase used in its ordinary sense.",
    },
}


def criteria_of(vocabulary: Mapping[str, Any]) -> dict[str, Any]:
    """The kinds a real name may be: the vocabulary's ``entity_kinds``, key to description. A kind with ``what`` (and optionally
    ``not_for``) is described to Jev by both; one with only a ``label`` by the label."""
    criteria: dict[str, Any] = {}
    for entry in vocabulary.get("entity_kinds") or ():
        if isinstance(entry, Mapping) and entry.get("key"):
            what = entry.get("what")
            criteria[str(entry["key"])] = {"what": str(what), "not_for": str(entry.get("not_for") or "")} if what else str(entry.get("label") or entry["key"])
    if not criteria:
        raise ExtractionError("The vocabulary has no entity_kinds with keys.")
    return criteria


def describe_publication(vocabulary: Mapping[str, Any]) -> str:
    """How Jev is told what the publication is. Set ``description`` in the site's vocabulary (``a publication about ...``); without
    it the publication's key is used."""
    description = str(vocabulary.get("description") or "").strip() or f"the {vocabulary.get('publication') or 'knowledge'} publication"
    return f"{description}, {PUBLICATION_PURPOSE}"


def questions_for(criteria: Mapping[str, Any]) -> dict[str, Any]:
    return {"real": REAL_QUESTION, "kind": {"type": "choice", "instructions": KIND_INSTRUCTIONS, "criteria": dict(criteria)}, "page": PAGE_QUESTION}


def cache_key(name: str, passages: list[str], questions: Mapping[str, Any], publication: str, model: str) -> str:
    return hashlib.sha256(json.dumps([name, passages, questions, publication, model], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


class JevClient:
    """Three questions per name in one request. ``ask`` returns the answers, or None when Jev could not be reached after the retries."""

    RETRY = frozenset({408, 429, 500, 502, 503, 504})

    def __init__(self, api_key: str, *, model: str = JEV_MODEL, url: str = JEV_URL, session: Any = None, sleep: Callable[[float], None] = time.sleep, attempts: int = 6) -> None:
        if not api_key:
            raise ExtractionError("No Jev key: set TYPESAFE_API_KEY (the cloud run reads it from SSM and passes it in the environment).")
        if session is None:
            import requests  # noqa: PLC0415

            session = requests.Session()
        self.model, self.url, self.session, self.sleep, self.attempts = model, url, session, sleep, attempts
        self.session.headers["Authorization"] = f"Bearer {api_key}"
        self.failures: Counter = Counter()

    def ask(self, name: str, passages: list[str], criteria: Mapping[str, Any], publication: str) -> dict | None:
        """``{real, choice, kind_confidence, page, usage, model}``: ``real`` and ``page`` are Jev's probabilities of a yes."""
        body = {"model": self.model, "state": {"publication": publication, "name": name, "passages": passages}, "questions": questions_for(criteria)}
        for attempt in range(self.attempts):
            try:
                response = self.session.post(self.url, json=body, timeout=60)
                if response.status_code == 200:
                    answer = response.json()
                    answers = answer["answers"]
                    return {
                        "real": float(answers["real"]["noul"]),
                        "choice": answers["kind"]["choice"],
                        "kind_confidence": answers["kind"]["confidence"],
                        "page": float(answers["page"]["noul"]),
                        "usage": answer.get("usage"),
                        "model": answer.get("model") or self.model,
                    }
                if response.status_code not in self.RETRY:
                    self.failures[response.status_code] += 1
                    return None
            except (OSError, KeyError, ValueError, TypeError):  # a network error (requests' errors are OSErrors) or an answer of another shape
                pass
            self.sleep(2 ** attempt)
        self.failures["gave up"] += 1
        return None


def read_cache(path: Path) -> dict[str, dict]:
    cache: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                cache[row["key"]] = row
    return cache


def decide(
    candidates: Mapping[str, dict],
    criteria: Mapping[str, Any],
    ask: Callable[[str, list[str]], dict | None],
    *,
    publication: str,
    model: str,
    cache_path: Path,
    workers: int = 12,
) -> tuple[dict[str, dict], list[dict], int]:
    """``(decisions by candidate key, usage of the calls made, names left undecided)``. Cached answers are not asked again; every new
    answer is appended to the cache as it arrives, so a run that stops half way keeps what it paid for."""
    cache = read_cache(cache_path)
    questions = questions_for(criteria)
    keys = {key: cache_key(candidate["name"], candidate["contexts"], questions, publication, model) for key, candidate in candidates.items()}
    decisions = {key: cache[digest] for key, digest in keys.items() if digest in cache}
    todo = [key for key in candidates if key not in decisions]
    usage: list[dict] = []
    if todo:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("a", encoding="utf-8") as out, ThreadPoolExecutor(workers) as pool:
            for key, answer in zip(todo, pool.map(lambda key: ask(candidates[key]["name"], candidates[key]["contexts"]), todo)):
                if answer is None:
                    continue
                row = {"key": keys[key], **{field: answer[field] for field in ("real", "choice", "kind_confidence", "page")}, "model": answer["model"]}
                out.write(json.dumps(row) + "\n")
                out.flush()
                decisions[key] = row
                tokens = answer.get("usage") or {}
                call = {"model": answer["model"], "promptTokens": int(tokens.get("input_tokens") or 0), "completionTokens": int(tokens.get("output_tokens") or 0)}
                usage.append(call if tokens else {**call, "usageMissing": True})
    return decisions, usage, len([key for key in candidates if key not in decisions])


# -- 3. the output ----------------------------------------------------------------------------------------------------
def build_output(
    documents: Mapping[str, str],
    candidates: Mapping[str, dict],
    decisions: Mapping[str, dict],
    matcher: RegistryMatcher,
    vocabulary: Mapping[str, Any],
    *,
    model: str,
) -> dict:
    """The file ``publish-run --entities`` reads. Mentions of names Jev has not answered for are left out, and so are names it does not
    call real. Each proposed entity carries the page answer: Jev's probability that the name deserves a page of its own and whether
    that is a yes, both 0 for a name in only one document outside the reference lists (decided here, not asked in the prompt), and
    ``page_documents``, the number of documents the name is in (null on a resolved entity), which is shown beside the score and never blended into it."""
    by_item: dict[str, list[tuple[int, int, str, str, float, str | None, float | None, int | None]]] = defaultdict(list)
    for item_id, text in documents.items():
        for start, end, written, key, kind in matcher.find(text):
            by_item[item_id].append((start, end, written, kind, 1.0, key, None, None))
    resolved_spans = {item_id: [(start, end) for start, end, *_rest in mentions] for item_id, mentions in by_item.items()}
    for key, decision in decisions.items():
        if decision["real"] < FILED_AT or matcher.knows(candidates[key]["name"]):
            continue
        found_in = len({mention[0] for mention in candidates[key]["mentions"]})
        page = 0.0 if found_in < 2 else decision["page"]
        for item_id, start, end, written in candidates[key]["mentions"]:
            if any(a <= start and end <= b for a, b in resolved_spans.get(item_id, ())):  # inside the mention of an accepted entity
                continue
            by_item[item_id].append((start, end, written, decision["choice"], decision["real"], None, page, found_in))
    items = []
    for item_id in sorted(documents):
        entities = [
            {
                "id": f"e{number}", "kind": kind, "text": written, "state": "resolved" if entity_key else "proposed", "entity_key": entity_key,
                "span": {"start": start, "end": end}, "score": score, "page_score": page, "page_answer": None if page is None else page >= FILED_AT,
                "page_documents": documents,
            }
            for number, (start, end, written, kind, score, entity_key, page, documents) in enumerate(sorted(by_item[item_id], key=lambda mention: mention[:3]), 1)
        ]
        items.append({"item_id": item_id, "entities": entities, "relations": []})
    resolved = sum(1 for item in items for entity in item["entities"] if entity["state"] == "resolved")
    total = sum(len(item["entities"]) for item in items)
    return {
        "schema_version": SCHEMA_VERSION,
        "backend": {"id": "jev", "model": model},
        "vocabulary": {"publication": vocabulary.get("publication"), "version": vocabulary.get("version"), "hash": hashlib.sha256(json.dumps(vocabulary, sort_keys=True).encode("utf-8")).hexdigest()},
        "items": items,
        "summary": {"entities": total, "items": len(items), "proposed": total - resolved, "resolved": resolved, "relations": 0},
    }
