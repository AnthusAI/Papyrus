"""The Story checklist (docs/story-procedure.md, features_backend/story-checklist.feature): the creation paths, the rules and the sweep. The backend is a fake."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from papyrus_content import newsroom_process as process
from papyrus_content import story_checklist as checklist
from papyrus_content.story_reporting import create_story, latest_story_version, save_story_version
from procedures.newsroom.tests.fake_client import FakeAuthoringClient
from procedures.newsroom.tests.test_create_story_from_reference import backend as reference_backend, create as create_from_reference

PERSON = {"kind": "person", "label": "Ryan", "sub": "sub-1"}


@pytest.fixture(autouse=True)
def no_check_store(real_checklist_gate):   # this module exercises the publish rule (see conftest.py)
    with patch("papyrus_content.editorial_commands.read_item_check_run", lambda item_id: None):
        yield


def lineage_of(client) -> str:
    return sorted({row["lineageId"] for row in client.tables["Item"].values()})[0]


def test_the_template_has_an_item_for_every_live_step_and_the_gate_excludes_publishing():
    live = [step.key for step in process.STEPS if step.status == process.LIVE]
    assert [step.key for step in checklist.template_steps()] == live
    assert "publish" in live and "publish" not in checklist.required_keys()
    assert {"review_people", "review_reader_agents", "review_search", "review_social"} <= set(checklist.required_keys())
    assert "fact_check" not in live and "editor_review" not in live


def test_stories_next_order_puts_the_four_reviews_between_copy_edit_and_publish():
    keys = [step.key for step in process.STEPS]
    assert keys.index("copy_edit") < keys.index("review_people") < keys.index("review_social") < keys.index("publish")
    assert all(process.STEP_BY_KEY[key].manual and not process.STEP_BY_KEY[key].optional for key in process.REVIEW_STEP_KEYS)


def test_create_story_makes_a_checklist_with_the_template_version():
    client = FakeAuthoringClient()
    item = create_story(client, title="A Story", section_key=None, actor="AI")
    rows = checklist.read_steps(client, item["lineageId"])
    assert len(rows) == len(checklist.template_steps()) and {row["templateVersion"] for row in rows} == {process.TEMPLATE_VERSION}
    assert [row["stepOrder"] for row in rows] == sorted(row["stepOrder"] for row in rows)
    assert all(row["title"] and row["state"] == "open" for row in rows)
    assert any(row["command"].endswith("--state done --note <findings>") and item["lineageId"] in row["command"] for row in rows)


def test_the_editors_create_story_from_a_reference_makes_a_checklist_with_the_choice_made():
    client = reference_backend()
    result = create_from_reference(client)
    rows = {row["stepKey"]: row for row in checklist.read_steps(client, result["lineageId"])}
    assert len(rows) == len(checklist.template_steps())
    assert rows["choose"]["state"] == "done" and rows["choose"]["actorKind"] == "system"   # created at copywriting
    assert rows["review_people"]["state"] == "open"


def test_an_assignment_that_mints_a_story_makes_its_checklist():
    from papyrus_content.assignments_workflow import _checklist_for_new_content_item
    from papyrus_content.content_item_lifecycle import build_new_content_item_version

    client = FakeAuthoringClient()
    version = build_new_content_item_version(lineage_id="minted-1", title="Minted", summary=None, section_key=None, stage="assignment", actor_label="AI", now="2026-11-07T10:00:00Z")
    client.create_record("Item", version)
    _checklist_for_new_content_item(client, version)
    assert len(checklist.read_steps(client, "minted-1")) == len(checklist.template_steps())
    _checklist_for_new_content_item(client, None)   # an Assignment on an existing Story mints nothing


def load_handler():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "amplify" / "functions" / "content-actions" / "handler.py"
    spec = importlib.util.spec_from_file_location("content_actions_handler", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_console_save_of_a_story_makes_a_checklist_and_a_page_is_left_alone():
    handler = load_handler()
    client = FakeAuthoringClient()
    item = create_story(client, title="Saved", section_key=None, actor="AI")
    for row in list(client.tables.get("StoryStep", {})):
        client.delete_record("StoryStep", row)
    handler.sync_story_checklist(client, item)
    assert len(checklist.read_steps(client, item["lineageId"])) == len(checklist.template_steps())
    client.tables["StoryStep"].clear()
    handler.sync_story_checklist(client, {**item, "type": "wiki_page"})
    assert checklist.read_steps(client, item["lineageId"]) == []


def test_the_set_step_action_stamps_the_signed_in_person_and_records_an_agent_as_the_agent():
    handler = load_handler()
    client = FakeAuthoringClient()
    item = create_story(client, title="Acted", section_key=None, actor="AI")
    lineage = item["lineageId"]
    person_event = {"identity": {"sub": "sub-1", "issuer": "https://cognito.example.test", "username": "ryan"}}
    with patch.object(handler, "create_authoring_client", lambda: (client, None)):
        refused = handler.set_story_step_action({"lineageId": lineage, "stepKey": "outline", "state": "skipped"}, person_event)
        assert refused["ok"] is False and "needs a reason" in refused["errors"][0]["message"]
        ok = handler.set_story_step_action({"lineageId": lineage, "stepKey": "outline", "state": "skipped", "reason": "Wrote it by hand"}, person_event)
        assert ok["ok"] and ok["step"]["state"] == "skipped"
        row = {r["stepKey"]: r for r in checklist.read_steps(client, lineage)}["outline"]
        assert (row["actorKind"], row["actorSub"], row["reason"]) == ("person", "sub-1", "Wrote it by hand")
        agent = handler.set_story_step_action({"lineageId": lineage, "stepKey": "review_search", "state": "done", "note": "Fine", "agent": "AI"}, person_event)
        assert agent["ok"]
        row = {r["stepKey"]: r for r in checklist.read_steps(client, lineage)}["review_search"]
        assert (row["actorKind"], row["actorLabel"], row["actorSub"]) == ("agent", "AI", "sub-1")
        refused = handler.set_story_step_action({"lineageId": lineage, "stepKey": "review_search", "state": "open", "agent": "AI"}, person_event)
        assert refused["ok"] is False and "Only a person reopens" in refused["errors"][0]["message"]
        anonymous = handler.set_story_step_action({"lineageId": lineage, "stepKey": "outline", "state": "open"}, {"identity": {}})
        assert anonymous["errors"][0]["code"] == "not-signed-in"


def test_a_change_records_every_entry_and_a_reopen_by_a_person_works():
    client = FakeAuthoringClient()
    lineage = create_story(client, title="History", section_key=None, actor="AI")["lineageId"]
    checklist.set_step(client, lineage, "outline", "skipped", actor=PERSON, reason="Later", now="2026-11-07T10:00:00Z")
    checklist.set_step(client, lineage, "outline", "open", actor=PERSON, now="2026-11-07T11:00:00Z")
    checklist.set_step(client, lineage, "outline", "done", actor={"kind": "agent", "label": "AI"}, evidence="Item x", now="2026-11-07T12:00:00Z")
    row = {r["stepKey"]: r for r in checklist.read_steps(client, lineage)}["outline"]
    assert [entry["state"] for entry in row["history"]] == ["skipped", "open", "done"]
    assert row["reason"] is None and row["evidence"] == "Item x"   # a reopen clears the old answer
    assert isinstance(client.tables["StoryStep"][row["id"]]["history"], str)   # stored as JSON text


def test_an_actor_is_required_and_a_system_actor_cannot_be_claimed():
    client = FakeAuthoringClient()
    lineage = create_story(client, title="Actors", section_key=None, actor="AI")["lineageId"]
    for actor in ({"kind": "person", "label": ""}, {"kind": "system", "label": "evidence"}, {"kind": "robot", "label": "x"}):
        with pytest.raises(checklist.ChecklistError):
            checklist.set_step(client, lineage, "outline", "done", actor=actor)


def test_the_summary_on_the_story_changes_with_each_step_and_moves_its_updated_time():
    client = FakeAuthoringClient()
    item = create_story(client, title="Summary", section_key=None, actor="AI", now="2026-11-07T09:00:00Z")
    lineage = item["lineageId"]
    checklist.set_step(client, lineage, "outline", "skipped", actor=PERSON, reason="Later", now="2026-11-07T10:30:00Z")
    latest = latest_story_version(client, lineage)
    summary = json.loads(latest["metadata"])["checklist"]
    assert (summary["total"], summary["skipped"], summary["open"]) == (len(checklist.template_steps()), 1, len(checklist.template_steps()) - 1)
    assert "outline" not in summary["requiredOpen"] and "draft" in summary["requiredOpen"]
    assert latest["updatedAt"] == "2026-11-07T10:30:00Z"   # the board refreshes by this time
    assert checklist.progress_text(summary) == f"0/{summary['total']} · 1 skipped"


def test_a_new_version_keeps_the_summary_the_story_carries():
    client = FakeAuthoringClient()
    lineage = create_story(client, title="Versions", section_key=None, actor="AI")["lineageId"]
    save_story_version(client, lineage, front_matter_yaml='title: "Versions"', body_markus="Text.", actor="AI", change_reason="draft")
    assert json.loads(latest_story_version(client, lineage)["metadata"])["checklist"]["total"] == len(checklist.template_steps())


def test_the_summary_is_not_rewritten_when_nothing_changed():
    client = FakeAuthoringClient()
    lineage = create_story(client, title="Quiet", section_key=None, actor="AI")["lineageId"]
    before = len(client.write_calls())
    checklist.sync_checklist(client, lineage)
    assert len(client.write_calls()) == before


def test_a_sync_that_fails_prints_one_line_and_never_raises(capsys):
    class Broken(FakeAuthoringClient):
        def list_by_index(self, index_name, key_value, **kwargs):
            if index_name == "storyStepsByStory":
                raise RuntimeError("index unreachable")
            return super().list_by_index(index_name, key_value, **kwargs)

    client = Broken()
    create_story(client, title="Broken", section_key=None, actor="AI")   # the Story is created; the checklist is not
    assert capsys.readouterr().err.startswith("checklist\tnot updated\tRuntimeError")


def test_the_gate_names_each_open_step_with_the_command_and_a_wiki_page_is_not_held():
    client = FakeAuthoringClient()
    item = create_story(client, title="Held", section_key=None, actor="AI")
    with pytest.raises(checklist.ChecklistError) as error:
        checklist.require_checklist_closed(client, item)
    assert "Reviewed for social previews (review_social)" in str(error.value) and f"papyrus stories step --story {item['lineageId']}" in str(error.value)
    checklist.require_checklist_closed(client, {**item, "type": "wiki_page"})


def test_the_backfill_pages_every_stage_counts_and_writes_nothing_on_a_dry_run():
    client = FakeAuthoringClient()
    first = create_story(client, title="One", section_key=None, actor="AI")["lineageId"]
    second = create_story(client, title="Two", section_key=None, actor="AI", stage="reporting", now="2026-11-07T08:00:00Z")["lineageId"]
    client.tables["StoryStep"].clear()
    client.calls.clear()
    pages = []
    original = client.iterate_newest_first
    client.iterate_newest_first = lambda index, key, *, page_size=50: pages.append((index, key, page_size)) or original(index, key, page_size=page_size)
    dry = checklist.backfill(client, apply=False, page_size=10)
    assert client.write_calls() == [] and dry["stories"] == 2 and dry["created_items"] == 2 * len(checklist.template_steps())
    assert {page[2] for page in pages} == {10} and {page[1] for page in pages} >= {"idea", "reporting", "published"}   # every stage, paged
    applied = checklist.backfill(client, apply=True)
    assert applied["created_items"] == dry["created_items"] and len(client.tables["StoryStep"]) == dry["created_items"]
    again = checklist.backfill(client, apply=True)
    assert again["already_complete"] == 2 and again["created_items"] == 0
    assert {row["storyLineageId"] for row in client.tables["StoryStep"].values()} == {first, second}


def test_the_backfill_skips_pages_that_are_not_stories_and_survives_one_bad_story(capsys):
    client = FakeAuthoringClient()
    create_story(client, title="Good", section_key=None, actor="AI")
    client.tables["Item"]["page-1"] = {"id": "page-1", "lineageId": "page-1", "versionNumber": 1, "versionState": "current", "type": "wiki_page", "stage": "idea", "metadata": "{}", "updatedAt": "2026-11-07T00:00:00Z"}
    client.tables["Item"]["bad-1"] = {"id": "bad-1", "lineageId": "bad-1", "versionNumber": 1, "versionState": "current", "type": "article", "stage": "idea", "updatedAt": "2026-11-07T00:00:00Z"}
    client.tables["StoryStep"].clear()
    original = checklist._backfill_one

    def flaky(client, lineage, *, apply):
        if lineage == "bad-1":
            raise RuntimeError("unreadable")
        return original(client, lineage, apply=apply)

    with patch.object(checklist, "_backfill_one", flaky):
        counts = checklist.backfill(client, apply=True)
    assert counts["stories"] == 2 and counts["failed"] == 1 and "bad-1" in capsys.readouterr().err
    assert "page-1" not in {row["storyLineageId"] for row in client.tables["StoryStep"].values()}
