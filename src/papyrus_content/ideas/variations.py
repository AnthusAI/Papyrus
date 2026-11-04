"""Variations: the different ways one idea could connect to what the newsroom knows, offered with the idea (epic PPY-4b070c, ticket PPY-96c540;
docs/story-variations.md, "Offered by idea runs").

When a run files an idea it also offers variations of it: distinct angles that connect the same item to different existing knowledge, so an editor can see the
options side by side instead of the one the writer happened to pick. The connections are the real ones and no more:

* ``reference``: another accepted Reference related to this one (``connections.NEIGHBOUR``);
* ``story``: another Story that rests on such a Reference or carries a concept the Reference has (``connections.story_options``);
* ``concept``: a concept the Reference carries, including the hashtags editors typed (``connections.concept_options``).

Variation 1 is always the idea as filed, with the point it passed on. Every other connection the idea does not already rest on gets one more variation, written
in one model call, and a variation is offered only when it passes everything the idea itself passed: the citation rules, the "more than a summary" rules of
``connections.standard_problems`` and the model judge of ``point_check``. A Reference with few connections therefore gets one variation, or two, and a writer that
has no point for a connection says so with an empty ``point`` and offers nothing for it: no connection is used twice and none is stretched to make variety.
There is no count. What stops the pass is a real constraint: the run's cost limit, or a prompt too large for the model, or a write that fails.

The pass never costs the idea: it runs after the idea is filed, a failure is recorded in the run and the idea stays. The same failure twice in a row is systemic (a
missing grant, a model the backend does not have), so the pass turns itself off for the rest of the run rather than pay for variations that cannot be kept.
A Story that already has generated variations is left alone, so a rerun adds nothing (``story_variations.offer_variation`` is also idempotent on the wording).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .. import story_variations
from . import connections as rules, point_check, synthesis, trends

MAXIMUM_OUTPUT_TOKENS_EACH = 3_000   # one variation; the call's allowance is this times the number of connections it is asked about
MAXIMUM_OUTPUT_TOKENS = 16_000       # the model's own limit on one answer

NO_POINT = "no_point_offered"
ANCHOR_NOT_CITED = "anchor_not_cited"
ANCHOR_UNKNOWN = "unknown_connection"
REPEATS_ANOTHER = "repeats_another_variation"

INTRO = """You write other versions of one story idea for a publication. You are given one item that a monitor found (the "source": a link to a page, with the page's text where it could be read and any facts the monitor stored), the publication's mission, policy and allowed sections, other material bearing on it ("what_the_newsroom_knows"), the idea as it was already written ("the_idea_as_filed") and a list of "options". Each option is one thing the source could be connected to: another article (R), another story the publication has (S) or a concept the publication follows (C).

Write one version for each option, built on that option: the version's angle is what the connection shows about the source. Every version must make a different point from the idea as filed and from every other version. Give each its "anchor" (the option's handle). If an option shows nothing about the source that a reader could not get from the source alone, leave "point" empty for it and write its other fields as briefly as the format allows: an empty point is a good answer and nothing is offered for that option. Do not stretch for one, and do not write a version whose point is the idea's point with the option's name added.

First decide what the version claims that a reader could not get from the source alone, and write that as one sentence in "point". It must be specific: where two sources disagree, what one reports that another leaves out and why that changes the picture, or a concrete consequence or open question that follows from the facts. These are not points: that another article, story or concept covers the same topic, that something is interesting, notable or worth watching, that it matters for some group, why someone liked it, or that the source does not prove something it never claimed to prove. Then write the version around that point: at most one sentence on what the item is and who made it, and everything else in service of the point. The headline names the concrete thing. The dek states the point; the body gives the evidence for it and does not state it again.

The dek, and at least one body sentence, must cite the option's own handle (the "anchor"), alone or with the source."""

#: What the single-item writer already knows (monitor_stories.SYSTEM_PROMPT's rules) holds here too, with two more handles.
EXTRA_RULES = """
- S is another story the publication has, with its title and dek. Name it by its title and say what it reports and how that bears on the source. Never describe how the two came to be connected: do not write "linked", "tagged", "suggested" or "the newsroom". A story grounds no number or date: take a figure only from the source or from another article.
- C is a concept the publication follows, with its name and description. Say what the concept shows about the source: what it is an instance of, or where it differs from the concept's other cases. A concept grounds no fact about the source. Never write that the item was tagged, or that anyone chose the concept."""

VARIATION_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "name": "story_variations",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "variations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "anchor": {"type": "string"},
                        "point": {"type": "string"},
                        "headline": trends.SENTENCE_SCHEMA,
                        "dek": trends.SENTENCE_SCHEMA,
                        "section": {"type": "string"},
                        "paragraphs": {
                            "type": "array",
                            "items": {"type": "object", "properties": {"sentences": {"type": "array", "items": trends.SENTENCE_SCHEMA}}, "required": ["sentences"], "additionalProperties": False},
                        },
                    },
                    "required": ["anchor", "point", "headline", "dek", "section", "paragraphs"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["variations"],
        "additionalProperties": False,
    },
}


def system_prompt() -> str:
    """The introduction, then the single-item writer's rules (one place for what a sentence may say), then the two handles only a variation writer is shown."""
    from .monitor_stories import SYSTEM_PROMPT

    rules_of_the_writer = SYSTEM_PROMPT.split("Rules:", 1)[1].rstrip()
    return f"{INTRO}\n\nRules:{rules_of_the_writer}{EXTRA_RULES}\n"


# --- the options ---------------------------------------------------------------------------------------------------------------


def kind_of(entry: rules.Connection) -> str | None:
    return {rules.NEIGHBOUR: story_variations.REFERENCE, rules.STORY_OPTION: story_variations.STORY, rules.CONCEPT_OPTION: story_variations.CONCEPT}.get(entry.kind)


def connection_row(entry: rules.Connection) -> dict[str, str]:
    """A connection as ``StoryVariation.connections`` keeps it: ``kind``, the id of what it connects to (a Reference lineage, an Item lineage or a concept lineage),
    its title and, in plain words, ``how`` it is connected."""
    if entry.kind == rules.NEIGHBOUR:
        neighbour = entry.reference
        how = "Linked by an editor" if neighbour.provenance == rules.CONFIRMED else "A close match"
        return {"kind": story_variations.REFERENCE, "id": neighbour.lineage_id, "title": neighbour.title, "how": how}
    if entry.kind == rules.STORY_OPTION:
        return {"kind": story_variations.STORY, "id": entry.story.lineage_id, "title": entry.story.title, "how": entry.story.via}
    option = entry.concept
    return {"kind": story_variations.CONCEPT, "id": option.lineage_id, "title": option.hashtag or option.name, "how": "Tagged by an editor" if option.by_editor else "Tagged"}


def options_for(connections: rules.Connections, cited: Sequence[str]) -> list[rules.Connection]:
    """The connections a variation can be built on: every related Reference, Story and concept the idea as filed does not already rest on."""
    return [entry for entry in connections.entries if kind_of(entry) is not None and entry.handle not in set(cited)]


def option_view(entry: rules.Connection) -> dict[str, str]:
    row = connection_row(entry)
    return {"anchor": entry.handle, "kind": row["kind"], "title": row["title"]}


# --- the pass ------------------------------------------------------------------------------------------------------------------


@dataclass
class Pass:
    """One run's variations: shared by every idea the run files. ``spent`` is the run's cost meter (``pack_stories.CostMeter``), so what the variations cost counts
    against ``maximum_cost_usd`` and the idea runs' own meter."""

    client: Any
    transport: synthesis.Transport
    model: str
    meter: Any
    run: dict[str, Any]
    maximum_cost_usd: float
    dry_run: bool = False
    out_of_time: Callable[[], bool] | None = None
    disabled: str | None = None
    streak: int = 0
    last_error: str | None = None
    calls: int = 0
    cost: float = 0.0
    offered: int = 0

    def failed(self, error: Exception, where: str) -> None:
        message = f"{type(error).__name__}: {error}"[:300]
        self.run.setdefault("variationErrors", []).append({"where": where, "error": message})
        self.streak = self.streak + 1 if self.last_error == message else 1
        self.last_error = message
        if self.streak >= 2:
            self.disabled = message

    def succeeded(self) -> None:
        self.streak, self.last_error = 0, None

    def record(self, entry: dict[str, Any], **more: Any) -> dict[str, Any]:
        """Adds this idea's line to the run record and keeps the totals current (``variations``, ``variationsOffered``, ``variationCost``)."""
        entry.update(more)
        self.run.setdefault("variations", []).append(entry)
        self.run["variationsOffered"] = self.offered
        self.run["variationCost"] = {"calls": self.calls, "costUsd": round(self.cost, 6)}
        if self.disabled:
            self.run["variationsDisabled"] = self.disabled
        return entry

    def offer(
        self, *, story_lineage_id: str | None, item: Any, view: dict[str, Any], connections: rules.Connections, knowledge: rules.Knowledge, raw: Mapping[str, Any], draft: Mapping[str, Any],
        record: Mapping[str, Any], verdict: Mapping[str, Any], context: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Offers variation 1 (the idea as filed) and one more for each other connection that has a point of its own. Returns this idea's line of the run record."""
        entry: dict[str, Any] = {"referenceId": item.reference_id, "lineageId": item.lineage_id, "storyLineageId": story_lineage_id, "title": record.get("title"), "offered": [], "dropped": []}
        if self.disabled:
            return self.record(entry, skipped="disabled", error=self.disabled)
        if not self.dry_run and not story_lineage_id:
            return self.record(entry, skipped="no_story")
        try:
            existing = story_variations.variations_of(self.client, story_lineage_id) if (story_lineage_id and not self.dry_run) else []
        except Exception as error:  # noqa: BLE001 - the idea is filed; a read that fails costs the variations only
            self.failed(error, "read")
            return self.record(entry, skipped="read_failed", error=self.last_error)
        if any(row["origin"] == story_variations.GENERATED for row in existing):
            return self.record(entry, skipped="already_offered", offered=[row["id"] for row in existing])
        cited = list(draft.get("citedHandles") or [])
        known = connections.by_handle()
        own = [connection_row(known[handle]) for handle in cited if handle in known and kind_of(known[handle]) is not None]
        own = own or [{"kind": story_variations.REFERENCE, "id": item.lineage_id, "title": item.title, "how": "The item this idea is about"}]
        base = {
            "point": str(raw.get("point") or "").strip(), "headline": draft["headline"]["text"], "deck": draft["dek"]["text"], "body_markus": record.get("body"), "section": record.get("section"),
            "connections": own, "point_check": dict(verdict),
        }
        self.write(story_lineage_id, entry, base, anchor=None)
        if self.disabled:
            return self.record(entry, skipped="write_failed", error=self.disabled)
        try:
            extended = rules.with_options(
                connections, *self.other_ways(item, knowledge, connections, cited))
        except Exception as error:  # noqa: BLE001
            self.failed(error, "options")
            return self.record(entry, options=[], error=self.last_error)
        options = options_for(extended, cited)
        entry["options"] = [option_view(option) for option in options]
        if not options:
            return self.record(entry)
        self.write_others(story_lineage_id, entry, item=item, view=view, extended=extended, options=options, cited=cited, raw=raw, draft=draft, context=context)
        return self.record(entry)

    def other_ways(self, item: Any, knowledge: rules.Knowledge, connections: rules.Connections, cited: Sequence[str]) -> tuple[list[rules.StoryOption], list[rules.ConceptOption]]:
        """The Stories and concepts the Reference could be connected to: what the newsroom already has, read once for the idea."""

        catalogue = knowledge.concept_catalogue_by_lineage()
        concepts = rules.concept_options(knowledge.client, item.lineage_id, catalogue)
        neighbours = [entry.reference for entry in connections.entries if entry.kind == rules.NEIGHBOUR]
        stories = rules.story_options(
            knowledge.client, neighbours=neighbours, concepts=concepts, read_concept_stories=not (self.out_of_time is not None and self.out_of_time()))
        return stories, concepts

    def write(self, story_lineage_id: str | None, entry: dict[str, Any], fields: dict[str, Any], *, anchor: str | None) -> None:
        if self.dry_run:
            entry["offered"].append({"anchor": anchor, "headline": fields["headline"], "point": fields["point"], "connections": fields["connections"], "dryRun": True})
            return
        try:
            row = story_variations.offer_variation(
                self.client, story_lineage_id, run_id=self.run.get("runId"), model=self.model, created_by="AI", origin=story_variations.GENERATED, **fields)
        except story_variations.VariationRefused as refusal:
            entry["dropped"].append({"anchor": anchor, "reason": "refused", "message": str(refusal)})
            return
        except Exception as error:  # noqa: BLE001 - recorded; the same error twice stops the pass
            self.failed(error, "write")
            entry["dropped"].append({"anchor": anchor, "reason": "write_failed", "message": self.last_error})
            return
        self.succeeded()
        self.offered += 1
        entry["offered"].append({"id": row["id"], "variationNumber": row["variationNumber"], "anchor": anchor, "headline": row["headline"], "point": row["point"]})

    def spend(self, usage: synthesis.Usage) -> None:
        self.meter.add(usage.cost_usd)
        self.cost += usage.cost_usd or 0.0
        self.calls += 1
        self.run["modelCalls"].append({"model": self.model, "promptTokens": usage.input_tokens, "completionTokens": usage.output_tokens, "cachedTokens": usage.cached_input_tokens})

    def write_others(
        self, story_lineage_id: str | None, entry: dict[str, Any], *, item: Any, view: dict[str, Any], extended: rules.Connections, options: Sequence[rules.Connection], cited: Sequence[str],
        raw: Mapping[str, Any], draft: Mapping[str, Any], context: Mapping[str, Any],
    ) -> None:
        """One call writes a version for each option; each is then checked like the idea was and offered only if it passes."""
        from .monitor_stories import draft_body, draft_sentences, check_story

        allowed = [section["title"] for section in context.get("sections", [])]
        sentences = draft_sentences(draft)
        prompt = system_prompt()
        options = list(options)
        shown = {
            "mission": context.get("mission"), "policy": context.get("policy"), "allowed_sections": allowed, "source": view,
            "what_the_newsroom_knows": extended.view(),
            "the_idea_as_filed": {"point": str(raw.get("point") or "").strip(), "headline": sentences[0], "dek": sentences[1], "body": sentences[2:]},
        }
        if extended.rating is not None:
            shown["editor_rating"] = {"stars": extended.rating, "of": 5}

        def model_input() -> dict[str, Any]:
            return {**shown, "options": [option_view(option) for option in options]}

        while len(options) > 1 and len(prompt) + len(str(model_input())) > synthesis.MAXIMUM_INPUT_CHARACTERS:
            options.pop()   # a real limit: the model's own. The connections left out are the last ones, which are the weakest (closest first, editors' tags first).
            entry["optionsDropped"] = entry.get("optionsDropped", 0) + 1
        size = len(prompt) + len(str(model_input()))
        if size > synthesis.MAXIMUM_INPUT_CHARACTERS:
            entry["skipped"] = "input_too_large"
            return
        if self.out_of_time is not None and self.out_of_time():
            entry["skipped"] = "time"
            return
        output = min(MAXIMUM_OUTPUT_TOKENS_EACH * len(options), MAXIMUM_OUTPUT_TOKENS)
        estimate = synthesis.estimate_cost_usd(self.model, size, output + len(options) * point_check.MAXIMUM_OUTPUT_TOKENS)
        if estimate is not None and self.meter.spent_usd + estimate > self.maximum_cost_usd:
            entry["skipped"] = "cost"
            entry["stoppedForCost"] = f"The variations are estimated at ${estimate:.4f}; ${self.meter.spent_usd:.4f} is spent of the run's ${self.maximum_cost_usd:.2f}."
            return
        payload = synthesis.request_payload(self.model, model_input()) | {"instructions": prompt, "text": {"format": VARIATION_SCHEMA}, "max_output_tokens": output}
        try:
            body = self.transport(synthesis.RESPONSES_URL, {"Content-Type": "application/json"}, payload)
            text = synthesis.response_text(body)
            if body.get("status") == "incomplete" or text is None:
                raise synthesis.SynthesisError("The model returned no complete answer.")
            try:
                answer = json.loads(text)
            except ValueError as error:
                raise synthesis.SynthesisError("The model did not answer with the variations format.") from error
            written = answer.get("variations") if isinstance(answer, dict) else None
            if not isinstance(written, list):
                raise synthesis.SynthesisError("The model did not answer with a list of variations.")
        except synthesis.SynthesisError as error:
            entry["error"] = str(error)[:300]
            entry["dropped"] += [{"anchor": option.handle, "reason": "model_error"} for option in options]
            return
        except Exception as error:  # noqa: BLE001
            self.failed(error, "model")
            entry["error"] = self.last_error
            return
        usage = synthesis.usage_of(body, self.model)
        self.spend(usage)
        entry["costUsd"] = round(usage.cost_usd or 0.0, 6)
        by_handle = {option.handle: option for option in options}
        seen_headlines = {_plain(sentences[0])}
        seen_points = {_plain(str(raw.get("point") or ""))}
        done: set[str] = set()
        for version in written:
            if self.disabled:
                break
            anchor = str(version.get("anchor") or "").strip() if isinstance(version, dict) else ""
            if anchor not in by_handle or anchor in done:
                entry["dropped"].append({"anchor": anchor or None, "reason": ANCHOR_UNKNOWN})
                continue
            done.add(anchor)
            if not str(version.get("point") or "").strip():
                entry["dropped"].append({"anchor": anchor, "reason": NO_POINT})
                continue
            checked, record = check_story(version, item, view, allowed, extended)
            if checked is None:
                entry["dropped"].append({"anchor": anchor, "reason": "citation_check_failed", "problems": [problem["reason"] for problem in record["problems"]]})
                continue
            if not _cites(checked, anchor):
                entry["dropped"].append({"anchor": anchor, "reason": ANCHOR_NOT_CITED})
                continue
            wording = draft_sentences(checked)
            if _plain(wording[0]) in seen_headlines or _plain(str(version["point"])) in seen_points:
                entry["dropped"].append({"anchor": anchor, "reason": REPEATS_ANOTHER})
                continue
            try:
                verdict, judged = point_check.judge(self.transport, self.model, view, extended.view(), wording)
            except synthesis.SynthesisError as error:
                entry["dropped"].append({"anchor": anchor, "reason": point_check.POINT_CHECK_ERROR, "message": str(error)[:300]})
                continue
            self.spend(judged)
            entry["costUsd"] = round(entry["costUsd"] + (judged.cost_usd or 0.0), 6)
            failed = point_check.failures(verdict)
            self.run["pointChecks"].append({
                "referenceId": item.reference_id, "lineageId": item.lineage_id, "title": item.title, "variation": anchor, "failures": failed, "verdict": verdict, "point": version["point"], "sentences": wording})
            if failed:
                entry["dropped"].append({"anchor": anchor, "reason": "point_check_failed", "failures": failed, "reasonGiven": verdict.get("reason")})
                continue
            seen_headlines.add(_plain(wording[0]))
            seen_points.add(_plain(str(version["point"])))
            ways = [connection_row(extended.by_handle()[handle]) for handle in checked["citedHandles"] if handle in extended.by_handle() and kind_of(extended.by_handle()[handle]) is not None]
            first = connection_row(by_handle[anchor])
            ways.sort(key=lambda row: row != first)
            self.write(story_lineage_id, entry, {
                "point": str(version["point"]).strip(), "headline": wording[0], "deck": wording[1], "body_markus": draft_body(checked, item, extended), "section": checked["section"],
                "connections": ways, "point_check": dict(verdict),
            }, anchor=anchor)
        entry["dropped"] += [{"anchor": option.handle, "reason": "not_answered"} for option in options if option.handle not in done]


def _plain(text: str) -> str:
    return " ".join("".join(character.lower() if character.isalnum() else " " for character in str(text)).split())


def _cites(draft: Mapping[str, Any], anchor: str) -> bool:
    """The dek and at least one body sentence rest on the anchor: the version is built on its connection, not on the others."""
    return anchor in (draft["dek"].get("handles") or []) and any(anchor in sentence.get("handles", []) for paragraph in draft["paragraphs"] for sentence in paragraph)
