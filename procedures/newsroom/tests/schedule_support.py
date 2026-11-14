"""Shared stand-ins for the scheduled publishing tests: a Scheduler that records what it was asked, a Story with versions, and a clock that can be moved."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from papyrus_content.publishing import ItemFields, publish_item, save_item
from papyrus_content.story_reporting import save_story_version
from papyrus_content.story_schedule import Caller, ScheduleService, run_operation, schedule_name
from procedures.newsroom.tests.fake_client import FakeAuthoringClient

LINEAGE = "item-articles-robots"
PREFIX = "papyrus-pub-test-"
ZONE = "America/New_York"


class FakeScheduler:
    """What EventBridge Scheduler holds: one schedule per name, with the time and the version it will publish."""

    name_prefix = PREFIX

    def __init__(self) -> None:
        self.schedules: dict[str, dict[str, str]] = {}
        self.deleted: list[str] = []
        self.history: list[dict[str, str]] = []   # every event a timer was ever set to deliver, including ones since moved or removed

    def name_for(self, item_id: str) -> str:
        return schedule_name(PREFIX, item_id)

    def upsert(self, name: str, item_id: str, at: str) -> None:
        self.schedules[name] = {"itemId": item_id, "scheduledPublishAt": at}
        self.history.append({"itemId": item_id, "scheduledPublishAt": at})

    def delete(self, name: str) -> None:
        self.deleted.append(name)
        self.schedules.pop(name, None)


class Clock:
    def __init__(self, text: str) -> None:
        self.moment = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.moment

    def set(self, text: str) -> None:
        self.moment = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

    def iso(self) -> str:
        return self.moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def story_fields(title: str = "Robots in the warehouse") -> ItemFields:
    return ItemFields(type="article", slug="robots", section="articles", front_matter_yaml=f"title: {title}\n", body_markus="Robots arrived.\n", aliases=[], id=LINEAGE)


def new_story(client: FakeAuthoringClient, *, first_published: str | None = None, versions: int = 1) -> str:
    """A Story of ``versions`` versions (the first published at ``first_published`` when given). Returns the newest version's id."""
    save_item(client, story_fields(), actor="Alex", now="2026-11-01T12:00:00Z")
    if first_published:
        publish_item(client, LINEAGE, actor="Pat", now=first_published)
    newest = LINEAGE
    for number in range(2, versions + 1):
        newest = save_story_version(client, LINEAGE, front_matter_yaml="title: Robots in the warehouse\n", body_markus=f"Version {number}.\n", actor="Alex",
                                    change_reason=f"edit {number}", now=f"2026-11-0{number}T12:00:00Z")["id"]
    return newest


def service_for(client: FakeAuthoringClient, scheduler: FakeScheduler, clock: Clock, zone: str | None = ZONE) -> ScheduleService:
    return ScheduleService(client, zone_name=zone, scheduler=scheduler, now=clock)  # type: ignore[arg-type]


def item(client: FakeAuthoringClient, item_id: str) -> dict[str, Any]:
    return client.tables["Item"][item_id]


class SiteClient:
    """The authoring client a CLI session holds, with the ``scheduleItem`` mutation answered by the site's own operation table (as the Lambda does)."""

    def __init__(self, client: FakeAuthoringClient, service: Any) -> None:
        self._client, self.service = client, service
        self.mutations: list[dict[str, Any]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        assert "scheduleItem(input: $input)" in query
        payload = json.loads(variables["input"])
        self.mutations.append(payload)
        return {"scheduleItem": json.dumps(run_operation(payload["operation"], payload["arguments"], self.service, Caller(actor="sam", person="sam-sub", groups=("editor",))))}
