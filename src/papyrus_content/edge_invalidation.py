"""CloudFront invalidations: exact paths for small runs, one wildcard for large ones, retried on throttling, counted for the monthly alarm."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from typing import Any
from urllib.parse import quote

WILDCARD_INVALIDATION_PATH = "/*"
# CloudFront bills every path in an invalidation ($0.005 after 1,000 a month) but a wildcard counts as one,
# so a run that would purge more than this many paths purges everything with a single "/*".
WILDCARD_THRESHOLD = 10
THROTTLED_ERROR_CODES = frozenset(
    {"Throttling", "ThrottlingException", "TooManyInvalidationsInProgress", "ServiceUnavailable", "RequestLimitExceeded"}
)
MAXIMUM_ATTEMPTS = 5
FIRST_RETRY_DELAY_SECONDS = 1.0
METRIC_NAMESPACE = "Papyrus/Edge"
METRIC_NAME = "InvalidatedPaths"
METRIC_DIMENSION = "DistributionId"


class WholeSiteInvalidationRefused(ValueError):
    """Callers name exact paths; the wildcard is only ever chosen here, when a run is too large to list."""


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
    """Invalidate these paths on one distribution with one call; returns the paths invalidated.

    More than ``WILDCARD_THRESHOLD`` distinct paths become a single ``/*``, which bills as one path.
    """
    unique = list(dict.fromkeys(encoded_path(path) for path in paths))
    refuse_wildcards(unique)
    if not unique:
        return []
    if len(unique) > WILDCARD_THRESHOLD:
        unique = [WILDCARD_INVALIDATION_PATH]
    if cloudfront_client is None:
        import boto3

        cloudfront_client = boto3.client("cloudfront")
    _create_invalidation_with_retries(cloudfront_client, distribution_id, unique, sleep)
    emit_invalidated_paths_metric(distribution_id, len(unique))
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


REVALIDATE_DISTRIBUTION_IDS_ENV = "PAPYRUS_REVALIDATE_DISTRIBUTION_IDS"


def distribution_ids_from_environment(environment: dict[str, str] | Any) -> list[str]:
    configured = (environment.get(REVALIDATE_DISTRIBUTION_IDS_ENV) or "").split(",")
    return [identifier.strip() for identifier in configured if identifier.strip()]


def invalidate_revalidated_paths(
    distribution_ids: Sequence[str],
    revalidated: dict[str, Any] | None,
    cloudfront_client: Any = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """After a Pretext reader refreshed its own cache, purge our CloudFront copies of exactly those paths.

    The reader answers with the paths it revalidated; each distribution that fronts it is invalidated for
    them. A failure on one distribution never stops the others and is reported, never raised.
    """
    paths = [path for path in (revalidated or {}).get("revalidatedPaths", []) if isinstance(path, str) and path.startswith("/")]
    if not paths:
        return {"ok": True, "paths": [], "distributions": {}}
    outcomes: dict[str, Any] = {}
    for distribution_id in distribution_ids:
        try:
            outcomes[distribution_id] = {"ok": True, "paths": len(invalidate_distribution(distribution_id, paths, cloudfront_client, sleep=sleep))}
        except Exception as error:  # noqa: BLE001 - reported per distribution; the publish never fails because of an edge purge
            outcomes[distribution_id] = {"ok": False, "error": f"{type(error).__name__}: {error}"}
    return {"ok": all(outcome["ok"] for outcome in outcomes.values()), "paths": paths, "distributions": outcomes}
