"""Idea synthesis: one model call that turns a digest into story ideas, and the checks that decide which ideas are kept.

The model sees references by short handles (R1, R2, ...). An idea is kept only if it cites at least two distinct handles that
exist in the digest, every claim it makes cites handles it also lists, its section is one the site has, and it does not use a
banned word. Anything else is dropped and reported with its reason. The model call goes through a ``transport`` so tests never
reach the network.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

DEFAULT_MODEL = "gpt-6-luna"
RESPONSES_URL = "https://api.openai.com/v1/responses"
MINIMUM_CITATIONS = 2
DEFAULT_MAXIMUM_IDEAS = 5
MAXIMUM_TITLE = 200
MAXIMUM_ANGLE = 1500
MAXIMUM_OUTPUT_TOKENS = 6000
MAXIMUM_INPUT_CHARACTERS = 120_000
REQUEST_TIMEOUT_SECONDS = 180
BANNED_WORDS = ("desk",)

#: USD per million tokens. Source: LiteLLM model price table, standard tier, as recorded in Cyclotron on 2026-10-11.
PRICES = {
    "gpt-6-luna": {"input": 0.10, "cached_input": 0.01, "output": 0.50, "source": "LiteLLM model price table (standard tier), read 2026-10-11"},
}

Transport = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]

SYSTEM_PROMPT = """You propose story ideas for a publication. You are given the publication's mission and policy, its allowed sections, a digest of recent references, its recent and in-flight stories, any earlier drafts, and any reviewer feedback.

Each idea must be a synthesis: it connects at least two different references into a story none of them is on its own. Never rewrite a single reference.

Rules:
- Use only what the supplied reference fields say (title, source, summary text, why it was included). If a reference has only a title, keep claims about it at the level of that title. Do not invent facts, numbers, quotes, dates or names.
- Every claim you list must cite one or more handles, and those handles must also be in the idea's cited_references. Put handles only in the cited_references and references fields; in the angle, claims and novelty note refer to sources by their titles or publishers, never by handle (R1).
- The angle is one paragraph in plain words: what the story would say and why those references together support it. Write it as a proposal ("a story on...", "the piece would show..."), never as finished reporting.
- Make no present-tense statement about the publisher's own production systems or results. Anything about them stays out unless a supplied reference says it.
- References with status "pending" are unreviewed: say in the angle that the idea rests on unreviewed references.
- Choose the section from the allowed list, exactly as written.
- The novelty note says what the recent and in-flight stories, earlier drafts and feedback already cover, and why this idea is not that. If it is not clearly different, leave the idea out.
- Follow the mission and policy. Propose as many distinct ideas as the references support, up to maximum_ideas, each built from a different cluster of references; give fewer only when the references really do not support more. Weak or unsupported ideas are worse than none. Never use the word "desk".
"""

SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "name": "story_ideas",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "ideas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "working_title": {"type": "string"},
                        "section": {"type": "string"},
                        "angle": {"type": "string"},
                        "cited_references": {"type": "array", "items": {"type": "string"}},
                        "claims": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"claim": {"type": "string"}, "references": {"type": "array", "items": {"type": "string"}}},
                                "required": ["claim", "references"],
                                "additionalProperties": False,
                            },
                        },
                        "novelty_note": {"type": "string"},
                    },
                    "required": ["working_title", "section", "angle", "cited_references", "claims", "novelty_note"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["ideas"],
        "additionalProperties": False,
    },
}


class SynthesisError(ValueError):
    """The model call failed or returned something that is not a list of ideas."""


@dataclass(frozen=True)
class Usage:
    model: str
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0

    @property
    def cost_usd(self) -> float | None:
        return cost_usd(self)

    def as_dict(self) -> dict[str, Any]:
        price = PRICES.get(self.model)
        return {
            "model": self.model,
            "inputTokens": self.input_tokens,
            "cachedInputTokens": self.cached_input_tokens,
            "outputTokens": self.output_tokens,
            "costUsd": self.cost_usd,
            "priceBasis": price["source"] if price else "no price recorded for this model",
        }


def cost_usd(usage: Usage) -> float | None:
    price = PRICES.get(usage.model)
    if price is None:
        return None
    fresh = max(usage.input_tokens - usage.cached_input_tokens, 0)
    total = fresh * price["input"] + usage.cached_input_tokens * price["cached_input"] + usage.output_tokens * price["output"]
    return round(total / 1_000_000, 6)


def estimate_cost_usd(model: str, input_characters: int, output_tokens: int = MAXIMUM_OUTPUT_TOKENS) -> float | None:
    """An upper-leaning estimate before the call (three characters per token, the whole output allowance used)."""
    return cost_usd(Usage(model, input_tokens=input_characters // 3 + 1, output_tokens=output_tokens))


def handles_for(digest: dict[str, Any]) -> dict[str, str]:
    """Handle (R1, R2, ...) to reference id, in digest order."""
    return {f"R{index}": entry["id"] for index, entry in enumerate(digest["references"], start=1)}


def reference_view(handle: str, entry: dict[str, Any]) -> dict[str, Any]:
    view = {
        "handle": handle,
        "title": entry["title"],
        "source": entry.get("source"),
        "status": entry.get("status"),
        "arrived": (entry.get("arrivedAt") or "")[:10] or None,
        "why_included": entry.get("whyIncluded"),
        "section": entry.get("section"),
        "label": entry.get("label"),
    }
    if entry.get("summary"):
        view["summary"] = entry["summary"]
    if entry.get("entities"):
        view["entities"] = entry["entities"]
    return {key: value for key, value in view.items() if value not in (None, "")}


def build_input(digest: dict[str, Any], context: dict[str, Any], feedback: list[dict[str, Any]], maximum: int) -> dict[str, Any]:
    handles = handles_for(digest)
    by_id = {entry["id"]: entry for entry in digest["references"]}
    model_input = {
        "publication": digest["publication"],
        "mission": context.get("mission"),
        "policy": context.get("policy"),
        "allowed_sections": [section["title"] for section in context.get("sections", [])],
        "maximum_ideas": maximum,
        "references": [reference_view(handle, by_id[identifier]) for handle, identifier in handles.items()],
        "earlier_drafts": [
            {key: draft.get(key) for key in ("title", "state", "angle") if draft.get(key)} for draft in context.get("drafts", [])
        ],
        "reviewer_feedback": feedback,
    }
    model_input["recent_and_in_flight_stories"] = fit_stories(model_input, context)
    return model_input


STORY_VIEW_FIELDS = ("title", "section", "state", "date", "summary")


def fit_stories(model_input: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    """The stories for a prompt, newest first, as many as fit ``MAXIMUM_INPUT_CHARACTERS`` after everything else in ``model_input`` (source text first).
    Dedupe still compares against every story; only the prompt is bounded. The smallest count any prompt got is kept in ``context['promptStories']``."""
    remaining = MAXIMUM_INPUT_CHARACTERS - len(json.dumps(model_input, ensure_ascii=False, separators=(",", ":")))
    fitted: list[dict[str, Any]] = []
    for story in context.get("stories", []):
        view = {key: story.get(key) for key in STORY_VIEW_FIELDS if story.get(key)}
        remaining -= len(json.dumps(view, ensure_ascii=False, separators=(",", ":"))) + 1
        if remaining < 0:
            break
        fitted.append(view)
    context["promptStories"] = min(len(fitted), context.get("promptStories", len(fitted)))
    return fitted


def request_payload(model: str, model_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": model,
        "instructions": SYSTEM_PROMPT,
        "input": json.dumps(model_input, ensure_ascii=False, separators=(",", ":")),
        "text": {"format": SCHEMA},
        "max_output_tokens": MAXIMUM_OUTPUT_TOKENS,
        "store": False,
    }


def openai_transport(api_key: str) -> Transport:
    def send(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode()
        last: Exception | None = None
        for attempt in range(2):
            request = urllib.request.Request(url, data=body, headers={**headers, "Authorization": f"Bearer {api_key}"}, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed https URL
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")[:300]
                last = SynthesisError(f"The model service answered {error.code}: {detail}")
                if error.code not in {429, 500, 502, 503, 504} or attempt:
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                last = SynthesisError(f"The model service could not be reached ({type(error).__name__}).")
                if attempt:
                    break
            time.sleep(3)
        assert last is not None
        raise last

    return send


def response_text(body: dict[str, Any]) -> str | None:
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    for message in body.get("output") or []:
        for part in message.get("content") or []:
            if part.get("type") in {"output_text", "text"} and isinstance(part.get("text"), str):
                return part["text"]
    return None


def usage_of(body: dict[str, Any], model: str) -> Usage:
    usage = body.get("usage") or {}
    return Usage(
        model=model,
        input_tokens=int(usage.get("input_tokens") or 0),
        cached_input_tokens=int((usage.get("input_tokens_details") or {}).get("cached_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
    )


def call_model(transport: Transport, model: str, model_input: dict[str, Any]) -> tuple[list[dict[str, Any]], Usage]:
    body = transport(RESPONSES_URL, {"Content-Type": "application/json"}, request_payload(model, model_input))
    text = response_text(body)
    if body.get("status") == "incomplete" or text is None:
        raise SynthesisError("The model returned no complete answer.")
    try:
        ideas = json.loads(text)["ideas"]
    except (ValueError, KeyError, TypeError) as error:
        raise SynthesisError("The model did not answer with the story ideas format.") from error
    if not isinstance(ideas, list):
        raise SynthesisError("The model did not answer with a list of ideas.")
    return ideas, usage_of(body, model)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def validate_ideas(
    raw: list[Any], handles: dict[str, str], allowed_sections: list[str], maximum: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(valid ideas with real reference ids, dropped ideas with their reason). The first ``maximum`` valid ideas are kept."""
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    sections = {section.strip().lower(): section for section in allowed_sections}

    def reject(item: Any, reason: str) -> None:
        title = str(item.get("working_title")) if isinstance(item, dict) else ""
        invalid.append({"title": title[:MAXIMUM_TITLE], "reason": reason})

    for item in raw:
        if not isinstance(item, dict):
            reject(item, "not_an_object")
            continue
        title, angle, note = (str(item.get(key) or "").strip() for key in ("working_title", "angle", "novelty_note"))
        cited = [str(handle).strip() for handle in item.get("cited_references") or []]
        unknown = sorted({handle for handle in cited if handle not in handles})
        claims = item.get("claims") or []
        if not title or not angle or not note:
            reject(item, "missing_title_angle_or_novelty_note")
        elif len(title) > MAXIMUM_TITLE or len(angle) > MAXIMUM_ANGLE:
            reject(item, "title_or_angle_too_long")
        elif unknown:
            reject(item, f"cites_unknown_references:{','.join(unknown)}")
        elif len(set(cited)) < MINIMUM_CITATIONS:
            reject(item, "fewer_than_two_citations")
        elif not claims or not all(isinstance(claim, dict) and str(claim.get("claim") or "").strip() for claim in claims):
            reject(item, "no_claims")
        elif any(not claim.get("references") or not set(claim["references"]) <= set(cited) for claim in claims):
            reject(item, "claim_cites_a_reference_the_idea_does_not_list")
        elif sections and str(item.get("section") or "").strip().lower() not in sections:
            reject(item, "unknown_section")
        elif _words(f"{title} {angle} {note} " + " ".join(str(c["claim"]) for c in claims)) & set(BANNED_WORDS):
            reject(item, "banned_word")
        else:
            section = sections.get(str(item["section"]).strip().lower(), str(item["section"]).strip())
            ordered = list(dict.fromkeys(cited))
            valid.append(
                {
                    "title": title,
                    "angle": angle,
                    "section": section,
                    "noveltyNote": note,
                    "citedReferenceIds": [handles[handle] for handle in ordered],
                    "claims": [
                        {"claim": str(claim["claim"]).strip(), "referenceIds": [handles[handle] for handle in dict.fromkeys(claim["references"])]}
                        for claim in claims
                    ],
                }
            )
    for extra in valid[maximum:]:
        invalid.append({"title": extra["title"], "reason": "over_the_maximum"})
    return valid[:maximum], invalid
