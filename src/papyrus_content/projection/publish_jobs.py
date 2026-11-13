"""Page builds of a publish as jobs: started at once, joined by a retry of the same story, queued when the site is busy, and asked about later.

AppSync gives a Lambda resolver about 30 seconds, and building the pages of a publish on a large site can take longer, so a publish that waits
for its pages always looked like a failure to its caller even though the function finished the work later (PPY-4611d5). And a retry that
arrived while the first build ran waited 120 seconds for the projection lease and then failed. So a publish that asks for it (the CLI) gets
its answer as soon as the data is saved and the build is started, with a job id it can ask about.

The records live in the projection lock table (hash key ``publication``), which the content-actions function already reads and writes with
``GetItem``, ``PutItem``, ``UpdateItem`` and ``DeleteItem``; no new table, index or permission:

* ``<bucket>#publish-job#<item id>``: the item's latest job: ``jobId``, ``state`` (``queued``, ``running``, ``done``, ``failed``), the published
  ``version`` it was asked for, ``requestedAt``, ``startedAt``, ``finishedAt``, ``updatedAt`` (epoch seconds), and when it finished the outcome the
  caller reports (``outcome``: pages written, the page's own paths and URL, the edge purge, an error). A record expires (``expiresAt``) after a day.
* ``<bucket>#publish-queue``: the string set ``items`` of the items waiting for a build. A build that finds the lease held leaves its item
  there; whoever holds the lease builds what is queued before it lets go.

A request for an item whose job is still ``queued`` joins it (that job reads the data when it starts, so it builds the newest version), and so
does a request for the version a ``running`` job is already building. Anything else starts a new job. A job not touched for
``STALE_SECONDS`` (longer than any function may run) is treated as gone.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any

JOB_INFIX = "#publish-job#"
QUEUE_SUFFIX = "#publish-queue"
QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"
STALE_SECONDS = 15 * 60
RECORD_LIFETIME_SECONDS = 24 * 60 * 60
CONDITION_FAILED = "ConditionalCheckFailedException"
OUTCOME_PATH_LIMIT = 200


def _is_condition_failure(error: Exception) -> bool:
    return getattr(error, "response", {}).get("Error", {}).get("Code") == CONDITION_FAILED


def _plain(value: Any) -> Any:
    """DynamoDB numbers come back as Decimal: make a record JSON-able."""
    from decimal import Decimal

    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: _plain(entry) for key, entry in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(entry) for entry in value]
    return value


class PublishJobs:
    def __init__(self, table: Any, bucket: str, *, clock: Callable[[], float] = time.time, new_id: Callable[[], str] = lambda: uuid.uuid4().hex) -> None:
        self.table, self.bucket, self.clock, self.new_id = table, bucket, clock, new_id

    def job_key(self, item_id: str) -> str:
        return f"{self.bucket}{JOB_INFIX}{item_id}"

    @property
    def queue_key(self) -> str:
        return f"{self.bucket}{QUEUE_SUFFIX}"

    # ------------------------------------------------------------------ reading

    def status(self, item_id: str) -> dict | None:
        """The item's latest job, or None. ``stale`` is added when a queued or running job has not been touched for ``STALE_SECONDS``."""
        found = self.table.get_item(Key={"publication": self.job_key(item_id)}, ConsistentRead=True).get("Item")
        if not found:
            return None
        record = _plain({key: value for key, value in found.items() if key not in ("publication", "expiresAt")})
        if record.get("state") in (QUEUED, RUNNING) and self.clock() - float(record.get("updatedAt") or 0) > STALE_SECONDS:
            record["stale"] = True
        return record

    def queued_items(self) -> set[str]:
        found = self.table.get_item(Key={"publication": self.queue_key}, ConsistentRead=True).get("Item") or {}
        return {str(item) for item in found.get("items") or ()}

    # ------------------------------------------------------------------ writing

    def request(self, item_id: str, version: int | None, *, announce: Mapping[str, Any] | None = None, queue: bool = True) -> tuple[dict, bool]:
        """``(job, joined)``: the job that will build this item's pages, and whether it was already there (nothing new to start).

        ``queue=False`` is for a job that is not one story's build (a page re-render, keyed by its own request): it has a record to ask about
        but is not added to the build queue the lease holder drains.

        ``announce`` (``{"publishedItemId": ...}``) marks a real publish: the job tells the newsletter once the page is live. A queued job that is
        joined takes the mark over, since it builds the newest version."""
        for _attempt in range(3):
            current = self.status(item_id)
            if current is not None and not current.get("stale"):
                if current.get("state") == QUEUED:
                    if announce:
                        self._set_announcement(item_id, current["jobId"], announce)
                    return current, True
                if current.get("state") == RUNNING and version is not None and current.get("version") == version:
                    return current, True
            now = self.clock()
            job = {"jobId": self.new_id(), "itemId": item_id, "state": QUEUED, "version": version, "requestedAt": now, "updatedAt": now}
            if announce:
                job["announce"] = dict(announce)
            condition: dict[str, Any] = (
                {"ConditionExpression": "attribute_not_exists(publication)"}
                if current is None
                else {"ConditionExpression": "jobId = :seen", "ExpressionAttributeValues": {":seen": current["jobId"]}}
            )
            try:
                self.table.put_item(Item={"publication": self.job_key(item_id), **self._numbers(job), "expiresAt": int(now + RECORD_LIFETIME_SECONDS)}, **condition)
            except Exception as error:  # noqa: BLE001
                if _is_condition_failure(error):
                    continue   # someone else started or moved a job for this item meanwhile: look again (usually to join it)
                raise
            if queue:
                self.enqueue(item_id)
            return job, False
        current = self.status(item_id)
        return (current or {"itemId": item_id, "state": QUEUED}), True

    def enqueue(self, item_id: str) -> None:
        self.table.update_item(
            Key={"publication": self.queue_key}, UpdateExpression="ADD #items :item",
            ExpressionAttributeNames={"#items": "items"}, ExpressionAttributeValues={":item": {item_id}},
        )

    def take(self, item_id: str) -> None:
        """Take an item out of the queue: its build is starting now."""
        self.table.update_item(
            Key={"publication": self.queue_key}, UpdateExpression="DELETE #items :item",
            ExpressionAttributeNames={"#items": "items"}, ExpressionAttributeValues={":item": {item_id}},
        )

    def start(self, item_id: str, job_id: str | None) -> str:
        """Mark the item's job running (a build with no job of its own, such as a drained one or the newsroom's own publish, gets one). Returns the job id."""
        now = self.clock()
        job_id = job_id or (self.status(item_id) or {}).get("jobId") or self.new_id()
        self.table.update_item(
            Key={"publication": self.job_key(item_id)},
            UpdateExpression="SET jobId = :job, itemId = :item, #state = :running, startedAt = :now, updatedAt = :now, expiresAt = :expires REMOVE outcome",
            ExpressionAttributeNames={"#state": "state"},
            ExpressionAttributeValues={":job": job_id, ":item": item_id, ":running": RUNNING, ":now": self._number(now), ":expires": int(now + RECORD_LIFETIME_SECONDS)},
        )
        return job_id

    def finish(self, item_id: str, job_id: str, *, ok: bool, outcome: Mapping[str, Any]) -> None:
        """Record how the build ended, unless a newer job for the item started meanwhile (then that one reports)."""
        now = self.clock()
        kept = dict(outcome)
        for key in ("paths", "itemPaths"):
            if isinstance(kept.get(key), list) and len(kept[key]) > OUTCOME_PATH_LIMIT:
                kept[key] = kept[key][:OUTCOME_PATH_LIMIT]
        try:
            self.table.update_item(
                Key={"publication": self.job_key(item_id)},
                UpdateExpression="SET #state = :state, finishedAt = :now, updatedAt = :now, outcome = :outcome",
                ConditionExpression="jobId = :job",
                ExpressionAttributeNames={"#state": "state"},
                ExpressionAttributeValues={":state": DONE if ok else FAILED, ":now": self._number(now), ":outcome": self._numbers(kept), ":job": job_id},
            )
        except Exception as error:  # noqa: BLE001
            if not _is_condition_failure(error):
                raise

    def announcement(self, item_id: str) -> dict | None:
        """The newsletter mark of the item's job (see :meth:`request`), or None."""
        found = (self.status(item_id) or {}).get("announce")
        return dict(found) if isinstance(found, dict) else None

    def _set_announcement(self, item_id: str, job_id: str, announce: Mapping[str, Any]) -> None:
        try:
            self.table.update_item(
                Key={"publication": self.job_key(item_id)}, UpdateExpression="SET announce = :announce", ConditionExpression="jobId = :job",
                ExpressionAttributeValues={":announce": dict(announce), ":job": job_id},
            )
        except Exception as error:  # noqa: BLE001
            if not _is_condition_failure(error):
                raise

    def touch(self, item_id: str, job_id: str) -> None:
        """Keep a queued job fresh while it waits for the lease (so a request still joins it rather than starting another)."""
        try:
            self.table.update_item(
                Key={"publication": self.job_key(item_id)}, UpdateExpression="SET updatedAt = :now", ConditionExpression="jobId = :job",
                ExpressionAttributeValues={":now": self._number(self.clock()), ":job": job_id},
            )
        except Exception as error:  # noqa: BLE001
            if not _is_condition_failure(error):
                raise

    # ------------------------------------------------------------------ DynamoDB numbers

    @staticmethod
    def _number(value: float):
        from decimal import Decimal

        return Decimal(str(round(value, 3)))

    @classmethod
    def _numbers(cls, value: Any) -> Any:
        if isinstance(value, float):
            return cls._number(value)
        if isinstance(value, dict):
            return {key: cls._numbers(entry) for key, entry in value.items() if entry is not None}
        if isinstance(value, (list, tuple)):
            return [cls._numbers(entry) for entry in value]
        return value


def publish_jobs_from_environment(environ: Mapping[str, str] | None = None, *, table: Any = None) -> PublishJobs | None:
    """The jobs of this site's bucket in the lock table, or None where there is no lock table (a local run): then a publish builds as before."""
    from .lease import lock_table_from_environment
    from .runtime import SITE_BUCKET_ENV, store_name

    environment = os.environ if environ is None else environ
    bucket = (environment.get(SITE_BUCKET_ENV) or "").strip()
    found = table if table is not None else (lock_table_from_environment(environment) if bucket else None)
    if not bucket or found is None:
        return None
    return PublishJobs(found, store_name(environment))
