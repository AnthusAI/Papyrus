from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures/newsroom/tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.model import ProjectionReport  # noqa: E402
from papyrus_content.projection.engine import _finish  # noqa: E402
from papyrus_content.projection.writers import CloudFrontInvalidator, TargetedCloudFrontInvalidator, invalidation_paths_for  # noqa: E402
from procedures.newsroom.tests.incremental_site import Site, add_item  # noqa: E402


class Edge:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def create_invalidation(self, **arguments):
        self.calls.append(arguments["InvalidationBatch"]["Paths"]["Items"])
        return {"Invalidation": {"Id": f"I{len(self.calls)}", "Status": "InProgress"}}

    @property
    def paths(self) -> list[str]:
        return [path for call in self.calls for path in call]


def quiet(function, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return function(*args, **kwargs)


def handler_module():
    path = REPO_ROOT / "amplify/functions/content-actions/handler.py"
    specification = importlib.util.spec_from_file_location("content_actions_handler_feature", path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@given("a site that opted in to targeted invalidation with a cap of {cap:d} paths")
def targeted_site(context, cap: int) -> None:
    context.edge = Edge()
    context.invalidator = TargetedCloudFrontInvalidator("EDIST", cap, context.edge)
    context.environment_value = "targeted"


@given("a site that has not set the cache invalidation")
def default_site(context) -> None:
    context.edge = Edge()
    context.invalidator = TargetedCloudFrontInvalidator("EDIST", 25, context.edge)
    context.environment_value = None


@given('a site that set the cache invalidation to "all"')
def all_site(context) -> None:
    context.edge = Edge()
    context.invalidator = CloudFrontInvalidator("EDIST", context.edge)
    context.environment_value = "all"


@when("one story is published with a new version")
def one_story(context) -> None:
    work = tempfile.TemporaryDirectory()
    context.tmp_dirs.append(work)
    site = Site("feed", Path(work.name))
    for number in range(5):
        add_item(site, f"item-{number}", f"seed-{number}", date=f"2026-01-{number + 1:02d}")
    site.context.invalidate = context.invalidator.invalidate
    site.drafts["item-0"].body = "A new version.\n"
    site.publish("item-0")
    context.report = quiet(site.project_item, "item-0")


@when("a publish writes {count:d} pages")
def many_pages(context, count: int) -> None:
    context.report = ProjectionReport(written=[f"articles/p{number}/index.html" for number in range(count)])
    quiet(_finish, type("Ctx", (), {"invalidate": context.invalidator.invalidate})(), context.report)


@when("a publish writes the story page and {count:d} listing pages")
def story_and_listings(context, count: int) -> None:
    keys = [f"articles/p{number}/index.html" for number in range(count)] + ["articles/hello/index.html", "articles/hello/index.md"]
    context.report = ProjectionReport(written=keys, item_paths=["articles/hello/index.html", "articles/hello/index.md"])
    quiet(_finish, type("Ctx", (), {"invalidate": context.invalidator.invalidate})(), context.report)


@then("the first paths purged are the story page and its twin")
def story_first(context) -> None:
    assert context.edge.paths[:3] == ["/articles/hello/index.html", "/articles/hello/", "/articles/hello/index.md"], context.edge.paths


@when("the whole site is rendered")
def whole_site(context) -> None:
    handler = handler_module()
    ctx = mock.Mock()
    ctx.invalidate = context.invalidator.invalidate
    report = mock.Mock(ok=True, unpurged=[], written=[], deleted=[], follow_up_item_pages=False)
    with mock.patch.dict("os.environ", {}, clear=False), mock.patch.object(handler, "create_authoring_client", return_value=(object(), {})), mock.patch.object(
        handler, "projection_context", return_value=ctx
    ), mock.patch.object(handler, "project_all", return_value=report) as run:
        handler._run_projection_task({"task": "all"})
    if run.call_args.args[0].invalidate is not None:
        run.call_args.args[0].invalidate(["articles/a/index.html"])


@when("the site is rendered by a deploy")
def deploy(context) -> None:
    handler = handler_module()
    ctx = mock.Mock()
    ctx.invalidate = context.invalidator.invalidate
    report = mock.Mock(ok=True)
    report.render.unpurged = []
    report.to_dict.return_value = {}
    with mock.patch.dict(handler.os.environ, {"PAPYRUS_EDGE_INVALIDATION": context.environment_value or ""}), mock.patch.object(handler, "ensure_publication_from_environment"), mock.patch.object(
        handler, "ensure_default_editorial_policies"
    ), mock.patch.object(handler, "projection_context", return_value=ctx), mock.patch.object(handler, "drift_metric_line", return_value=""), mock.patch.object(
        handler, "deploy_render"
    ) as render:
        render.return_value = report
        handler.run_deploy_render_task(object())
    # What the deploy would do with the context it was given: invalidate whatever it wrote.
    if render.call_args.args[0].invalidate is not None:
        render.call_args.args[0].invalidate(["articles/a/index.html"])


@then("the edge was asked to purge exactly the paths of the pages that publish wrote")
def exact(context) -> None:
    written = [key for key in [*context.report.written, *context.report.deleted] if not key.startswith("_papyrus/")]
    assert sorted(context.edge.paths) == sorted(invalidation_paths_for(written)), (context.edge.paths, written)
    assert context.edge.paths


@then("no purged path is a wildcard")
def no_wildcard(context) -> None:
    assert "/*" not in context.edge.paths and not any("*" in path for path in context.edge.paths), context.edge.paths


@then("the publish reports the pages written and the paths purged as separate outcomes")
def separate(context) -> None:
    assert context.report.written and context.report.invalidated and not context.report.unpurged


@then("the edge was asked to purge {count:d} paths")
def purge_count(context, count: int) -> None:
    assert len(context.edge.paths) == count, context.edge.paths


@then("the publish names the paths that were not purged")
def names_skipped(context) -> None:
    assert context.report.invalidation_capped and not context.report.unpurged


@then("the pages are reported as written, not as a failed write")
def not_failed(context) -> None:
    assert context.report.ok and context.report.written


@then("the edge was asked to purge the whole site with one wildcard")
def wildcard(context) -> None:
    assert context.edge.paths == ["/*"], context.edge.paths


@then("the edge was not asked to purge anything")
def nothing(context) -> None:
    assert context.edge.paths == []
