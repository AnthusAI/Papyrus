"""Request limits: per visitor address (5 per 10 minutes), per subscriber (3 per hour), per site (300 per hour).

Counters are fixed-window DynamoDB counters with a TTL. Visitor addresses are hashed with the site's hash key before
they become part of a counter key, and the key never holds an email address (the subscriber id is already a keyed hash).
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

IP_LIMIT, IP_WINDOW_SECONDS = 5, 10 * 60
SUBSCRIBER_LIMIT, SUBSCRIBER_WINDOW_SECONDS = 3, 60 * 60
SITE_LIMIT, SITE_WINDOW_SECONDS = 300, 60 * 60

Counter = Callable[[str, float, int], int]


def window_key(kind: str, subject: str, window_seconds: int, now: float) -> str:
    return f"{kind}#{subject}#{int(now // window_seconds)}"


def check(count: Counter, *, ip_hash: str, hid: str, site_id: str, now: float) -> str | None:
    """The scope that is over its limit (``ip``, ``subscriber`` or ``site``), or None. Stops at the first one."""
    scopes = (
        ("ip", ip_hash, IP_LIMIT, IP_WINDOW_SECONDS),
        ("subscriber", hid, SUBSCRIBER_LIMIT, SUBSCRIBER_WINDOW_SECONDS),
        ("site", site_id, SITE_LIMIT, SITE_WINDOW_SECONDS),
    )
    for kind, subject, limit, window in scopes:
        if count(window_key(kind, subject, window, now), now, window * 2) > limit:
            return kind
    return None


def log_metric(site_id: str, name: str, **dimensions: str) -> None:
    """One CloudWatch Embedded Metric Format line: a metric without a PutMetricData call. No personal data."""
    names = sorted(dimensions)
    line: dict[str, Any] = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": "Papyrus/Newsletter",
                    "Dimensions": [["Site", *names]],
                    "Metrics": [{"Name": name, "Unit": "Count"}],
                }
            ],
        },
        "Site": site_id,
        name: 1,
        **dimensions,
    }
    print(json.dumps(line, separators=(",", ":")))
