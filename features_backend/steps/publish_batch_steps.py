"""features_backend/publish-batch.feature: the batch publish of the signed-in lane (queue each Story, drain once) and the site's one-lease build of the queue."""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import publish_commands  # noqa: E402

IDS = ["story-a--es-419-v1", "story-b--es-419-v1", "story-c--es-419-v1"]


class RecordingClient:
    """The signed-in lane's GraphQL client: records every publishItem input and answers like the backend."""

    def __init__(self):
        self.inputs = []
        self.job_asks = []

    def get_record(self, model, record_id):
        return {"id": record_id, "slug": "a-real-slug"}

    def graphql(self, query, variables):
        payload = json.loads(variables["input"])
        self.inputs.append(payload)
        if payload.get("drain"):
            answer = {"ok": True, "scheduled": True}
        elif payload.get("jobStatus"):
            self.job_asks.append(payload["id"])
            answer = {"projection": {"jobId": f"job-{payload['id']}", "state": "done", "itemPaths": [], "paths": []}}
        else:
            answer = {"ok": True, "projection": {"jobId": f"job-{payload['id']}", "state": "queued", "queued": True, "joined": False}}
        return {"publishItem": json.dumps(answer)}


@given("a signed-in lane and three saved versions")
def step_lane(context):
    context.client = RecordingClient()


@when("the three versions are published as a batch")
def step_batch(context):
    result = SimpleNamespace(changed=True, version_number=1)
    patches = [
        mock.patch.object(publish_commands, "create_authoring_client", return_value=(context.client, {"sub": "editor"})),
        mock.patch.object(publish_commands, "publish_item", side_effect=lambda client, item_id, actor, **_: SimpleNamespace(item_id=item_id, changed=True, version_number=1, published_item_id=f"published-{item_id}")),
        mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=True),
        mock.patch("papyrus_content.projection_trigger.JOB_POLL_SECONDS", 0),
    ]
    for patcher in patches:
        patcher.start()
        context.add_cleanup(patcher.stop)
    flags = [part for item_id in IDS for part in ("--id", item_id)]
    with redirect_stdout(io.StringIO()):
        publish_commands.content_publish(flags)


@then("every version is queued with no build of its own")
def step_queued(context):
    queued = [payload for payload in context.client.inputs if payload.get("queueOnly")]
    assert [payload["id"] for payload in queued] == IDS and all(payload["async"] is True for payload in queued), context.client.inputs
    assert not [payload for payload in context.client.inputs if payload.get("async") and not payload.get("queueOnly")]


@then("the site is asked exactly once to build the queue")
def step_drain_once(context):
    assert [payload for payload in context.client.inputs if payload.get("drain")] == [{"drain": True}]


@then("each version's job is asked about until it is done")
def step_jobs(context):
    assert sorted(context.client.job_asks) == sorted(IDS), context.client.job_asks


# --- the site's one-lease build of the queue (the handler, with the lock table replaced by moto and the projection by a recorder) -----------------------

@given("the site's publish jobs and two published Stories queued by a batch")
def step_site(context):
    import test_publish_jobs as support   # procedures/newsroom/tests

    case = support.AsynchronousPublishTest("test_a_batch_queues_every_story_starts_no_build_and_one_drain_builds_them_all_under_one_lease")
    case.setUp()
    context.add_cleanup(case.tearDown)
    support.published_story(case.client, "story-2")
    case.queue("story-1")
    case.queue("story-2")
    context.case = case


@when("the one drain runs")
def step_drain(context):
    from test_publish_jobs import handler

    assert context.case.drain()["scheduled"]
    handler.handler({"projectionTask": context.case.scheduled[0]}, None)


@then("both Stories are built")
def step_built(context):
    assert sorted(context.case.projected) == ["story-1", "story-2"], context.case.projected


@then("the projection lease was taken once")
def step_one_lease(context):
    assert context.case.lease.holds == 1, context.case.lease.holds
