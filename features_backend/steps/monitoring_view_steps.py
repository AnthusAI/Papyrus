import json
from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import monitoring_view_fixture as fx  # noqa: E402
from papyrus_content.monitoring_view import Forbidden, monitoring_overview  # noqa: E402

ENDPOINTS = {"anth-us": fx.APP_ANTH, "p-apyr-us": fx.APP_PAPYRUS, "threat-intelligence": fx.APP_TI}


def item(context, title):
    found = [i for i in context.overview["items"] if i["title"] == title]
    assert found, f"{title!r} is not listed: {[i['title'] for i in context.overview['items']]}"
    return found[0]


def relevance(entry, publication):
    return next(r for r in entry["relevance"] if r["publicationId"] == publication)


@given("a monitoring table with runs, routed items and a ceiling configuration")
def full_table(context):
    context.store = fx.FakeViewStore()


@given("an empty monitoring table")
def empty_table(context):
    context.store = fx.FakeViewStore([])


def ask(context, groups, publication, scope):
    context.refused = False
    try:
        context.overview = monitoring_overview(context.store, groups=groups, site_endpoint=ENDPOINTS.get(publication), scope=scope, now=fx.NOW)
    except Forbidden:
        context.refused = True


@when('an editor of "{publication}" opens the monitoring overview')
def editor_opens(context, publication):
    ask(context, ["editor"], publication, "publication")


@when('an editor of "{publication}" asks for the whole pipeline')
def editor_asks_all(context, publication):
    ask(context, ["editor"], publication, "all")


@when("an admin opens the monitoring overview for the whole pipeline")
def admin_opens_all(context):
    ask(context, ["admin"], "anth-us", "all")


@when("a reader opens the monitoring overview")
def reader_opens(context):
    ask(context, ["reader"], "anth-us", "publication")


@then('the feed "{feed}" is watched on a 15 minute schedule and is enabled')
def feed_watched(context, feed):
    entry = next(f for f in context.overview["feeds"] if f["id"] == feed)
    assert entry["intervalSeconds"] == 900 and entry["enabled"] is True and entry["limit"] == 30


@then("the recent runs list the newest first with new, unchanged and error counts")
def runs_listed(context):
    runs = context.overview["runs"]
    assert [r["runId"] for r in runs] == ["r3", "r1", "r0"]
    assert (runs[0]["new"], runs[0]["revised"], runs[0]["unchanged"], runs[0]["errorCount"]) == (2, 1, 27, 0)
    assert runs[2]["errorCount"] == 1 and runs[2]["status"] == "partial"
    assert context.overview["routerRuns"][0]["stoppedBy"] == "request_ceiling_reached"


@then("the router is live with feedback on")
def router_state(context):
    router = context.overview["router"]
    assert router["mode"] == "live" and router["feedback"] is True and router["enabled"] is True


@then("usage reads {today:d} of {per_day:d} decisions today and {total:d} of {limit:d} in total")
def usage(context, today, per_day, total, limit):
    usage = context.overview["usage"]
    assert (usage["decisionsToday"], usage["decisionsTotal"]) == (today, total)
    assert usage["ceilings"]["decisionsPerDay"] == per_day and usage["ceilings"]["decisionsTotal"] == limit


@then('the queue shows only relevance for "{publication}"')
def only_own(context, publication):
    for entry in context.overview["items"]:
        assert {r["publicationId"] for r in entry["relevance"]} <= {publication}, entry


@then('the item "{title}" is relevant with confidence {confidence:f} and reached the References queue')
def relevant_delivered(context, title, confidence):
    row = relevance(item(context, title), "anth-us")
    assert row["relevant"] is True and row["confidence"] == confidence
    assert row["delivery"]["state"] == "delivered" and row["delivery"]["referenceLineageId"] == "lin-1"


@then('the item "{title}" is relevant but did not reach the References queue')
def relevant_undelivered(context, title):
    row = relevance(item(context, title), "anth-us")
    assert row["relevant"] is True and row["delivery"]["state"] == "failed"
    assert "throttled" in row["delivery"]["error"] and row["delivery"].get("referenceId") is None


@then("{count:d} item judged not relevant to the publication is not listed")
def hidden(context, count):
    assert context.overview["hiddenNotRelevant"] == count
    assert "A recipe for sourdough" not in [i["title"] for i in context.overview["items"]]


@then('the item "{title}" shows relevance for "{a}", "{b}" and "{c}"')
def all_publications(context, title, a, b, c):
    assert {r["publicationId"] for r in item(context, title)["relevance"]} == {a, b, c}


@then('the item "{title}" is listed')
def listed(context, title):
    item(context, title)


@then("the request is refused")
def refused(context):
    assert context.refused is True


@then("the overview says nothing is configured or collected yet")
def nothing_yet(context):
    overview = context.overview
    assert overview["state"] == "empty" and overview["feeds"] == [] and overview["items"] == [] and overview["runs"] == []


@then("the overview contains no endpoint, role ARN, account or run identifier of the shared Cyclotron")
def no_leaks(context):
    text = json.dumps(context.overview)
    for marker in fx.SECRET_MARKERS:
        assert marker not in text, marker
