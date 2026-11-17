"""The desired-state record that starts a translation run (docs/plans/multilingual-publishing.md, "Once per change, no O(N)").

One ``LocalizationRequest`` row per language group and language (id ``{languageGroupId}#{language}``), holding the newest source version that
should be translated. Whoever wants a translation writes it: ``papyrus stories localize`` today, the English publish next (M2, PPY-251157).
A newer request overwrites the older one (coalescing); a run reads the row before it translates and stops, writing nothing, when the row
names a newer source than the one it was started for, so an out-of-order run never replaces newer work. The run records its outcome on the row
(``state``: wanted, started, saved, held, waiting, failed, stopped, unchanged, published; ``runKey``; ``reason``), so the row also answers "where does the
Chinese translation of this Story stand". The row is also the queue of the automatic trigger (``auto.py``, ``dispatch.py``): ``wanted`` rows are the
runs still to start (the ``localizationRequestsByState`` index finds them without reading the table), ``automationId`` names the Automation that runs
them and ``publish`` says the run's clean result is published when it is saved.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:   # as publishing.utc_now_iso, kept here so the dispatcher's small bundle does not import the publish path
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


MODEL = "LocalizationRequest"
STATES = ("wanted", "started", "saved", "held", "waiting", "failed", "stopped", "unchanged", "published")
#: States of a request whose translation exists for the source it names (the run finished, whatever came after): nothing is left to run.
DONE_STATES = ("saved", "held", "unchanged", "published")


def request_id(language_group: str, language: str) -> str:
    return f"{language_group}#{language}"


def _record(source: dict[str, Any], language: str, requested_by: str, now: str, **fields: Any) -> dict[str, Any]:
    return {"id": request_id(source["lineageId"], language), "languageGroupId": source["lineageId"], "language": language,
            "sourceVersionId": source["id"], "sourceVersionNumber": int(source.get("versionNumber") or 0),
            "sourceContentHash": str(source.get("contentHash") or ""), "requestedBy": requested_by, "requestedAt": now, "updatedAt": now, **fields}


def want(client, *, source: dict[str, Any], language: str, requested_by: str, automation_id: str | None = None, publish: bool = False,
         now: str | None = None) -> dict[str, Any]:
    """Writes (or overwrites) the request for ``source`` (the published primary version) in ``language``. ``automation_id`` names the Automation that runs
    it (the automatic trigger and the dispatcher read it); ``publish`` asks for a clean result to be published when the run saves it."""
    from ..authored_editions import require_translation_owned
    require_translation_owned(client, source["lineageId"], language)
    now = now or utc_now_iso()
    record = _record(source, language, requested_by, now, state="wanted", runKey=None, reason=None, automationId=automation_id, publish=publish)
    client.upsert(MODEL, record)
    return record


def settled(client, *, source: dict[str, Any], language: str, requested_by: str, state: str, run_key: str, reason: str | None = None,
            now: str | None = None) -> dict[str, Any]:
    """Writes the request for ``source`` and ``language`` already finished (``saved`` or ``held``), for a translation that was not made by a run: finished
    copy a person or an agent wrote (``import_copy``). The request names no automation and never asks for a publish, so the dispatcher leaves it alone, and
    ``papyrus stories localize --all`` counts the language of this Story as up to date for exactly this source text."""
    if state not in ("saved", "held"):
        raise ValueError("A request settled without a run is saved or held.")
    now = now or utc_now_iso()
    record = _record(source, language, requested_by, now, state=state, runKey=run_key, reason=(reason or None) and reason[:1000], automationId=None, publish=False)
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


def record_outcome(client, record: dict[str, Any], *, state: str, run_key: str | None = None, reason: str | None = None) -> bool:
    """Records where the request stands, unless it has moved on: a request that now names a newer source belongs to the newer run, and an older run
    must not mark it saved. Returns whether the outcome was written."""
    if state not in STATES:
        raise ValueError(f"state must be one of {', '.join(STATES)}.")
    latest = client.get_record(MODEL, record["id"])
    if latest is not None and int(latest.get("sourceVersionNumber") or 0) != int(record.get("sourceVersionNumber") or 0):
        return False
    client.update_record(MODEL, {"id": record["id"], "state": state, "runKey": run_key, "reason": (reason or None) and reason[:1000],
                                 "updatedAt": utc_now_iso()})
    return True


def wanted(client) -> list[dict[str, Any]]:
    """The requests whose run has not started, oldest first, read from the state index (never the whole table)."""
    return sorted(client.list_by_index("localizationRequestsByState", "wanted"), key=lambda row: str(row.get("requestedAt") or ""))
