"""A per-publication projection lease: one projection of a site store at a time.

A deploy-time reprojection, a ``papyrus`` CLI projection, a publish-time item
projection and a scheduled cloud run all write the same site bucket. Each takes
a lease in a shared DynamoDB table before it writes and gives it back when it
finishes. The lease is a single item keyed by the site bucket name:

* acquire is a conditional put that succeeds when no item exists or the
  existing item has expired, so a crashed holder blocks nobody for longer than
  the time to live;
* release and renew are conditional on the owner, so a projection never deletes
  or extends somebody else's lease;
* a projection that finds the lease held waits with exponential backoff and
  jitter up to ``PAPYRUS_PROJECTION_LOCK_WAIT_SECONDS``, then fails with
  ``ProjectionLeaseHeld``;
* nested engine calls in one context share one hold, so they cannot deadlock.

Without a lock table (no environment variable, no SSM parameter) there is no
lease and projection behaves as it always did.
"""

from __future__ import annotations

import os
import random
import socket
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

TABLE_ENV = "PAPYRUS_PROJECTION_LOCK_TABLE"
TABLE_PARAMETER = "/papyrus/projection-lock/table-name"
WAIT_SECONDS_ENV = "PAPYRUS_PROJECTION_LOCK_WAIT_SECONDS"
PURPOSE_ENV = "PAPYRUS_PROJECTION_LEASE_PURPOSE"
DEFAULT_WAIT_SECONDS = 120.0
DEFAULT_TTL_SECONDS = 30 * 60
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 15.0
CONDITION_FAILED = "ConditionalCheckFailedException"

_table_name_cache: dict[str, str | None] = {}


class ProjectionLeaseHeld(RuntimeError):
    """The publication is being projected by someone else and the wait limit passed."""

    def __init__(self, key: str, table: str, holder: Mapping[str, Any], waited_seconds: float) -> None:
        self.key = key
        self.owner = str(holder.get("owner", "unknown"))
        self.purpose = str(holder.get("purpose", "unknown"))
        self.expires_at = float(holder.get("expiresAt", 0))
        expiry = datetime.fromtimestamp(self.expires_at, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        super().__init__(
            f"Projection lease for {key} is held by {self.owner} ({self.purpose}) until {expiry}; "
            f"waited {waited_seconds:.0f}s. Another projection of this publication is running. "
            "Retry when it finishes; if its holder crashed, the lease expires by itself. "
            f"To clear it now: aws dynamodb delete-item --table-name {table} "
            f"--key '{{\"publication\":{{\"S\":\"{key}\"}}}}'"
        )


class ProjectionLeaseLost(RuntimeError):
    """The lease expired and was taken over while this projection was still writing."""


def backoff_seconds(attempt: int, jitter: float = 1.0) -> float:
    """Delay before retry number ``attempt`` (0-based): 1, 2, 4, 8, 15, 15 ... seconds, scaled by jitter in [0.5, 1]."""
    return min(BACKOFF_BASE_SECONDS * 2**attempt, BACKOFF_CAP_SECONDS) * (0.5 + jitter / 2)


def _is_condition_failure(error: Exception) -> bool:
    return getattr(error, "response", {}).get("Error", {}).get("Code") == CONDITION_FAILED


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ProjectionLease:
    def __init__(
        self,
        table: Any,
        key: str,
        *,
        table_name: str = "papyrus-projection-locks",
        purpose: str = "projection",
        owner: str | None = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        wait_seconds: float = DEFAULT_WAIT_SECONDS,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.table, self.key, self.table_name, self.purpose = table, key, table_name, purpose
        self.owner = owner or f"{socket.gethostname()}-{uuid.uuid4().hex[:12]}"
        self.ttl_seconds, self.wait_seconds = ttl_seconds, wait_seconds
        self.clock, self.sleep, self.jitter = clock, sleep, jitter
        self.depth = 0
        self._renewed_at = 0.0

    def _try_put(self) -> bool:
        now = self.clock()
        try:
            self.table.put_item(
                Item={
                    "publication": self.key,
                    "owner": self.owner,
                    "acquiredAt": _iso(now),
                    "expiresAt": int(now + self.ttl_seconds),
                    "purpose": self.purpose,
                },
                ConditionExpression="attribute_not_exists(publication) OR expiresAt < :now",
                ExpressionAttributeValues={":now": int(now)},
            )
        except Exception as error:  # noqa: BLE001 - botocore ClientError; anything else propagates below
            if _is_condition_failure(error):
                return False
            raise
        self._renewed_at = now
        return True

    def acquire(self) -> None:
        if self.depth:
            self.depth += 1
            return
        started = self.clock()
        attempt = 0
        while not self._try_put():
            waited = self.clock() - started
            if waited >= self.wait_seconds:
                holder = self.table.get_item(Key={"publication": self.key}, ConsistentRead=True).get("Item") or {}
                raise ProjectionLeaseHeld(self.key, self.table_name, holder, waited)
            self.sleep(min(backoff_seconds(attempt, self.jitter()), self.wait_seconds - waited))
            attempt += 1
        self.depth = 1

    def release(self) -> None:
        if self.depth > 1:
            self.depth -= 1
            return
        if self.depth == 0:
            return
        self.depth = 0
        try:
            self.table.delete_item(
                Key={"publication": self.key},
                ConditionExpression="#owner = :owner",
                ExpressionAttributeNames={"#owner": "owner"},
                ExpressionAttributeValues={":owner": self.owner},
            )
        except Exception as error:  # noqa: BLE001
            if not _is_condition_failure(error):
                raise  # a lease that was taken over or already gone is not an error; anything else is

    def renew(self, *, force: bool = False) -> None:
        """Extend the lease. Cheap to call often: it writes only once half the time to live has passed."""
        now = self.clock()
        if not self.depth or (not force and now - self._renewed_at < self.ttl_seconds / 2):
            return
        try:
            self.table.update_item(
                Key={"publication": self.key},
                UpdateExpression="SET expiresAt = :expires",
                ConditionExpression="#owner = :owner",
                ExpressionAttributeNames={"#owner": "owner"},
                ExpressionAttributeValues={":expires": int(now + self.ttl_seconds), ":owner": self.owner},
            )
        except Exception as error:  # noqa: BLE001
            if _is_condition_failure(error):
                raise ProjectionLeaseLost(
                    f"The projection lease for {self.key} expired and was taken over; stopping before more writes."
                ) from error
            raise
        self._renewed_at = now

    @contextmanager
    def held(self) -> Iterator["ProjectionLease"]:
        self.acquire()
        try:
            yield self
        finally:
            self.release()


def _lock_table_name(environment: Mapping[str, str], ssm_client: Any) -> str | None:
    configured = (environment.get(TABLE_ENV) or "").strip()
    if configured:
        return configured
    if TABLE_PARAMETER in _table_name_cache:
        return _table_name_cache[TABLE_PARAMETER]
    import boto3  # provided by the Lambda runtime
    from botocore.exceptions import NoCredentialsError, NoRegionError

    try:
        ssm = ssm_client or boto3.client("ssm")
        name = ssm.get_parameter(Name=TABLE_PARAMETER)["Parameter"]["Value"]
    except (NoCredentialsError, NoRegionError):
        return None  # not an AWS context: nothing to lock against
    except Exception as error:  # noqa: BLE001
        if getattr(error, "response", {}).get("Error", {}).get("Code") == "ParameterNotFound":
            _table_name_cache[TABLE_PARAMETER] = None
            return None
        raise
    _table_name_cache[TABLE_PARAMETER] = name
    return name


def lease_from_environment(
    environ: Mapping[str, str] | None,
    bucket: str,
    *,
    ssm_client: Any = None,
    dynamodb: Any = None,
    **options: Any,
) -> ProjectionLease | None:
    """The lease for the publication stored in ``bucket``, or None when no lock table is configured."""
    environment = os.environ if environ is None else environ
    name = _lock_table_name(environment, ssm_client)
    if not name:
        return None
    if dynamodb is None:
        import boto3

        dynamodb = boto3.resource("dynamodb")
    wait = (environment.get(WAIT_SECONDS_ENV) or "").strip()
    purpose = (environment.get(PURPOSE_ENV) or "").strip() or (
        "lambda projection" if environment.get("AWS_LAMBDA_FUNCTION_NAME") else "cli projection"
    )
    if wait:
        options.setdefault("wait_seconds", float(wait))
    options.setdefault("purpose", purpose)
    return ProjectionLease(dynamodb.Table(name), bucket, table_name=name, **options)
