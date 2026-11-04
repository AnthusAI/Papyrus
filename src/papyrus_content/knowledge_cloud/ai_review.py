"""AI review of a run's entities, clusters and relations (GPT-6 Luna), accepted only on stated evidence.

The model never decides alone. For every candidate it gets short snippets of the site's own item text and must answer
``accept``, ``reject`` or ``unsure``. An ``accept`` counts only when the evidence it quotes is a verbatim piece of one of
the snippets it was given and names the thing (for a relation: both ends); anything else is treated as ``unsure`` and the
row stays as the extractor left it. ``reject`` is for junk. Everything is recorded as accepted or rejected by the actor
``ai`` ("AI" on the site), with the day.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..knowledge_snapshot.actors import Actor
from .cost import usage_entry
from ..knowledge_snapshot.cluster_records import CLUSTER_KIND, STATUS_PROPOSED, decode_metadata
from ..knowledge_snapshot.cluster_review import accept_cluster_patches
from ..knowledge_snapshot.entity_review import accept_patches, reject_patches
from ..knowledge_snapshot.keys import slug
from ..knowledge_snapshot.publish_run import is_item_mention
from ..knowledge_snapshot.relation_review import (
    PROPOSED,
    accept_relation_patches,
    is_node_relation,
    reject_relation_patches,
    review_state,
)

RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-6-luna"
BATCH_SIZE = 20
SNIPPETS_PER_CANDIDATE = 3
SNIPPET_MARGIN = 140
DEFAULT_MAX_CALLS = 150
REQUEST_TIMEOUT_SECONDS = 120
ATTEMPTS = 3
MINIMUM_CLUSTER_TITLES = 3

ACCEPT, REJECT, UNSURE = "accept", "reject", "unsure"
GATE_QUOTE_NOT_FOUND = "quote not in the snippets or does not name the thing"
GATE_PASSING_MENTION = "named in passing, not about the thing"
GATE_ABOUT_THE_THING = "quote names the thing and is about it"

VERDICT_FORMAT = {
    "type": "json_schema",
    "name": "review_verdicts",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["verdicts"],
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "verdict", "evidence", "about", "name", "reason"],
                    "properties": {
                        "id": {"type": "string"},
                        "verdict": {"type": "string", "enum": [ACCEPT, REJECT, UNSURE]},
                        "evidence": {"type": "array", "items": {"type": "string"}},
                        "about": {"type": "boolean"},
                        "name": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                },
            }
        },
    },
}

COMMON_RULES = (
    "You review machine-extracted knowledge for a publication. You are conservative: when the text does not make it plain, "
    "answer unsure. Answer for every candidate id, once. `evidence` holds exact, verbatim quotes copied from the snippets "
    "given for that candidate (never from memory, never paraphrased). `reason` is one short sentence. Leave `name` empty "
    "unless the task asks for a name. Set `about` to false unless the task asks for it."
)
ENTITY_TASK = (
    "Task: entities. Each candidate is a span the extractor typed with one kind from the vocabulary. accept = the snippets "
    "show it is a real, specific, named thing of exactly that kind (a named model, company, licence, dataset, platform, "
    "technique, task, concept) and the quoted evidence contains its name. `about` is true only when the quoted evidence "
    "is about the thing itself: it introduces, defines, describes, releases or reports on it. `about` is false when the thing "
    "is only named in passing: one of a list of examples, a comparison or baseline, a citation, an aside. Answer unsure, not "
    "accept, when the only evidence names it in passing. reject = it is junk: a generic noun, a size or "
    "number, a file format, a metric, a language, a heading word, a pronoun, or a thing of a different kind. unsure = "
    "plausible but not clear, or the right kind is doubtful."
)
RELATION_TASK = (
    "Task: relations. Each candidate says `subject --relation--> object` between two accepted entities. accept = the "
    "snippets state it explicitly and the quote names both entities (or their aliases); this holds for member_of too: a "
    "model belongs to a family only if the text says so, a shared name prefix is not evidence. reject = the snippets "
    "contradict it or the entities are of the wrong kind for the relation. unsure = the text only implies it."
)
CLUSTER_TASK = (
    "Task: clusters. Each candidate is a topic cluster with its top terms and the titles of its member items. accept = the "
    "members clearly share one subject; give a short plain `name` (at most six words, no marketing words) and put at "
    f"least {MINIMUM_CLUSTER_TITLES} member titles, copied exactly, in `evidence`. unsure = the members do not share a subject."
)


class ReviewError(RuntimeError):
    pass


def squash(text: str) -> str:
    return " ".join(str(text).split())


def contains_name(evidence: str, names: Iterable[str]) -> bool:
    folded = squash(evidence).casefold()
    return any(squash(name).casefold() in folded for name in names if squash(name))


def urllib_transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310 - a fixed https endpoint
        return json.loads(response.read().decode("utf-8"))


def response_text(body: Mapping[str, Any]) -> str:
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    parts = [
        part.get("text")
        for message in body.get("output") or []
        if isinstance(message, dict)
        for part in message.get("content") or []
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ]
    if not parts:
        raise ReviewError("The model returned no text.")
    return "".join(parts)


class LunaReviewer:
    """GPT-6 Luna through the OpenAI Responses API; the key lives in this object and nowhere else."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        guidance: str = "",
        max_calls: int = DEFAULT_MAX_CALLS,
        transport: Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]] = urllib_transport,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise ValueError("an API key is required")
        self._api_key = api_key
        self.model = model
        self.guidance = guidance.strip()
        self.max_calls = max_calls
        self.ceiling = max_calls  # the calls the current stage of the review may reach (``limit_stage``); never above ``max_calls``
        self.calls = 0
        self.usage: list[dict[str, Any]] = []  # one entry per response received: the usage object of the API (cost accounting)
        self._transport = transport
        self._sleep = sleep

    def exhausted(self) -> bool:
        return self.calls >= min(self.ceiling, self.max_calls)

    def limit_stage(self, reserved_for_later: int) -> None:
        """The stage that starts now may use every call that is left except the ``reserved_for_later`` its successors are owed (``fair_shares``)."""
        self.ceiling = max(self.calls, self.max_calls - max(0, reserved_for_later))

    def request_payload(self, task: str, candidates: list[dict]) -> dict[str, Any]:
        instructions = f"{COMMON_RULES}\n\n{task}"
        if self.guidance:
            instructions += f"\n\nPublication guidance from the editors:\n{self.guidance}"
        return {
            "model": self.model,
            "instructions": instructions,
            "input": json.dumps({"candidates": candidates}, ensure_ascii=False, separators=(",", ":")),
            "text": {"format": VERDICT_FORMAT},
            "max_output_tokens": 6000,
            "store": False,
        }

    def judge(self, task: str, candidates: list[dict]) -> dict[str, dict]:
        """The verdict for each candidate id the model answered (unknown ids are dropped)."""
        if self.exhausted():
            raise ReviewError(f"The review call limit ({min(self.ceiling, self.max_calls)}) is reached.")
        headers = {"authorization": f"Bearer {self._api_key}", "content-type": "application/json"}
        payload = self.request_payload(task, candidates)
        self.calls += 1
        last: Exception | None = None
        for attempt in range(ATTEMPTS):
            try:
                body = self._transport(RESPONSES_URL, headers, payload)
                self.usage.append(usage_entry(self.model, body))  # billed even if the answer is then unusable
                parsed = json.loads(response_text(body))
                break
            except urllib.error.HTTPError as error:
                last = error
                if error.code not in (408, 409, 429) and error.code < 500:
                    raise ReviewError(f"The model request failed with HTTP {error.code}.") from None
            except (urllib.error.URLError, TimeoutError, ValueError, ReviewError) as error:
                last = error
            self._sleep(2 ** attempt * 2)
        else:
            raise ReviewError(f"The model request failed after {ATTEMPTS} attempts: {type(last).__name__}.")
        known = {candidate["id"] for candidate in candidates}
        verdicts: dict[str, dict] = {}
        for verdict in parsed.get("verdicts") or []:
            if isinstance(verdict, dict) and verdict.get("id") in known and verdict.get("verdict") in (ACCEPT, REJECT, UNSURE):
                verdicts.setdefault(verdict["id"], verdict)
        return verdicts


@dataclass
class Decision:
    kind: str
    subject: str
    verdict: str
    reason: str
    evidence: list[str] = field(default_factory=list)
    applied: bool = False
    gate: str = ""  # why an accept was refused or let through: one of the GATE_* values; empty for a verdict the gate did not judge

    def to_dict(self) -> dict:
        entry = {"kind": self.kind, "subject": self.subject, "verdict": self.verdict, "reason": self.reason, "evidence": self.evidence, "applied": self.applied}
        return {**entry, "gate": self.gate} if self.gate else entry


def batches(rows: list, size: int = BATCH_SIZE):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def snippet_of(text: str, start: int, end: int) -> str:
    return squash(text[max(0, start - SNIPPET_MARGIN) : end + SNIPPET_MARGIN])


class TypedRun:
    """The typed-extraction output joined with the extracted texts, to find the sentence behind a node or relation."""

    def __init__(self, output: Mapping[str, Any], texts: Mapping[str, str]) -> None:
        self.texts = texts
        self.mentions: dict[tuple[str, str], list[tuple[str, int, int]]] = defaultdict(list)
        self.relations: dict[tuple[str, str, str], list[tuple[str, int, int]]] = defaultdict(list)
        for item in output.get("items") or []:
            item_id = str(item.get("item_id"))
            entities = {entity["id"]: entity for entity in item.get("entities") or []}
            for entity in entities.values():
                span = entity.get("span") or {}
                self.mentions[(slug(entity["kind"]), slug(entity["text"]))].append((item_id, span.get("start", 0), span.get("end", 0)))
            for relation in item.get("relations") or []:
                subject, target = entities.get(relation.get("subject")), entities.get(relation.get("object"))
                if not subject or not target:
                    continue
                span = relation.get("span") or {}
                key = (relation["type"], slug(subject["text"]), slug(target["text"]))
                self.relations[key].append((item_id, span.get("start", 0), span.get("end", 0)))

    def _snippets(self, places: list[tuple[str, int, int]]) -> list[str]:
        found: list[str] = []
        for item_id, start, end in places:
            text = self.texts.get(item_id)
            if text is None:
                continue
            snippet = snippet_of(text, start, end)
            if snippet and snippet not in found:
                found.append(snippet)
            if len(found) >= SNIPPETS_PER_CANDIDATE:
                break
        return found

    def entity_snippets(self, kind: str, names: Iterable[str]) -> list[str]:
        places: list[tuple[str, int, int]] = []
        for name in names:
            places += self.mentions.get((slug(kind), slug(name)), [])
        return self._snippets(places)

    def relation_snippets(self, predicate: str, subject_names: Iterable[str], object_names: Iterable[str]) -> list[str]:
        places: list[tuple[str, int, int]] = []
        for subject in subject_names:
            for target in object_names:
                places += self.relations.get((predicate, slug(subject), slug(target)), [])
        return self._snippets(places)


def node_names(node: Mapping[str, Any]) -> list[str]:
    return [str(name) for name in [node.get("displayName"), *(node.get("aliases") or [])] if name]


def entity_candidates(nodes: list[dict], typed: TypedRun) -> dict[str, dict]:
    """The generated nodes that have a sentence behind them: the only ones the model is asked about."""
    candidates: dict[str, dict] = {}
    for index, node in enumerate(nodes):
        snippets = typed.entity_snippets(str(node.get("nodeKind")), node_names(node))
        if snippets:
            candidates[f"n{index}"] = {"node": node, "snippets": snippets}
    return candidates


def review_entities(
    nodes: list[dict],
    typed: TypedRun,
    mentions_of: Callable[[dict], list[dict]],
    model: LunaReviewer,
    actor: Actor,
    *,
    now: str,
    vocabulary: Mapping[str, str],
) -> tuple[list[dict], list[Decision]]:
    """Patches and decisions for the nodes the extractor left ``generated``.

    An ``accept`` counts only through the evidence gate (``entity_gate``): the quote is verbatim in a snippet and names the thing, it says more than
    the name, and the model says it is *about* the thing and not a mention in passing. The decision records which of those it was."""
    candidates = entity_candidates(nodes, typed)
    patches: list[dict] = []
    decisions: list[Decision] = []
    for group in batches(sorted(candidates)):
        if model.exhausted():
            break
        payload = [
            {
                "id": key,
                "kind": candidates[key]["node"]["nodeKind"],
                "kind_label": vocabulary.get(slug(str(candidates[key]["node"]["nodeKind"])), ""),
                "name": candidates[key]["node"]["displayName"],
                "snippets": candidates[key]["snippets"],
            }
            for key in group
        ]
        verdicts = model.judge(ENTITY_TASK, payload)
        for key in group:
            node, snippets = candidates[key]["node"], candidates[key]["snippets"]
            verdict = verdicts.get(key)
            label = f"{node['nodeKind']}: {node['displayName']}"
            if verdict is None:
                continue
            decision = Decision("entity", label, verdict["verdict"], verdict["reason"], list(verdict["evidence"]))
            if verdict["verdict"] == ACCEPT:
                decision.gate = entity_gate(verdict, snippets, node_names(node))
                if decision.gate == GATE_ABOUT_THE_THING:
                    patches += accept_patches(node, mentions_of(node), actor=actor, now=now)
                    decision.applied = True
                else:
                    decision.verdict = UNSURE
                    decision.reason = f"{decision.gate}: {decision.reason}"
            elif verdict["verdict"] == REJECT:
                patches += reject_patches(node, actor=actor, now=now)
                decision.applied = True
            decisions.append(decision)
    return patches, decisions


def held_quotes(evidence: Iterable[str], snippets: list[str], names: Iterable[str]) -> list[str]:
    """The quotes that are verbatim in a snippet and name the thing."""
    pool = [squash(snippet) for snippet in snippets]
    names = list(names)
    return [flat for flat in (squash(quote) for quote in evidence) if flat and any(flat in snippet for snippet in pool) and contains_name(flat, names)]


def quotes_hold(evidence: Iterable[str], snippets: list[str], names: Iterable[str]) -> bool:
    """Some quote is verbatim in a snippet and names the thing."""
    return bool(held_quotes(evidence, snippets, names))


def says_more_than_the_name(quote: str, names: Iterable[str]) -> bool:
    """The quote still has words in it once the thing's names are taken out: a bare name is not evidence of anything about it."""
    rest = squash(quote).casefold()
    for name in sorted((squash(name).casefold() for name in names if squash(name)), key=len, reverse=True):
        rest = rest.replace(name, " ")
    return any(character.isalnum() for character in rest)


def entity_gate(verdict: Mapping[str, Any], snippets: list[str], names: Iterable[str]) -> str:
    """Why an ``accept`` of an entity passes (``GATE_ABOUT_THE_THING``) or is refused. The snippets surround each mention, so a quote that only names
    the thing (a baseline in a comparison, one of a list, a citation) used to pass; now it must also be about the thing, by the model's own
    statement (``about`` must be exactly true) and by saying more than the name."""
    names = list(names)
    held = held_quotes(verdict.get("evidence") or [], snippets, names)
    if not held:
        return GATE_QUOTE_NOT_FOUND
    if verdict.get("about") is not True or not any(says_more_than_the_name(quote, names) for quote in held):
        return GATE_PASSING_MENTION
    return GATE_ABOUT_THE_THING


def relation_candidates(
    relations: list[dict], nodes_by_lineage: Mapping[str, dict], typed: TypedRun, *, ends: tuple[str, ...] = ("accepted",),
) -> dict[str, dict]:
    """The proposed relations whose two ends have the given statuses and that have a sentence behind them."""
    candidates: dict[str, dict] = {}
    for index, relation in enumerate(relations):
        if not is_node_relation(relation) or review_state(relation) != PROPOSED:
            continue
        subject = nodes_by_lineage.get(str(relation.get("subjectLineageId")))
        target = nodes_by_lineage.get(str(relation.get("objectLineageId")))
        if subject is None or target is None or subject.get("status") not in ends or target.get("status") not in ends:
            continue
        snippets = typed.relation_snippets(str(relation.get("predicate")), node_names(subject), node_names(target))
        if snippets:
            candidates[f"r{index}"] = {"relation": relation, "subject": subject, "object": target, "snippets": snippets}
    return candidates


def review_relations(
    relations: list[dict],
    nodes_by_lineage: Mapping[str, dict],
    typed: TypedRun,
    model: LunaReviewer,
    actor: Actor,
    *,
    now: str,
) -> tuple[list[dict], list[Decision]]:
    candidates = relation_candidates(relations, nodes_by_lineage, typed)
    patches: list[dict] = []
    decisions: list[Decision] = []
    for group in batches(sorted(candidates)):
        if model.exhausted():
            break
        payload = [
            {
                "id": key,
                "relation": candidates[key]["relation"]["predicate"],
                "subject": f"{candidates[key]['subject']['displayName']} ({candidates[key]['subject']['nodeKind']})",
                "object": f"{candidates[key]['object']['displayName']} ({candidates[key]['object']['nodeKind']})",
                "snippets": candidates[key]["snippets"],
            }
            for key in group
        ]
        verdicts = model.judge(RELATION_TASK, payload)
        for key in group:
            entry = candidates[key]
            verdict = verdicts.get(key)
            if verdict is None:
                continue
            label = f"{entry['subject']['displayName']} --{entry['relation']['predicate']}--> {entry['object']['displayName']}"
            decision = Decision("relation", label, verdict["verdict"], verdict["reason"], list(verdict["evidence"]))
            both_named = any(
                quotes_hold([quote], entry["snippets"], node_names(entry["subject"])) and contains_name(quote, node_names(entry["object"]))
                for quote in verdict["evidence"]
            )
            if verdict["verdict"] == ACCEPT and both_named:
                patches += accept_relation_patches(entry["relation"], actor, now=now)
                decision.applied = True
            elif verdict["verdict"] == REJECT:
                patches += reject_relation_patches(entry["relation"], actor, now=now)
                decision.applied = True
            elif verdict["verdict"] == ACCEPT:
                decision.verdict = UNSURE
                decision.reason = f"evidence does not quote the snippets naming both ends: {decision.reason}"
            decisions.append(decision)
    return patches, decisions


CLUSTER_BATCH_SIZE = 8


def cluster_candidates(proposals: list[dict], titles_of: Callable[[list[str]], list[str]]) -> dict[str, dict]:
    """The new clusters with enough member titles to be judged."""
    candidates: dict[str, dict] = {}
    for index, proposal in enumerate(proposals):
        metadata = decode_metadata(proposal.get("summary"))
        if proposal.get("proposalKind") != CLUSTER_KIND or proposal.get("status") != STATUS_PROPOSED or metadata is None:
            continue
        titles = titles_of(list(proposal.get("evidenceItemIds") or []))[:15]
        if len(titles) >= MINIMUM_CLUSTER_TITLES:
            candidates[f"c{index}"] = {"proposal": proposal, "terms": metadata.get("topTerms") or [], "titles": titles}
    return candidates


def review_clusters(
    proposals: list[dict],
    titles_of: Callable[[list[str]], list[str]],
    model: LunaReviewer,
    actor: Actor,
    *,
    now: str,
) -> tuple[list[dict], list[Decision]]:
    candidates = cluster_candidates(proposals, titles_of)
    patches: list[dict] = []
    decisions: list[Decision] = []
    for group in batches(sorted(candidates), CLUSTER_BATCH_SIZE):
        if model.exhausted():
            break
        payload = [{"id": key, "top_terms": candidates[key]["terms"], "member_titles": candidates[key]["titles"]} for key in group]
        verdicts = model.judge(CLUSTER_TASK, payload)
        for key in group:
            entry, verdict = candidates[key], verdicts.get(key)
            if verdict is None:
                continue
            name = squash(verdict.get("name") or "")
            label = f"cluster {entry['proposal'].get('graphEntityId') or entry['proposal']['id']}"
            decision = Decision("cluster", label, verdict["verdict"], verdict["reason"], list(verdict["evidence"]))
            titles = set(entry["titles"])
            quoted = [quote for quote in verdict["evidence"] if quote in titles]
            if verdict["verdict"] == ACCEPT and name and len(name) <= 80 and len(set(quoted)) >= MINIMUM_CLUSTER_TITLES:
                patches += accept_cluster_patches(entry["proposal"], name, actor, now=now)
                decision.applied = True
                decision.reason = f"named {name!r}: {decision.reason}"
            elif verdict["verdict"] == ACCEPT:
                decision.verdict = UNSURE
                decision.reason = f"fewer than {MINIMUM_CLUSTER_TITLES} member titles quoted, or no name: {decision.reason}"
            decisions.append(decision)
    return patches, decisions


def calls_needed(candidates: int, batch_size: int) -> int:
    return -(-candidates // batch_size)


def fair_shares(needs: Mapping[str, int], budget: int) -> dict[str, int]:
    """How many of ``budget`` calls each kind of work is owed: max-min fair, so no kind gets more than it needs and a kind that needs little is
    served in full before a kind that needs a lot takes the rest. Equal shares are raised in turn (the kinds that need less than an equal share
    drop out with what they need, the others share the remainder equally); when fewer calls are left than kinds, the kinds with most still
    to do get one each.

    The review runs entities, then clusters, then relations, and each may use every call that is left except what the kinds after it are owed
    (``LunaReviewer.limit_stage``): the first kind cannot starve the later ones, and a call a later kind does not need goes back to the pool."""
    shares = {name: 0 for name in needs}
    active = {name for name, need in needs.items() if need > 0}
    remaining = max(0, budget)
    while active and remaining > 0:
        equal = remaining // len(active)
        if equal == 0:
            for name in sorted(active, key=lambda name: (-(needs[name] - shares[name]), name))[:remaining]:
                shares[name] += 1
            break
        satisfied = {name for name in active if needs[name] - shares[name] <= equal}
        if satisfied:
            for name in satisfied:
                remaining -= needs[name] - shares[name]
                shares[name] = needs[name]
            active -= satisfied
        else:
            for name in active:
                shares[name] += equal
            remaining -= equal * len(active)
    return shares


def record_changes(patches: Iterable[Mapping[str, Any]]) -> list[dict]:
    return [{"modelName": patch["modelName"], "expected": patch["expected"], "current": None, "action": "update"} for patch in patches]


def summary_of(decisions: list[Decision]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for decision in decisions:
        counts[f"{decision.kind}.{decision.verdict}{'.applied' if decision.applied else ''}"] += 1
    return dict(sorted(counts.items()))


def vocabulary_labels(vocabulary_text: str) -> dict[str, str]:
    """Entity kind key -> label from the publication's vocabulary.yml."""
    import yaml

    document = yaml.safe_load(vocabulary_text) or {}
    return {slug(str(row["key"])): str(row.get("label") or "") for row in document.get("entity_kinds") or [] if isinstance(row, dict) and row.get("key")}
