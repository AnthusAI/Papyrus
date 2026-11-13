"""The three model calls of a translation run: translate, judge, refine (PPY-843a7c).

One client, the OpenAI Responses API with structured output, for all three: the bilingual judge has to be a Python callable (Humanus builds the
judge's prompt and checks its answer but never calls a model), and translate and refine share the run's stored stages and its cost record, so
every model call of a run is made and priced in one place. The model is GPT-6 Luna, the house model for general tasks. The key is the
``OPENAI_API_KEY`` of the process (the procedure runner sets it from the publication's Amplify secret); it is never logged or returned.

Each call's usage goes to :mod:`papyrus_content.model_usage`, so the procedure runner prices the run like any other (``model_cost``). Nothing here
retries a refused or failed call on another model: a call that cannot be made fails the run, which resumes from its stored stages next time.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from ..model_cost import estimate_cost

MODEL = "gpt-6-luna"
RESPONSES_URL = "https://api.openai.com/v1/responses"
REQUEST_TIMEOUT_SECONDS = 300
PROMPT_VERSION = "localize-prompts-1"
TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})

Transport = Callable[[dict[str, Any]], dict[str, Any]]


class ModelUnavailable(RuntimeError):
    """A model call could not be made (no key, the service refused or could not be reached). The run fails with this reason."""


class StructuredOutputMissing(RuntimeError):
    """The model answered without the structured output it was asked for."""


@dataclass
class Spend:
    """Every model call of a run: what it was for and its usage, priced from the Papyrus price table."""

    calls: list[dict[str, Any]] = field(default_factory=list)

    def add(self, purpose: str, model: str, usage: Mapping[str, Any]) -> dict[str, Any]:
        call = {"agent": purpose, "model": model, "provider": "openai", "promptTokens": int(usage.get("input_tokens") or 0),
                "completionTokens": int(usage.get("output_tokens") or 0),
                "cachedTokens": int((usage.get("input_tokens_details") or {}).get("cached_tokens") or 0)}
        self.calls.append(call)
        from .. import model_usage

        model_usage.record(call)
        return call

    @property
    def cost_usd(self) -> float:
        return float(estimate_cost(self.calls)["costUsd"] or 0.0)

    def by_purpose(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for purpose in sorted({call["agent"] for call in self.calls}):
            calls = [call for call in self.calls if call["agent"] == purpose]
            out[purpose] = {"calls": len(calls), "promptTokens": sum(c["promptTokens"] for c in calls),
                            "completionTokens": sum(c["completionTokens"] for c in calls), "costUsd": round(float(estimate_cost(calls)["costUsd"] or 0.0), 6)}
        return out


class LocalizeModels(Protocol):
    model: str

    def translate(self, request: dict[str, Any]) -> dict[str, Any]: ...

    def refine(self, request: dict[str, Any]) -> dict[str, Any]: ...

    def judge(self, prompt: Mapping[str, Any]) -> Mapping[str, Any]: ...


BLOCKS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["blocks"],
    "properties": {"blocks": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "text"],
        "properties": {"id": {"type": "string"}, "text": {"type": "string"}}}}},
}

TRANSLATE_SYSTEM = """You translate one news Story, block by block, from {source_name} ({source}) into {target_name} ({target}).

Input: JSON with the blocks to translate (id, kind, text), neighbouring blocks for context only, the glossary entries that occur in the blocks,
and the language's register notes. Reply with every block to translate, by id, and its translation.

Rules:
- Keep every placeholder such as ⟦3⟧ exactly once, where its content belongs in the sentence. Placeholders stand for links, URLs, citations,
  code and fixed attributes; never translate, drop, repeat or invent one.
- Keep the Markus structure of each block: heading marks, list marks, quote marks, emphasis marks (** and *), directive names and attribute
  names. Translate only the reader-facing text, including the alt, caption and title attribute values.
- After a closing emphasis mark, keep a space or move the punctuation outside the emphasis, so the emphasis still renders.
- Do not add, drop, soften, strengthen or reorder claims. Keep every hedge (may, reportedly, about) at the same strength and every attribution
  (X says, according to) attached to the same speaker.
- Every number, date, amount and unit keeps its value, written the target language's way.
- Names of people, organisations and products stay as written unless the glossary gives an approved form. Use the glossary's approved forms.
- Translate quotations faithfully inside the target language's quotation marks; never polish a quotation.
- Write natural {target_name} as a news editor in that language would, restructuring sentences that would read as a calque.
{register}"""

REFINE_SYSTEM = """You repair blocks of a {target_name} ({target}) translation of a {source_name} ({source}) news Story.

Input: JSON with blocks (id, source text, current translation, and the problems found in it). Reply with every block, by id, and its repaired
translation. Repair exactly the problems listed; change nothing else in the block.

Rules: keep every placeholder such as ⟦3⟧ exactly once; keep the Markus structure and emphasis marks; the repaired block must say exactly what
the source block says: no claim added, dropped, softened or strengthened, every hedge and attribution kept, every number with its value, names
as written unless the glossary approves a local form. Problems about meaning come first. If a problem cannot be repaired without changing
the meaning, keep the current wording.
{register}"""


def _register(notes: list[str]) -> str:
    return ("Register and conventions for this language:\n" + "\n".join(f"- {note}" for note in notes)) if notes else ""


class ResponsesModels:
    """GPT-6 Luna through the Responses API. ``transport`` is replaceable (tests pass a scripted fake; nothing in a test reaches the network)."""

    def __init__(self, spend: Spend, *, transport: Transport | None = None, model: str = MODEL, api_key: str | None = None):
        self.model = model
        self.spend = spend
        self._transport = transport or _openai_transport(api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", ""))

    def _structured(self, purpose: str, system: str, user: str, schema: Mapping[str, Any], name: str) -> dict[str, Any]:
        payload = {"model": self.model, "instructions": system, "input": user, "store": False,
                   "text": {"format": {"type": "json_schema", "name": name, "strict": True, "schema": dict(schema)}}}
        body = self._transport(payload)
        self.spend.add(purpose, str(body.get("model") or self.model), body.get("usage") or {})
        text = _output_text(body)
        if not text:
            raise StructuredOutputMissing(f"the {purpose} model answered without structured output (status {body.get('status')})")
        try:
            return json.loads(text)
        except ValueError as error:
            raise StructuredOutputMissing(f"the {purpose} model's answer is not JSON: {error}") from error

    def translate(self, request: dict[str, Any]) -> dict[str, Any]:
        system = TRANSLATE_SYSTEM.format(register=_register(request.get("registerNotes") or []), **request["languages"])
        return self._structured("translate", system, json.dumps(_without(request, "languages", "registerNotes"), ensure_ascii=False), BLOCKS_SCHEMA, "translation")

    def refine(self, request: dict[str, Any]) -> dict[str, Any]:
        system = REFINE_SYSTEM.format(register=_register(request.get("registerNotes") or []), **request["languages"])
        return self._structured("refine", system, json.dumps(_without(request, "languages", "registerNotes"), ensure_ascii=False), BLOCKS_SCHEMA, "repair")

    def judge(self, prompt: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._structured("judge", prompt["system"], prompt["user"], _strict(prompt["responseSchema"]), "faithfulness_issues")


def _without(request: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: value for key, value in request.items() if key not in keys}


def _strict(schema: Mapping[str, Any]) -> dict[str, Any]:
    """A JSON Schema the Responses API's strict mode accepts: every object closed and every property required (Humanus's judge schema already is,
    except for descriptions and length bounds, which strict mode ignores or refuses)."""
    if isinstance(schema, Mapping):
        out = {key: _strict(value) for key, value in schema.items() if key not in ("minLength", "default")}
        if out.get("type") == "object" and "properties" in out:
            out["required"] = list(out["properties"])
            out["additionalProperties"] = False
        return out
    if isinstance(schema, list):
        return [_strict(item) for item in schema]
    return schema


def _output_text(body: Mapping[str, Any]) -> str | None:
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    for message in body.get("output") or []:
        for part in message.get("content") or []:
            if part.get("type") in ("output_text", "text") and isinstance(part.get("text"), str):
                return part["text"]
    return None


def _openai_transport(api_key: str) -> Transport:
    def send(payload: dict[str, Any]) -> dict[str, Any]:
        if not api_key:
            raise ModelUnavailable("OPENAI_API_KEY is not set in this process, so no model can be called")
        data = json.dumps(payload).encode("utf-8")
        for attempt in (1, 2):   # one more try on a transient answer, as the other Papyrus model clients do (ideas/synthesis.py)
            request = urllib.request.Request(RESPONSES_URL, data=data, method="POST",
                                             headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
            try:
                with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed https URL
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")[:300]
                if error.code not in TRANSIENT_STATUSES or attempt == 2:
                    raise ModelUnavailable(f"the model service answered {error.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                if attempt == 2:
                    raise ModelUnavailable(f"the model service could not be reached ({type(error).__name__})") from None
            time.sleep(3)
        raise ModelUnavailable("the model service could not be reached")

    return send
