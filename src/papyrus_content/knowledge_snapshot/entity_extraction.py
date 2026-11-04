"""The entity step of the knowledge run: a plain text pass finds candidate names, Jev decides what kind of concept each one is.

1. ``find_candidates`` reads the extracted texts with no model: capitalised sequences, mixed-case and versioned names, and
   lower-case words and phrases that appear in two documents or three times. Each distinct name keeps up to three passages from
   different documents.
2. ``decide`` asks Jev one ``choice`` per distinct name (not per mention): the site's vocabulary kinds plus ``not_a_concept``, as the
   name is used in those passages. Answers are cached by name, passages, vocabulary and model, so a rerun pays only for what is new.
3. ``build_output`` writes the file ``publish-run --entities`` reads: every mention of a name Jev called a concept is a ``proposed``
   entity whose ``score`` is Jev's confidence, and every mention of a name the registry already holds is a ``resolved`` entity with
   its ``entity_key``. Jev does not propose relations, so ``relations`` is empty.

Nothing here cuts entities off by confidence: ``publish-run``'s filter and the AI review decide what is kept.
"""

from __future__ import annotations

import hashlib
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
NOT_A_CONCEPT = "not_a_concept"
NOT_A_CONCEPT_LABEL = "not a specific thing worth its own wiki page: an ordinary word or phrase, a code identifier or variable, a heading, a citation, a sentence fragment"
PASSAGES = 3  # passages from different documents that show how a name is used
PASSAGE_MARGIN = 200  # characters on each side of the first mention in a document
SCHEMA_VERSION = 1

# A name is on one line: its words are joined by spaces or tabs, never by a line break.
NAMED = re.compile(r"\b[A-Z][\w+.\-]*[\w+](?:(?:[ \t]+(?:of|for|and|the|in|on))?[ \t]+[A-Z0-9][\w+.\-]*[\w+]){0,5}")
MIXED = re.compile(r"\b[a-z]+[A-Z][\w\-]*\b|\b[A-Za-z]+-\d[\w.\-]*\b")
# A lower-case word starts and ends at a word edge: never inside a capitalised word (``ganization`` of ``Organization``).
WORD = re.compile(r"(?<![A-Za-z0-9_\-])[a-z][a-z\-]*[a-z](?![A-Za-z0-9_])")
PHRASE = re.compile(r"[a-z\-]+(?: [a-z\-]+)*")


class ExtractionError(ValueError):
    pass


# -- 1. candidates ----------------------------------------------------------------------------------------------------
def scan_mentions(documents: Mapping[str, str], stop_words: Iterable[str]) -> tuple[dict[str, list[tuple[str, int, int, str]]], Counter]:
    """The finder: every place in the texts a name could be, by its shape, with no model. ``({case-folded name: [(item_id, start,
    end, text)]}, count of each lower-case word)``. Deciding which of them are worth asking about is ``find_candidates``'s job."""
    stop = frozenset(stop_words)
    seen: dict[str, list[tuple[str, int, int, str]]] = defaultdict(list)
    lower_words: Counter = Counter()
    for item_id, text in documents.items():
        words = [(m.group(), m.start(), m.end()) for m in WORD.finditer(text)]
        lower_words.update(word for word, _a, _b in words)
        for pattern in (NAMED, MIXED):
            for match in pattern.finditer(text):
                seen[match.group().casefold()].append((item_id, match.start(), match.end(), match.group()))
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
def criteria_of(vocabulary: Mapping[str, Any]) -> dict[str, str]:
    """The kinds a name may be: the vocabulary's ``entity_kinds`` (key to label) and ``not_a_concept``."""
    criteria = {str(entry["key"]): str(entry.get("label") or entry["key"]) for entry in vocabulary.get("entity_kinds") or () if isinstance(entry, Mapping) and entry.get("key")}
    if not criteria:
        raise ExtractionError("The vocabulary has no entity_kinds with keys.")
    if NOT_A_CONCEPT in criteria:
        raise ExtractionError(f"{NOT_A_CONCEPT!r} is the extractor's own answer; it cannot be a kind in the vocabulary.")
    criteria[NOT_A_CONCEPT] = NOT_A_CONCEPT_LABEL
    return criteria


def cache_key(name: str, passages: list[str], criteria: Mapping[str, str], model: str) -> str:
    return hashlib.sha256(json.dumps([name, passages, sorted(criteria.items()), model], ensure_ascii=False).encode("utf-8")).hexdigest()


class JevClient:
    """One ``choice`` question per name. ``ask`` returns the answer, or None when Jev could not be reached after the retries."""

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

    def ask(self, name: str, passages: list[str], criteria: Mapping[str, str], publication: str) -> dict | None:
        body = {
            "model": self.model,
            "state": {"publication": f"the {publication} publication, building a wiki of concepts", "name": name, "passages": passages},
            "questions": {"kind": {"type": "choice", "instructions": "As the name is used in these passages, which kind of wiki concept is it?", "criteria": dict(criteria)}},
        }
        for attempt in range(self.attempts):
            try:
                response = self.session.post(self.url, json=body, timeout=30)
                if response.status_code == 200:
                    answer = response.json()
                    kind = answer["answers"]["kind"]
                    return {"choice": kind["choice"], "confidence": kind["confidence"], "usage": answer.get("usage"), "model": answer.get("model") or self.model}
                if response.status_code not in self.RETRY:
                    self.failures[response.status_code] += 1
                    return None
            except (OSError, KeyError, ValueError):  # a network error (requests' errors are OSErrors) or an answer of another shape
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
    criteria: Mapping[str, str],
    ask: Callable[[str, list[str]], dict | None],
    *,
    model: str,
    cache_path: Path,
    workers: int = 12,
) -> tuple[dict[str, dict], list[dict], int]:
    """``(decisions by candidate key, usage of the calls made, names left undecided)``. Cached answers are not asked again; every new
    answer is appended to the cache as it arrives, so a run that stops half way keeps what it paid for."""
    cache = read_cache(cache_path)
    keys = {key: cache_key(candidate["name"], candidate["contexts"], criteria, model) for key, candidate in candidates.items()}
    decisions = {key: cache[digest] for key, digest in keys.items() if digest in cache}
    todo = [key for key in candidates if key not in decisions]
    usage: list[dict] = []
    if todo:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("a", encoding="utf-8") as out, ThreadPoolExecutor(workers) as pool:
            for key, answer in zip(todo, pool.map(lambda key: ask(candidates[key]["name"], candidates[key]["contexts"]), todo)):
                if answer is None:
                    continue
                row = {"key": keys[key], "choice": answer["choice"], "confidence": answer["confidence"], "model": answer["model"]}
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
    """The file ``publish-run --entities`` reads. Mentions of names Jev has not answered for are left out."""
    by_item: dict[str, list[tuple[int, int, str, str, float, str | None]]] = defaultdict(list)
    for item_id, text in documents.items():
        for start, end, written, key, kind in matcher.find(text):
            by_item[item_id].append((start, end, written, kind, 1.0, key))
    resolved_spans = {item_id: [(start, end) for start, end, *_rest in mentions] for item_id, mentions in by_item.items()}
    for key, decision in decisions.items():
        if decision["choice"] == NOT_A_CONCEPT or matcher.knows(candidates[key]["name"]):
            continue
        for item_id, start, end, written in candidates[key]["mentions"]:
            if any(a <= start and end <= b for a, b in resolved_spans.get(item_id, ())):  # inside the mention of an accepted entity
                continue
            by_item[item_id].append((start, end, written, decision["choice"], decision["confidence"], None))
    items = []
    for item_id in sorted(documents):
        entities = [
            {"id": f"e{number}", "kind": kind, "text": written, "state": "resolved" if entity_key else "proposed", "entity_key": entity_key, "span": {"start": start, "end": end}, "score": score}
            for number, (start, end, written, kind, score, entity_key) in enumerate(sorted(by_item[item_id], key=lambda mention: mention[:3]), 1)
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
