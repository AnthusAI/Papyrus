"""`papyrus stories schedule`, `schedule-list`, the schedule line of `stories show`, the MCP tools, and `stories retire` removing a schedule first."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from papyrus_content import story_commands, story_retire, story_schedule_commands
from papyrus_content.story_schedule import Caller
from procedures.newsroom.tests.fake_client import FakeAuthoringClient
from procedures.newsroom.tests.incremental_site import Site, add_item
from procedures.newsroom.tests.schedule_support import LINEAGE, ZONE, Clock, FakeScheduler, SiteClient, new_story, service_for


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch):
    client, scheduler, clock = FakeAuthoringClient(), FakeScheduler(), Clock("2026-11-10T15:00:00Z")
    newest = new_story(client)
    session = SiteClient(client, service_for(client, scheduler, clock))
    for module in (story_schedule_commands, story_commands, story_retire):
        monkeypatch.setattr(module, "create_authoring_client", lambda *a, **k: (session, {"sub": "sam-sub"}), raising=False)
    monkeypatch.setattr("papyrus_content.graphql_authoring.create_authoring_client", lambda *a, **k: (session, {"sub": "sam-sub"}))
    return session, scheduler, clock, newest


def test_schedule_prints_the_version_the_time_in_both_zones_and_who(cli, capsys) -> None:
    session, scheduler, _clock, newest = cli
    story_schedule_commands.stories_schedule(["--story", LINEAGE, "--at", "2026-11-13 09:00"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split("\t") == ["stories", "schedule", "scheduled", LINEAGE, "Robots in the warehouse", "version 1", "Fri 13 Nov 2026, 09:00 EST (2026-11-13T14:00:00Z)", "by sam", "write"]
    assert lines[1].endswith("Unrated: it will publish but will not be listed or announced until it is rated.")
    assert session.mutations == [{"operation": "schedule", "arguments": {"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}}] and len(scheduler.schedules) == 1


def test_schedule_dry_run_writes_nothing(cli, capsys) -> None:
    session, scheduler, *_ = cli
    story_schedule_commands.stories_schedule(["--story", LINEAGE, "--at", "2026-11-13 09:00", "--dry-run"])
    assert "would schedule" in capsys.readouterr().out and scheduler.schedules == {} and session.mutations[0]["arguments"]["dryRun"] is True


def test_schedule_clear_and_the_refusals(cli, capsys) -> None:
    _session, scheduler, *_ = cli
    story_schedule_commands.stories_schedule(["--story", LINEAGE, "--at", "2026-11-13 09:00"])
    story_schedule_commands.stories_schedule(["--story", LINEAGE, "--clear"])
    assert "cleared" in capsys.readouterr().out and scheduler.schedules == {}
    with pytest.raises(ValueError, match=r"\[nonexistent-time\] That time does not exist on 8 March in New York. Pick another time."):
        story_schedule_commands.stories_schedule(["--story", LINEAGE, "--at", "2026-03-08 02:30"])
    with pytest.raises(ValueError, match="Give --at TIME to schedule, or --clear"):
        story_schedule_commands.stories_schedule(["--story", LINEAGE])
    with pytest.raises(ValueError, match="--story is required"):
        story_schedule_commands.stories_schedule(["--at", "2026-11-13 09:00"])


def test_schedule_list_prints_one_line_each_and_json(cli, capsys) -> None:
    story_schedule_commands.stories_schedule(["--story", LINEAGE, "--at", "2026-11-13 09:00"])
    capsys.readouterr()
    story_schedule_commands.stories_schedule_list(["--from", "2026-11-13 00:00"])
    lines = [line.split("\t") for line in capsys.readouterr().out.splitlines()]
    assert lines[0][:3] == ["stories", "schedule-list", LINEAGE] and lines[0][5] == "scheduled" and lines[-1][2] == "1 schedules" and lines[-1][-1] == f"publication time zone {ZONE}"
    story_schedule_commands.stories_schedule_list(["--story", LINEAGE, "--json"])
    assert json.loads(capsys.readouterr().out)["schedules"][0]["scheduledPublishAt"] == "2026-11-13T14:00:00Z"


def test_stories_show_prints_the_schedule(cli, capsys) -> None:
    # far in the future: `stories show` judges overdue by the real clock
    story_schedule_commands.stories_schedule(["--story", LINEAGE, "--at", "2099-11-13 09:00"])
    capsys.readouterr()
    story_commands.stories_show(["--story", LINEAGE])
    schedule = [line.split("\t") for line in capsys.readouterr().out.splitlines() if line.startswith("stories\tshow\tschedule")]
    assert schedule == [["stories", "show", "schedule", "scheduled", "version 1", "publish at 2099-11-13T14:00:00Z (UTC)", "by sam", ""]]


def test_the_mcp_tools_are_the_table_and_call_the_same_operations(cli) -> None:
    from papyrus_content.story_signals_mcp import call_story_signal_tool

    session, scheduler, *_ = cli
    done = call_story_signal_tool("stories_schedule", {"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, session)
    assert done["scheduledPublishAt"] == "2026-11-13T14:00:00Z" and len(scheduler.schedules) == 1
    listed = call_story_signal_tool("stories_schedule_list", {"storyLineageId": LINEAGE}, session)
    assert listed["schedules"][0]["state"] == "scheduled"
    with pytest.raises(ValueError, match="nonexistent-time"):
        call_story_signal_tool("stories_schedule", {"storyLineageId": LINEAGE, "at": "2026-03-08 02:30"}, session)


# --- retire -------------------------------------------------------------------------------------------------------------------------------------------


def test_retiring_removes_the_schedule_before_anything_else(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    site = Site("feed", tmp_path)
    for item_id, slug in (("item-old", "old-article"), ("item-new", "merged")):
        add_item(site, item_id, slug)
        site.project_item(item_id)
    scheduler, clock = FakeScheduler(), Clock("2026-11-10T15:00:00Z")
    from papyrus_content.story_reporting import save_story_version

    save_story_version(site.client, "item-old", front_matter_yaml="title: Old\n", body_markus="Newer.\n", actor="Alex", change_reason="edit", now="2026-11-09T12:00:00Z")
    service = service_for(site.client, scheduler, clock)
    service.schedule({"storyLineageId": "item-old", "at": "2026-11-13 09:00"}, Caller(actor="sam", person="sam-sub", groups=("editor",)))
    session = SiteClient(site.client, service)
    monkeypatch.setattr("papyrus_content.graphql_authoring.create_authoring_client", lambda *a, **k: (session, {"sub": "sam-sub"}))
    monkeypatch.delenv("PAPYRUS_PUBLICATION_KIND", raising=False)
    monkeypatch.setenv("PAPYRUS_SITE_PROJECTOR", "site.projector")
    monkeypatch.setattr("papyrus_content.projection.runtime.load_projector", lambda *args, **kwargs: site.projector)

    story_retire.stories_retire(["--story", "item-old", "--redirect-to", "item-new", "--dry-run"])
    assert "unschedule" in capsys.readouterr().out and len(scheduler.schedules) == 1
    story_retire.stories_retire(["--story", "item-old", "--redirect-to", "item-new", "--no-trigger"])
    out = capsys.readouterr().out
    assert out.index("unscheduled") < out.index("saved") and scheduler.schedules == {}
    assert [m["arguments"] for m in session.mutations] == [{"storyLineageId": "item-old", "clear": True}]
