"""Translate a whole site: ``papyrus stories localize --all`` (docs/story-translation-procedure.md, "Translating the whole site").

The work is found, not scanned per Story: one paged listing of the published summaries (every projection reads it; each carries its language, its language
group and the source text's hash, the named sweep ``localize-all``) and the desired-state records (``LocalizationRequest``: one row per Story and language)
through the ``localizationRequestsByState`` index, one query per state of its closed set. A Story written in the primary language has an up-to-date translation in a language when its record there names this very text (the same
content hash) and its run finished (saved, held, unchanged or published); a held translation counts, because it waits for a person, not for a machine.
Everything else is remaining work: no record, a record for older text, a run that failed or stopped, a run that never started. Running it again does only
what remains.

Two ways to run the remaining work, as for one Story:

* **in this process** (the default; the operator lane, ``papyrus --auth iam``): each Story's registered procedure runs through the procedure runner's own code
  (``start.run_from_cli``), a few at a time. A failure is that Story's row in the table and the others go on. ``--publish-clean`` then publishes the
  translations whose run saved cleanly.
* **queued for the site's runner** (``--automation ID``): the records are written ``wanted`` with the automation and the publish choice, and the site's
  dispatcher (``dispatch.py``) starts and publishes them, as it does for translate on publish. Nothing waits here.

Publishing goes through ``publish.publishable`` and ``publishing.publish_item`` like every other publish: never a held translation, never when the original
is not published at this text, never in a language the site does not write in.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from .. import request_meter
from ..content_item_lifecycle import is_story_item_type
from ..item_language import bare_group_id, localization_lineage_id
from ..language_serving import serving_languages
from ..story_reporting import published_story_version, story_versions
from . import desired_state
from .publish import publishable

DEFAULT_CONCURRENCY = 3   # runs at a time in this process; each run is mostly waiting for the model, and the site's own limits apply on top
UP_TO_DATE, SAVED, HELD, FAILED, STOPPED, QUEUED, PLANNED, PUBLISHED, NOT_PUBLISHED = (
    "up to date", "saved", "held", "failed", "stopped", "queued", "to do", "published", "not published")


@dataclass
class Job:
    story: str
    language: str
    title: str = ""
    sourceHash: str = ""
    state: str | None = None    # the record's state when one exists for this text
    status: str = PLANNED
    costUsd: float | None = None
    detail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def row(self) -> dict[str, Any]:
        return {"story": self.story, "language": self.language, "status": self.status, "costUsd": self.costUsd, "detail": self.detail, **self.extra}


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("metadata")
    return json.loads(value) if isinstance(value, str) and value.strip() else dict(value or {})


def _never_reported(record: dict[str, Any], now: float) -> bool:
    """A run started and never reported back: it is older than the longest a run may take (the automation's own deadline, as ``automation_gate`` counts a run in flight) plus the grace."""
    from ..automation_gate import _epoch
    from ..automations import MAX_TIMEOUT_SECONDS

    started = _epoch(record.get("updatedAt") or record.get("requestedAt"))
    return started is not None and now - started > MAX_TIMEOUT_SECONDS + 120


def survey(client, settings: dict[str, Any], languages: list[str], *, now: float | None = None) -> list[Job]:
    """Every (published primary Story, language) with its place: ``up to date`` rows carry the record's state, the others are ``to do``."""
    import time

    now = time.time() if now is None else now
    serving = serving_languages(settings)
    tenant_id = getattr(client, "tenant_id", None)
    # The records come through the state index, one query per state of its closed set; the published summaries are the listing every projection reads,
    # read once here as the named sweep "localize-all".
    requests = {row["id"]: row for state in desired_state.STATES for row in client.list_by_index("localizationRequestsByState", state)}
    with request_meter.sweep("localize-all"):
        summaries = client.list_published_item_summaries()
    jobs: list[Job] = []
    for summary in sorted(summaries, key=lambda row: str(row.get("itemLineageId") or row.get("id"))):
        lineage = summary.get("itemLineageId")
        if (summary.get("status") not in (None, "published") or not lineage or summary.get("language") != serving.primary
                or bare_group_id(summary.get("languageGroupId"), tenant_id) != lineage or not is_story_item_type(summary.get("type")) or _metadata(summary).get("doNotLocalize")):
            continue
        source_hash = str(_metadata(summary).get("sourceContentHash") or "")
        for language in languages:
            record = requests.get(desired_state.request_id(lineage, language))
            current = record is not None and str(record.get("sourceContentHash") or "") == source_hash
            job = Job(story=lineage, language=language, title=summary.get("title") or "", sourceHash=source_hash)
            if current and record.get("state") in desired_state.DONE_STATES:
                job.state, job.status = record["state"], UP_TO_DATE
                job.detail = {"held": "held: a person answers its review request", "published": "published"}.get(record["state"], "")
            elif current and record.get("automationId") and (record.get("state") == "wanted" or (
                    record.get("state") == "started" and not _never_reported(record, now))):
                job.state, job.status, job.detail = record["state"], QUEUED, f"{record['state']} on {record['automationId']}"
            elif current:   # the request names this very text, yet does not say its run finished
                _vouched_by_translation(client, job, record, source_hash)
                if job.status == PLANNED and record.get("state") in ("failed", "stopped", "waiting"):
                    job.state, job.detail = record["state"], f"last run {record['state']}: {record.get('reason') or 'no reason recorded'}"[:300]
            jobs.append(job)
    return jobs


def _vouched_by_translation(client, job: Job, record: dict[str, Any], source_hash: str) -> None:
    """A request record that does not say its run finished (a run that crashed after saving, or a newer request that never ran) is not the whole story:
    the translation itself says which text it was made from and how its run ended. When the translation of exactly this text exists and its run saved it
    or held it, there is nothing for a machine to do, and above all a held one is never run again (a new run could replace what a person has yet to answer).
    Only Stories that have a record are read, one lineage each, so this is not a read per Story."""
    versions = story_versions(client, localization_lineage_id(job.story, job.language))
    version = next((row for row in versions if row.get("versionState") == "current"), versions[0] if versions else None)
    if version is None or str(version.get("sourceContentHash") or "") != source_hash:
        return
    outcome = _metadata(version).get("localization", {}).get("outcome")
    if outcome not in ("saved", "held"):
        return
    job.state, job.status = outcome, UP_TO_DATE
    job.detail = (f"held: a person answers its review request (its request record says {record.get('state')})" if outcome == "held"
                  else f"saved (its request record says {record.get('state')})")


def plan_cost(client, jobs: list[Job], *, procedure_key: str | None, ceiling_usd: float | None, collect: Callable[..., Any]) -> dict[str, Any]:
    """Predicts each remaining job's cost from the procedure's measured runs (read once). A job whose language has no measured run has no prediction."""
    from .plan import plan_of
    from .record import spend_history

    history = spend_history(client, procedure_key) if procedure_key else []
    shared: dict[Any, Any] = {}   # what depends only on the site, the section and the language is read once for the whole plan, not once per Story
    total, unknown = 0.0, 0
    for job in jobs:
        if job.status != PLANNED:
            continue
        try:
            plan = plan_of(collect(client, story=job.story, language=job.language, judge=None, procedure_version="plan", ceiling_usd=ceiling_usd,
                                   procedure_key=procedure_key, history=history, shared=shared), story=job.story)
        except Exception as error:   # noqa: BLE001 - one Story that cannot be planned is that Story's row, not the whole plan
            job.detail = f"cannot be planned: {error}"[:300]
            continue
        predicted = (plan["prediction"] or {}).get("predictedUsd")
        job.costUsd, job.extra = predicted, {"blocksToTranslate": plan["blocksToTranslate"]}
        job.detail = "no measured run of this language yet" if predicted is None else ""
        total, unknown = total + (predicted or 0.0), unknown + (predicted is None)
    return {"predictedUsd": round(total, 6), "withoutPrediction": unknown}


def run_one(job: Job, *, client_factory: Callable[[], Any], run: Callable[..., dict[str, Any]], publish: Callable[[Any, Job], None] | None,
            settings: dict[str, Any], ceiling_usd: float | None, procedure_key: str, key: str, requested_by: str = "cli --all") -> Job:
    """Run one Story's translation in this process and, when asked, publish it if it saved cleanly. Never raises: the outcome is the job's row."""
    client = client_factory()
    try:
        source = published_story_version(client, job.story)
        if source is None:
            job.status, job.detail = STOPPED, "the Story is no longer published"
            return job
        desired_state.want(client, source=source, language=job.language, requested_by=requested_by)
        result = run(client, story=job.story, language=job.language, ceiling_usd=ceiling_usd, procedure_key=procedure_key, key=key)
    except Exception as error:   # noqa: BLE001 - isolated: the other Stories go on
        job.status, job.detail = FAILED, f"{type(error).__name__}: {error}"[:300]
        return job
    job.costUsd = result.get("costUsd")
    output = result.get("output") or {}
    if result.get("runStatus") != "completed":
        job.status, job.detail = FAILED, str(result.get("error") or "the run did not complete")[:300]
        return job
    outcome = output.get("outcome")
    job.status = {"saved": SAVED, "held": HELD, "unchanged": UP_TO_DATE}.get(outcome, STOPPED)
    job.detail = str(output.get("reason") or "")[:300]
    if job.status == HELD:
        job.detail = f"held: a person answers its review request ({job.detail})"[:300]
    if publish is not None and job.status in (SAVED, UP_TO_DATE):
        publish(client, job)
    return job


def publish_clean(client, job: Job, settings: dict[str, Any], *, actor: str, project: Callable[[Any, str, str], dict[str, Any]]) -> None:
    """Publish ``job``'s translation when ``publish.publishable`` allows it; sets the job's status and detail. ``project`` builds the page (the CLI's trigger)."""
    from ..publishing import PublishError, publish_item

    record = client.get_record(desired_state.MODEL, desired_state.request_id(job.story, job.language))
    if record is None:
        job.detail = "no request records this translation"
        return
    decision = publishable(client, record, settings)
    if decision.done:
        job.status, job.detail = PUBLISHED, "already published"
        desired_state.record_outcome(client, record, state="published", run_key=record.get("runKey"))
        return
    if decision.version is None:
        job.detail = decision.reason[:300]
        job.status = HELD if decision.held else NOT_PUBLISHED
        return
    try:
        result = publish_item(client, decision.version["id"], actor=actor)
    except PublishError as error:
        job.status, job.detail = NOT_PUBLISHED, f"[{error.code}] {error.message}"[:300]
        return
    shown = project(client, decision.version["id"], result.published_item_id)
    job.status = PUBLISHED
    job.detail = "published" if shown.get("ok") else f"published; the page is not built yet: {shown.get('error')} (retry: papyrus ops content publish --id {decision.version['id']})"[:300]
    desired_state.record_outcome(client, record, state="published", run_key=record.get("runKey"))


def run_all(client, jobs: list[Job], *, client_factory: Callable[[], Any], run: Callable[..., dict[str, Any]], settings: dict[str, Any],
            publish_clean_results: bool, concurrency: int, ceiling_usd: float | None, procedure_key: str, key: str,
            project: Callable[[Any, str, str], dict[str, Any]], actor: str = "papyrus-cli") -> list[Job]:
    """Runs every remaining job in this process, ``concurrency`` at a time, then publishes the clean ones that were already saved (a record whose run
    finished earlier and was never published) when ``publish_clean_results``. Returns the jobs, in the order they were given."""
    def publish(worker_client, job: Job) -> None:
        publish_clean(worker_client, job, settings, actor=actor, project=project)

    todo = [job for job in jobs if job.status == PLANNED]
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        list(pool.map(lambda job: run_one(job, client_factory=client_factory, run=run, publish=publish if publish_clean_results else None,
                                          settings=settings, ceiling_usd=ceiling_usd, procedure_key=procedure_key, key=key), todo))
    if publish_clean_results:
        publish_saved(client, jobs, settings, project=project, actor=actor)
    return jobs


def publish_saved(client, jobs: list[Job], settings: dict[str, Any], *, project: Callable[[Any, str, str], dict[str, Any]], actor: str = "papyrus-cli") -> None:
    """Publishes the translations whose run finished cleanly earlier and were never published (the jobs found up to date in state saved or unchanged)."""
    for job in jobs:
        if job.status == UP_TO_DATE and job.state in ("saved", "unchanged"):
            publish_clean(client, job, settings, actor=actor, project=project)


def queue_all(client, jobs: list[Job], *, automation_id: str, publish: bool, requested_by: str = "cli --all") -> list[Job]:
    """Writes every remaining job's record ``wanted`` with its automation: the site's dispatcher starts the runs (and publishes the clean ones when ``publish``)."""
    for job in jobs:
        if job.status != PLANNED:
            continue
        source = published_story_version(client, job.story)
        if source is None:
            job.status, job.detail = STOPPED, "the Story is no longer published"
            continue
        desired_state.want(client, source=source, language=job.language, requested_by=requested_by, automation_id=automation_id, publish=publish)
        job.status, job.detail = QUEUED, f"queued on {automation_id}"
    return jobs


def table(jobs: list[Job]) -> list[str]:
    """One tab-separated line per job: status, Story, language, cost, detail; then the totals line."""
    lines = [f"{job.status}\t{job.story}\t{job.language}\t{'' if job.costUsd is None else f'${job.costUsd:.4f}'}\t{job.detail}" for job in jobs]
    counts = {status: sum(1 for job in jobs if job.status == status) for status in dict.fromkeys(job.status for job in jobs)}
    spent = sum(job.costUsd or 0.0 for job in jobs if job.status in (SAVED, HELD, FAILED, PUBLISHED))
    lines.append("total\t" + ", ".join(f"{count} {status}" for status, count in counts.items()) + (f"\tcost ${spent:.4f}" if spent else ""))
    return lines
