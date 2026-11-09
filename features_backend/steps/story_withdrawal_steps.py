"""Steps for features_backend/story-withdraw-restore.feature. The data client, the site's function and the edge are in-memory stand-ins."""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures/newsroom/tests", REPO_ROOT / "features_backend/steps"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import story_commands, story_withdrawal  # noqa: E402
from papyrus_content.page_refresh.budget import Budget  # noqa: E402
from papyrus_content.page_refresh.operations import run_operation  # noqa: E402
from papyrus_content.page_refresh.service import RefreshService  # noqa: E402
from papyrus_content.projection.directory_source import DirectoryContentSource  # noqa: E402
from papyrus_content.projection.engine import ProjectionContext  # noqa: E402
from papyrus_content.projection.standard.projector import StandardMarkusProjector  # noqa: E402
from papyrus_content.projection.writers import LocalDirectoryWriter  # noqa: E402
from papyrus_content.publishing import ItemFields, publish_item, save_item  # noqa: E402
from page_refresh_steps import ITEMS, SETTINGS, EdgeFake  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402
from procedures.newsroom.tests.standard_frontend_content_support import DirectorySite  # noqa: E402

NOW = "2026-11-09T10:00:00Z"


class World:
    """The stand-in for the site: the directory site answers the plan and the purge exactly as the real function does; the projection answer is canned."""

    def __init__(self, context, lineage: str) -> None:
        built = DirectorySite(SETTINGS, ITEMS)
        context.tmp_dirs.append(built.work)
        projector = StandardMarkusProjector.from_static_directory(built.static, environ=built.environ)
        self.projection = ProjectionContext(source=DirectoryContentSource(built.content), projector=projector, writer=LocalDirectoryWriter(built.out), keep_state=False)
        self.edge, self.cap, self.tasks, self.lineage = EdgeFake(), 25, [], lineage
        self.client = FakeAuthoringClient()
        self.out = ""
        self.failure = None
        self.exit_code = None

    def lane(self, _client, name, arguments):
        service = RefreshService(distribution_id="EDIST", context=lambda: self.projection, cloudfront=self.edge, sleep=lambda _s: None, emit_metric=False, budget=Budget(self.cap))
        return run_operation(name, arguments, service)

    def trigger(self, _client, task):
        self.tasks.append(task)
        return {"ok": True, "status": "projected", "invalidation": {"status": "skipped", "paths": []}}

    def run(self, function, flags):
        out = io.StringIO()
        self.failure = self.exit_code = None
        with mock.patch.object(story_commands, "create_authoring_client", return_value=(self.client, {})), mock.patch.object(story_withdrawal, "lane_call", self.lane), \
                mock.patch.object(story_withdrawal, "projection_trigger", self.trigger), mock.patch.object(story_withdrawal, "projecting", return_value=True), \
                contextlib.redirect_stdout(out):
            try:
                function(flags)
            except SystemExit as error:
                self.exit_code = error.code
            except ValueError as error:
                self.failure = error
        self.out = out.getvalue()
        return self.out

    @property
    def item(self) -> dict:
        return self.client.tables["Item"][self.lineage]


def world(context) -> World:
    return context.withdrawal


@given('a published Story "{lineage}" on a site with four articles in two pages of the articles section')
def published_story(context, lineage: str) -> None:
    context.withdrawal = built = World(context, lineage)
    fields = ItemFields(type="article", slug="a1", section="articles", front_matter_yaml="title: A1\n", body_markus="Body of a1.\n", aliases=[], id=lineage)
    save_item(built.client, fields, actor="behave", now="2026-11-01T10:00:00Z")
    publish_item(built.client, lineage, actor="behave", now="2026-11-01T10:00:00Z")


@given("the site allows at most {count:d} paths in one call")
def cap(context, count: int) -> None:
    world(context).cap = count


@given("the Story is a draft that was never published")
def never_published(context) -> None:
    built = world(context)
    built.client = FakeAuthoringClient()
    fields = ItemFields(type="article", slug="a1", section="articles", front_matter_yaml="title: A1\n", body_markus="Body of a1.\n", aliases=[], id=built.lineage)
    save_item(built.client, fields, actor="behave", now=NOW)


@given("the Story was withdrawn")
def was_withdrawn(context) -> None:
    built = world(context)
    built.run(story_commands.stories_withdraw, ["--story", built.lineage, "--run", "--author-label", "Ryan", "--reason", "mistake"])
    assert built.item["stage"] == "spiked", built.out
    built.edge.requests.clear()
    built.tasks.clear()


def withdraw(context, *flags: str) -> None:
    built = world(context)
    built.run(story_commands.stories_withdraw, ["--story", built.lineage, *flags])


@when("an editor withdraws the Story as a dry run")
def withdraw_dry(context) -> None:
    withdraw(context, "--dry-run")


@when("an editor withdraws the Story without --run")
def withdraw_without_run(context) -> None:
    withdraw(context)


@when('an editor "{name}" withdraws the Story with the reason "{reason}"')
def withdraw_named(context, name: str, reason: str) -> None:
    withdraw(context, "--run", "--author-label", name, "--reason", reason)


@when("an editor withdraws the Story forcing up to {count:d} paths")
def withdraw_forced(context, count: int) -> None:
    withdraw(context, "--run", "--force-paths", str(count))


@when("an editor tries to withdraw the Story")
def withdraw_try(context) -> None:
    withdraw(context, "--run")


@when("an editor withdraws the Story again")
def withdraw_again(context) -> None:
    withdraw(context, "--run")


@when("an editor restores the Story")
def restore(context) -> None:
    built = world(context)
    built.run(story_commands.stories_restore, ["--story", built.lineage, "--run"])


@when("an editor tries to restore the Story")
def restore_try(context) -> None:
    restore(context)


@when('an editor reads the help of "stories move"')
def read_help(context) -> None:
    from papyrus.operator.group_commands import COMMAND_USAGE

    context.help_text = story_commands.stories_move.__doc__ + "\n" + COMMAND_USAGE[("stories", "move")]


def listed(text: str) -> list[str]:
    return [part.strip() for part in text.replace(" and ", ",").replace('"', "").split(",") if part.strip()]


@then("the plan lists the Story page and its Markdown twin {keys}")
def plan_story(context, keys: str) -> None:
    for key in listed(keys):
        assert key in world(context).out, (key, world(context).out)


@then("the plan lists the index pages {keys}")
def plan_indexes(context, keys: str) -> None:
    for key in listed(keys):
        assert key in world(context).out, (key, world(context).out)


@then("the plan lists {count:d} invalidation paths and says they cost at most {usd} USD at 0.005 USD each")
def plan_count(context, count: int, usd: str) -> None:
    out = world(context).out
    assert f"invalidation: {count} paths" in out and f"at most {usd} USD for {count} paths" in out and "0.005 USD each" in out, out


@then('the plan lists the path "{path}"')
def plan_path(context, path: str) -> None:
    assert f"    {path}" in world(context).out.splitlines(), world(context).out


@then("nothing was written and nothing was purged")
def untouched(context) -> None:
    built = world(context)
    assert built.item["status"] == "published" and "dry run" in built.out
    assert built.edge.requests == [] and built.tasks == [], (built.edge.requests, built.tasks)


@then("the Story is still published")
def still_published(context) -> None:
    built = world(context)
    assert built.item["status"] == "published" and "published-" + built.lineage in built.client.tables["PublishedItem"], built.out
    assert built.tasks == []


@then("the output says to repeat the command with --run")
def says_run(context) -> None:
    assert "--run" in world(context).out, world(context).out


@then("no published row remains for the Story")
def no_rows(context) -> None:
    assert not world(context).client.tables.get("PublishedItem") and not world(context).client.tables.get("PublishedMediaAsset")


@then('the Story\'s board stage is "{stage}"')
def stage_is(context, stage: str) -> None:
    assert world(context).item["stage"] == stage, world(context).out


@then('the Story\'s board stage is not "{stage}"')
def stage_is_not(context, stage: str) -> None:
    assert world(context).item["stage"] != stage


@then('the Story\'s withdrawal record names version {version:d}, "{name}", the reason "{reason}" and the previous stage "{stage}"')
def record_names(context, version: int, name: str, reason: str, stage: str) -> None:
    record = story_withdrawal.withdrawal_of(world(context).item)
    assert record["withdrawnVersion"] == version and record["withdrawnBy"] == name and record["reason"] == reason and record["previousStage"] == stage, record
    assert record["withdrawnAt"], record


@then("the site was asked to take the Story's pages away")
def asked_to_project(context) -> None:
    assert world(context).tasks == [{"task": "item", "itemId": world(context).lineage, "unpublished": True}], world(context).tasks


@then("the withdrawal asked the edge to purge exactly the {count:d} planned paths")
def edge_exact(context, count: int) -> None:
    built = world(context)
    paths = [path for request in built.edge.requests for path in request["InvalidationBatch"]["Paths"]["Items"]]
    expected = {"/", "/index.html", "/index.md", "/articles/", "/articles/index.html", "/articles/index.md", "/articles/a1/", "/articles/a1/index.html", "/articles/a1/index.md"}
    assert len(paths) == count and set(paths) == expected, paths
    assert not any("*" in path for path in paths)


@then("the withdrawal is refused as over the cap")
def refused_cap(context) -> None:
    assert world(context).exit_code == 2 and "over the cap" in world(context).out, (world(context).exit_code, world(context).out)


@then("the withdrawal asked the edge for no purge")
def edge_untouched(context) -> None:
    assert world(context).edge.requests == []


@then("the withdrawal is refused because the Story is not published")
def refused_unpublished(context) -> None:
    assert world(context).failure is not None and "not published" in str(world(context).failure), world(context).out


@then("the output says the Story is already withdrawn")
def already(context) -> None:
    assert "already-withdrawn" in world(context).out, world(context).out


@then("nothing new was purged")
def nothing_new(context) -> None:
    assert world(context).edge.requests == [] and world(context).tasks == []


@then('the Story is published again with the board stage "{stage}"')
def republished(context, stage: str) -> None:
    built = world(context)
    assert built.item["status"] == "published" and built.item["stage"] == stage and "published-" + built.lineage in built.client.tables["PublishedItem"], built.out


@then("the Story has no withdrawal record")
def no_record(context) -> None:
    assert story_withdrawal.withdrawal_of(world(context).item) is None


@then("the restore is refused because nothing was withdrawn")
def restore_refused(context) -> None:
    assert world(context).failure is not None and "nothing to restore" in str(world(context).failure), world(context).out


@then("the help says the move is board-only")
def help_board_only(context) -> None:
    assert "board-only" in context.help_text or "board stage only" in context.help_text


@then('the help points to "{command}" to take a page down')
def help_points(context, command: str) -> None:
    assert command in context.help_text
