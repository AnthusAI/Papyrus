"""The ``newsletter-send-worker`` Lambda: one SQS message (up to 50 subscriber ids of one issue) per invocation.

Reserved concurrency 1 and a batch size of 1, so sends are paced under the SES MaxSendRate and no two messages run at once.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from .runtime import build_sender
from .send import Sender

_sender: Sender | None = None


def handler(event: Mapping[str, Any], context: Any = None) -> dict[str, Any]:
    global _sender
    if _sender is None:
        _sender = build_sender()
    remaining = context.get_remaining_time_in_millis if context is not None else (lambda: 10**9)
    for record in event.get("Records", []):
        print(json.dumps({"event": "worker_message", **_sender.process(json.loads(record["body"]), remaining)}))
    return {}
