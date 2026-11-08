from __future__ import annotations

import contextlib
import io
import json
import re
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures/newsroom/tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.page_refresh import cli as refresh_cli  # noqa: E402
from papyrus_content.page_refresh.mcp import call_page_refresh_tool, page_refresh_tools  # noqa: E402
from papyrus_content.page_refresh.service import RefreshService  # noqa: E402
from papyrus_content.projection.directory_source import DirectoryContentSource  # noqa: E402
from papyrus_content.projection.engine import ProjectionContext  # noqa: E402
from papyrus_content.projection.standard.projector import StandardMarkusProjector  # noqa: E402
from papyrus_content.projection.writers import LocalDirectoryWriter  # noqa: E402
from procedures.newsroom.tests.no_lock_parameter import NoLockParameter  # noqa: E402
from procedures.newsroom.tests.standard_frontend_content_support import DirectorySite, item, settings  # noqa: E402

SETTINGS = settings(
    urls={"style": "directory", "sections": {"articles": {"pageSize": 2}, "videos": {}}},
    listings={"pageSize": 2, "featuredCount": 0, "tags": False},
    agents={"markdown": True},
)
ITEMS = [
    item("a1", section="articles", date="2026-01-05"),
    item("a2", section="articles", date="2026-01-04"),
    item("a3", section="articles", date="2026-01-03"),
    item("a4", section="articles", date="2026-01-02"),
    item("v1", section="videos", date="2026-01-01"),
]
TEN_PATH_NOTE = "the first 1000 paths a month are free"


class EdgeFake:
    """A CloudFront that answers like the service: an id and a status for each request, or an error."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.rejects = False

    def create_invalidation(self, **arguments):
        if self.rejects:
            raise RuntimeError("AccessDenied: User is not authorized to perform cloudfront:CreateInvalidation")
        self.requests.append(arguments)
        return {"Invalidation": {"Id": f"INV{len(self.requests):03d}", "Status": "InProgress"}}

    @property
    def paths(self) -> list[str]:
        return [path for request in self.requests for path in request["InvalidationBatch"]["Paths"]["Items"]]


def state(context):
    return context.page_refresh


@given("a site with four articles in two pages of the articles section and one video")
def a_site(context) -> None:
    built = DirectorySite(SETTINGS, ITEMS)
    context.tmp_dirs.append(built.work)
    projector = StandardMarkusProjector.from_static_directory(built.static, environ=built.environ)
    projection = ProjectionContext(source=DirectoryContentSource(built.content), projector=projector, writer=LocalDirectoryWriter(built.out), keep_state=False)
    context.page_refresh = type("State", (), {})()
    state(context).site, state(context).projection, state(context).edge = built, projection, EdgeFake()
    state(context).result = state(context).exit_code = state(context).output = None


@given("the edge rejects invalidations")
def edge_rejects(context) -> None:
    state(context).edge.rejects = True


def service(context) -> RefreshService:
    return RefreshService(distribution_id="EDIST", context=lambda: state(context).projection, cloudfront=state(context).edge, sleep=lambda _s: None)


@when('the editor refreshes the page "{path}"')
def refresh_page(context, path: str) -> None:
    state(context).result = call_page_refresh_tool("site_refresh_pages", {"paths": [path]}, service(context))


@when('the editor refreshes the page "{path}" as a dry run')
def refresh_page_dry(context, path: str) -> None:
    state(context).result = call_page_refresh_tool("site_refresh_pages", {"paths": [path], "dryRun": True}, service(context))


@when('the editor refreshes the Story "{lineage}"')
def refresh_story(context, lineage: str) -> None:
    state(context).result = call_page_refresh_tool("site_refresh_story", {"storyLineageId": lineage}, service(context))


@when("the editor refreshes the index pages")
def refresh_indexes(context) -> None:
    state(context).result = call_page_refresh_tool("site_refresh_indexes", {}, service(context))


@when("the editor refreshes {count:d} pages")
def refresh_many(context, count: int) -> None:
    paths = [f"/articles/story-{number}/" for number in range(count)]
    state(context).result = call_page_refresh_tool("site_refresh_pages", {"paths": paths}, service(context))


@when("the editor re-renders the index pages")
def rerender_indexes(context) -> None:
    state(context).result = call_page_refresh_tool("site_rerender_pages", {"scope": "indexes"}, service(context))


@when('the editor re-renders the Story "{lineage}"')
def rerender_story(context, lineage: str) -> None:
    state(context).result = call_page_refresh_tool("site_rerender_pages", {"scope": "story", "storyLineageId": lineage}, service(context))


@when("the editor re-renders the whole site as a dry run")
def rerender_all_dry(context) -> None:
    state(context).result = call_page_refresh_tool("site_rerender_pages", {"scope": "all", "dryRun": True}, service(context))


def quoted(text: str) -> list[str]:
    """``"/a/", "/b/" and "/c/"`` as ``['/a/', '/b/', '/c/']``."""
    return [part.strip() for part in text.replace(" and ", ",").replace('"', "").split(",") if part.strip()]


def invalidated(context) -> list[str]:
    return state(context).result["invalidation"]["paths"]


@then("the refresh succeeded")
def refresh_succeeded(context) -> None:
    assert state(context).result["ok"] is True, state(context).result


@then("the refresh did not succeed")
def refresh_failed(context) -> None:
    assert state(context).result["ok"] is False, state(context).result


@then("the edge was asked to invalidate exactly {paths}")
def edge_exactly(context, paths: str) -> None:
    assert state(context).edge.paths == quoted(paths), state(context).edge.paths


@then("the edge was not asked to invalidate anything")
def edge_untouched(context) -> None:
    assert state(context).edge.requests == [], state(context).edge.requests


@then("the result names the CloudFront invalidation id and its status")
def result_has_id(context) -> None:
    requests = state(context).result["invalidation"]["requests"]
    assert requests and requests[0]["id"] == "INV001" and requests[0]["status"] == "InProgress", requests


@then('the result lists "{path}" among the paths')
def result_lists(context, path: str) -> None:
    assert path in invalidated(context), invalidated(context)


@then("the paths invalidated include {paths}")
def paths_include(context, paths: str) -> None:
    wanted = quoted(paths)
    if "the home page" in paths:
        wanted = ["/", "/index.html", "/index.md", "/articles/", "/articles/index.html", "/articles/index.md"]
    missing = [path for path in wanted if path not in invalidated(context)]
    assert not missing, (missing, invalidated(context))


@then("the paths invalidated do not include {paths}")
def paths_exclude(context, paths: str) -> None:
    found = invalidated(context)
    assert "/articles/page/2/" not in found and not any(path.startswith("/videos/") for path in found), found


@then("the paths invalidated name no Story page")
def no_story_pages(context) -> None:
    found = invalidated(context)
    assert not any(any(f"/{slug}/" in path for slug in ("a1", "a2", "a3", "a4", "v1")) for path in found), found


@then("no path invalidated is a wildcard")
def no_wildcard(context) -> None:
    assert not any("*" in path for path in invalidated(context)), invalidated(context)
    assert not any("*" in path for path in state(context).edge.paths)


@then("the edge received more than one request of at most 3000 paths each")
def several_requests(context) -> None:
    sizes = [request["InvalidationBatch"]["Paths"]["Quantity"] for request in state(context).edge.requests]
    assert len(sizes) > 1 and max(sizes) <= 3000, sizes


@then("the result says how many paths were invalidated")
def result_count(context) -> None:
    invalidation = state(context).result["invalidation"]
    assert invalidation["count"] == len(invalidation["paths"]) > 0, invalidation


@then("the result says the first 1000 paths a month are free and each one after costs 0.005 USD")
def result_cost(context) -> None:
    cost = state(context).result["invalidation"]["cost"]
    assert cost["freePathsPerMonth"] == 1000 and cost["usdPerPathAfterFree"] == 0.005, cost


@then("the request is refused as invalid input")
def refused_invalid(context) -> None:
    assert state(context).result["ok"] is False and state(context).result["error"]["code"] == "invalid_input", state(context).result


@then("the request is refused as not found")
def refused_not_found(context) -> None:
    assert state(context).result["ok"] is False and state(context).result["error"]["code"] == "not_found", state(context).result


@then("the re-render wrote the home page and the articles list page")
def rerender_wrote_indexes(context) -> None:
    written = state(context).result["rendered"]["written"]
    assert "index.html" in written and "articles/index.html" in written, written


@then('the re-render wrote "{key}"')
def rerender_wrote(context, key: str) -> None:
    assert key in state(context).result["rendered"]["written"], state(context).result["rendered"]


@then("the re-render outcome is ok and the invalidation outcome is ok")
def both_ok(context) -> None:
    assert state(context).result["rendered"]["ok"] is True and state(context).result["invalidation"]["ok"] is True, state(context).result


@then("the re-render outcome is ok and the invalidation outcome is failed with a reason")
def render_ok_invalidation_failed(context) -> None:
    result = state(context).result
    assert result["rendered"]["ok"] is True and result["invalidation"]["ok"] is False, result
    assert result["invalidation"]["status"] == "failed" and "AccessDenied" in result["invalidation"]["error"], result


@then("the result lists the pages it would write")
def lists_would_write(context) -> None:
    rendered = state(context).result["rendered"]
    assert rendered["dryRun"] and "articles/a1/index.html" in rendered["wouldWrite"], rendered


@then("nothing was written to the site")
def nothing_written(context) -> None:
    assert not (state(context).site.out / "index.html").exists()


# ------------------------------------------------------------------ the command, operator lane


def run_command(context, words: str, *, signed_in: bool, client=None) -> None:
    flags = words.split()
    command = refresh_cli.content_rerender if flags[0] == "rerender" else refresh_cli.content_refresh
    out, err = io.StringIO(), io.StringIO()
    edge = getattr(context, "page_refresh", None) and state(context).edge
    patches = [
        mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=signed_in),
        mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(client, {})),
    ]
    if not signed_in:
        patches += [
            mock.patch("papyrus_content.project_commands._context_for", side_effect=lambda _client, _options: state(context).projection),
            mock.patch("papyrus_content.project_commands._projection_environment", return_value={"PAPYRUS_EDGE_DISTRIBUTION_ID": "EDIST"}),
            mock.patch("boto3.client", side_effect=lambda name, **_kwargs: edge),
        ]
    exit_code, error = 0, None
    with contextlib.ExitStack() as stack, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        for patch in patches:
            stack.enter_context(patch)
        try:
            command(flags[1:])
        except SystemExit as exit_:
            exit_code = exit_.code
        except ValueError as refused:
            exit_code, error = 2, str(refused)
    context.command_exit, context.command_out, context.command_err, context.command_error = exit_code, out.getvalue(), err.getvalue(), error


@when('an operator runs the page refresh command "{words}"')
def operator_runs(context, words: str) -> None:
    run_command(context, words, signed_in=False)


@then("the page refresh command exits with status {code:d}")
def command_exit(context, code: int) -> None:
    assert context.command_exit == code, (context.command_exit, context.command_out, context.command_err, context.command_error)


@then("the page refresh command output says the invalidation FAILED")
def command_says_failed(context) -> None:
    assert "invalidation: FAILED" in context.command_out and "AccessDenied" in context.command_out, context.command_out


@then("the page refresh command output lists the paths, the cost and the CloudFront invalidation id with its status")
def command_lists(context) -> None:
    out = context.command_out
    assert "/articles/a1/index.html" in out and "at most" in out and "USD" in out and "INV001: InProgress" in out, out
    assert TEN_PATH_NOTE.replace("1000", "1,000") in out, out


@then('the page refresh command printed JSON for the operation "{operation}" with {count:d} paths')
def command_json(context, operation: str, count: int) -> None:
    printed = json.loads(context.command_out)
    assert printed["operation"] == operation and printed["invalidation"]["count"] == count, printed


@then('the page refresh command is refused with "{message}"')
def command_refused(context, message: str) -> None:
    assert context.command_exit == 2 and message in (context.command_error or ""), (context.command_exit, context.command_error)


@when('an agent calls the tool "{tool}" with the Story "{lineage}"')
def agent_calls(context, tool: str, lineage: str) -> None:
    state(context).tool_result = call_page_refresh_tool(tool, {"storyLineageId": lineage, "dryRun": True}, service(context))
    run_command(context, f"refresh --story {lineage} --dry-run --json", signed_in=False)


@then("the tool result is the same JSON the page refresh command prints for that Story")
def tool_equals_command(context) -> None:
    assert json.loads(context.command_out) == state(context).tool_result


@then("the tool list is site_refresh_pages, site_refresh_story, site_refresh_indexes and site_rerender_pages")
def tool_list(context) -> None:
    assert sorted(page_refresh_tools()) == sorted(["site_refresh_pages", "site_refresh_story", "site_refresh_indexes", "site_rerender_pages"])


# ------------------------------------------------------------------ the editor lane (the content-actions function)


@given("a content actions backend with an s3-projection publication whose saves do not invalidate")
def backend_without_save_invalidation(context) -> None:
    context.execute_steps("Given a content actions backend with an s3-projection publication")
    context.environment["PAPYRUS_EDGE_INVALIDATION"] = "off"


@given("the edge reports invalidation ids and statuses")
def edge_reports_ids(context) -> None:
    original = context.cloudfront.create_invalidation

    def create(**arguments):
        original(**arguments)
        return {"Invalidation": {"Id": f"INV{len(context.cloudfront.invalidations):03d}", "Status": "InProgress"}}

    context.cloudfront.create_invalidation = create


def clients(context) -> dict:
    return {"s3": context.s3, "cloudfront": context.cloudfront, "sqs": context.sqs, "lambda": context.lambda_client, "ssm": NoLockParameter()}


def call_handler(context, event: dict):
    with mock.patch.object(context.handler_module, "create_authoring_client", return_value=(context.client, {})), \
            mock.patch("boto3.client", side_effect=lambda name, **_kwargs: clients(context)[name]), \
            mock.patch.dict("os.environ", context.environment, clear=False):
        return context.handler_module.handler(event, None)


class NewsroomClient:
    """What the signed-in command talks to: its mutation reaches the content-actions function."""

    def __init__(self, context) -> None:
        self.context = context

    def graphql(self, query, variables=None):
        field = "refreshSitePages"
        assert field in query, query
        event = {"fieldName": field, "arguments": {"input": variables["input"]}, "identity": {"username": "behave-editor"}}
        return {field: json.dumps(call_handler(self.context, event))}


@when('a signed-in editor runs the page refresh command "{words}"')
@given('a signed-in editor runs the page refresh command "{words}"')
def signed_in_runs(context, words: str) -> None:
    run_command(context, words, signed_in=True, client=NewsroomClient(context))


@when("a signed-in editor refreshes the published article through the newsroom")
def signed_in_story(context) -> None:
    event = {"fieldName": "refreshSitePages", "arguments": {"input": json.dumps({"operation": "site_refresh_story", "storyLineageId": "item-articles-hello"})}, "identity": {"username": "behave-editor"}}
    context.newsroom_answer = call_handler(context, event)


@then("the newsroom answer is ok")
def newsroom_ok(context) -> None:
    assert context.newsroom_answer["ok"] is True, context.newsroom_answer


@then("the edge distribution was asked to invalidate {paths}")
def distribution_asked(context, paths: str) -> None:
    sent = [path for call in context.cloudfront.invalidations for path in call["InvalidationBatch"]["Paths"]["Items"]]
    missing = [path for path in quoted(paths) if path not in sent]
    assert not missing and all(call["DistributionId"] == "EDISTRIBUTION" for call in context.cloudfront.invalidations), (missing, sent)
    assert not any("*" in path for path in sent), sent


@then("the page refresh command output lists the CloudFront invalidation id with its status")
def command_lists_id(context) -> None:
    assert re.search(r"CloudFront invalidation INV\d+: InProgress", context.command_out), context.command_out


@then("the page refresh command output says the re-render was scheduled")
def command_scheduled(context) -> None:
    assert "scheduled" in context.command_out, context.command_out


def scheduled_tasks(context) -> list[dict]:
    return [call["Payload"]["projectionTask"] for call in context.lambda_client.invocations if "projectionTask" in call["Payload"]]


@then("the scheduled task re-renders the whole site and invalidates what it wrote")
def task_scheduled(context) -> None:
    tasks = [task for task in scheduled_tasks(context) if task["task"] == "page-refresh-rerender"]
    assert tasks and tasks[-1]["scope"] == "all" and tasks[-1]["invalidate"] is True, scheduled_tasks(context)


@when("the scheduled re-render task runs")
def scheduled_runs(context) -> None:
    task = [task for task in scheduled_tasks(context) if task["task"] == "page-refresh-rerender"][-1]
    context.cloudfront.invalidations.clear()
    context.task_result = call_handler(context, {"projectionTask": task})


@then('the site bucket holds "{key}"')
def bucket_holds(context, key: str) -> None:
    assert key in context.s3.objects, list(context.s3.objects)


@then("the page refresh command output says the site does not project its pages")
def command_not_projected(context) -> None:
    assert "does not project its pages" in context.command_out, context.command_out
