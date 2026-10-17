"""Publish-time site triggers: Amplify rebuilds (IAM only) and Pretext revalidation."""

from __future__ import annotations

import os
from typing import Any

from .reader_revalidation import trigger_reader_cache_revalidation

READER_APP_ID_ENV = "PAPYRUS_READER_AMPLIFY_APP_ID"
READER_BRANCH_ENV = "PAPYRUS_READER_BRANCH"
DEFAULT_READER_BRANCH = "main"
DEFAULT_STAGING_BRANCH = "staging"
PENDING_STATUS = "PENDING"
LIST_JOBS_PAGE_SIZE = 5


def _create_amplify_client():
    import boto3

    return boto3.client("amplify")


def _start_release_unless_pending(*, app_id: str, branch: str, boto_client=None) -> dict[str, Any]:
    try:
        amplify = boto_client or _create_amplify_client()
        listing = amplify.list_jobs(appId=app_id, branchName=branch, maxResults=LIST_JOBS_PAGE_SIZE)
        for summary in listing.get("jobSummaries") or []:
            if summary.get("status") == PENDING_STATUS:
                return {"started": False, "jobId": summary.get("jobId"), "reason": "pending-job-exists"}
        started = amplify.start_job(appId=app_id, branchName=branch, jobType="RELEASE")
        job_id = ((started.get("jobSummary") or {}).get("jobId"))
        return {"started": True, "jobId": job_id}
    except Exception as error:  # noqa: BLE001 - a trigger failure is reported, never raised
        return {"started": False, "error": f"{type(error).__name__}: {error}"}


def trigger_rebuild(
    *,
    reader_app_id: str | None,
    reader_branch: str = DEFAULT_READER_BRANCH,
    boto_client=None,
) -> dict[str, Any]:
    if not reader_app_id:
        return {"started": False, "reason": "not-configured"}
    return _start_release_unless_pending(app_id=reader_app_id, branch=reader_branch, boto_client=boto_client)


def trigger_staging_build(
    *,
    cms_app_id: str,
    staging_branch: str = DEFAULT_STAGING_BRANCH,
    boto_client=None,
) -> dict[str, Any]:
    return _start_release_unless_pending(app_id=cms_app_id, branch=staging_branch, boto_client=boto_client)


def trigger_pretext_revalidation(
    slugs: list[str],
    edition_date: str | None,
    *,
    base_url: str | None = None,
) -> dict[str, Any] | None:
    return trigger_reader_cache_revalidation(
        edition_date=edition_date,
        article_slugs=slugs,
        item_slugs=slugs,
        base_url=base_url,
    )


def reader_target_from_environment() -> tuple[str | None, str]:
    app_id = (os.environ.get(READER_APP_ID_ENV) or "").strip() or None
    branch = (os.environ.get(READER_BRANCH_ENV) or "").strip() or DEFAULT_READER_BRANCH
    return app_id, branch
