"""AI moderation: a model reads each new submission and comment and answers allow or hide, with a reason.

The decision is applied as an ordinary moderation action marked ``by: "ai"``, so it appears in the log, shows in the panel,
and a human can undo it or decide differently. A human decision always stands: an item a person has acted on is never
judged by the model again. A model that fails, times out or answers something that is not a valid verdict leaves the item
in the human queue.

Secrets: the API key is read from an SSM SecureString at the start of a run and lives only in the object that makes the
request. It is never logged, never put in a returned value and never in an error message (errors are reported by class name).
Tests stub the model; nothing in the tests, CI or this module's defaults makes a paid call.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import moderation as rules

PROMPT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "moderation-prompt.md")
DEFAULT_MODEL = "gpt-6-luna"
RESPONSES_URL = "https://api.openai.com/v1/responses"
ALLOW, HIDE = "allow", "hide"
MAXIMUM_REASON = 200
MAXIMUM_TEXT = 4000
BATCH_LIMIT = 25
CONSECUTIVE_FAILURES_BEFORE_STOPPING = 3
REQUEST_TIMEOUT_SECONDS = 20
AI_ACTOR = "ai"
REASON_PREFIX = "AI: "
PARAMETER_NAME = re.compile(r"/papyrus/[a-z0-9][a-z0-9-]{0,62}/openai-api-key")


class ModelOutputError(ValueError):
    pass


@dataclass(frozen=True)
class Verdict:
    decision: str
    reason: str


class ModerationModel(Protocol):
    def judge(self, item: dict[str, Any]) -> Verdict: ...


def load_prompt(path: str = PROMPT_FILE) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read().strip()


def parse_verdict(text: Any) -> Verdict:
    """A strict reading of the model's answer: one JSON object, ``decision`` allow or hide, a short plain reason."""
    if not isinstance(text, str):
        raise ModelOutputError("the model answered nothing")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ModelOutputError("the model did not answer with a JSON object")
    try:
        data = json.loads(text[start : end + 1])
    except ValueError as error:
        raise ModelOutputError("the model's answer is not valid JSON") from error
    decision, reason = data.get("decision") if isinstance(data, dict) else None, data.get("reason") if isinstance(data, dict) else None
    if decision not in (ALLOW, HIDE):
        raise ModelOutputError("the decision is neither allow nor hide")
    if not isinstance(reason, str) or not reason.strip():
        raise ModelOutputError("the model gave no reason")
    return Verdict(decision, " ".join(reason.split())[:MAXIMUM_REASON])


def response_text(body: Any) -> str | None:
    """The text of a Responses API answer: ``output_text`` when present, else the text parts of the output messages."""
    if not isinstance(body, dict):
        return None
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    parts = [
        part.get("text")
        for message in body.get("output") or []
        if isinstance(message, dict)
        for part in message.get("content") or []
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ]
    return "".join(parts) if parts else None


def urllib_transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310 - a fixed https endpoint
        return json.loads(response.read().decode("utf-8"))


class OpenAIModerationModel:
    """GPT-6 Luna (``moderation.ai.model``) through the OpenAI Responses API. The key is held here and nowhere else."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        prompt: str | None = None,
        transport: Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]] = urllib_transport,
    ) -> None:
        if not api_key:
            raise ValueError("an API key is required")
        self._api_key = api_key
        self._model = model
        self._prompt = prompt if prompt is not None else load_prompt()
        self._transport = transport

    def request_payload(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": self._model,
            "instructions": self._prompt,
            "input": json.dumps(item, ensure_ascii=False, separators=(",", ":")),
            "text": {"format": {"type": "json_object"}},
            "max_output_tokens": 300,
            "store": False,
        }

    def judge(self, item: dict[str, Any]) -> Verdict:
        body = self._transport(RESPONSES_URL, {"authorization": f"Bearer {self._api_key}", "content-type": "application/json"}, self.request_payload(item))
        return parse_verdict(response_text(body))


def model_input(kind: str, row: dict[str, Any]) -> dict[str, Any]:
    """What the model sees: the content, the automatic signals and the report count. Never a reader id, a handle or a siteSubject."""
    signals = row.get("signals")
    if isinstance(signals, str):
        try:
            signals = json.loads(signals)
        except ValueError:
            signals = []
    listed = [
        {"policy": str(signal.get("policy", ""))[:60], "detector": str(signal.get("detector", ""))[:60], "severity": str(signal.get("severity", ""))[:12]}
        for signal in (signals if isinstance(signals, list) else [])
        if isinstance(signal, dict)
    ][:20]
    if kind == rules.TARGET_SUBMISSION:
        item: dict[str, Any] = {"kind": "submission", "title": row["title"], "url": row["canonicalUrl"], "domain": row["domain"], "text": row.get("note") or ""}
    else:
        item = {"kind": "comment", "text": row["body"]}
    item["text"] = str(item["text"])[:MAXIMUM_TEXT]
    item["signals"] = listed
    item["reports"] = int(row.get("reportCount") or 0)
    return item


@dataclass
class AiReport:
    judged: int = 0
    allowed: int = 0
    hidden: int = 0
    skipped_human: int = 0
    errors: dict[str, int] = field(default_factory=dict)
    stopped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"judged": self.judged, "allowed": self.allowed, "hidden": self.hidden, "skippedHuman": self.skipped_human, "errors": dict(self.errors), "stopped": self.stopped}


class AiStore(Protocol):
    def new_content(self) -> list[tuple[str, dict[str, Any]]]: ...

    def human_acted_on(self) -> set[str]: ...


def run_ai_moderation(
    store: Any,
    model: ModerationModel,
    *,
    now: Callable[[], float],
    settings: rules.ModerationSettings,
    deadline: float,
    limit: int = BATCH_LIMIT,
    iso: Callable[[float], str],
) -> AiReport:
    """Judges the oldest new items first, until the batch limit, the deadline, or three failures in a row."""
    report = AiReport()
    human_targets = store.human_acted_on()
    failures_in_a_row = 0
    candidates = sorted(store.new_content(), key=lambda entry: (entry[1]["createdAt"], entry[1]["id"]))
    for kind, row in candidates:
        if report.judged >= limit or now() >= deadline:
            break
        if row["id"] in human_targets:
            report.skipped_human += 1
            continue
        if row.get("state") == "deleted":
            continue
        try:
            verdict = model.judge(model_input(kind, row))
        except Exception as error:  # noqa: BLE001 - reported by class name only: a message could carry the key or the content
            report.errors[type(error).__name__] = report.errors.get(type(error).__name__, 0) + 1
            failures_in_a_row += 1
            if failures_in_a_row >= CONSECUTIVE_FAILURES_BEFORE_STOPPING:
                report.stopped = True
                break
            continue
        failures_in_a_row = 0
        action = rules.APPROVE if verdict.decision == ALLOW else rules.HIDE
        outcome = rules.apply_action(
            store,
            action=action,
            target_type=kind,
            target=row["id"],
            reason=REASON_PREFIX + verdict.reason,
            undo_of=None,
            actor_sub=AI_ACTOR,
            by=rules.BY_AI,
            now_iso=iso(now()),
            settings=settings,
        )
        if outcome.status != "ok":
            report.errors[outcome.error or "refused"] = report.errors.get(outcome.error or "refused", 0) + 1
            continue
        report.judged += 1
        if action == rules.APPROVE:
            report.allowed += 1
        else:
            report.hidden += 1
    return report
