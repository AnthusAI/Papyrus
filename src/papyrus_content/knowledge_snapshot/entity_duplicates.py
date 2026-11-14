"""Catch a second entity for a thing the map already has, before it is made or accepted.

The extractor meets one thing under several names (``The NTSB``, ``National Transportation Safety Board``; ``Musk``, ``Elon Musk``), and the registry
only resolves a name it already holds. This is the check both ways in use: ``publish-run`` asks it before it makes a node from an extractor
candidate, and the AI review asks it before it accepts a generated node.

``find_duplicate(kind, name, nodes)`` compares a candidate with the accepted entities of the same kind by the rules in
``data/entity-duplicate-rules.yml`` (the list is data: order, kinds and action of each rule; the checks themselves are the functions below):

* ``same_name``: equal under ``registry.alias_identity`` (case, punctuation and spacing ignored);
* ``leading_word``: equal once a leading article or conjunction is taken off (``The``, ``A``, ``An``, ``And``, repeatedly: ``And the UK ...``);
* ``acronym``: a single upper case token that is the initials of the other name (``MCP``, ``Model Context Protocol``);
* ``surname``: a single word that is the last word of exactly one full-name person of the kind (``Musk``, ``Elon Musk``);
* ``containment``: one name is a whole-word start or end of the other (``Redwood``, ``Redwood Research``), for organizations.

A hit says what to do: ``resolve`` (the same thing under another spelling: link the mention to the entity and add the name as an alias) or
``propose`` (it looks the same; a person decides). Nothing is merged here; ``entities merge`` is the command that merges two entities.

Pure: rows in, a hit or ``None`` out. A rejected or superseded node is never a target. Names of different kinds are never duplicates (a model and the
lab that made it share a name); that is an ambiguity, which ``entities add`` tags with the disambiguation concept.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..ids import hash_short
from .keys import kind_key
from .registry import alias_identity

RULES_FILE = Path(__file__).resolve().parents[1] / "data" / "entity-duplicate-rules.yml"
RESOLVE, PROPOSE = "resolve", "propose"
ACTIONS = (RESOLVE, PROPOSE)
ACRONYM_TOKEN = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")
PROPOSAL_MARKER = "papyrus-entity-duplicate@1"
PROPOSAL_KIND_NEW_ALIAS = "entity-alias-edit"  # a candidate name that is not an entity yet: add it to the existing entity as an alias
PROPOSAL_KIND_MERGE = "merge-graph-entity"  # a generated entity that duplicates an accepted one: merge it into the accepted one
PROPOSAL_DOMAIN = "graph"
STATUS_PROPOSED = "proposed"


@dataclass(frozen=True)
class Rule:
    id: str
    check: str
    action: str
    kinds: frozenset[str] | None
    description: str


@dataclass(frozen=True)
class Rules:
    leading_words: frozenset[str]
    connectors: frozenset[str]
    rules: tuple[Rule, ...]


@dataclass(frozen=True)
class DuplicateHit:
    """``candidate`` is a duplicate of ``node``: ``rule`` fired on ``candidate_name`` against ``matched_name``."""

    rule: str
    action: str
    node: Mapping[str, Any]
    candidate_name: str
    matched_name: str
    description: str

    @property
    def key(self) -> str:
        return str(self.node.get("nodeKey") or self.node.get("id"))

    def sentence(self) -> str:
        return f"{self.candidate_name!r} looks like {self.matched_name!r} ({self.key}): {self.description}"


class RulesError(ValueError):
    pass


def parse_rules(body: Any) -> Rules:
    """The rules of a parsed rules file; a malformed file is an error, never a silent gap in the check."""
    if not isinstance(body, dict) or not isinstance(body.get("rules"), list):
        raise RulesError("The duplicate rules file needs a `rules` list.")
    rules = []
    for entry in body["rules"]:
        if not isinstance(entry, dict) or entry.get("check") not in CHECKS or entry.get("action") not in ACTIONS or not entry.get("id"):
            raise RulesError(f"A duplicate rule needs an id, a known check ({', '.join(CHECKS)}) and an action ({', '.join(ACTIONS)}): {entry!r}")
        kinds = entry.get("kinds")
        rules.append(
            Rule(
                id=str(entry["id"]),
                check=entry["check"],
                action=entry["action"],
                kinds=frozenset(kind_key(str(kind)) for kind in kinds) if kinds else None,
                description=str(entry.get("description") or entry["id"]),
            )
        )
    return Rules(
        leading_words=frozenset(str(word).casefold() for word in body.get("leading_words") or ()),
        connectors=frozenset(str(word).casefold() for word in body.get("connectors") or ()),
        rules=tuple(rules),
    )


@lru_cache(maxsize=1)
def default_rules() -> Rules:
    return parse_rules(yaml.safe_load(RULES_FILE.read_text(encoding="utf-8")))


# -- names ------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Name:
    """A name read once: as written, its words (``registry.alias_identity``), the words without leading articles, and the tokens as written."""

    text: str
    words: tuple[str, ...]
    plain: tuple[str, ...]
    tokens: tuple[str, ...]

    @property
    def acronym(self) -> str | None:
        """The lower case form of a single upper case token (``NTSB``), else ``None``: the case is how an acronym is told from a word."""
        return self.tokens[0].casefold() if len(self.tokens) == 1 and ACRONYM_TOKEN.match(self.tokens[0]) else None

    def initials(self, rules: Rules) -> set[str]:
        """What a name of several words can be abbreviated to: the initials of every word, and of every word that is not a connector."""
        return {
            "".join(word[0] for word in kept)
            for kept in (self.plain, [word for word in self.plain if word not in rules.connectors])
            if len(kept) >= 2
        }


def read_name(name: str, rules: Rules) -> Name:
    spoken = tuple(alias_identity(name).split())
    plain = list(spoken)
    while len(plain) > 1 and plain[0] in rules.leading_words:
        plain.pop(0)
    tokens = [token for token in re.split(r"[\s\-/]+", name.strip()) if token]
    while len(tokens) > 1 and tokens[0].casefold() in rules.leading_words:
        tokens.pop(0)
    return Name(" ".join(name.split()), spoken, tuple(plain), tuple(tokens))


def names_of(node: Mapping[str, Any]) -> list[str]:
    return [" ".join(str(name).split()) for name in [node.get("displayName"), *(node.get("aliases") or ())] if name and str(name).strip()]


def is_target(node: Mapping[str, Any]) -> bool:
    return node.get("versionState", "current") == "current" and node.get("status") == "accepted"


# -- the checks. Each says which lookup keys a name is filed and searched under (so a candidate is compared with a few names, not with all of them)
# and whether two names are one thing. ``lookup`` returns the keys under which the OTHER names that could match are filed.
class Check:
    def file_under(self, name: Name, rules: Rules) -> Iterable[Hashable]:
        raise NotImplementedError

    def look_under(self, name: Name, rules: Rules) -> Iterable[Hashable]:
        raise NotImplementedError

    def holds(self, candidate: Name, other: Name, rules: Rules) -> bool:
        raise NotImplementedError


class SameName(Check):
    def file_under(self, name, rules):
        return [name.words] if name.words else []

    look_under = file_under

    def holds(self, candidate, other, rules):
        return bool(candidate.words) and candidate.words == other.words


class LeadingWord(Check):
    def file_under(self, name, rules):
        return [name.plain] if name.plain else []

    look_under = file_under

    def holds(self, candidate, other, rules):
        return bool(candidate.words and other.words) and candidate.words != other.words and candidate.plain == other.plain


class Acronym(Check):
    def file_under(self, name, rules):
        return [("short", name.acronym)] * bool(name.acronym) + [("long", initials) for initials in name.initials(rules)]

    def look_under(self, name, rules):
        return [("long", name.acronym)] * bool(name.acronym) + [("short", initials) for initials in name.initials(rules)]

    def holds(self, candidate, other, rules):
        return any(short.acronym is not None and short.acronym in long.initials(rules) for short, long in ((candidate, other), (other, candidate)))


class Surname(Check):
    """The pair is a surname beside a full name. That it is the only full name with the surname is decided by the finder, over the kind."""

    def file_under(self, name, rules):
        return [("single", name.plain[0])] if len(name.plain) == 1 else [("full", name.plain[-1])] if len(name.plain) >= 2 else []

    def look_under(self, name, rules):
        return [("full", name.plain[0])] if len(name.plain) == 1 else [("single", name.plain[-1])] if len(name.plain) >= 2 else []

    def holds(self, candidate, other, rules):
        return any(len(one.plain) == 1 and len(many.plain) >= 2 and many.plain[-1] == one.plain[0] for one, many in ((candidate, other), (other, candidate)))


class Containment(Check):
    def file_under(self, name, rules):
        return [("first", name.plain[0]), ("last", name.plain[-1])] if name.plain else []

    look_under = file_under

    def holds(self, candidate, other, rules):
        first, second = candidate.plain, other.plain
        if not first or not second or first == second:
            return False
        short, long = sorted((first, second), key=len)
        return long[: len(short)] == short or long[len(long) - len(short) :] == short


CHECKS: dict[str, Check] = {"same_name": SameName(), "leading_word": LeadingWord(), "acronym": Acronym(), "surname": Surname(), "containment": Containment()}


# -- the search -------------------------------------------------------------------------------------------------------------
class DuplicateFinder:
    """The accepted entities, read once and filed for lookup. Build it once per run and ask it for every candidate: the cost of a question does not grow with the map."""

    def __init__(self, nodes: Iterable[Mapping[str, Any]], rules: Rules | None = None) -> None:
        self.rules = rules or default_rules()
        self._table: dict[tuple[str, str, Hashable], list[tuple[Mapping[str, Any], Name]]] = defaultdict(list)
        self._full_names: dict[tuple[str, str], set[str]] = defaultdict(set)  # (kind, surname) -> lineages of the entities with a full name ending in it
        self._cache: dict[tuple[str, str, str | None], DuplicateHit | None] = {}
        for node in sorted(nodes, key=lambda row: str(row.get("nodeKey") or row.get("id"))):
            self.add(node)

    def add(self, node: Mapping[str, Any]) -> None:
        """File one more accepted entity (a node accepted a moment ago). Anything that is not an accepted, current node is ignored."""
        if not is_target(node):
            return
        self._cache.clear()
        kind = kind_key(node.get("nodeKind") or "")
        lineage = str(node.get("lineageId") or node.get("id"))
        for text in names_of(node):
            name = read_name(text, self.rules)
            for rule in self.rules.rules:
                if rule.kinds is not None and kind not in rule.kinds:
                    continue
                for key in CHECKS[rule.check].file_under(name, self.rules):
                    self._table[(kind, rule.check, key)].append((node, name))
            if len(name.plain) >= 2:
                self._full_names[(kind, name.plain[-1])].add(lineage)

    def find(self, kind: str, name: str, *, own_lineage: str | None = None, among: Callable[[Mapping[str, Any]], bool] | None = None) -> DuplicateHit | None:
        """The accepted entity of ``kind`` that ``name`` duplicates, or ``None``. ``own_lineage`` is the candidate's own lineage when it is a node already.

        The first rule (in the rules file's order) that fires against any accepted entity of the kind decides; among entities that fire the same rule, the
        first by node key. ``among`` narrows the entities the candidate may duplicate (the surname rule still counts every entity of the kind)."""
        wanted = kind_key(kind)
        cached = among is None and self._cache.get((wanted, name, own_lineage), False)
        if cached is not False:
            return cached
        candidate = read_name(name, self.rules)
        hit = self._search(wanted, candidate, own_lineage, among) if candidate.words else None
        if among is None:
            self._cache[(wanted, name, own_lineage)] = hit
        return hit

    def _search(self, kind: str, candidate: Name, own_lineage: str | None, among: Callable[[Mapping[str, Any]], bool] | None) -> DuplicateHit | None:
        for rule in self.rules.rules:
            if rule.kinds is not None and kind not in rule.kinds:
                continue
            check = CHECKS[rule.check]
            found: dict[str, tuple[Mapping[str, Any], Name]] = {}
            for key in check.look_under(candidate, self.rules):
                for node, other in self._table.get((kind, rule.check, key), ()):
                    lineage = str(node.get("lineageId") or node.get("id"))
                    if lineage == own_lineage or (among is not None and not among(node)) or not check.holds(candidate, other, self.rules):
                        continue
                    if rule.check == "surname":
                        # Exactly one full-name person has the surname: the candidate itself when it is the full name, else the entity that has it.
                        holders = self._full_names[(kind, candidate.plain[-1])] - ({own_lineage} if own_lineage else set())
                        if len(holders) + (1 if len(candidate.plain) >= 2 else 0) != 1:
                            continue
                    found.setdefault(str(node.get("nodeKey") or node.get("id")), (node, other))
            if found:
                node, other = found[min(found)]
                return DuplicateHit(rule.id, rule.action, node, candidate.text, other.text, rule.description)
        return None


def find_duplicate(
    kind: str,
    name: str,
    nodes: Iterable[Mapping[str, Any]],
    *,
    rules: Rules | None = None,
    own_lineage: str | None = None,
    among: Callable[[Mapping[str, Any]], bool] | None = None,
) -> DuplicateHit | None:
    """One question to a finder built for the occasion (``DuplicateFinder.find``). A run that asks many questions builds one finder."""
    return DuplicateFinder(nodes, rules).find(kind, name, own_lineage=own_lineage, among=among)


def find_duplicate_pairs(nodes: Iterable[Mapping[str, Any]], *, rules: Rules | None = None) -> list[tuple[DuplicateHit, Mapping[str, Any]]]:
    """Every pair of accepted entities in which one duplicates the other, as ``(hit, entity)``: the hit is the duplicate's view (its ``node`` is the entity
    it duplicates). Each pair is reported once, the entity with the larger node key as the duplicate. Read-only: a report for a person."""
    rows = [node for node in nodes if is_target(node)]
    finder = DuplicateFinder(rows, rules)
    pairs = []
    for node in sorted(rows, key=lambda row: str(row.get("nodeKey") or row.get("id"))):
        earlier = lambda other, node=node: str(other.get("nodeKey") or "") < str(node.get("nodeKey") or "")  # noqa: E731
        hit = finder.find(str(node.get("nodeKind") or ""), str(node.get("displayName") or ""), own_lineage=str(node.get("lineageId") or node.get("id")), among=earlier)
        if hit is not None:
            pairs.append((hit, node))
    return pairs


# -- the proposal a person decides -------------------------------------------------------------------------------------------
def proposal_id(candidate_kind: str, candidate_name: str, node: Mapping[str, Any]) -> str:
    return f"steering-proposal-duplicate-{hash_short([kind_key(candidate_kind), alias_identity(candidate_name), str(node.get('lineageId') or node.get('id'))])}"


def duplicate_proposal(
    hit: DuplicateHit,
    candidate_kind: str,
    candidate: Mapping[str, Any] | None,
    *,
    corpus_id: str,
    import_run_id: str,
    now: str,
) -> dict:
    """The ``SteeringProposal`` that asks a person about a hit. For a candidate that is a node (the AI review) it is a ``merge-graph-entity``: merge the
    candidate into the entity (``entities merge``). For a candidate that is only a name (the extractor) it is an ``entity-alias-edit``: add the name to
    the entity (``entities alias``). One proposal per candidate and entity, so a rerun files nothing new, and the row is created once (a person's decision on it stays)."""
    merge = candidate is not None
    summary = json.dumps(
        {
            "kind": PROPOSAL_MARKER,
            "rule": hit.rule,
            "candidateKind": kind_key(candidate_kind),
            "candidateName": hit.candidate_name,
            "candidateKey": candidate.get("nodeKey") if candidate else None,
            "entityKey": hit.key,
            "matchedName": hit.matched_name,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "id": proposal_id(candidate_kind, hit.candidate_name, hit.node),
        "corpusId": corpus_id,
        "importRunId": import_run_id,
        "proposalKind": PROPOSAL_KIND_MERGE if merge else PROPOSAL_KIND_NEW_ALIAS,
        "steeringDomain": PROPOSAL_DOMAIN,
        "status": STATUS_PROPOSED,
        "title": f"{hit.candidate_name} may be {hit.node.get('displayName')}",
        "summary": summary,
        "graphEntityId": hit.key,
        "displayName": hit.candidate_name,
        "description": hit.sentence() + (f" Merge it with `knowledge entities merge --from {candidate['nodeKey']} --into {hit.key}`." if merge else f" Add it with `knowledge entities alias --key {hit.key} --add {hit.candidate_name!r}`."),
        "proposedAt": now,
        "updatedAt": now,
    }
