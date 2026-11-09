"""The table of topic operations (docs/topics.md; epic PPY-d0f028).

Built the way the image operations are (``images/operations.py``): every topic action is one ``Operation`` here, and the CLI group
``papyrus topics``, the MCP tool schema, the newsroom's TypeScript types, the skill's reference block and docs/topics.md are all generated from
this table by ``scripts/generate-topic-operations.py``. A test fails when any of them differs.

To add or change an operation: edit ``OPERATIONS``, then run ``python scripts/generate-topic-operations.py``.
"""
from __future__ import annotations

from dataclasses import dataclass

from papyrus_content.images.operations import ErrorCode, Example, Operation, choice, flag, many, obj, record, text, whole

from .windows import DEFAULT_WINDOW, PRESETS

STATES = ("pending", "accepted", "rejected")


@dataclass(frozen=True)
class TopicOperation(Operation):
    @property
    def command(self) -> str:
        return " ".join(("papyrus", "topics", *self.cli))


ERRORS = (
    ErrorCode("invalid_input", "The request does not fit the operation's input.", details="path names the field"),
    ErrorCode("unknown_operation", "There is no topic operation by that name.", details="operation, or command for the CLI"),
    ErrorCode("not_implemented", "This operation is described but not built yet.", details="operation"),
    ErrorCode("not_authorized", "You are not an editor or admin of this site."),
    ErrorCode("not_found", "No such section in this publication.", details="section"),
    ErrorCode("engine_failed", "The topic engine could not run, so nothing was modeled and nothing was saved.", retryable=True,
              details="message says why, for example that Biblicus is not installed"),
    ErrorCode("service_unavailable", "A permission or backend check could not be made. Nothing was changed.", retryable=True),
)
ERROR_BY_CODE = {error.code: error for error in ERRORS}
COMMON_ERRORS = ("invalid_input", "not_authorized", "service_unavailable", "not_implemented")

TREND = choice("rising", "falling", "steady", "new")
REFERENCE_EXAMPLE = record({"id": text(), "lineageId": text(), "title": {"type": "string"}, "sourceUri": {"type": "string"},
                            "sourcePublishedAt": {"type": "string"}, "state": choice(*STATES)}, ("id", "lineageId", "title"))
DAY_RANGE = record({"start": text("First day, included (UTC)."), "end": text("Last day, included (UTC)."), "days": whole()}, ("start", "end", "days"))
TOPIC = record({
    "topicId": text("A short id inside this run, such as t1."), "label": text("The three best terms, joined."), "terms": many(text(), "The top terms, best first."),
    "count": whole("How many References of the window are in the topic.", minimum=0),
    "previousCount": whole("How many References of the previous window are in it. Present when a comparison was made.", minimum=0),
    "trend": TREND, "mark": text("The trend as a mark: ▲ rising, ▼ falling, = steady, + new. Never colour alone."),
    "references": many(REFERENCE_EXAMPLE, "A few representative References, the newest first."),
}, ("topicId", "label", "terms", "count", "references"))

OPERATIONS: tuple[TopicOperation, ...] = (
    TopicOperation(
        "topics_model", ("model",), "Find the topics in the References of the last 7, 14 or 28 days, by their source date, and say which are rising or falling.", "read",
        obj({
            "window": choice(*PRESETS, description=f"How far back to look, counted from asOf on each Reference's source date. Default {DEFAULT_WINDOW}."),
            "asOf": text("The last day of the window, YYYY-MM-DD (UTC). Default today."),
            "section": text("Only References filed under this section (its id, slug or name)."),
            "monitor": text("Only References this monitor delivered, for example hn."),
            "states": many(choice(*STATES), "Which votes to include. Default pending and accepted; rejected only when asked for."),
            "minClusterSize": whole("The fewest References in a topic. Default scales with the number of References: the square root, never under 3."),
            "compareTo": choice("previous", "none", description="previous (the default): also read the window just before and mark each topic rising, falling, "
                                                              "steady or new. none: this window only."),
            "maxReferences": whole("A safety stop. Reading ends at this many References, and the result and the log say so. Never a quiet cap; omit it to read the window."),
            "representatives": whole("How many representative References to show per topic. Default 3."),
            "refresh": flag("Model again even when the same question was answered before on the same References."),
        }),
        record({
            "savedId": text("Keeps this run. The same question on the same References gives the same id."),
            "cached": flag("True when an earlier answer was found and nothing was modeled."),
            "engine": record({"name": text(), "version": text()}, ("name", "version")),
            "window": DAY_RANGE, "compareTo": {**DAY_RANGE, "type": ["object", "null"], "description": "The previous window, or null when no comparison was asked for."},
            "filters": record({"section": {"type": ["string", "null"]}, "monitor": {"type": ["string", "null"]}, "states": many(text())}, ("states",)),
            "referencesInWindow": whole("References read and modeled in the window.", minimum=0),
            "referencesInPreviousWindow": {"type": ["integer", "null"]},
            "minClusterSize": whole(), "unassigned": whole("References in the window that fit no topic.", minimum=0),
            "legend": {"type": ["object", "null"], "description": "What each trend mark means."},
            "topics": many(TOPIC, "Biggest first."),
        }, ("savedId", "cached", "window", "referencesInWindow", "minClusterSize", "unassigned", "topics")),
        ("not_found", "engine_failed"),
        (Example({"window": "14d", "section": "ai-models"}, {
            "savedId": "topics-0f3a9c1d2b7e4a65", "cached": False, "engine": {"name": "biblicus-bertopic", "version": "1.15.0"},
            "window": {"start": "2026-10-26", "end": "2026-11-08", "days": 14}, "compareTo": {"start": "2026-10-12", "end": "2026-10-25", "days": 14},
            "filters": {"section": "section-ai-models", "monitor": None, "states": ["accepted", "pending"]},
            "referencesInWindow": 212, "referencesInPreviousWindow": 187, "minClusterSize": 14, "unassigned": 31,
            "legend": {"rising": "▲ rising: a larger share of the window than before", "new": "+ new: nothing like it in the previous window"},
            "topics": [{"topicId": "t1", "label": "open weights, language model, benchmark", "terms": ["open weights", "language model", "benchmark"],
                        "count": 38, "previousCount": 21, "trend": "rising", "mark": "▲",
                        "references": [{"id": "reference-1", "lineageId": "reference-1", "title": "An open weights model tops a benchmark",
                                        "sourceUri": "https://example.invalid/a", "sourcePublishedAt": "2026-11-07T09:00:00Z", "state": "accepted"}]}]}),),
        notes="Reads References through the source-date index (listReferencesByCorpusAndSourcePublishedAt); it never scans the table. A Reference with no "
              "source date, or one that is not ISO text, is not seen. The section is the one the Reference's vote was filed under. The engine reads each "
              "Reference's title and the summary held on its row. The result is kept on this machine under savedId.",
    ),
)

BY_NAME = {operation.name: operation for operation in OPERATIONS}
BY_CLI = {operation.cli: operation for operation in OPERATIONS}


def operation(name: str) -> TopicOperation | None:
    return BY_NAME.get(name)
