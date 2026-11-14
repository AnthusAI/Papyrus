"""features_backend/reference-enrichment-on-create.feature. Fakes only; procedures/newsroom/tests/test_reference_enrichment_on_create.py shares them."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from curation_support import MemoryStore, Summarizer  # noqa: E402
from papyrus_content import monitoring_enrichment as me  # noqa: E402
from papyrus_content import reference_prediction_queue as queue  # noqa: E402
from papyrus_content.monitoring_view import TableViewStore  # noqa: E402
from procedures.newsroom.tests import test_reference_enrichment_on_create as te  # noqa: E402
from procedures.newsroom.tests.test_monitoring_enrichment import SUMMARY, Capturer, failed, good  # noqa: E402
from procedures.newsroom.tests.test_monitoring_router import FakeTable, go, router_config, setup_router  # noqa: E402


def world(context):
    if not hasattr(context, "enrich"):
        for target, value in (("papyrus_content.records.upload_attachment_body", lambda client, expected, body: None),
                              ("papyrus_content.monitoring_enrichment.AttachmentStore", lambda c: MemoryStore(c))):
            patcher = mock.patch(target, value)
            patcher.start()
            context.add_cleanup(patcher.stop)
        table = FakeTable()
        store, cyclotron = setup_router(table)
        context.enrich = type("World", (), {"table": table, "store": store, "cyclotron": cyclotron, "client": te.EnrichedLab(te.ENDPOINT_ANTH, te.CORPUS),
                                            "queue_store": TableViewStore(table, "hn"), "now": 2000, "result": None, "capture": None})
    return context.enrich


def run(context, capture):
    held = world(context)
    held.capture = capture
    enrich = me.Enricher(texts=me.MemoryTexts(), summarizer=Summarizer(SUMMARY), capture=capture)
    held.result = go(held.table, held.store, held.cyclotron, now=held.now, task="email-references", appsync=lambda endpoint: held.client, enricher=enrich)
    held.now += 24 * 3600
    return held.result


def add(context, row, ask=True):
    held = world(context)
    held.client.rows[("Reference", row["id"])] = row
    context.row = row
    if ask:
        queue.queue_reference_predictions(held.queue_store, endpoint=te.ENDPOINT_ANTH, references=[te.request_of(row)], subject="user-intake")


def route(context):
    return next(r for k, r in world(context).table.items.items() if k[1].startswith("ROUTE#"))


@given("the intake action created a pending page and a pending video")
def step_intake_created(context):
    context.created = {"ok": True, "references": [{"id": "reference-user-intake-aaa-v1", "sourceUri": te.PAGE, "curationStatus": "pending"},
                                                   {"id": "reference-user-intake-vid-v1", "sourceUri": te.VIDEO, "curationStatus": "pending"}]}


@when("the intake action queues them and then queues them again")
def step_intake_queues(context):
    held = world(context)
    env = {"PAPYRUS_GRAPHQL_ENDPOINT": te.ENDPOINT_ANTH}
    context.first = queue.queue_after_intake(context.created, {"items": []}, env=env, store=held.queue_store)
    context.second = queue.queue_after_intake(context.created, {"items": []}, env=env, store=held.queue_store)


@then("each has exactly one request that asks for enrichment and the second run added none")
def step_one_each(context):
    rows = te.lane_rows(world(context).table)
    assert context.first["queued"] == 2 and context.second["queued"] == 0 and len(rows) == 2 and all(queue.wants_enrichment(r) for r in rows)


@given("a command that applied a plan creating one pending Reference")
def step_plan(context):
    context.changes = [{"modelName": "Reference", "action": "create", "expected": te.reference_row()}]
    held = world(context)
    context.patches = [mock.patch("papyrus_content.user_auth_mode.user_auth_requested", lambda: False),
                       mock.patch("papyrus_content.monitoring_view.default_email_store_factory", lambda env: (lambda: held.queue_store))]
    for patcher in context.patches:
        patcher.start()
        context.add_cleanup(patcher.stop)


@when("the command asks for its prediction twice and attaches previews")
def step_command_asks(context):
    from papyrus_content import cli

    class Client:
        endpoint = te.ENDPOINT_ANTH

    context.previews = []
    with mock.patch("papyrus_content.reference_images.attach_preview", lambda client, reference: context.previews.append(reference["id"])):
        queue.request_for_created(Client(), context.changes, "references\tcreate-from-catalog")
        queue.request_for_created(Client(), context.changes, "references\tcreate-from-catalog")
        cli.attach_previews_for_created(Client(), context.changes)


@then("there is one request that asks for enrichment and the preview was attempted once")
def step_one_request(context):
    (row,) = te.lane_rows(world(context).table)
    assert queue.wants_enrichment(row) and context.previews == ["reference-user-intake-aaa-v1"]


@given("a pending page Reference whose request asks for enrichment")
def step_page(context):
    add(context, te.reference_row())


@given("a pending page Reference whose request does not ask for enrichment")
def step_page_legacy(context):
    add(context, te.reference_row())
    for row in te.lane_rows(world(context).table):
        row["predictFor"].pop("enrich")


@given("a pending video Reference whose request asks for enrichment")
def step_video(context):
    add(context, te.reference_row("reference-video-v1", address=te.VIDEO, title="A talk", medium="video"))


@given("a person had already supplied its text")
def step_person_text(context):
    world(context).client.rows[("Reference", context.row["id"])]["captureState"] = "full"


@when("the router enriches and decides the queued requests")
def step_runs(context):
    run(context, Capturer(good()))


@when("the router enriches and decides the queued requests twice")
def step_runs_twice(context):
    capture = Capturer(good())
    run(context, capture)
    queue.queue_reference_predictions(world(context).queue_store, endpoint=te.ENDPOINT_ANTH, references=[te.request_of(context.row)], subject="user-intake")
    run(context, capture)


@when("the router enriches and decides the queued requests and the page cannot be read")
def step_runs_failed(context):
    run(context, Capturer(failed("blocked")))


@when("the router enriches and decides the queued requests and the source is too large")
def step_runs_large(context):
    capture = Capturer(failed("too_large"))
    run(context, capture)
    queue.queue_reference_predictions(world(context).queue_store, endpoint=te.ENDPOINT_ANTH, references=[te.request_of(context.row)], subject="user-intake")
    run(context, capture)


@when("the router enriches and decides the queued requests and the video platform refuses the cloud")
def step_runs_video(context):
    run(context, Capturer(failed("blocked")))


@then("the existing Reference has a curation card with the summary and no second Reference was created")
def step_card(context):
    held = world(context)
    assert held.client.card(context.row["id"])["summary"]["text"] == SUMMARY
    assert len([k for k in held.client.rows if k[0] == "Reference"]) == 1


@then("the decision was made on the summary and the captured text")
def step_decided_enriched(context):
    (post,) = world(context).cyclotron.posts()
    values = post[2]["payload"]["item"]["values"]
    assert values["summary"] == SUMMARY and values["text"].endswith(te.ARTICLE)


@then("the page was captured once")
def step_captured_once(context):
    assert len(world(context).capture.calls) == 1


@then("the Reference's card says the capture failed with its reason")
def step_card_failed(context):
    card = world(context).client.card(context.row["id"])
    assert card["capture"]["status"] == "failed" and card["capture"]["reason"]


@then("the Reference was predicted anyway and the failure was counted and logged")
def step_predicted_anyway(context):
    held = world(context)
    assert held.result["counts"]["predicted"] == 1 and held.result["counts"]["enrichmentFailed"] == 1
    assert held.client.rows[("Reference", context.row["id"])]["predictedAcceptProbability"] is not None


@then("the enrichment state is oversized and the reason is on the Reference")
def step_oversized(context):
    assert route(context)["enrichment"]["state"] == "oversized"
    assert world(context).client.card(context.row["id"])["capture"]["reason"] == "too_large"


@then("a later run does not fetch it again")
def step_not_again(context):
    assert len(world(context).capture.calls) == 1


@then("the page was not captured and the Reference was predicted")
def step_not_captured(context):
    held = world(context)
    assert held.capture.calls == [] and held.result["counts"]["predicted"] == 1


@then("the card says the extraction is automated and its completeness is not checked")
def step_label(context):
    origin = world(context).client.card(context.row["id"])["origin"]
    assert origin["completenessChecked"] is False and "not independently checked" in origin["note"]


@then("the video is in the content-needed index the local runners read and was counted as needing a local run")
def step_video_indexed(context):
    held = world(context)
    assert held.client.rows[("Reference", context.row["id"])]["contentNeededKey"] == f"{te.CORPUS}#video#needs_content#pending"
    assert held.result["counts"]["videosNeedLocalRun"] == 1 and route(context)["enrichment"]["needsLocalRun"] is True


@then("the command line says that one video needs a local run")
def step_cli_says(context):
    assert "1 video needs a local run: papyrus references capture-thumbnails --write" in queue.video_line("references\tcreate-from-catalog", 1)


@given("a collected monitor item")
def step_monitor_item(context):
    from procedures.newsroom.tests.test_monitoring_router import ONE_FEED, collected_table
    context.monitor_table = collected_table(ONE_FEED)


@when("the router runs over the monitor item with enrichment on")
def step_router_runs_monitor(context):
    from procedures.newsroom.tests.test_monitoring_enrichment import enricher
    store, cyclotron = setup_router(context.monitor_table)
    context.monitor_result = go(context.monitor_table, store, cyclotron, enricher=enricher(good()))


@then("it was enriched and decided and no existing Reference was enriched")
def step_monitor_ok(context):
    counts = context.monitor_result["counts"]
    assert counts["enriched"] == 1 and counts["decided"] == 1 and counts["referencesEnriched"] == 0


@given("a corpus with an uncaptured page, a captured page and an uncaptured predicted video")
def step_corpus(context):
    unrated = f"{te.CORPUS}#unrated"
    context.rows = [te.reference_row("reference-a-v1", address="https://example.org/a", feedStateKey=unrated),
                    te.reference_row("reference-b-v1", address="https://example.org/b", feedStateKey=unrated, captureState="full"),
                    te.reference_row("reference-c-v1", address=te.VIDEO, feedStateKey=unrated, predictedAcceptProbability=0.4)]
    held = world(context)
    context.patches = [mock.patch("papyrus_content.user_auth_mode.user_auth_requested", lambda: False),
                       mock.patch("papyrus_content.monitoring_view.default_email_store_factory", lambda env: (lambda: held.queue_store))]
    for patcher in context.patches:
        patcher.start()
        context.add_cleanup(patcher.stop)


@when("an operator runs the enrichment backfill twice")
def step_backfill(context):
    from papyrus_content import references_commands as commands

    class Listing:
        endpoint = te.ENDPOINT_ANTH

        def iterate_newest_first(self, index, key):
            yield from (row for row in context.rows if row.get("feedStateKey") == key)

    with mock.patch.object(commands, "create_authoring_client", lambda: (Listing(), {})):
        commands.references_queue_enrichment(["--site", "anth-us"])
        commands.references_queue_enrichment(["--site", "anth-us"])


@then("two enrich-only requests exist, none asks for a prediction, and the second run added none")
def step_backfilled(context):
    rows = te.lane_rows(world(context).table)
    assert len(rows) == 2 and all(r["predictFor"]["enrichOnly"] for r in rows)
    assert all(r["sourceId"] == queue.enrichment_source_id(te.ENDPOINT_ANTH, te.CORPUS, r["predictFor"]["referenceId"]) for r in rows)


@given("the line a creating command prints when the catalog holds videos")
def step_hint_line(context):
    context.hint_line = queue.video_line("references\tcreate-from-catalog", 2)


@when("each command named in the hint is parsed with exactly the flags the hint gives it")
def step_parse_hint(context):
    try:
        context.hint_parsed = te.parse_local_run_hint(context.hint_line)
    except SystemExit as exit_:
        context.hint_parsed, context.hint_exit = None, exit_.code


@then("both commands accept those flags")
def step_hint_accepted(context):
    assert context.hint_parsed is not None and set(context.hint_parsed) == {"capture-thumbnails", "capture-transcripts"}
    assert context.hint_parsed["capture-thumbnails"].write is True


@then("the hint does not give capture-transcripts a --write flag, which it does not take")
def step_hint_no_write(context):
    assert ("capture-transcripts", ["--write"]) not in te.local_run_commands(context.hint_line)
