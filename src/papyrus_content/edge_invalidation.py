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


class InvalidationCapped(Exception):
    """A targeted purge listed more paths than the per-call cap. ``invalidated`` were purged; ``skipped`` were not (never collapsed to a wildcard).

    Not a failure of the write or of the purge it did make: the caller reports the skipped paths and does not retry them (a retry would be over the cap again).
    """

    def __init__(self, invalidated: list[str], skipped: list[str], cap: int) -> None:
        super().__init__(f"{len(skipped)} of {len(invalidated) + len(skipped)} paths were not purged: over the cap of {cap} paths per call (publication.cache.maxInvalidationPaths).")
        self.invalidated = invalidated
        self.skipped = skipped
        self.cap = cap


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
) -> dict[str, Any]:
    """Create one invalidation; returns the service's invalidation record (``Id``, ``Status``), ``{}`` when the client returns none."""
    caller_reference = uuid.uuid4().hex
    for attempt in range(MAXIMUM_ATTEMPTS):
        try:
            response = cloudfront_client.create_invalidation(
                DistributionId=distribution_id,
                InvalidationBatch={
                    "Paths": {"Quantity": len(batch), "Items": batch},
                    "CallerReference": caller_reference,
                },
            )
            record = (response or {}).get("Invalidation") if isinstance(response, dict) else None
            return record if isinstance(record, dict) else {}
        except Exception as error:  # noqa: BLE001 - only throttling is retried; the caller reports anything else
            if _error_code(error) not in THROTTLED_ERROR_CODES or attempt == MAXIMUM_ATTEMPTS - 1:
                raise
            sleep(FIRST_RETRY_DELAY_SECONDS * (2**attempt))
    return {}


# CloudFront accepts at most 3,000 paths in one invalidation request.
MAXIMUM_PATHS_PER_REQUEST = 3000
FREE_PATHS_PER_MONTH = 1000
USD_PER_PATH_AFTER_FREE = 0.005


def invalidation_cost_note(path_count: int) -> dict[str, Any]:
    """What these paths cost at most: the first 1,000 a month are free, then 0.005 USD each. The month's use so far is not known here."""
    return {
        "paths": path_count,
        "freePathsPerMonth": FREE_PATHS_PER_MONTH,
        "usdPerPathAfterFree": USD_PER_PATH_AFTER_FREE,
        "usdAtMost": round(path_count * USD_PER_PATH_AFTER_FREE, 4),
    }


def invalidate_exact_paths(
    distribution_id: str,
    paths: Sequence[str],
    cloudfront_client: Any = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    emit_metric: bool = True,
) -> list[dict[str, Any]]:
    """Invalidate exactly these paths, never a wildcard and never collapsed to ``/*`` however many there are.

    Used by the explicit page-refresh operations. Up to 3,000 paths go in each request; returns one ``{"id", "status", "paths"}`` per request.
    ``emit_metric`` writes the monthly-alarm metric line to standard output, which only a Lambda's log wants. Raises ``WholeSiteInvalidationRefused`` for a wildcard. A failure raises, after the requests already made are in the error's ``made`` list.
    """
    unique = list(dict.fromkeys(encoded_path(path) for path in paths))
    refuse_wildcards(unique)
    if not unique:
        return []
    if cloudfront_client is None:
        import boto3

        cloudfront_client = boto3.client("cloudfront")
    made: list[dict[str, Any]] = []
    for start in range(0, len(unique), MAXIMUM_PATHS_PER_REQUEST):
        batch = unique[start : start + MAXIMUM_PATHS_PER_REQUEST]
        try:
            record = _create_invalidation_with_retries(cloudfront_client, distribution_id, batch, sleep)
        except Exception as error:
            error.made = made  # type: ignore[attr-defined]
            raise
        made.append({"id": record.get("Id"), "status": record.get("Status"), "paths": len(batch)})
        if emit_metric:
            emit_invalidated_paths_metric(distribution_id, len(batch))
    return made


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
