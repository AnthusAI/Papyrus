"""Automatic acceptance (features_backend/reference-automatic-acceptance.feature). The backend and the Cyclotron are fakes."""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

import test_monitoring_router as tr  # noqa: E402
from ideas_fixtures import NOW, reference  # noqa: E402
from papyrus_content.auto_accept import validate_auto_accept  # noqa: E402
from papyrus_content.monitoring_cloud import DynamoStore, run_collection  # noqa: E402
from papyrus_content.monitoring_router import CyclotronClient, run_router, validate_router_config  # noqa: E402
from papyrus_content.reference_vote import latest_vote  # noqa: E402
from papyrus_content.relevance_decisions import human_label_for_review  # noqa: E402
from test_monitor_stories import decision, provenance  # noqa: E402

CORPUS = "knowledge-corpus-anth-us"
EDITOR = "user:sub-1"


class AutoClient:
    """A publication's backend: References, their Cyclotron verdicts, and the writes an automatic acceptance makes."""

    def __init__(self):
        self.rows, self.relations, self.messages, self.written, self.incoming = {}, {}, [], [], {}

    def list_semantic_relations_by_object_state(self, key):
        return list(self.incoming.get(key.split("#")[1], []))

    def list_by_index(self, index, key):
        assert index == "referencesByCurationStatusKey", index
        return [dict(row) for row in self.rows.values() if f"{row['corpusId']}#{row['curationStatus']}" == key]

    def list_semantic_relations_by_subject_state(self, key):
        return list(self.relations.get(key.split("#")[1], []))

    def get_record(self, model, record_id):
        assert model == "Reference"
        row = self.rows.get(record_id)
        return dict(row) if row else None

    def update_record(self, model, payload):
        self.written.append((model, payload))
        self.rows[payload["id"]].update(payload)

    def upsert(self, model, payload):
        self.written.append((model, payload))
        if model == "Message":
            self.messages.append(payload)
        return "created"


def world(context):
    return context.auto


def add(context, *, status, actor, verdict, created_days_ago, voted_after_days=None, label="include"):
    held = world(context)
    number = len(held.client.rows) + 1
    row = reference(number, status=status, days_ago=created_days_ago, corpus=CORPUS)
    row["curationStatusUpdatedBy"] = actor
    if voted_after_days is not None:
        created = datetime.fromisoformat(row["createdAt"].replace("Z", "+00:00"))
        row["curationStatusUpdatedAt"] = (created + timedelta(days=voted_after_days)).isoformat().replace("+00:00", "Z")
    held.client.rows[row["id"]] = row
    held.client.relations[row["lineageId"]] = [decision(row, verdict, label)]
    return row


@given('a router with the publication "{publication}" and no autoAccept setting')
def step_router(context, publication):
    table = tr.FakeTable()
    table.put_item(tr.COLLECTOR_CONFIG)
    run_collection(DynamoStore(table), "hn", fetch=lambda url: tr.FEED, now=1000)
    store, cyclotron = tr.setup_router(table)
    context.auto = type("State", (), {"table": table, "store": store, "cyclotron": cyclotron, "client": AutoClient(), "lines": [], "target": None})()


@given("the publication's autoAccept setting is {setting}")
def step_setting(context, setting):
    held = world(context)
    config = held.table.get_item({"pk": "MONITOR#hn", "sk": "CONFIG#router"})["Item"]
    config["publications"][0]["autoAccept"] = json.loads(setting)
    held.table.put_item(config)


@given("the editors accepted {count:d} References the Cyclotron was {percent:d}% sure were relevant, each within {days:d} days")
def step_accepted(context, count, percent, days):
    for _ in range(count):
        add(context, status="accepted", actor=EDITOR, verdict=percent / 100, created_days_ago=20, voted_after_days=days)


@given("the editors rejected {count:d} References the Cyclotron was {percent:d}% sure were relevant, each within {days:d} days")
def step_rejected(context, count, percent, days):
    for _ in range(count):
        add(context, status="rejected", actor=EDITOR, verdict=percent / 100, created_days_ago=20, voted_after_days=days)


@given("the Cyclotron accepted {count:d} more References automatically that it was {percent:d}% sure about")
def step_auto_voted(context, count, percent):
    for _ in range(count):
        add(context, status="accepted", actor="auto:cyclotron", verdict=percent / 100, created_days_ago=20, voted_after_days=15)


@given("a pending Reference delivered {days:d} days ago that the Cyclotron judged {judged} with {percent:d}% confidence")
@given("a pending Reference delivered {days:d} day ago that the Cyclotron judged {judged} with {percent:d}% confidence")
def step_pending(context, days, judged, percent):
    label = "include" if judged == "relevant" else "exclude"
    world(context).target = add(context, status="pending", actor="papyrus-monitoring-worker", verdict=percent / 100, created_days_ago=days, label=label)


@given("an editor reopened that Reference")
def step_reopened(context):
    world(context).client.rows[world(context).target["id"]]["curationStatusUpdatedBy"] = "editor@example.test"


@when("the router runs its automatic acceptance")
def step_run(context):
    held = world(context)
    config = validate_router_config(held.table.get_item({"pk": "MONITOR#hn", "sk": "CONFIG#router"})["Item"])
    cyclotron = CyclotronClient(config, sign=lambda m, u, b: {}, http=held.cyclotron.http, sleep=lambda s: None, clock=lambda: 0)
    out = io.StringIO()
    with redirect_stdout(out):
        held.result = run_router(held.store, "hn", now=NOW.timestamp(), task="auto-accept", cyclotron=cyclotron,
                                 appsync=lambda endpoint: held.client, deliver=tr.Delivery())
    held.lines = [json.loads(line) for line in out.getvalue().splitlines() if line.startswith('{"autoAccept"')]


def target_row(context):
    held = world(context)
    return held.client.rows[held.target["id"]]


def line_for(context, publication):
    lines = [line for line in world(context).lines if line["publicationId"] == publication]
    assert len(lines) == 1, (publication, world(context).lines)
    return lines[0]


@then('the Reference is accepted by "{actor}"')
def step_accepted_by(context, actor):
    row = target_row(context)
    assert (row["curationStatus"], row["curationStatusUpdatedBy"]) == ("accepted", actor), row
    assert row["curationStatusKey"] == f"{CORPUS}#accepted" and row["curationStatusUpdatedAt"], row


@then("the Reference stays pending")
def step_pending_still(context):
    assert target_row(context)["curationStatus"] == "pending", target_row(context)
    assert not world(context).client.written


@then("its reason names the {confidence}% confidence, the {threshold}% threshold, the {votes:d} votes and the {days:d} day delay")
def step_reason(context, confidence, threshold, votes, days):
    reason = target_row(context)["curationStatusReason"]
    for fact in (f"{confidence}.0% sure", f"{threshold}.0%", f"{votes} editor votes", f"{days}.0 days", "95% lower bound", "estimated accept rate"):
        assert fact in reason, (fact, reason)


@then('the log line for "{publication}" says status "{status}", threshold {threshold:f}, candidates {candidates:d} and accepted {accepted:d}')
def step_log(context, publication, status, threshold, candidates, accepted):
    line = line_for(context, publication)
    assert (line["status"], line["threshold"], line["candidates"], line["accepted"]) == (status, threshold, candidates, accepted), line
    assert line["autoAccept"] == status and line["delaySeconds"] and line["precisionLowerBound"] and line["targetPrecision"] == 0.9, line


@then('the log line for "{publication}" says status "{status}" because "{reason}"')
def step_log_reason(context, publication, status, reason):
    line = line_for(context, publication)
    assert line["status"] == status and reason in line["reason"], line
    assert line["accepted"] == 0 and line["threshold"] is None, line


@then("the log line counts {votes:d} votes")
def step_votes(context, votes):
    assert line_for(context, "anth-us")["votes"] == votes


@then('there is no log line for "{publication}"')
def step_no_line(context, publication):
    assert [line for line in world(context).lines if line["publicationId"] == publication] == []


@then("the autoAccept setting {setting} is accepted as written")
def step_valid(context, setting):
    expected = {"enabled": True, "precision": 0.9, "latencyQuantile": 0.9, **json.loads(setting)}
    assert validate_auto_accept("anth-us", json.loads(setting)) == expected


@then("the autoAccept setting {setting} is refused")
def step_invalid(context, setting):
    try:
        validate_auto_accept("anth-us", json.loads(setting))
    except ValueError:
        return
    raise AssertionError(f"{setting} was accepted")


@then("the Reference records an automatic accept by the Cyclotron that is not a human label and no Message is written")
def step_message(context):
    assert not world(context).client.messages
    row = target_row(context)
    vote = latest_vote(row)
    assert (vote["actorKind"], vote["action"]) == ("cyclotron", "accept"), vote
    assert human_label_for_review(row, labels=["include", "exclude"]) is None


# --- monitors that deliver by a fixed rule -----------------------------------------------------------------------------------------


@given("the monitor delivers by a fixed rule that takes every collected item")
def step_direct(context):
    held = world(context)
    config = held.table.get_item({"pk": "MONITOR#hn", "sk": "CONFIG#router"})["Item"]
    config.update(decisions="direct", cyclotron=None)
    config.pop("rule", None)
    held.table.put_item(config)


@given('a pending Reference the router is about to deliver for "{publication}"')
def step_to_deliver(context, publication):
    held = world(context)
    identifier = f"reference-{publication}-101"
    held.target = {"id": identifier, "lineageId": identifier, "versionState": "current", "corpusId": f"knowledge-corpus-{publication}",
                   "title": "A delivered item", "curationStatus": "pending", "curationStatusUpdatedBy": "papyrus-monitoring-worker",
                   "createdAt": "2027-01-14T00:00:00Z"}
    held.client.rows[identifier] = held.target


@when("the router delivers the item")
def step_deliver(context):
    held = world(context)
    out = io.StringIO()
    with redirect_stdout(out):
        held.result = tr.go(held.table, held.store, None, now=2000, deliver=tr.Delivery(), appsync=lambda endpoint: held.client)
    held.lines = [json.loads(line) for line in out.getvalue().splitlines() if line.startswith('{"autoAccept"')]


@then('its reason names the monitor "{monitor}" and the rule "{rule}"')
def step_rule_reason(context, monitor, rule):
    reason = target_row(context)["curationStatusReason"]
    assert f"{monitor} monitor's rule ({rule})" in reason and "no relevance prediction" in reason, reason


@then("the Reference records an automatic accept by the rule that is not a human label and no Message is written")
def step_rule_message(context):
    assert not world(context).client.messages
    row = target_row(context)
    vote = latest_vote(row)
    assert (vote["actorKind"], vote["action"]) == ("rule", "accept"), vote
    assert human_label_for_review(row, labels=["include", "exclude"]) is None


def site_client(context, site):
    held = world(context)
    held.site, held.corpus = site, f"knowledge-corpus-{site}"
    held.client = AutoClient()
    return held


def delivered(held, monitor, verdict=None):
    number = len(held.client.rows) + 1
    row = reference(number, status="pending", days_ago=3, corpus=held.corpus)
    row["curationStatusUpdatedBy"] = "papyrus-monitoring-worker"
    held.client.rows[row["id"]] = row
    held.client.incoming[row["lineageId"]] = [provenance(row, monitor)]
    held.client.relations[row["lineageId"]] = [decision(row, verdict)] if verdict is not None else []
    return row


@given('the site "{site}" whose monitor "{monitor}" delivered {count:d} pending References by its rule')
def step_rule_site(context, site, monitor, count):
    held = site_client(context, site)
    for _ in range(count):
        delivered(held, monitor)


@given("an editor already rejected one of them")
def step_editor_rejected(context):
    row = next(iter(world(context).client.rows.values()))
    row.update(curationStatus="rejected", curationStatusUpdatedBy="editor@example.test")
    world(context).rejected = row["id"]


@given('the monitor "{monitor}" delivered {count:d} pending References the Cyclotron judged relevant')
def step_judged_site(context, monitor, count):
    for _ in range(count):
        delivered(world(context), monitor, verdict=0.97)


def run_cli(context, flags):
    from papyrus_content.references_commands import references_auto_accept
    held = world(context)
    out = io.StringIO()
    with mock.patch("papyrus_content.references_commands.create_authoring_client", return_value=(held.client, None)), redirect_stdout(out):
        references_auto_accept(flags)
    held.cli = [json.loads(line) for line in out.getvalue().splitlines() if line.startswith('{"autoAccept"')]
    held.backfill = next(line for line in held.cli if line["autoAccept"] == "rule-backfill")


@when('the operator runs references auto-accept for "{site}" as a dry run')
def step_cli_dry(context, site):
    run_cli(context, ["--site", site, "--dry-run"])


@when('the operator runs references auto-accept for "{site}"')
def step_cli(context, site):
    run_cli(context, ["--site", site])


@then('the backfill lists {count:d} deliveries from "{monitor}" and nothing was written')
def step_backfill_listed(context, count, monitor):
    held = world(context)
    assert held.backfill["dryRun"] and held.backfill["candidates"] == count and held.backfill["accepted"] == 0, held.backfill
    assert {entry["monitorId"] for entry in held.backfill["references"]} == {monitor}, held.backfill["references"][:2]
    assert held.client.written == [] and all(row["curationStatus"] != "accepted" for row in held.client.rows.values())


@then('{count:d} deliveries are accepted by "{actor}" and the editor\'s Reject stands')
def step_backfill_done(context, count, actor):
    held = world(context)
    accepted = [row for row in held.client.rows.values() if row["curationStatus"] == "accepted"]
    assert len(accepted) == count and all(row["curationStatusUpdatedBy"] == actor for row in accepted), len(accepted)
    assert held.client.rows[held.rejected]["curationStatus"] == "rejected"
    assert held.backfill["accepted"] == count
