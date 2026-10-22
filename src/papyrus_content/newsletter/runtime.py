"""Building the real collaborators (AWS clients, GraphQL client) from the function environment."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Mapping

from .compliance import Compliance
from .issues import IssueService
from .keys import Keys
from .mailer import Mailer
from .postal import PostalAddress
from .scheduler import IssueScheduler
from .send import Pacer, SendQueue, Sender
from .store import Store

PUBLISHER_ACTOR = "newsletter"


def content_actions_publisher(function_name: str, client: Any = None) -> Callable[[str], Mapping[str, Any]]:
    """Publish an Item through the site's ``content-actions`` function, so the publish triggers and the projection run once, there."""

    def publish(item_id: str) -> Mapping[str, Any]:
        lam = client
        if lam is None:
            import boto3

            lam = boto3.client("lambda")
        event = {
            "fieldName": "publishItem",
            "arguments": {"input": json.dumps({"id": item_id})},
            "identity": {"username": PUBLISHER_ACTOR},
        }
        response = lam.invoke(FunctionName=function_name, InvocationType="RequestResponse", Payload=json.dumps(event).encode("utf-8"))
        payload = json.loads(response["Payload"].read() or b"{}")
        if response.get("FunctionError") or not isinstance(payload, dict) or payload.get("ok") is not True:
            raise RuntimeError("publishItem was refused")
        return payload

    return publish


def authoring_client() -> Any:
    from papyrus_content.graphql_authoring import create_authoring_client

    return create_authoring_client()[0]


def build_issue_service(
    environment: Mapping[str, str],
    settings: Any,
    store: Store,
    keys: Keys,
    mailer: Mailer,
    *,
    clock: Callable[[], float] = time.time,
) -> IssueService:
    return IssueService(
        settings=settings,
        store=store,
        mailer=mailer,
        compliance=Compliance(store=store, keys=keys, site_origin=settings.site_origin, base_path=settings.base_path),
        postal=PostalAddress(settings.site_id, clock=clock),
        scheduler=IssueScheduler(function_arn=environment.get("FUNCTION_ARN", ""), role_arn=environment.get("SCHEDULER_ROLE_ARN", "")),
        queue=SendQueue(environment.get("QUEUE_URL", "")),
        content=authoring_client,
        publisher=content_actions_publisher(environment.get("CONTENT_ACTIONS_FUNCTION", "")),
        clock=clock,
    )


def build_sender(environment: Mapping[str, str] = os.environ) -> Sender:
    from .handler import Settings
    from .keys import load_keys

    settings = Settings.from_environment(environment)
    store = Store(environment["TABLE_NAME"])
    mailer = Mailer(
        from_name=settings.from_name, from_address=settings.from_address,
        configuration_set=settings.configuration_set, site_id=settings.site_id,
    )
    service = build_issue_service(environment, settings, store, load_keys(environment["KEY_PARAMETER"]), mailer)
    return Sender(service, pacer=Pacer(mailer.client))
