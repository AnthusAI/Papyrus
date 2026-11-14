"""`papyrus stories withdraw|restore` and their MCP tools. The client is an in-memory fake, the site's function and the edge are stand-ins, nothing leaves the process."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

import test_cli_reads as support  # noqa: E402
from papyrus_content import story_commands, story_withdrawal  # noqa: E402
from papyrus_content.edge_invalidation import invalidation_cost_note  # noqa: E402
from papyrus_content.publishing import ItemFields, publish_item, save_item  # noqa: E402
from papyrus_content.story_reporting import published_story_version  # noqa: E402
from papyrus_content.story_withdrawal import WithdrawalError, restore_story, withdraw_story, withdrawal_of  # noqa: E402
from papyrus_content.story_withdrawal_mcp import call_story_withdrawal_tool, story_withdrawal_descriptions, story_withdrawal_tools  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402

LINEAGE = "item-articles-hello"
PAGES = ["articles/hello/index.html", "articles/hello/index.md"]
LISTINGS = ["index.html", "index.md", "articles/index.html", "articles/index.md"]
PATHS = ["/articles/hello/index.html", "/articles/hello/", "/articles/hello/index.md", "/index.html", "/", "/index.md",
         "/articles/index.html", "/articles/", "/articles/index.md"]
NOW = "2026-11-09T10:00:00Z"


class Site:
    """The content-actions function as the CLI sees it: a plan for refresh-story, a guarded purge for refresh-pages, a projection that answers."""

    def __init__(self, paths=PATHS, cap=25, projection=None):
        self.paths, self.cap, self.calls, self.tasks, self.purged = list(paths), cap, [], [], []
        self.projection = projection if projection is not None else {"ok": True, "status": "projected", "invalidation": {"status": "skipped", "paths": []}}

    def lane(self, _client, name, arguments):
        self.calls.append((name, arguments))
        if name == "site_refresh_story":
            count = len(self.paths)
            allowed = arguments.get("forcePaths") or self.cap
            refusal = {"code": "over_path_cap", "message": f"{count} paths is over the cap of {allowed} paths per call."} if count > allowed else None
            return {"ok": True, "pages": {"story": PAGES, "indexes": LISTINGS},
                    "invalidation": {"paths": self.paths, "count": count, "cost": invalidation_cost_note(count), "guard": {"cap": allowed, **({"refusal": refusal} if refusal else {})}}}
        assert name == "site_refresh_pages" and arguments["confirm"] is True
        from papyrus_content.page_refresh.paths import expand_site_paths

        expanded = expand_site_paths(arguments["paths"])
        self.purged.extend(expanded)
        return {"ok": True, "invalidation": {"paths": expanded, "count": len(expanded), "status": "invalidated", "requests": [{"id": "INV001", "status": "InProgress"}]}}

    def trigger(self, _client, task):
        self.tasks.append(task)
        return dict(self.projection)


def published_client(extra_version=False):
    client = FakeAuthoringClient()
    fields = ItemFields(type="article", slug="hello", section="articles", front_matter_yaml="title: Hello\n", body_markus="Hello world.\n", aliases=[], id=LINEAGE)
    save_item(client, fields, actor="test", now="2026-11-01T10:00:00Z")
    publish_item(client, LINEAGE, actor="test", now="2026-11-01T10:00:00Z")
    return client


@pytest.fixture(autouse=True)
def projecting():
    with mock.patch.object(story_withdrawal, "projecting", return_value=True):
        yield


def item(client):
    return client.tables["Item"][LINEAGE]


def withdraw(client, site, **kwargs):
    arguments = dict(actor="Ryan", reason="wrong", run=True, lane=site.lane, trigger=site.trigger, now=NOW)
    arguments.update(kwargs)
    return withdraw_story(client, LINEAGE, **arguments)


def test_the_plan_lists_exact_pages_paths_count_and_cost_and_writes_nothing():
    client, site = published_client(), Site()
    before = [call for call in client.calls if call[0] in ("update", "upsert", "delete", "create")]
    result = withdraw(client, site, dry_run=True)
    assert result["status"] == "dry-run"
    plan = result["plan"]
    assert plan["storyPages"] == PAGES and plan["listingPages"] == LISTINGS and plan["paths"] == PATHS and plan["count"] == 9
    assert plan["cost"]["usdPerPathAfterFree"] == 0.005 and plan["cost"]["usdAtMost"] == 0.045
    assert [call for call in client.calls if call[0] in ("update", "upsert", "delete", "create")] == before
    assert site.tasks == [] and site.purged == [] and item(client)["status"] == "published"
    text = "\n".join(story_withdrawal.render_lines(result))
    assert "/articles/hello/index.md" in text and "9 paths" in text and "0.005 USD" in text and "articles/index.html" in text


def test_more_than_five_paths_is_a_dry_run_until_run():
    client, site = published_client(), Site()
    result = withdraw(client, site, run=False)
    assert result["status"] == "needs-run" and item(client)["status"] == "published" and site.tasks == []
    assert "--run" in "\n".join(story_withdrawal.render_lines(result))


def test_withdrawing_removes_published_rows_spikes_the_card_and_records_it():
    client, site = published_client(), Site()
    result = withdraw(client, site)
    assert result["status"] == "withdrawn" and result["ok"] is True
    assert not client.tables.get("PublishedItem") and not client.tables.get("PublishedMediaAsset")
    row = item(client)
    assert row["status"] == "draft" and row["stage"] == "spiked"
    record = withdrawal_of(row)
    assert record["withdrawnVersion"] == 1 and record["withdrawnBy"] == "Ryan" and record["withdrawnAt"] == NOW
    assert record["reason"] == "wrong" and record["previousStage"] == "published"
    assert site.tasks == [{"task": "item", "itemId": LINEAGE, "unpublished": True}]


def test_the_planned_paths_are_purged_exactly_when_the_projection_purged_nothing():
    client, site = published_client(), Site()
    result = withdraw(client, site)
    assert sorted(site.purged) == sorted(PATHS) and result["purge"]["count"] == 9 and len(result["purge"]["purged"]) == 9


def test_paths_the_projection_already_purged_are_not_purged_twice():
    done = {"ok": True, "status": "projected", "invalidation": {"status": "ok", "paths": PATHS[:6] + ["/sitemap.xml"]}}
    client, site = published_client(), Site(projection=done)
    result = withdraw(client, site)
    assert sorted(site.purged) == sorted(PATHS[6:]) and result["purge"]["extra"] == ["/sitemap.xml"]


def test_a_failed_projection_leaves_the_data_withdrawn_and_says_how_to_retry():
    client, site = published_client(), Site(projection={"ok": False, "error": "boom"})
    result = withdraw(client, site)
    assert result["ok"] is False and result["retry"].endswith(f"unpublish --id {LINEAGE}") and site.purged == []
    assert item(client)["stage"] == "spiked"


def test_a_plan_over_the_cap_is_refused_unless_forced():
    paths = [f"/p{n}/" for n in range(30)]
    client, site = published_client(), Site(paths=paths)
    result = withdraw(client, site)
    assert result["status"] == "refused" and "over the cap" in result["error"]["message"]
    assert item(client)["status"] == "published" and site.tasks == [] and withdrawal_of(item(client)) is None
    forced = withdraw(client, site, force_paths=30)
    assert forced["status"] == "withdrawn" and forced["plan"]["count"] == 30


def test_a_story_that_is_not_published_is_refused():
    client = FakeAuthoringClient()
    save_item(client, ItemFields(type="article", slug="hello", section="articles", front_matter_yaml="title: Hello\n", body_markus="Hi.\n", aliases=[], id=LINEAGE), actor="t", now=NOW)
    with pytest.raises(WithdrawalError) as error:
        withdraw(client, Site())
    assert error.value.code == "not_published"
    assert item(client)["stage"] != "spiked"


def test_withdrawing_a_withdrawn_story_says_so_and_changes_nothing():
    client, site = published_client(), Site()
    withdraw(client, site)
    writes = len(client.updates)
    again = withdraw(client, Site())
    assert again["status"] == "already-withdrawn" and len(client.updates) == writes
    assert "already-withdrawn" in "\n".join(story_withdrawal.render_lines(again))


def test_restore_republishes_the_version_clears_the_record_and_purges_the_same_pages():
    client, site = published_client(), Site()
    withdraw(client, site)
    restoring = Site()
    plan = restore_story(client, LINEAGE, actor="Ryan", dry_run=True, lane=restoring.lane, trigger=restoring.trigger)
    assert plan["status"] == "dry-run" and plan["plan"]["paths"] == PATHS and restoring.tasks == []
    result = restore_story(client, LINEAGE, actor="Ryan", run=True, lane=restoring.lane, trigger=restoring.trigger, now=NOW)
    assert result["status"] == "restored" and result["ok"] is True
    row = item(client)
    assert row["status"] == "published" and row["stage"] == "published" and withdrawal_of(row) is None
    assert published_story_version(client, LINEAGE)["id"] == LINEAGE
    assert restoring.tasks == [{"task": "item", "itemId": LINEAGE, "unpublished": False}]
    assert sorted(restoring.purged) == sorted(PATHS)


def test_restore_refuses_when_nothing_was_withdrawn():
    client = published_client()
    with pytest.raises(WithdrawalError) as error:
        restore_story(client, LINEAGE, actor="Ryan", lane=Site().lane, trigger=Site().trigger)
    assert error.value.code == "not_withdrawn"


def test_restore_twice_is_refused_the_second_time():
    client, site = published_client(), Site()
    withdraw(client, site)
    restore_story(client, LINEAGE, actor="Ryan", run=True, lane=site.lane, trigger=site.trigger)
    with pytest.raises(WithdrawalError):
        restore_story(client, LINEAGE, actor="Ryan", run=True, lane=site.lane, trigger=site.trigger)


def test_other_stories_are_never_touched():
    client = published_client()
    other = ItemFields(type="article", slug="other", section="articles", front_matter_yaml="title: Other\n", body_markus="Other.\n", aliases=[], id="item-articles-other")
    save_item(client, other, actor="t", now=NOW)
    publish_item(client, "item-articles-other", actor="t", now=NOW)
    withdraw(client, Site())
    assert client.tables["Item"]["item-articles-other"]["status"] == "published" and "published-item-articles-other" in client.tables["PublishedItem"]


def test_a_site_that_does_not_project_pages_only_changes_the_data():
    client = published_client()
    with mock.patch.object(story_withdrawal, "projecting", return_value=False):
        result = withdraw(client, Site(), run=False)
    assert result["status"] == "withdrawn" and result["plan"] is None and item(client)["stage"] == "spiked"


def test_the_commands_print_the_plan_and_exit_2_over_the_cap():
    client, site = published_client(), Site(paths=[f"/p{n}/" for n in range(30)])
    patches = (mock.patch.object(story_commands, "create_authoring_client", return_value=(client, {})), mock.patch.object(story_withdrawal, "lane_call", site.lane),
               mock.patch.object(story_withdrawal, "projection_trigger", site.trigger))
    with patches[0], patches[1], patches[2]:
        with pytest.raises(SystemExit) as exit_info:
            support.run(story_commands.stories_withdraw, ["--story", LINEAGE, "--run"])
    assert exit_info.value.code == 2 and item(client)["status"] == "published"


def test_the_withdraw_command_writes_by_default_and_a_dry_run_writes_nothing():
    client, site = published_client(), Site()
    with mock.patch.object(story_commands, "create_authoring_client", return_value=(client, {})), mock.patch.object(story_withdrawal, "lane_call", site.lane), \
            mock.patch.object(story_withdrawal, "projection_trigger", site.trigger):
        dry = support.run(story_commands.stories_withdraw, ["--story", LINEAGE, "--dry-run"])
        assert "dry run" in dry and item(client)["status"] == "published"
        out = support.run(story_commands.stories_withdraw, ["--story", LINEAGE, "--run", "--reason", "wrong", "--author-label", "Ryan"])
        assert "withdrawn" in out and item(client)["stage"] == "spiked"
        back = support.run(story_commands.stories_restore, ["--story", LINEAGE, "--run"])
        assert "restored" in back and item(client)["status"] == "published"


def test_move_help_says_it_is_board_only_and_points_to_withdraw():
    doc = story_commands.stories_move.__doc__
    assert "board-only" in doc and "stories withdraw" in doc
    from papyrus.operator.group_commands import COMMAND_USAGE

    assert "stories withdraw" in COMMAND_USAGE[("stories", "move")] and ("stories", "withdraw") in COMMAND_USAGE and ("stories", "restore") in COMMAND_USAGE


def test_the_mcp_tools_have_the_cli_flags_and_run_the_same_operations():
    assert set(story_withdrawal_tools()) == {"stories_withdraw", "stories_restore"} == set(story_withdrawal_descriptions())
    client, site = published_client(), Site()
    hooks = dict(lane=site.lane, trigger=site.trigger, now=NOW)
    planned = call_story_withdrawal_tool("stories_withdraw", {"storyLineageId": LINEAGE, "dryRun": True}, client, **hooks)
    assert planned["status"] == "dry-run" and planned["plan"]["count"] == 9
    done = call_story_withdrawal_tool("stories_withdraw", {"storyLineageId": LINEAGE, "run": True, "reason": "wrong", "authorLabel": "Ryan"}, client, **hooks)
    assert done["status"] == "withdrawn"
    restored = call_story_withdrawal_tool("stories_restore", {"storyLineageId": LINEAGE, "run": True}, client, **hooks)
    assert restored["status"] == "restored"
    refused = call_story_withdrawal_tool("stories_restore", {"storyLineageId": LINEAGE}, client, **hooks)
    assert refused["ok"] is False and refused["error"]["code"] == "not_withdrawn"
