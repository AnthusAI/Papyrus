from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import live_schema  # noqa: E402


class LiveSchema:
    """A GraphQL API that answers the schema question with every selected field except the ones it lacks."""

    def __init__(self, lacking: set[str], lacks_for: int | None) -> None:
        self.lacking = lacking
        self.lacks_for = lacks_for
        self.asked = 0

    def graphql(self, query: str, variables=None) -> dict:
        self.asked += 1
        lacks = self.lacks_for is None or self.asked <= self.lacks_for
        selected = live_schema.selected_fields()
        answer = {}
        for index, name in enumerate(sorted(selected)):
            served = {field for field in selected[name] if not (lacks and f"{name}.{field}" in self.lacking)}
            answer[f"t{index}"] = {"fields": [{"name": field} for field in sorted(served)]}
        return answer


def handler_module():
    path = REPO_ROOT / "amplify/functions/content-actions/handler.py"
    specification = importlib.util.spec_from_file_location("content_actions_handler_schema_wait", path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@when("the post-deploy render is added next to a content-actions function in the data stack")
def add_render(context) -> None:
    done = subprocess.run(
        [str(REPO_ROOT / "node_modules/.bin/tsx"), str(REPO_ROOT / "scripts/reproject-dependency-probe.ts")],
        capture_output=True, text=True, cwd=REPO_ROOT, check=True,
    )
    context.stacks = json.loads(done.stdout.strip().splitlines()[-1])


@then("the render's stack depends on the data stack")
def depends(context) -> None:
    assert context.stacks["dependsOnFunctionStack"] is True, context.stacks


@then("the render is a single custom resource")
def single(context) -> None:
    assert context.stacks["renderResourceInOwnStack"] is True, context.stacks


@given("a live schema that serves every field the tools select")
def complete_schema(context) -> None:
    context.schema = LiveSchema(set(), 0)


@given('a live schema that lacks "{first}" and "{second}" for the first {count:d} questions')
def late_schema(context, first: str, second: str, count: int) -> None:
    context.schema = LiveSchema({first, second}, count)


@given('a live schema that never gets "{first}" and "{second}"')
def never_schema(context, first: str, second: str) -> None:
    context.schema = LiveSchema({first, second}, None)


@when("the deploy-render task runs")
def run_task(context) -> None:
    handler = handler_module()
    clock = {"now": 0.0}

    def sleep(seconds: float) -> None:
        clock["now"] += seconds

    real_wait = live_schema.wait_for_live_schema
    context.failure = None
    with mock.patch.object(handler, "create_authoring_client", return_value=(context.schema, {})), mock.patch.object(
        handler, "run_deploy_render_task", return_value={"ok": True}
    ) as render, mock.patch.object(
        handler, "wait_for_live_schema", lambda client: real_wait(client, sleep=sleep, clock=lambda: clock["now"])
    ):
        try:
            handler.handler({"projectionTask": {"task": "deploy-render"}}, None)
        except live_schema.LiveSchemaIncomplete as error:
            context.failure = str(error)
    context.rendered = render.called


@then("the live schema was asked {count:d} time")
@then("the live schema was asked {count:d} times")
def asked(context, count: int) -> None:
    assert context.schema.asked == count, context.schema.asked


@then("the site was rendered")
def rendered(context) -> None:
    assert context.rendered is True and context.failure is None, context.failure


@then("the site was not rendered")
def not_rendered(context) -> None:
    assert context.rendered is False


@then('the deploy-render task failed saying "{text}"')
def failed(context, text: str) -> None:
    assert context.failure is not None and text in context.failure, context.failure
