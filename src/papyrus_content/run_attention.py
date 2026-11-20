"""The runs that need a person, as one sparse index (PPY-577310, slice A5).

A finished run needs a person when its outcome is `failed` or `unknown` and nobody has acknowledged it. Such a run carries
`attentionKey` (the constant `attention`, with the tenant in front on a shared stack) and `dueAt` (when it needed attention: its
finish time). A run that needs nobody has neither, so DynamoDB leaves it out of the index `listProcedureRunsByAttentionKeyAndDueAt`
and Today and the overdue check read only what needs a person (docs/design/always-on-agents-architecture.md sections 3.6 and 7.1).

Acknowledging a run clears both fields in one update and records who and when; the run stays as history. Acknowledging a run
that needs nobody changes nothing.

The wait kinds of the design (`waiting`) belong to records that wait, which keep their own due indexes (a Delivery's `dueKey`); a run
that has asked a person waits on a review request, which is read from the review request index. A `waiting` run is not a state the
runner writes, so this index holds the two outcomes that need a person to look.
"""
from __future__ import annotations

from typing import Any

from .tenant_knowledge_keys import global_key

ATTENTION = "attention"
ATTENTION_OUTCOMES = ("failed", "unknown")
INDEX = "procedureRunsByAttention"
MODEL = "ProcedureRun"


class AttentionError(ValueError):
    """The request names a run that does not exist or has no id."""


def attention_key() -> str:
    return global_key(ATTENTION)


def needs_attention(run: dict[str, Any]) -> bool:
    return run.get("outcome") in ATTENTION_OUTCOMES and not run.get("acknowledgedAt")


def attention_fields(outcome: str | None, finished_at: str | None) -> dict[str, Any]:
    """The fields a run's finishing write carries: the key and time when the outcome needs a person, nothing otherwise.

    Nothing is sent for a run that needs nobody, so the run is never written with an empty key. A finished run has no earlier key to clear."""
    if outcome in ATTENTION_OUTCOMES and finished_at:
        return {"attentionKey": attention_key(), "dueAt": finished_at}
    return {}


def list_attention(client) -> list[dict[str, Any]]:
    """Every run that needs a person, oldest first: one key-condition query on the sparse index."""
    return sorted(client.list_by_index(INDEX, attention_key()), key=lambda run: str(run.get("dueAt") or ""))


def acknowledge(client, run_id: str, by: str, now: str) -> dict[str, Any]:
    """Take a run off the attention list. Clears the key and time and records who and when; says whether anything changed."""
    if not run_id:
        raise AttentionError("acknowledging a run needs its run id.")
    run = client.get_record(MODEL, run_id)
    if not run:
        raise AttentionError(f"run {run_id} does not exist.")
    if not run.get("attentionKey"):
        return {"runId": run_id, "changed": False, "reason": "acknowledged already" if run.get("acknowledgedAt") else "needs nobody"}
    client.update_record(MODEL, {"id": run_id, "attentionKey": None, "dueAt": None, "acknowledgedAt": now, "acknowledgedBy": by})
    return {"runId": run_id, "changed": True, "reason": None}
