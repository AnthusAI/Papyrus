import json
from pathlib import Path
import sys

from behave import given, then, when

TESTS = Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"
sys.path.insert(0, str(TESTS))
import test_story_triggers as t  # noqa: E402
from papyrus_content import automations as au  # noqa: E402
from papyrus_content import story_triggers as st  # noqa: E402
from papyrus_content.story_reporting import move_story_stage  # noqa: E402

FACT, EDIT = "distinctive.ruling.fact-check", "distinctive.ruling.copy-edit"


def setup(context, *automations, stage):
    context.world = t.World(*automations, stage=stage)
    context.outcomes, context.moved = [], None


@given("a story in the {stage} stage and a copywriting bot that moves stories to typesetting")
def basic(context, stage):
    setup(context, t.stage_automation(), stage=stage)


@given("a story in the {stage} stage and a copywriting bot with no next stage")
def no_next(context, stage):
    setup(context, t.stage_automation(next_stage=None), stage=stage)


@given("a story in the {stage} stage and a copywriting bot whose static input tries to set the story and the hop")
def sneaky(context, stage):
    setup(context, t.stage_automation(inputTemplate=json.dumps({"story": "wrong", "hop": 99})), stage=stage)


@given("a story in the {stage} stage and a copywriting bot limited to {hops:d} hops")
def limited(context, stage, hops):
    setup(context, t.stage_automation(max_hops=hops), stage=stage)


@given("a story in the {stage} stage and a copywriting bot that may run one at a time with another story already running")
def busy(context, stage):
    import json as _json
    setup(context, t.stage_automation(limits=_json.dumps({"timeoutSeconds": 600, "maxConcurrent": 1})), stage=stage)
    other = f"STAGE#{t.COPY_BOT}#other#copywriting#other-v1"
    context.world.table.rows[("MONITOR#ttab", other)] = {"pk": "MONITOR#ttab", "sk": other, "status": "running", "startedAt": t.NOW}


@given("a story in the {stage} stage and the fact-check and copy-edit bots")
def chain(context, stage):
    setup(context, t.stage_automation(FACT, "reporting", "copywriting"), t.stage_automation(EDIT, "copywriting", "typesetting"), stage=stage)


@when("the story has already had {hops:d} bot hops")
def prior_hops(context, hops):
    world = context.world
    row = t.latest_story_version(world.client, t.LINEAGE)
    world.client.update_record("Item", {"id": row["id"], "metadata": json.dumps({**st.story_metadata(row), st.CHAIN_KEY: {"hops": hops}})})


@when("the story's stage-entry triggers are delivered")
def deliver(context):
    context.outcomes = context.world.deliver()


@when("the story's stage-entry triggers are delivered twice")
def deliver_twice(context):
    context.outcomes = [context.world.deliver(), context.world.deliver()]


@when("a person saves a new version and the triggers are delivered again")
def new_version(context):
    context.world.bot_writes_version("person")
    context.world.deliver()


@when("the procedure writes a new version and finishes")
def finish(context):
    world = context.world
    # the run that has not been finished yet: the last request whose story is still waiting
    pending = getattr(context, "finished", 0)
    request = world.invoked[pending]
    context.finished = pending + 1
    new = world.bot_writes_version(request["actorLabel"])
    context.moved = world.finish(request, output={"version": new})
    context.new_version = new


@when('the procedure writes a new version and holds the story because "{reason}"')
def hold(context, reason):
    world = context.world
    new = world.bot_writes_version("bot")
    context.moved = world.finish(world.invoked[0], output={"version": new, "hold": True, "reason": reason})


@when('the run fails with "{error}"')
def fail(context, error):
    context.moved = context.world.finish(context.world.invoked[0], status="failed", error=error)


@when("the procedure finishes without returning a version")
def no_version(context):
    context.moved = context.world.finish(context.world.invoked[0], output={})


@when("a person moves the story to {stage} while the bot runs")
def person_moves(context, stage):
    move_story_stage(context.world.client, t.LINEAGE, stage, actor="person", now=t.NOW)


@when("a person moves the story to copywriting and the triggers are delivered")
def person_moves_and_delivers(context):
    move_story_stage(context.world.client, t.LINEAGE, "copywriting", actor="person", now=t.NOW)
    context.outcomes = context.world.deliver()


@when("an operator describes a bot with on-stage copywriting, next-stage typesetting and max-hops 3")
def describe(context):
    base = {"id": t.COPY_BOT, "title": "Copywriter", "on-stage": "copywriting", "next-stage": "typesetting", "monitor": "ttab",
            "publication": "distinctive", "procedure": t.PROCEDURE, "max-hops": "3", "input": '{"tone":"plain"}'}
    context.record = au.read_record(au.stored_payload(au.build_record(au.fields_from_options(base), actor="t", now=t.NOW)))
    context.base = base


@then("the bot's procedure starts once")
def started_once(context):
    assert len(context.world.invoked) == 1, context.world.invoked


@then("the bot's procedure starts twice")
def started_twice(context):
    assert len(context.world.invoked) == 2


@then("no bot procedure starts")
def none_started(context):
    assert context.world.invoked == []


@then("no third procedure started")
def no_third(context):
    assert len(context.world.invoked) == 2


@then("its input names the story, its version, the stage, the run key, the automation id and hop 1")
def input_names(context):
    key = f"STAGE#{t.COPY_BOT}#{t.LINEAGE}#copywriting#{t.LINEAGE}"
    assert context.world.invoked[0]["input"] == {"tone": "plain", "story": t.LINEAGE, "version": t.LINEAGE, "versionNumber": 1,
                                                 "stage": "copywriting", "runKey": key, "automationId": t.COPY_BOT, "hop": 1}


@then("the bot's input carries the real story and hop 1")
def real_input(context):
    values = context.world.invoked[0]["input"]
    assert values["story"] == t.LINEAGE and values["hop"] == 1


@then("the run is recorded on a claim row for that story, stage and version")
def claim_row(context):
    row = context.world.table.rows[("MONITOR#ttab", f"STAGE#{t.COPY_BOT}#{t.LINEAGE}#copywriting#{t.LINEAGE}")]
    assert row["status"] == "starting" and row["requestedBy"] == f"automation:{t.COPY_BOT}"


@then("the second delivery is reported as a duplicate")
def duplicate(context):
    assert context.outcomes[1][0]["status"] == "duplicate"


@then("the story counts one bot hop")
def one_hop(context):
    assert context.world.chain()["hops"] == 1


@then("the outcome is deferred because of the concurrency limit")
def deferred(context):
    assert context.outcomes[0]["status"] == "deferred" and "concurrency limit" in context.outcomes[0]["reason"]


@then("the story is in the {stage} stage")
def in_stage(context, stage):
    assert context.world.stage() == stage


@then("the story's trail names automation:distinctive.copywriter as the actor of the move")
def trail(context):
    messages = list(context.world.client.tables["Message"].values())
    assert any("copywriting -> typesetting" in json.dumps(m) and "automation:distinctive.copywriter" in json.dumps(m) for m in messages)


@then("the new version is labelled as a bot action of distinctive.copywriter")
def labelled(context):
    metadata = json.loads(context.world.client.tables["Item"][context.new_version]["metadata"])
    assert metadata["botAction"]["automationId"] == t.COPY_BOT


@then('one flag review request raised by automation:distinctive.copywriter mentions "{text}"')
def flag(context, text):
    (review,) = context.world.reviews()
    assert review["mode"] == "flag" and review["raisedBy"] == f"automation:{t.COPY_BOT}" and text in review["reason"]


@then("a flag review request exists")
def any_flag(context):
    assert [r["mode"] for r in context.world.reviews()] == ["flag"]


@then("exactly one hard gate review request says \"{text}\"")
def hard_gate(context, text):
    (review,) = context.world.reviews()
    assert review["mode"] == "hard_gate" and text in review["reason"]


@then("the bots ran in order fact-check then copy-edit, at hops 1 and 2")
def order(context):
    runs = [(r["input"]["automationId"], r["input"]["hop"]) for r in context.world.invoked]
    assert runs == [(FACT, 1), (EDIT, 2)], runs


@then("only the copy-edit bot starts")
def only_edit(context):
    assert [r["input"]["automationId"] for r in context.world.invoked] == [EDIT]


@then("the record is an event automation firing when a story enters copywriting, then moving it to typesetting, with at most 3 hops")
def record_shape(context):
    record = context.record
    assert record["trigger"]["kind"] == "event" and record["supported"]
    assert (record["onStage"], record["nextStage"], record["maxHops"]) == ("copywriting", "typesetting", 3)


@then("a stage the publication does not have is refused")
def bad_stage(context):
    try:
        au.build_record(au.fields_from_options({**context.base, "on-stage": "nowhere"}), actor="t", now=t.NOW)
    except au.AutomationError as error:
        assert "onStage" in str(error)
    else:
        raise AssertionError("accepted")


@then("a static input that uses placeholders is refused")
def bad_input(context):
    try:
        au.build_record(au.fields_from_options({**context.base, "input": '{"a":"{story}"}'}), actor="t", now=t.NOW)
    except au.AutomationError as error:
        assert "static" in str(error)
    else:
        raise AssertionError("accepted")


@when("the procedure returns the version it received with extra findings")
def unchanged(context):
    world = context.world
    context.moved = world.finish(world.invoked[0], output={"version": t.LINEAGE, "hold": False, "corrections": [],
                                                           "unverifiable": ["a date"], "remaining_findings": 1})


@then("the story's trail says distinctive.copywriter made no changes")
def no_changes_note(context):
    assert context.moved["noChanges"] is True
    assert "distinctive.copywriter: no changes" in json.dumps(list(context.world.client.tables["Message"].values()))


@then("no version is labelled as a bot action")
def no_label(context):
    assert all("botAction" not in json.loads(row["metadata"]) for row in context.world.client.tables["Item"].values())


@then("no review request is raised")
def no_review(context):
    assert context.world.reviews() == []


@given("a procedure run started by a monitor created that story through a tool, so nothing delivered its triggers")
def tool_created(context):
    context.run_trigger = {"event": "monitor.matched", "pk": "MONITOR#ttab", "sk": "RUN#1"}
    assert context.world.invoked == []


def after_run(context, result):
    world = context.world
    return st.deliver_after_run(world.client, context.run_trigger, result, reader=au.MonitoringReader(world.table),
                                writer=au.MonitoringWriter(world.table), invoke=world.invoked.append, now=t.NOW)


@when("the run completes and its output names the story")
def run_completes(context):
    context.outcomes = [after_run(context, {"runStatus": "completed", "output": {"story": t.LINEAGE, "version_id": t.LINEAGE}})]


@then("the fact-check bot starts exactly once")
def fact_check_once(context):
    assert [r["input"]["automationId"] for r in context.world.invoked] == [FACT]


@then("a second look at the same completed run starts nothing more")
def second_look(context):
    again = after_run(context, {"runStatus": "completed", "output": {"story": t.LINEAGE}})
    assert [o["status"] for o in again] == ["duplicate"] and len(context.world.invoked) == 1


@then("a run that failed fires no trigger")
def failed_fires_nothing(context):
    assert after_run(context, {"runStatus": "failed", "output": None, "error": "x"}) == []


def story_moves(context):
    row = t.latest_story_version(context.world.client, t.LINEAGE)
    return json.loads(row["metadata"]).get("stageMoves") or []


@then("the story keeps a record that {actor} moved it to {stage} with a new version")
def move_record_new(context, actor, stage):
    move = story_moves(context)[-1]
    assert (move["to"], move["by"]) == (stage, actor) and move["reason"].endswith("(new version v2)"), move


@then("the story keeps a record that {actor} moved it to {stage} with no changes")
def move_record_none(context, actor, stage):
    move = story_moves(context)[-1]
    assert (move["to"], move["by"]) == (stage, actor) and move["reason"].endswith("(no changes)"), move
