"""Story-state triggers (PPY-f0914799): a bot starts when a story enters a stage; one run per story, stage and revision."""
import json

import pytest

import automation_fixture as fx
from fake_client import FakeAuthoringClient
from papyrus_content import automations as au
from papyrus_content import story_triggers as st
from papyrus_content.automations import AutomationError, MonitoringReader, MonitoringWriter
from papyrus_content.story_reporting import latest_story_version, move_story_stage

LINEAGE = "content-item-board-refuses-1"
NOW = "2026-10-24T09:00:00.000000Z"
COPY_BOT = "distinctive.copywriter"
EDIT_BOT = "distinctive.copy-editor"
PROCEDURE = "distinctive.newsroom.copywriter"


class ClaimTable(fx.FakeMonitoringTable):
    """The fake monitoring table with the two writes the story triggers make: a plain put and a conditional put."""

    def __init__(self):
        super().__init__([fx.router_config()])
        self.puts = []

    def put_item(self, Item, ConditionExpression=None):
        key = (Item["pk"], Item["sk"])
        if ConditionExpression and key in self.rows:
            error = Exception("exists")
            error.response = {"Error": {"Code": "ConditionalCheckFailedException"}}
            raise error
        self.puts.append(dict(Item))
        self.rows[key] = dict(Item)


def stage_automation(automation_id=COPY_BOT, stage="copywriting", next_stage="typesetting", max_hops=None, **changes):
    config = {"event": st.STAGE_ENTERED, "onStage": stage, "monitorId": "ttab", "publicationId": "distinctive"}
    if next_stage:
        config["nextStage"] = next_stage
    limits = {"timeoutSeconds": 600, **({"maxHops": max_hops} if max_hops else {})}
    row = {"id": automation_id, "title": f"{automation_id} bot", "description": None, "enabled": True,
           "trigger": json.dumps({"kind": "event", "config": config}), "procedureKey": PROCEDURE,
           "inputTemplate": json.dumps({"tone": "plain"}), "limits": json.dumps(limits),
           "createdBy": "t", "createdAt": NOW, "updatedBy": "t", "updatedAt": NOW}
    row.update(changes)
    return row


def story_row(stage="reporting", metadata=None):
    return {"id": LINEAGE, "lineageId": LINEAGE, "versionNumber": 1, "versionState": "current", "type": "article", "slug": "board",
            "section": None, "status": "draft", "stage": stage, "headline": "Board refuses", "title": "Board refuses", "aliases": [],
            "metadata": json.dumps({"frontMatterYaml": 'title: "Board refuses"', **(metadata or {})}), "bodyMarkus": "First.",
            "createdAt": NOW, "updatedAt": NOW}


class World:
    def __init__(self, *automations, stage="reporting", metadata=None):
        self.client = FakeAuthoringClient({"Item": [story_row(stage, metadata)], "Automation": list(automations or [stage_automation()])})
        self.table, self.invoked = ClaimTable(), []

    def deliver(self):
        return st.deliver_stage_entered(self.client, story=LINEAGE, reader=MonitoringReader(self.table), writer=MonitoringWriter(self.table),
                                        invoke=self.invoked.append, now=NOW)

    def finish(self, request, status="completed", output=None, error=None):
        return st.finish_stage_run(self.client, request["trigger"], {"runStatus": status, "output": output, "error": error},
                                   reader=MonitoringReader(self.table), writer=MonitoringWriter(self.table), invoke=self.invoked.append, now=NOW)

    def bot_writes_version(self, label):
        """What a procedure does with `stories save-version`: a new current version, the old one superseded."""
        latest = latest_story_version(self.client, LINEAGE)
        number = latest["versionNumber"] + 1
        new = {**latest, "id": f"{LINEAGE}-v{number}", "versionNumber": number, "versionState": "current", "previousVersionId": latest["id"],
               "versionCreatedBy": label, "bodyMarkus": f"{label}\n"}
        self.client.create_record("Item", new)
        self.client.update_record("Item", {"id": latest["id"], "versionState": "superseded"})
        return new["id"]

    def chain(self):
        return st.chain_of(latest_story_version(self.client, LINEAGE))

    def stage(self):
        return latest_story_version(self.client, LINEAGE)["stage"]

    def reviews(self):
        return list(self.client.tables.get("ReviewRequest", {}).values())


# --- the trigger record ----------------------------------------------------------------------------------


def test_a_stage_entry_trigger_is_a_supported_event_automation():
    record = au.read_record(stage_automation(max_hops=3))
    assert record["supported"] is True and record["trigger"]["kind"] == "event"
    assert (record["onStage"], record["nextStage"], record["maxHops"]) == ("copywriting", "typesetting", 3)
    assert record["runNow"]["available"] is False


def test_the_cli_fields_build_a_stage_entry_automation():
    fields = au.fields_from_options({"id": COPY_BOT, "title": "Copywriter", "on-stage": "copywriting", "next-stage": "typesetting",
                                     "monitor": "ttab", "publication": "distinctive", "procedure": PROCEDURE, "max-hops": "3",
                                     "input": '{"tone":"plain"}'})
    record = au.build_record(fields, actor="t", now=NOW)
    assert record["trigger"] == {"kind": "event", "config": {"event": st.STAGE_ENTERED, "onStage": "copywriting", "nextStage": "typesetting",
                                                              "monitorId": "ttab", "publicationId": "distinctive"}}
    assert record["limits"]["maxHops"] == 3 and record["inputTemplate"] == {"tone": "plain"}


@pytest.mark.parametrize("config, message", [
    ({"onStage": "nowhere", "monitorId": "ttab", "publicationId": "distinctive"}, "config.onStage"),
    ({"onStage": "copywriting", "publicationId": "distinctive"}, "monitorId"),
    ({"onStage": "copywriting", "nextStage": "copywriting", "monitorId": "ttab", "publicationId": "distinctive"}, "nextStage"),
])
def test_a_stage_trigger_needs_real_stages_and_a_monitor_partition(config, message):
    with pytest.raises(AutomationError, match=message):
        au.validate_trigger({"kind": "event", "config": {"event": st.STAGE_ENTERED, **config}})


def test_a_stage_automations_input_is_static():
    trigger = au.validate_trigger({"kind": "event", "config": {"event": st.STAGE_ENTERED, "onStage": "copywriting", "monitorId": "ttab",
                                                               "publicationId": "distinctive"}})
    assert au.validate_input_template({"tone": "plain"}, trigger) == {"tone": "plain"}
    with pytest.raises(AutomationError, match="static"):
        au.validate_input_template({"tone": "{story}"}, trigger)


# --- entering a stage starts the bot -----------------------------------------------------------------------


def test_entering_the_stage_starts_the_procedure_with_the_contract_input():
    world = World(stage="copywriting")
    (outcome,) = world.deliver()
    assert outcome["status"] == "started"
    (request,) = world.invoked
    key = f"STAGE#{COPY_BOT}#{LINEAGE}#copywriting#{LINEAGE}"
    assert request["input"] == {"tone": "plain", "story": LINEAGE, "version": LINEAGE, "versionNumber": 1, "stage": "copywriting",
                                "runKey": key, "automationId": COPY_BOT, "hop": 1}
    assert request["procedureKey"] == PROCEDURE and request["timeoutSeconds"] == 600 and request["appsyncEndpoint"] == fx.SITE_ENDPOINT
    assert request["trigger"]["sk"] == key and request["trigger"]["pk"] == "MONITOR#ttab"
    assert world.table.rows[("MONITOR#ttab", key)]["status"] == "starting"


def test_the_contract_keys_win_over_the_static_input():
    world = World(stage_automation(inputTemplate=json.dumps({"story": "wrong", "hop": 99, "tone": "plain"})), stage="copywriting")
    world.deliver()
    assert world.invoked[0]["input"]["story"] == LINEAGE and world.invoked[0]["input"]["hop"] == 1


def test_other_stages_and_disabled_automations_start_nothing():
    other = World(stage="reporting")
    assert other.deliver() == [] and other.invoked == []
    off = World(stage_automation(enabled=False), stage="copywriting")
    assert [o["status"] for o in off.deliver()] == ["skipped"] and off.invoked == []


# --- exactly one run per story, stage and version ---------------------------------------------------------------


def test_a_second_delivery_of_the_same_event_starts_nothing():
    world = World(stage="copywriting")
    assert world.deliver()[0]["status"] == "started"
    assert world.deliver()[0]["status"] == "duplicate"
    assert len(world.invoked) == 1 and world.chain()["hops"] == 1


def test_a_new_version_in_the_same_stage_is_a_new_claim():
    world = World(stage="copywriting")
    world.deliver()
    world.bot_writes_version("person")
    assert world.deliver()[0]["status"] == "started" and len(world.invoked) == 2


def test_the_concurrency_limit_defers_and_a_later_delivery_starts_it():
    world = World(stage_automation(limits=json.dumps({"timeoutSeconds": 600, "maxConcurrent": 1})), stage="copywriting")
    other = f"STAGE#{COPY_BOT}#other#copywriting#other-v1"
    world.table.rows[("MONITOR#ttab", other)] = {"pk": "MONITOR#ttab", "sk": other, "status": "running", "startedAt": NOW}
    (outcome,) = world.deliver()
    assert outcome["status"] == "deferred" and "concurrency limit" in outcome["reason"] and world.invoked == []
    world.table.rows[("MONITOR#ttab", other)]["status"] = "completed"
    assert world.deliver()[0]["status"] == "started"


def test_a_failed_start_is_recorded_on_the_claim_row():
    world = World(stage="copywriting")

    def broken(request):
        raise RuntimeError("no")

    outcome = st.deliver_stage_entered(world.client, story=LINEAGE, reader=MonitoringReader(world.table), writer=MonitoringWriter(world.table),
                                       invoke=broken, now=NOW)[0]
    assert outcome["status"] == "startFailed"
    assert world.table.rows[("MONITOR#ttab", f"STAGE#{COPY_BOT}#{LINEAGE}#copywriting#{LINEAGE}")]["status"] == "startFailed"


# --- the engine moves the story ----------------------------------------------------------------------------


def test_a_successful_run_moves_the_story_to_next_stage_as_the_bot_and_labels_its_version():
    world = World(stage="copywriting")
    world.deliver()
    new = world.bot_writes_version(f"automation:{COPY_BOT}")
    result = world.finish(world.invoked[0], output={"version": new})
    assert result["status"] == "moved" and world.stage() == "typesetting"
    assert json.loads(world.client.tables["Item"][new]["metadata"])["botAction"]["automationId"] == COPY_BOT
    notes = json.dumps(list(world.client.tables["Message"].values()))
    assert f"automation:{COPY_BOT}" in notes and "copywriting -> typesetting" in notes
    assert world.invoked and len(world.invoked) == 1   # no bot at typesetting


def test_returning_the_entering_version_means_no_changes_and_still_advances():
    world = World(stage="copywriting")
    world.deliver()
    output = {"version": LINEAGE, "hold": False, "corrections": [], "unverifiable": ["a date"], "remaining_findings": 1}
    result = world.finish(world.invoked[0], output=output)
    assert result["status"] == "moved" and result["noChanges"] is True and world.stage() == "typesetting"
    notes = json.dumps(list(world.client.tables["Message"].values()))
    assert f"{COPY_BOT}: no changes" in notes and not world.reviews()
    assert "botAction" not in json.loads(world.client.tables["Item"][LINEAGE]["metadata"])


def test_without_next_stage_the_story_stays():
    world = World(stage_automation(next_stage=None), stage="copywriting")
    world.deliver()
    new = world.bot_writes_version("bot")
    assert world.finish(world.invoked[0], output={"version": new})["status"] == "stayed" and world.stage() == "copywriting"


def test_a_hold_keeps_the_story_and_raises_a_flag_with_the_reason():
    world = World(stage="copywriting")
    world.deliver()
    new = world.bot_writes_version("bot")
    assert world.finish(world.invoked[0], output={"version": new, "hold": True, "reason": "two sources disagree"})["status"] == "held"
    (review,) = world.reviews()
    assert world.stage() == "copywriting" and review["mode"] == "flag" and "two sources disagree" in review["reason"]


@pytest.mark.parametrize("status", ["failed", "notRunnable"])
def test_a_failed_run_keeps_the_story_and_raises_a_flag_with_the_error(status):
    world = World(stage="copywriting")
    world.deliver()
    assert world.finish(world.invoked[0], status=status, error="timed out after 600 s")["status"] == "failed"
    (review,) = world.reviews()
    assert world.stage() == "copywriting" and review["mode"] == "flag" and "timed out after 600 s" in review["reason"]
    assert review["raisedBy"] == f"automation:{COPY_BOT}"


def test_a_run_that_returns_no_version_keeps_the_story_and_raises_a_flag():
    world = World(stage="copywriting")
    world.deliver()
    assert world.finish(world.invoked[0], output={})["status"] == "no_version" and world.stage() == "copywriting" and world.reviews()


def test_a_story_a_person_moved_meanwhile_is_not_moved_again():
    world = World(stage="copywriting")
    world.deliver()
    new = world.bot_writes_version("bot")
    move_story_stage(world.client, LINEAGE, "illustration", actor="person", now=NOW)
    assert world.finish(world.invoked[0], output={"version": new})["status"] == "stayed" and world.stage() == "illustration"


# --- the chain: reporting -> fact-check -> copywriting -> copy-edit -> typesetting -----------------------------------


def chain_world():
    return World(stage_automation("distinctive.ruling.fact-check", "reporting", "copywriting"),
                 stage_automation("distinctive.ruling.copy-edit", "copywriting", "typesetting"), stage="reporting")


def test_the_example_chain_runs_each_bot_once_and_stops_at_typesetting():
    world = chain_world()
    assert [o["automationId"] for o in world.deliver()] == ["distinctive.ruling.fact-check"]
    first = world.bot_writes_version("fact")
    result = world.finish(world.invoked[0], output={"version": first})
    assert result["stage"] == "copywriting" and [o["status"] for o in result["next"]] == ["started"]
    assert world.invoked[1]["input"]["automationId"] == "distinctive.ruling.copy-edit" and world.invoked[1]["input"]["hop"] == 2
    assert world.invoked[1]["input"]["version"] == first
    second = world.bot_writes_version("edit")
    result = world.finish(world.invoked[1], output={"version": second})
    assert result["stage"] == "typesetting" and result["next"] == [] and world.stage() == "typesetting"
    assert len(world.invoked) == 2 and world.chain()["hops"] == 2


def test_a_human_move_into_a_stage_fires_it_too():
    world = chain_world()
    move_story_stage(world.client, LINEAGE, "copywriting", actor="person", now=NOW)
    assert [o["automationId"] for o in world.deliver()] == ["distinctive.ruling.copy-edit"]


# --- the hop limit ------------------------------------------------------------------------------------------------


def test_at_the_hop_limit_nothing_starts_the_story_stays_and_one_hard_gate_is_raised():
    world = World(stage_automation(max_hops=2), stage="copywriting")
    for _ in range(2):
        assert world.deliver()[0]["status"] == "started"
        world.bot_writes_version("person")
    (outcome,) = world.deliver()
    assert outcome["status"] == "blocked" and "limit" in outcome["reason"]
    world.deliver()
    (review,) = world.reviews()
    assert review["mode"] == "hard_gate" and "bot hop limit reached" in review["reason"]
    assert json.loads(review["subject"]) == {"type": "story", "id": LINEAGE}
    assert len(world.invoked) == 2 and world.stage() == "copywriting"


def test_the_default_limit_is_five_and_a_record_can_override_it():
    assert st.max_hops_of({}) == 5 and st.max_hops_of({"maxHops": 9}) == 9
    world = World(stage="copywriting", metadata={st.CHAIN_KEY: {"hops": 5}})
    assert world.deliver()[0]["status"] == "blocked" and world.invoked == []
    raised = World(stage_automation(max_hops=6), stage="copywriting", metadata={st.CHAIN_KEY: {"hops": 5}})
    assert raised.deliver()[0]["status"] == "started"


# --- a procedure that created the story through a tool ---------------------------------------------------

RUN_TRIGGER = {"event": "monitor.matched", "pk": "MONITOR#ttab", "sk": "RUN#1"}


def completed(story=LINEAGE):
    return {"runStatus": "completed", "output": {"story": story, "version_id": LINEAGE}}


def deliver_after(world, result, trigger=None):
    return st.deliver_after_run(world.client, trigger, result, reader=MonitoringReader(world.table), writer=MonitoringWriter(world.table),
                                invoke=world.invoked.append, now=NOW)


def test_a_completed_run_that_names_a_story_fires_its_stage_triggers_once():
    world = World(stage_automation("distinctive.ruling.fact-check", "reporting", "copywriting"), stage="reporting")
    (outcome,) = deliver_after(world, completed(), RUN_TRIGGER)
    assert outcome["status"] == "started"
    assert deliver_after(world, completed(), RUN_TRIGGER)[0]["status"] == "duplicate"
    assert len(world.invoked) == 1


@pytest.mark.parametrize("result", [
    {"runStatus": "failed", "output": None},
    {"runStatus": "completed", "output": None},
    {"runStatus": "completed", "output": {"title": "no story"}},
    {"runStatus": "completed", "output": {"story": 5}},
])
def test_a_run_that_failed_or_names_no_story_fires_nothing(result):
    world = World(stage="copywriting")
    assert deliver_after(world, result) == [] and world.invoked == []


def test_a_stage_runs_own_story_is_left_to_the_engine_but_another_story_is_not(capsys):
    world = World(stage="copywriting")
    own = {"event": st.STAGE_ENTERED, "story": LINEAGE}
    assert deliver_after(world, completed(), own) == [] and world.invoked == []
    assert capsys.readouterr().out == ""
    deliver_after(world, completed("another-story"), own)   # attempted (and, with no such story, logged)
    assert "not delivered after the run" in capsys.readouterr().out


def test_a_delivery_failure_never_raises(capsys):
    world = World(stage="copywriting")
    assert deliver_after(world, completed("missing-story"), RUN_TRIGGER) == []
    assert "not delivered after the run" in capsys.readouterr().out
