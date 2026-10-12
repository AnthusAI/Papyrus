"""Targeted CloudFront invalidations: exact paths, batched, retried on throttling, counted for the monthly alarm."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from typing import Any
from urllib.parse import quote

MAXIMUM_PATHS_PER_BATCH = 500
THROTTLED_ERROR_CODES = frozenset(
    {"Throttling", "ThrottlingException", "TooManyInvalidationsInProgress", "ServiceUnavailable", "RequestLimitExceeded"}
)
MAXIMUM_ATTEMPTS = 5
FIRST_RETRY_DELAY_SECONDS = 1.0
METRIC_NAMESPACE = "Papyrus/Edge"
METRIC_NAME = "InvalidatedPaths"
METRIC_DIMENSION = "DistributionId"


class WholeSiteInvalidationRefused(ValueError):
    """The edge is purged by exact path; a wildcard would clear every page and costs a path per match."""


def encoded_path(path: str) -> str:
    return quote(path, safe="/*")


def refuse_wildcards(paths: Iterable[str]) -> None:
    for path in paths:
        if "*" in path:
            raise WholeSiteInvalidationRefused(f"wildcard invalidation refused: {path!r}")


def _error_code(error: Exception) -> str:
    return str(getattr(error, "response", {}).get("Error", {}).get("Code", ""))


def emit_invalidated_paths_metric(distribution_id: str, count: int) -> None:
    """One CloudWatch embedded-metric-format line, summed per day by the monthly path-count alarm."""
    print(
        json.dumps(
            {
                "_aws": {
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": METRIC_NAMESPACE,
                            "Dimensions": [[METRIC_DIMENSION]],
                            "Metrics": [{"Name": METRIC_NAME, "Unit": "Count"}],
                        }
                    ],
                },
                METRIC_DIMENSION: distribution_id,
                METRIC_NAME: count,
            }
        ),
        flush=True,
    )


def invalidate_distribution(
    distribution_id: str,
    paths: Sequence[str],
    cloudfront_client: Any = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> list[str]:
    """Invalidate exactly these paths on one distribution, in batches; returns the paths invalidated."""
    unique = list(dict.fromkeys(encoded_path(path) for path in paths))
    refuse_wildcards(unique)
    if not unique:
        return []
    if cloudfront_client is None:
        import boto3

        cloudfront_client = boto3.client("cloudfront")
    for start in range(0, len(unique), MAXIMUM_PATHS_PER_BATCH):
        batch = unique[start : start + MAXIMUM_PATHS_PER_BATCH]
        _create_invalidation_with_retries(cloudfront_client, distribution_id, batch, sleep)
        emit_invalidated_paths_metric(distribution_id, len(batch))
    return unique


def _create_invalidation_with_retries(
    cloudfront_client: Any, distribution_id: str, batch: list[str], sleep: Callable[[float], None]
) -> None:
    caller_reference = uuid.uuid4().hex
    for attempt in range(MAXIMUM_ATTEMPTS):
        try:
            cloudfront_client.create_invalidation(
                DistributionId=distribution_id,
                InvalidationBatch={
                    "Paths": {"Quantity": len(batch), "Items": batch},
                    "CallerReference": caller_reference,
                },
            )
            return
        except Exception as error:  # noqa: BLE001 - only throttling is retried; the caller reports anything else
            if _error_code(error) not in THROTTLED_ERROR_CODES or attempt == MAXIMUM_ATTEMPTS - 1:
                raise
            sleep(FIRST_RETRY_DELAY_SECONDS * (2**attempt))
