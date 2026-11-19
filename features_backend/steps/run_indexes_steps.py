import os
from collections import Counter
import sys
from pathlib import Path

from behave import given, then, when

TESTS = Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"
sys.path.insert(0, str(TESTS))
import priming_export_fixture as fx  # noqa: E402
from papyrus_content import priming_export as pe, run_attention, run_outcomes  # noqa: E402
from papyrus_content.cloud_procedures import update_cloud_procedure_run_record  # noqa: E402
import run_outcomes_steps  # noqa: E402,F401  (the runner steps this feature shares)

NOW = "2026-11-19T10:00:00Z"


class RunTable:
    """The ProcedureRun rows with the three reads a run index allows. Every read is recorded; listing the table is a failure."""

    tenant_id = None

    def __init__(self):
        self.rows, self.reads = {}, []

    def graphql(self, query, variables):
        assert "updateProcedureRun" in query, query
        row = self.rows.setdefault(variables["input"]["id"], {})
        row.update(variables["input"])
        return {"updateProcedureRun": row}

    def get_record(self, model, record_id):
        self.reads.append(("get", model))
        return dict(self.rows[record_id]) if record_id in self.rows else None

    def update_record(self, model, payload):
        self.reads.append(("update", model))
        self.rows[payload["id"]].update(payload)
        for key in [key for key, value in payload.items() if value is None]:
            del self.rows[payload["id"]][key]   # a null clears the attribute, which is what takes the row out of the sparse index

    def list_by_index(self, index, key, **_):
        self.reads.append(("index", index))
        assert index == "procedureRunsByAttention", index
        return [dict(row) for row in self.rows.values() if row.get("attentionKey") == key]

    def list_records(self, model, **_):
        raise AssertionError(f"the whole {model} table was listed")


def table_of(context):
    """The run table as the runner's client left it: its updates, in order, applied to rows."""
    if not hasattr(context, "run_table"):
        context.run_table = RunTable()
        for update in getattr(getattr(context, "client", None), "updates", []):
            context.run_table.rows.setdefault(update["id"], {}).update(update)
    return context.run_table


def finish(table, run_id, outcome, finished_at):
    ended = run_outcomes.finished_outcome(outcome != "failed", {"title": "x"}, "boom" if outcome == "failed" else None)
    update_cloud_procedure_run_record(table, {"id": run_id, "runStatus": ended["runStatus"], "outcome": ended["outcome"],
                                              "outcomeReason": ended["outcomeReason"], "finishedAt": finished_at})


@then("the run is recorded with the attention key and the time it finished")
def attention_recorded(context):
    update = context.client.updates[0]
    assert update["attentionKey"] == "attention" and update["dueAt"] == update["finishedAt"], update


@then("the run is recorded with no attention key and no attention time")
def no_attention(context):
    update = context.client.updates[0]
    assert "attentionKey" not in update and "dueAt" not in update, update


@then("the run is the only one on the attention list")
def only_one(context):
    assert [run["id"] for run in run_attention.list_attention(table_of(context))] == [context.client.updates[0]["id"]]


@given("a failed run on the attention list")
def failed_run(context):
    context.run_table = RunTable()
    finish(context.run_table, "run-1", "failed", "2026-11-19T09:00:00Z")
    context.run_id = "run-1"
    assert [run["id"] for run in run_attention.list_attention(context.run_table)] == ["run-1"]


@given("a finished run that did its work")
def acted_run(context):
    context.run_table = RunTable()
    finish(context.run_table, "run-2", "acted", "2026-11-19T09:00:00Z")
    context.run_id = "run-2"


@when("an operator acknowledges that run")
def acknowledge(context):
    context.answer = run_attention.acknowledge(context.run_table, context.run_id, "an operator", NOW)


@when("an operator acknowledges that run again")
def acknowledge_again(context):
    context.second = run_attention.acknowledge(context.run_table, context.run_id, "another operator", "2026-11-19T11:00:00Z")


@then("the attention list is empty")
def empty(context):
    assert run_attention.list_attention(context.run_table) == []


@then("the run records who acknowledged it and when")
def who(context):
    row = context.run_table.rows[context.run_id]
    assert (row["acknowledgedBy"], row["acknowledgedAt"]) == ("an operator", NOW), row


@then("the run is still in the history as failed")
def still_failed(context):
    row = context.run_table.get_record("ProcedureRun", context.run_id)
    assert (row["runStatus"], row["outcome"]) == ("failed", "failed"), row


@then("the second acknowledgement says the run was acknowledged already")
def twice(context):
    assert context.second == {"runId": context.run_id, "changed": False, "reason": "acknowledged already"}, context.second
    assert context.run_table.rows[context.run_id]["acknowledgedBy"] == "an operator"


@then("the acknowledgement says the run needs nobody")
def needs_nobody(context):
    assert context.answer == {"runId": context.run_id, "changed": False, "reason": "needs nobody"}, context.answer


@given("three runs that need a person, finished at different times")
def three_runs(context):
    context.run_table = RunTable()
    for run_id, outcome, at in (("late", "failed", "2026-11-19T09:30:00Z"), ("early", "failed", "2026-11-19T08:00:00Z"),
                                ("middle", "failed", "2026-11-19T09:00:00Z")):
        finish(context.run_table, run_id, outcome, at)
    finish(context.run_table, "fine", "acted", "2026-11-19T07:00:00Z")
    context.run_table.reads.clear()


@when("an operator lists the runs that need a person")
def list_attention(context):
    context.listed = run_attention.list_attention(context.run_table)


@then("the list is the three runs, oldest first")
def oldest_first(context):
    assert [run["id"] for run in context.listed] == ["early", "middle", "late"]


@then("the only read made was the attention index")
def only_index(context):
    assert context.run_table.reads == [("index", "procedureRunsByAttention")], context.run_table.reads


@given("a site with a monitor's analysis runs")
def monitor_runs(context):
    fx.FakeCards.bodies = {}
    pe.AttachmentStore = fx.FakeCards
    context.site = fx.FakeSite(automations=[fx.automation()], runs=[fx.run("story-a", "11111111"), fx.run("story-b", "22222222", at="2026-10-25T17:05:50Z")])


@when("the priming export reads the monitor's runs")
def export_reads(context):
    context.rows = pe.ttab_rows(context.site, fx.PUBLICATION, [], None, include_unlabeled=True, skipped=Counter())


@then("the runs are read through the procedure index and no read lists the whole run table")
def by_index(context):
    calls = context.site.calls
    assert ("index", "procedureRunsByProcedure") in calls, calls
    assert ("list", "ProcedureRun") not in calls, calls


@given('a shared stack for the tenant "{tenant}"')
def shared(context, tenant):
    for name, value in (("PAPYRUS_TENANCY_MODE", "shared"), ("PAPYRUS_TENANT_ID", tenant)):
        previous = os.environ.get(name)
        os.environ[name] = value
        context.add_cleanup(lambda name=name, previous=previous: os.environ.pop(name, None) if previous is None else os.environ.__setitem__(name, previous))


@when("a failed run finishes")
def failed_finishes(context):
    context.run_table = RunTable()
    finish(context.run_table, "run-3", "failed", "2026-11-19T09:00:00Z")


@then('the run is recorded with the attention key "{key}"')
def key_is(context, key):
    assert context.run_table.rows["run-3"]["attentionKey"] == key
