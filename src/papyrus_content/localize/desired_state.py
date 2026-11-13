"""The desired-state record that starts a translation run (docs/plans/multilingual-publishing.md, "Once per change, no O(N)").

One ``LocalizationRequest`` row per language group and language (id ``{languageGroupId}#{language}``), holding the newest source version that
should be translated. Whoever wants a translation writes it: ``papyrus stories localize`` today, the English publish next (M2, PPY-251157).
A newer request overwrites the older one (coalescing); a run reads the row before it translates and stops, writing nothing, when the row
names a newer source than the one it was started for, so an out-of-order run never replaces newer work. The run records its outcome on the row
(``state``: wanted, started, saved, held, waiting, failed, stopped, unchanged; ``runKey``; ``reason``), so the row also answers "where does the
Chinese translation of this Story stand".
"""
from __future__ import annotations

from typing import Any

from ..publishing import utc_now_iso

MODEL = "LocalizationRequest"
STATES = ("wanted", "started", "saved", "held", "waiting", "failed", "stopped", "unchanged")


def request_id(language_group: str, language: str) -> str:
    return f"{language_group}#{language}"


def want(client, *, source: dict[str, Any], language: str, requested_by: str, now: str | None = None) -> dict[str, Any]:
    """Writes (or overwrites) the request for ``source`` (the published primary version) in ``language``."""
    now = now or utc_now_iso()
    record = {"id": request_id(source["lineageId"], language), "languageGroupId": source["lineageId"], "language": language,
              "sourceVersionId": source["id"], "sourceVersionNumber": int(source.get("versionNumber") or 0),
              "sourceContentHash": str(source.get("contentHash") or ""), "state": "wanted", "requestedBy": requested_by, "requestedAt": now,
              "runKey": None, "reason": None, "updatedAt": now}
    client.upsert(MODEL, record)
    return record


def current(client, language_group: str, language: str) -> dict[str, Any] | None:
    return client.get_record(MODEL, request_id(language_group, language))


def stale_reason(record: dict[str, Any] | None, source: dict[str, Any]) -> str | None:
    """Why a run for ``source`` must not translate: no request exists, or the request names a newer source. None when it may run."""
    if record is None:
        return "no translation is requested for this Story and language (papyrus stories localize writes the request)"
    if int(record.get("sourceVersionNumber") or 0) > int(source.get("versionNumber") or 0):
        return f"a newer source (version {record['sourceVersionNumber']}) is requested; this run was for version {source.get('versionNumber')}"
    return None


def record_outcome(client, record: dict[str, Any], *, state: str, run_key: str | None = None, reason: str | None = None) -> None:
    if state not in STATES:
        raise ValueError(f"state must be one of {', '.join(STATES)}.")
    client.update_record(MODEL, {"id": record["id"], "state": state, "runKey": run_key, "reason": (reason or None) and reason[:1000],
                                 "updatedAt": utc_now_iso()})
