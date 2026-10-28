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


@given("a monitoring table with runs, routed items and a legacy quota configuration")
def full_table(context):
    context.store = fx.FakeViewStore()


@given("an empty monitoring table")
def empty_table(context):
    context.store = fx.FakeViewStore([])


@given('a separate private email receiver partition for "{publication}"')
def separate_email_partition(context, publication):
    context.store = fx.FakeViewStore()
    context.email_monitor_id = "p-apyr-us-email"
    email_pk = f"MONITOR#{context.email_monitor_id}"
    router = next(row for row in fx.rows() if row["sk"] == "CONFIG#router").copy()
    router["pk"] = email_pk
    digest = "a" * 64
    receipt_id = f"EMAIL#{digest}"
    context.email_store = fx.FakeViewStore([
        router,
        {"pk": email_pk, "sk": f"EMAILINDEX#2026-10-21T02:30:00Z#{digest}",
         "receiptId": receipt_id, "destinationPublicationIds": [publication]},
        {"pk": email_pk, "sk": receipt_id, "status": "pending_review", "emailTrustMode": "data-only",
         "emailDestinationPublicationIds": [publication], "observedAt": "2026-10-21T02:30:00Z",
         "subject": "Private newsletter", "linkCount": 1, "processedCount": 0,
         "warnings": ["ses_authentication_unverified"]},
    ])


def ask(context, groups, publication, scope):
    context.refused = False
    try:
        if getattr(context, "stores", None):
            from papyrus_content.monitoring_view import monitoring_site_overview
            context.overview = monitoring_site_overview(context.stores, groups=groups, site_endpoint=ENDPOINTS.get(publication), scope=scope, now=fx.NOW)
        else:
            context.overview = monitoring_overview(context.store, groups=groups, site_endpoint=ENDPOINTS.get(publication), scope=scope, now=fx.NOW)
    except Forbidden:
        context.refused = True


@when('an editor of "{publication}" opens the monitoring overview')
def editor_opens(context, publication):
    ask(context, ["editor"], publication, "publication")


@when('an editor of "{publication}" opens the monitoring overview with that partition')
def editor_opens_with_email_partition(context, publication):
    context.refused = False
    context.overview = monitoring_overview(
        context.store, groups=["editor"], site_endpoint=ENDPOINTS.get(publication),
        scope="publication", now=fx.NOW, email_store=context.email_store,
    )


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
    assert entry["intervalSeconds"] == 900 and entry["enabled"] is True


@then("the recent runs list the newest first with new, unchanged and error counts")
def runs_listed(context):
    runs = context.overview["runs"]
    assert [r["runId"] for r in runs] == ["r3", "r1", "r0"]
    assert (runs[0]["new"], runs[0]["revised"], runs[0]["unchanged"], runs[0]["errorCount"]) == (2, 1, 27, 0)
    assert runs[2]["errorCount"] == 1 and runs[2]["status"] == "partial"
    assert context.overview["routerRuns"][0]["stoppedBy"] == "request_ceiling_reached"


@then("the router is live and sends editor feedback")
def router_state(context):
    router = context.overview["router"]
    assert router["mode"] == "live" and router["feedback"] is True and router["enabled"] is True


@then("usage reports {today:d} decisions today and {total:d} recorded decisions in inspected history without quotas")
def usage(context, today, total):
    usage = context.overview["usage"]
    assert (usage["decisionsToday"], usage["decisionsTotal"], usage["historyComplete"]) == (today, total, True)
    assert "ceilings" not in usage


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


@then('the shared feed still comes from the "{monitor_id}" partition')
def shared_feed_from_partition(context, monitor_id):
    assert context.email_monitor_id == "p-apyr-us-email"
    assert [feed["id"] for feed in context.overview["feeds"]] == [monitor_id]


@then('the email receipt appears from the "{monitor_id}" partition')
def email_receipt_from_partition(context, monitor_id):
    assert context.email_monitor_id == monitor_id
    assert [item["subject"] for item in context.overview["emailSubmissions"]] == ["Private newsletter"]


@then("the overview contains no endpoint, role ARN, account or run identifier of the shared Cyclotron")
def no_leaks(context):
    text = json.dumps(context.overview)
    for marker in fx.SECRET_MARKERS:
        assert marker not in text, marker


DISTINCTIVE = "https://dist9.appsync-api.us-east-1.amazonaws.com/graphql"


@given('monitors "hn", "ttab" and "huggingface" where only "ttab" routes to the publication "distinctive"')
def several_monitors(context):
    ENDPOINTS["distinctive"] = DISTINCTIVE
    context.stores = {"hn": fx.FakeViewStore(), "ttab": fx.FakeViewStore(fx.ttab_rows(DISTINCTIVE)),
                      "huggingface": fx.FakeViewStore(fx.ttab_rows(fx.APP_PAPYRUS, monitor="huggingface"))}
    context.store = None


@then('the queue lists only the items of the monitor "{monitor}"')
def only_monitor(context, monitor):
    assert context.overview["items"] and {i["monitorId"] for i in context.overview["items"]} == {monitor}


@then('the item "{title}" is waiting for the router')
def waiting(context, title):
    assert item(context, title)["routing"] == "collected"


@then('no item of the monitors "{a}" and "{b}" is returned')
def none_of_others(context, a, b):
    text = json.dumps(context.overview)
    for title in ("Fresh Show HN", "Quantum paper on arXiv", "Model release"):
        assert title not in text


@then('the monitors "{a}" and "{b}" are named as not routed to this site')
def named_not_routed(context, a, b):
    assert sorted(context.overview["otherMonitors"]) == sorted([a, b])


# --- paging ---------------------------------------------------------------------------------------

from papyrus_content import monitoring_view as mv  # noqa: E402


def follow(context, name, **options):
    """Load more of one list, as the page's button does, until the cursor ends. Returns the rows after the first page."""
    cursor, rows = mv.encode_cursor({"hn": context.overview["cursors"][name]}), []
    while cursor:
        page = mv.monitoring_list_page({"hn": context.store}, list_name=name, cursor=cursor, groups=["editor"],
                                       site_endpoint=fx.APP_ANTH, scope="publication", now=fx.NOW, **options)
        rows += page["rows"]
        cursor = page["cursor"]
    return rows


@given('a monitoring table with {count:d} email receipts for "{publication}"')
def many_receipts(context, count, publication):
    context.store = fx.FakeViewStore(fx.rows() + fx.receipt_rows(count))


@given('a monitoring table with {count:d} email receipts for "{publication}" where the oldest is held for review')
def many_receipts_oldest_held(context, count, publication):
    context.store = fx.FakeViewStore(fx.rows() + fx.receipt_rows(count, held={0}))


@given("a monitoring table with {runs:d} more collector runs and {router:d} more router runs")
def many_runs(context, runs, router):
    table = fx.rows()
    for n in range(runs):
        stamp = f"2026-10-19T00:{n:02d}:00.000000Z"
        table.append({"pk": fx.PK, "sk": f"RUN#{stamp}#x{n}", "runId": f"x{n}", "startedAt": stamp, "status": "complete"})
    for n in range(router):
        stamp = f"2026-10-19T00:{n:02d}:00.000000Z"
        table.append({"pk": fx.PK, "sk": f"ROUTERUN#{stamp}#y{n}", "runId": f"y{n}", "startedAt": stamp, "status": "complete"})
    context.store = fx.FakeViewStore(table)


@then("the first page lists {count:d} email receipts, newest first, and offers more")
def first_page_emails(context, count):
    subjects = [e["subject"] for e in context.overview["emailSubmissions"]]
    assert len(subjects) == count and subjects[0] == "Mail 44", subjects
    assert context.overview["cursors"]["emailSubmissions"]
    context.listed = subjects


@when("the editor loads more email receipts until the list ends")
def load_more_emails(context):
    context.listed += [e["subject"] for e in follow(context, "emailSubmissions")]


@then("all {count:d} email receipts have been listed exactly once")
def all_emails_once(context, count):
    assert sorted(context.listed) == sorted(f"Mail {n}" for n in range(count)), len(context.listed)


@then("the oldest receipt is not on the first page")
def oldest_not_first(context):
    assert "Mail 0" not in [e["subject"] for e in context.overview["emailSubmissions"]]


@when('the editor filters to "Held for review"')
def filter_held(context):
    page = mv.monitoring_list_page({"hn": context.store}, list_name="emailSubmissions", cursor=None, held_only=True,
                                   groups=["editor"], site_endpoint=fx.APP_ANTH, scope="publication", now=fx.NOW)
    context.held = page["rows"]


@then("the oldest receipt is listed as held for review")
def oldest_held(context):
    assert [e["subject"] for e in context.held] == ["Mail 0"]
    assert context.held[0]["quarantine"]["state"] == "quarantined"


@then("the held filter lists nothing that was not held")
def only_held(context):
    assert all(e["quarantine"] and e["quarantine"]["state"] == "quarantined" for e in context.held)


@then("the first page of runs offers more")
def runs_offer_more(context):
    assert context.overview["cursors"]["runs"] and context.overview["cursors"]["routerRuns"]
    context.listed_runs = [r["runId"] for r in context.overview["runs"]]


@when("the editor loads more runs until the list ends")
def load_more_runs(context):
    context.listed_runs += [r["runId"] for r in follow(context, "runs")]


@then("every collector run has been listed exactly once")
def runs_once(context):
    expected = {"r0", "r1", "r3"} | {f"x{n}" for n in range(40)}
    assert sorted(context.listed_runs) == sorted(expected)
