"""A publish writes only its own records and tells no other function (PPY-e3bb2b). The newsletter and notifications functions are no longer invoked from a publish: the
Story's own record entering the published stage reaches the announce agent through the Item change feed (``features_backend/announcements/announce-durable-triggers.feature``)."""

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
from procedures.newsroom.tests.no_lock_parameter import NoLockParameter
from papyrus_content.projection_trigger import item_task

ITEM = "item-articles-hello"
PUBLISHED = "published-item-articles-hello"


def test_the_cli_marks_only_a_publish_in_its_projection_task() -> None:
    assert item_task(ITEM, unpublished=False) == {"task": "item", "itemId": ITEM, "unpublished": False}
    assert item_task(ITEM, unpublished=False, published_item_id=PUBLISHED)["published"] == {"publishedItemId": PUBLISHED}
    assert "published" not in item_task(ITEM, unpublished=True, published_item_id=PUBLISHED)


def test_the_cli_passes_changed_through_to_the_task() -> None:
    from papyrus_content import publish_commands
    from papyrus_content.publishing import PublishResult

    tasks: list[dict[str, Any]] = []
    with mock.patch.dict("os.environ", {"PAPYRUS_GRAPHQL_AUTH": "iam"}), mock.patch.object(publish_commands, "projection_enabled", return_value=True), mock.patch.object(
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

    def __init__(self, *, projection: bool, rejects_writes: bool = False) -> None:
        specification = importlib.util.spec_from_file_location("content_actions_publish_handler", Path(HANDLER_PATH))
        self.module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(self.module)
        self.client = FakeAuthoringClient()
        self.s3, self.cloudfront, self.sqs, self.lam = FakeS3(rejects_writes), FakeCloudFront(), FakeSqs(), FakeLambda()
        self.environment = dict(PUBLICATION_ENVIRONMENT) if projection else {}

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
        return self.run({"fieldName": field, "arguments": {"input": json.dumps(payload)}, "identity": {"username": "editor", "claims": {}}})

    def save(self, body: str = "Hello.\n") -> dict[str, Any]:
        return self.action(
            "saveItemDraft",
            {"id": ITEM, "type": "article", "slug": "hello", "section": "articles", "frontMatterYaml": "title: Hello\n", "bodyMarkus": body},
        )

    def invoked_functions(self) -> list[str]:
        return [call["FunctionName"] for call in self.lam.invocations]

    def retries(self) -> list[dict[str, Any]]:
        return [call["Payload"]["projectionTask"] for call in self.lam.invocations if "projectionTask" in call["Payload"]]


#: The records a publish writes: the Story's own rows and the published copy the pages are made from. Nothing about an announcement, a Delivery or a list.
PUBLISH_MODELS = {"Item", "PublishedItem", "PublishedMediaAsset", "MediaAsset", "Item"}
#: The names the old best-effort call used; a publish in an environment that still sets them invokes nothing.
OLD_ENVIRONMENT = {"PAPYRUS_NEWSLETTER_FUNCTION": "papyrus-newsletter-example", "PAPYRUS_NOTIFICATIONS_FUNCTION": "papyrus-notifications-example"}


@pytest.mark.parametrize("projection", [True, False])
def test_a_publish_invokes_no_function_and_writes_only_its_own_records(projection: bool) -> None:
    backend = Backend(projection=projection)
    backend.environment.update(OLD_ENVIRONMENT)
    backend.save()
    backend.client.calls.clear()
    assert backend.action("publishItem", {"id": ITEM})["changed"] is True
    assert [name for name in backend.invoked_functions() if name in OLD_ENVIRONMENT.values()] == []
    assert {model for kind, model, _ in backend.client.write_calls() } <= PUBLISH_MODELS, backend.client.write_calls()
    assert all(model not in ("AnnouncementDecision", "Delivery", "Announcement") for _, model, _ in backend.client.calls)


def test_the_publish_path_has_no_best_effort_call_or_swallowed_error() -> None:
    root = Path(__file__).resolve().parents[2]
    assert importlib.util.find_spec("papyrus_content.publish_alerts") is None, "the module that invoked the newsletter and notifications functions is gone"
    handler = (root / "amplify" / "functions" / "content-actions" / "handler.py").read_text()
    for name in ("announce_published", "publish_alerts", "PAPYRUS_NEWSLETTER_FUNCTION", "PAPYRUS_NOTIFICATIONS_FUNCTION", "item_published_announce_failed"):
        assert name not in handler, f"content-actions still names {name}"
    for plugin in ("newsletter", "notifications"):
        source = (root / "amplify" / "plugins" / plugin / "papyrus.plugin.ts").read_text()
        assert "contentActions" not in source, f"the {plugin} plugin still reaches into the content-actions function"


def test_an_edit_unpublish_and_draft_save_call_nothing() -> None:
    backend = Backend(projection=True)
    backend.save()
    backend.action("publishItem", {"id": ITEM})
    backend.lam.invocations.clear()
    backend.save("A new body.\n")
    assert backend.action("unpublishItem", {"id": ITEM})["changed"] is True
    assert set(backend.invoked_functions()) <= {"content-actions-function"}, "only the function's own follow-up projection, never another function"


def test_a_projection_failure_leaves_a_retry_that_still_marks_the_publish() -> None:
    backend = Backend(projection=True, rejects_writes=True)
    backend.save()
    response = backend.action("publishItem", {"id": ITEM})
    assert response["ok"] is True and response["live"] is False
    (retry,) = backend.retries()
    assert retry["published"] == {"publishedItemId": PUBLISHED}
    backend.s3.rejects_writes = False
    assert backend.run({"projectionTask": retry})["ok"] is True
