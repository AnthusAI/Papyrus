"""The publish hook (PPY-d415c0): when the newsletter function is told about a publish, and when it is not."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from features_backend.steps.projection_publish_steps import (
    HANDLER_PATH,
    PUBLICATION_ENVIRONMENT,
    FakeCloudFront,
    FakeLambda,
    FakeS3,
    FakeSqs,
)
from procedures.newsroom.tests.fake_client import FakeAuthoringClient
from papyrus_content import publish_alerts
from procedures.newsroom.tests.no_lock_parameter import NoLockParameter
from papyrus_content.projection_trigger import item_task
from papyrus_content.publish_alerts import NEWSLETTER_FUNCTION_ENV, announce_published, lineage_of

NEWSLETTER = "papyrus-newsletter-example"
ITEM = "item-articles-hello"
PUBLISHED = "published-item-articles-hello"


# -- the module ----------------------------------------------------------------------------------------------------------


def test_lineage_comes_from_the_published_item_id() -> None:
    assert lineage_of("item-a", "published-lin-1") == "lin-1"
    assert lineage_of("item-a", None) == "item-a"
    assert lineage_of("item-a", "unexpected") == "item-a"
    assert lineage_of("item-a", "published-") == "item-a"


def test_an_unset_environment_is_a_no_op() -> None:
    calls: list[Any] = []
    outcome = announce_published(ITEM, PUBLISHED, environment={}, invoke=lambda name, payload: calls.append((name, payload)))
    assert calls == [] and outcome["ok"] is True and outcome["skipped"] == "not-configured"
    assert announce_published(ITEM, PUBLISHED, environment={NEWSLETTER_FUNCTION_ENV: "  "}, invoke=lambda *_: calls.append(1))["skipped"]
    assert calls == []


def test_the_event_names_the_item_and_its_lineage() -> None:
    calls: list[Any] = []
    outcome = announce_published(ITEM, PUBLISHED, environment={NEWSLETTER_FUNCTION_ENV: NEWSLETTER}, invoke=lambda name, payload: calls.append((name, payload)))
    assert outcome["ok"] is True
    assert calls == [(NEWSLETTER, {"task": "item-published", "itemId": ITEM, "lineageId": "item-articles-hello", "publishedItemId": PUBLISHED})]


def test_every_failure_is_swallowed_and_logged(capsys: pytest.CaptureFixture[str]) -> None:
    def explode(name: str, payload: dict[str, Any]) -> None:
        raise RuntimeError("secret-looking detail")

    outcome = announce_published(ITEM, PUBLISHED, environment={NEWSLETTER_FUNCTION_ENV: NEWSLETTER}, invoke=explode)
    assert outcome == {"ok": False, "error": "RuntimeError"}
    logged = capsys.readouterr().out
    assert "item_published_announce_failed" in logged and "secret-looking detail" not in logged


def test_the_real_invocation_is_asynchronous_with_short_timeouts() -> None:
    created: dict[str, Any] = {}

    class Client:
        def invoke(self, **arguments: Any) -> None:
            created["invoke"] = arguments

    def factory(service: str, **kwargs: Any) -> Client:
        created["service"], created["config"] = service, kwargs.get("config")
        return Client()

    with mock.patch("boto3.client", side_effect=factory):
        publish_alerts._invoke(NEWSLETTER, {"task": "item-published"})
    assert created["service"] == "lambda" and created["invoke"]["InvocationType"] == "Event"
    assert created["invoke"]["FunctionName"] == NEWSLETTER
    assert created["config"].connect_timeout == 2 and created["config"].read_timeout == 3


def test_the_cli_marks_only_a_publish_in_its_projection_task() -> None:
    assert item_task(ITEM, unpublished=False) == {"task": "item", "itemId": ITEM, "unpublished": False}
    assert item_task(ITEM, unpublished=False, published_item_id=PUBLISHED)["published"] == {"publishedItemId": PUBLISHED}
    assert "published" not in item_task(ITEM, unpublished=True, published_item_id=PUBLISHED)


def test_the_cli_passes_changed_through_to_the_task() -> None:
    from papyrus_content import publish_commands
    from papyrus_content.publishing import PublishResult

    tasks: list[dict[str, Any]] = []
    with mock.patch.object(publish_commands, "projection_enabled", return_value=True), mock.patch.object(
        publish_commands, "trigger_projection", side_effect=lambda task: tasks.append(task) or {"ok": True}
    ):
        publish_commands.run_site_triggers(mock.Mock(), {"no-trigger": False}, PublishResult(False, ITEM, PUBLISHED, 1))
        publish_commands.run_site_triggers(
            mock.Mock(get_record=lambda *_: {}), {}, PublishResult(True, ITEM, PUBLISHED, 2)
        )
        publish_commands.run_site_triggers(mock.Mock(get_record=lambda *_: {}), {}, PublishResult(True, ITEM, PUBLISHED, 2), unpublished=True)
    assert ["published" in task for task in tasks] == [False, True, False]


# -- the content-actions function ----------------------------------------------------------------------------------------


class Backend:
    """The content-actions handler over a fake content API; the Lambda client records what it is asked to invoke."""

    def __init__(self, *, projection: bool, newsletter: bool = True, rejects_writes: bool = False) -> None:
        specification = importlib.util.spec_from_file_location("content_actions_alerts_handler", Path(HANDLER_PATH))
        self.module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(self.module)
        self.client = FakeAuthoringClient()
        self.s3, self.cloudfront, self.sqs, self.lam = FakeS3(rejects_writes), FakeCloudFront(), FakeSqs(), FakeLambda()
        self.environment = dict(PUBLICATION_ENVIRONMENT) if projection else {}
        if newsletter:
            self.environment[NEWSLETTER_FUNCTION_ENV] = NEWSLETTER

    def _patched(self):
        clients = {"s3": self.s3, "cloudfront": self.cloudfront, "sqs": self.sqs, "lambda": self.lam, "ssm": NoLockParameter()}
        return (
            mock.patch.object(self.module, "create_authoring_client", return_value=(self.client, {})),
            mock.patch("boto3.client", side_effect=lambda name, **_kwargs: clients[name]),
            mock.patch.dict("os.environ", self.environment, clear=False),
        )

    def run(self, event: dict[str, Any]) -> Any:
        first, second, third = self._patched()
        with first, second, third:
            return self.module.handler(event, None)

    def action(self, field: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.run({"fieldName": field, "arguments": {"input": json.dumps(payload)}, "identity": {"username": "editor"}})

    def save(self, body: str = "Hello.\n") -> dict[str, Any]:
        return self.action(
            "saveItemDraft",
            {"id": ITEM, "type": "article", "slug": "hello", "section": "articles", "frontMatterYaml": "title: Hello\n", "bodyMarkus": body},
        )

    def announcements(self) -> list[dict[str, Any]]:
        return [call["Payload"] for call in self.lam.invocations if call["FunctionName"] == NEWSLETTER]

    def retries(self) -> list[dict[str, Any]]:
        return [call["Payload"]["projectionTask"] for call in self.lam.invocations if "projectionTask" in call["Payload"]]


EXPECTED = {"task": "item-published", "itemId": ITEM, "lineageId": ITEM, "publishedItemId": PUBLISHED}


@pytest.mark.parametrize("projection", [True, False])
def test_the_newsroom_publish_announces_once_and_only_when_changed(projection: bool) -> None:
    backend = Backend(projection=projection)
    backend.save()
    assert backend.action("publishItem", {"id": ITEM})["changed"] is True
    assert backend.announcements() == [EXPECTED]
    assert backend.action("publishItem", {"id": ITEM})["changed"] is False
    assert len(backend.announcements()) == 1, "the same published content does not announce again"


def test_an_edit_to_a_live_item_does_not_announce() -> None:
    backend = Backend(projection=True)
    backend.save()
    backend.action("publishItem", {"id": ITEM})
    backend.lam.invocations.clear()
    backend.save("A new body.\n")
    assert backend.announcements() == []


def test_unpublishing_does_not_announce() -> None:
    backend = Backend(projection=True)
    backend.save()
    backend.action("publishItem", {"id": ITEM})
    backend.lam.invocations.clear()
    assert backend.action("unpublishItem", {"id": ITEM})["changed"] is True
    assert backend.announcements() == [] and not any("published" in task for task in backend.retries())


def test_saving_a_draft_does_not_announce() -> None:
    backend = Backend(projection=True)
    backend.save()
    assert backend.announcements() == []


def test_without_the_plugin_nothing_is_invoked() -> None:
    for projection in (True, False):
        backend = Backend(projection=projection, newsletter=False)
        backend.save()
        assert backend.action("publishItem", {"id": ITEM})["ok"] is True
        assert [call for call in backend.lam.invocations if call["FunctionName"] == NEWSLETTER] == []


def test_a_failing_announcement_never_fails_the_publish(capsys: pytest.CaptureFixture[str]) -> None:
    backend = Backend(projection=True)
    backend.save()
    original = backend.lam.invoke

    def refuse(**arguments: Any) -> None:
        if arguments["FunctionName"] == NEWSLETTER:
            raise RuntimeError("AccessDenied")
        original(**arguments)

    backend.lam.invoke = refuse  # type: ignore[assignment]
    response = backend.action("publishItem", {"id": ITEM})
    assert response["ok"] is True and response["live"] is True
    assert "item_published_announce_failed" in capsys.readouterr().out


def test_a_projection_failure_defers_the_announcement_to_the_retry() -> None:
    backend = Backend(projection=True, rejects_writes=True)
    backend.save()
    response = backend.action("publishItem", {"id": ITEM})
    assert response["ok"] is True and response["live"] is False
    assert backend.announcements() == [], "the page is not live yet"
    (retry,) = backend.retries()
    assert retry["published"] == {"publishedItemId": PUBLISHED}
    backend.s3.rejects_writes = False
    backend.lam.invocations.clear()
    assert backend.run({"projectionTask": retry})["ok"] is True
    assert backend.announcements() == [EXPECTED], "announced once the page is live"


def test_a_failing_retry_does_not_announce() -> None:
    backend = Backend(projection=True, rejects_writes=True)
    backend.save()
    backend.action("publishItem", {"id": ITEM})
    (retry,) = backend.retries()
    backend.lam.invocations.clear()
    with pytest.raises(Exception):  # noqa: B017 - the task raises so Lambda retries it
        backend.run({"projectionTask": retry})
    assert backend.announcements() == []


def test_the_cli_task_announces_after_projection_and_reprojection_never_does() -> None:
    backend = Backend(projection=True)
    backend.save()
    # `papyrus content publish` publishes through the data API itself, then schedules this task on the function.
    from papyrus_content.publishing import publish_item

    result = publish_item(backend.client, ITEM, actor="papyrus-cli")
    assert result.changed
    backend.run({"projectionTask": item_task(ITEM, unpublished=False, published_item_id=result.published_item_id)})
    assert backend.announcements() == [EXPECTED]
    backend.lam.invocations.clear()
    for task in (
        item_task(ITEM, unpublished=False),  # a CLI publish that changed nothing, or any plain reprojection of the item
        item_task(ITEM, unpublished=True),
        {"task": "all"},
        {"task": "item-pages", "exceptItemId": ITEM},
        {"task": "deploy-render"},
        {"task": "invalidate", "keys": []},
    ):
        backend.run({"projectionTask": task})
    assert backend.announcements() == []


def test_a_cli_unpublish_task_never_announces_even_if_marked() -> None:
    backend = Backend(projection=True)
    backend.save()
    backend.action("publishItem", {"id": ITEM})
    backend.lam.invocations.clear()
    backend.run({"projectionTask": {"task": "item", "itemId": ITEM, "unpublished": True, "published": {"publishedItemId": PUBLISHED}}})
    assert backend.announcements() == []
