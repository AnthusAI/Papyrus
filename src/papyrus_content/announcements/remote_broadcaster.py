"""A Broadcaster (``channel.Broadcaster``) for a process that holds none of the site's Caducus wiring: the shared procedure runner, where the announce agent decides and sends.

It hands each call to the site's own broadcast function (``papyrus-notifications-broadcast-<siteId>``, ``notifications.handler.broadcast``), which builds the Caducus runtime
from the site's tables, queues and X token as its other notification functions do. The runner holds no token and no table of the site's: it may only invoke that function.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any, Callable, Mapping

from .channel import DeliveryView
from .records import RecordError

FUNCTION_PREFIX = "papyrus-notifications-broadcast-"
FUNCTION_NAME = re.compile(r"papyrus-notifications-broadcast-[a-z0-9-]{1,40}")
ENVIRONMENT = "X_BROADCAST_FUNCTION"


def function_name_for(site_id: str) -> str:
    return f"{FUNCTION_PREFIX}{site_id}"


def view_payload(view: DeliveryView | None) -> dict[str, Any] | None:
    return asdict(view) if view is not None else None


def view_from(payload: Mapping[str, Any] | None) -> DeliveryView | None:
    return DeliveryView(**{key: payload.get(key) for key in DeliveryView.__dataclass_fields__ if key in payload}) if payload else None


class RemoteBroadcaster:
    def __init__(self, function_name: str, invoke: Callable[[str, dict], dict] | None = None):
        if not FUNCTION_NAME.fullmatch(function_name):
            raise ValueError(f"{function_name!r} is not a site's broadcast function name.")
        self.function_name, self._invoke = function_name, invoke or lambda_invoker()

    def _call(self, operation: str, **arguments: Any) -> dict:
        answer = self._invoke(self.function_name, {"operation": operation, **arguments})
        if not answer.get("ok"):
            from .caducus_errors import refusal

            raise refusal(answer)
        return answer

    def submit(self, *, account_id: str, event_id: str, text: str, url: str) -> None:
        self._call("submit", accountId=account_id, eventId=event_id, text=text, url=url)

    def delivery(self, event_id: str) -> DeliveryView | None:
        return view_from(self._call("delivery", eventId=event_id).get("delivery"))

    def withdraw(self, event_id: str, *, by: str) -> DeliveryView:
        view = view_from(self._call("withdraw", eventId=event_id, by=by).get("delivery"))
        if view is None:
            raise RecordError(f"The broadcast function returned no delivery for {event_id}.")
        return view


def lambda_invoker() -> Callable[[str, dict], dict]:
    import boto3

    client = boto3.client("lambda")

    def invoke(function_name: str, payload: dict) -> dict:
        response = client.invoke(FunctionName=function_name, InvocationType="RequestResponse", Payload=json.dumps(payload).encode("utf-8"))
        body = response["Payload"].read()
        if response.get("FunctionError"):
            raise RuntimeError(f"The site's broadcast function {function_name} failed: {body[:500].decode('utf-8', 'replace')}")
        return json.loads(body)

    return invoke
