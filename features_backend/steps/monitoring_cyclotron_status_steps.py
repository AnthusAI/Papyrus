import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import monitoring_view_fixture as fx  # noqa: E402
import test_monitoring_router as tr  # noqa: E402
from papyrus_content import monitoring_router as mr  # noqa: E402
from papyrus_content import monitoring_view as mv  # noqa: E402
from papyrus_content.monitoring_cloud import DynamoStore, run_collection  # noqa: E402

PUBLICATIONS = list(tr.PUBS)


@given("a router with three publications on one shared Cyclotron run")
def step_given(context):
    context.table_ = tr.FakeTable()
    context.table_.put_item(tr.COLLECTOR_CONFIG)
    run_collection(DynamoStore(context.table_), "hn", fetch=lambda url: tr.FEED, now=1000)
    context.store, context.cyclotron = tr.setup_router(context.table_)


@given("the Cyclotron has no verified snapshot yet for the first publication")
def step_no_snapshot(context):
    context.cyclotron.status_answers[PUBLICATIONS[0]] = (503, {"detail": "no verified publication status snapshot yet"})


@given("the Cyclotron reports no refits and no labels for the first publication")
def step_never(context):
    context.cyclotron.status_answers[PUBLICATIONS[0]] = (200, tr.status_answer(PUBLICATIONS[0], refits=0, labels=0))


def status_rows(context):
    return tr.status_rows(context.table_)


@when("the router runs the cyclotron-status task")
def step_run(context):
    out = io.StringIO()
    with redirect_stdout(out):
        context.result = tr.status_run(context.table_, context.store, context.cyclotron)


@then("each of the three publications has one status row with the snapshot's own as-of time")
def step_rows(context):
    rows = status_rows(context)
    assert sorted(rows) == sorted(PUBLICATIONS), rows.keys()
    assert {row["asOf"] for row in rows.values()} == {"2026-11-02T10:00:00.000Z"}


def served(context, publication_index, groups=("editor",)):
    """What the Monitoring view serves the editor of one publication's site: the stored rows, as the signed-in site's own endpoint sees them."""
    endpoint = tr.ENDPOINT.replace("abc123", f"api{publication_index}")
    rows = [mv._clean(dict(row)) for row in context.table_.items.values() if row["sk"].startswith("CYCLOTRONSTATUS#") or row["sk"] in ("CONFIG", "CONFIG#router")]
    for row in rows:
        row.setdefault("pk", "MONITOR#hn")
    store = fx.FakeViewStore(rows)
    event = {"fieldName": "monitoringPage", "arguments": {"list": "cyclotronStatus", "scope": "publication"}, "identity": {"groups": list(groups), "sub": "u1"}}
    return mv.handle(event, env={"PAPYRUS_GRAPHQL_ENDPOINT": endpoint}, store_factory=fx.only_hn(store))


@then("an editor of the first publication's site is served the first publication's snapshot")
def step_served_first(context):
    out = served(context, 0)
    assert [r["publicationId"] for r in out["rows"]] == [PUBLICATIONS[0]]
    assert out["rows"][0]["status"]["cyclotron"]["id"] == f"{PUBLICATIONS[0]}-relevance"


@given("the Cyclotron's answer for the first publication holds only another output's snapshot")
def step_other_output(context):
    other = f"{PUBLICATIONS[1]}-relevance"
    context.cyclotron.status_answers[PUBLICATIONS[0]] = (200, {"bindingId": PUBLICATIONS[0], "classifiers": {other: tr.status_snapshot(PUBLICATIONS[1])}})


@then("the first publication's run says its answer was not a status snapshot")
def step_not_snapshot(context):
    assert context.result["publications"][PUBLICATIONS[0]] == {"status": "unavailable", "reason": "not a status snapshot"}
    assert sorted(status_rows(context)) == sorted(PUBLICATIONS[1:])


@then("the first publication has no status row and the other two have one")
def step_one_missing(context):
    assert sorted(status_rows(context)) == sorted(PUBLICATIONS[1:])
    assert context.result["publications"][PUBLICATIONS[0]] == {"status": "no_snapshot"}


@then("an editor of the first publication's site is served no snapshot")
def step_served_none(context):
    assert served(context, 0)["rows"] == []


@then("the first publication's row says zero refits, no last change and zero labels, and invents nothing")
def step_never_row(context):
    status = status_rows(context)[PUBLICATIONS[0]]["status"]
    assert status["cyclotron"]["refits"] == 0 and status["lastChange"] is None and status["alignment"]["labels"] == 0
    assert status["alignment"]["accuracy"] is None


@then("an editor of the second publication's site is served the second publication's snapshot only")
def step_served_second(context):
    out = served(context, 1)
    assert [r["publicationId"] for r in out["rows"]] == [PUBLICATIONS[1]], out
    assert PUBLICATIONS[0] not in json.dumps(out) and PUBLICATIONS[2] not in json.dumps(out)


@then("a reader who is not an editor is refused")
def step_refused(context):
    assert served(context, 1, groups=("reader",)) == {"error": "forbidden"}


@then("the monitor has no lab pause")
def step_no_pause(context):
    assert ("MONITOR#hn", mr.LAB_BACKOFF_SK) not in context.table_.items


@when("the router then runs a routing sweep")
def step_sweep(context):
    out = io.StringIO()
    with redirect_stdout(out):
        context.sweep = tr.go(context.table_, context.store, context.cyclotron, now=2100)


@then("the sweep was not stopped and it posted decisions to the Cyclotron")
def step_sweep_ran(context):
    assert context.sweep["status"] != "stopped" and context.cyclotron.posts()


@then("a sweep that is running does not delay the status task, because each has its own lock")
def step_locks(context):
    assert context.store.acquire_router_lock("hn", "sweep", now=3000)
    out = io.StringIO()
    with redirect_stdout(out):
        result = tr.status_run(context.table_, context.store, context.cyclotron, now=3000)
    assert result["status"] == "complete"


@then("the stack has an hourly cyclotron-status schedule for the hn monitor and one for the web-distinctive monitor")
def step_schedules(context):
    resources = tr._template()["Resources"]
    found = sorted(json.loads(r["Properties"]["Target"]["Input"])["monitorId"] for r in resources.values()
                   if r["Type"] == "AWS::Scheduler::Schedule" and isinstance(r["Properties"]["Target"]["Input"], str)
                   and json.loads(r["Properties"]["Target"]["Input"]).get("task") == "cyclotron-status")
    assert found == ["hn", "web-distinctive"], found
    context.schedules = [r["Properties"] for r in resources.values() if r["Type"] == "AWS::Scheduler::Schedule"
                         and isinstance(r["Properties"]["Target"]["Input"], str) and "cyclotron-status" in r["Properties"]["Target"]["Input"]]
    assert all(s["ScheduleExpression"].endswith(" * * ? *)") for s in context.schedules)


@then("neither status schedule retries a failed run")
def step_no_retry(context):
    assert all(s["Target"]["RetryPolicy"]["MaximumRetryAttempts"] == 0 for s in context.schedules)
