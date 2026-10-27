"""TTAB Reading Room monitor: the JSON search source, collection, and direct routing without a Cyclotron."""
import json

import pytest

from papyrus_content import monitoring_intake, monitoring_router as mr
from papyrus_content.monitoring import TTAB_DECISIONS_URL, parse_ttab_decisions, ttab_document_aliases, ttab_search_body
from papyrus_content.monitoring_cloud import DynamoStore, _validate_config, run_collection
from papyrus_content.monitoring_router import RouterStore, run_router, validate_router_config

from test_monitoring_router import ENDPOINT, Delivery, FakeTable

DAY = 86400
NOW = 1792540800  # 2026-10-21T00:00:00Z


def decision(document, proceeding, party, outcome, *, category="Final Decision", precedential="N", issued=1791432000000, kind="OPP"):
    return {"documentId": document, "proceedingNumber": proceeding, "partyName": party, "decision": outcome,
            "decisionTypeCategory": category, "precedentCitableIndicator": precedential, "issueDate": issued,
            "proceedingTypeCd": kind}


def search_response(*rows):
    return json.dumps({"results": list(rows), "recordTotalQuantity": len(rows)}).encode()


WEMBY = decision("/legal-proceeding/97752244/decision/EXA_26.pdf", 97752244, "Wemby Corporation",
                 "Refusal Affirmed (on both grounds)", kind="EXA")
OVERLAND = decision("/legal-proceeding/92082396/decision/CAN_53.pdf", 92082396,
                    "Overland Sheepskin Company v. Storyteller Overland, LLC", "Petition to Cancel Granted", kind="CAN")
RECONSIDERATION = decision("/legal-proceeding/99176400/decision/EXA_15.pdf", 99176400, "Learn 2 Read Read 2 Learn LLC",
                           "Request for Reconsideration of Final Decision Denied", category="Request for Reconsideration", kind="EXA")
TTAB_CONFIG = {"pk": "MONITOR#ttab", "sk": "CONFIG", "sourceType": "ttab-decisions", "sourceUrl": TTAB_DECISIONS_URL,
               "intervalSeconds": DAY, "limit": 100, "lookbackDays": 30, "enabled": True}
DISTINCTIVE = {"publicationId": "distinctive", "site": "distinctive-mark.com", "appsyncEndpoint": ENDPOINT}


def direct_router_config(mode="live", **overrides):
    return {"pk": "MONITOR#ttab", "sk": "CONFIG#router", "mode": mode, "decisions": "direct",
            "publications": [DISTINCTIVE], **overrides}


# --- the source --------------------------------------------------------------------------------------

def test_final_decisions_become_items_with_stable_ids_pdf_links_and_proceeding_pages():
    items = parse_ttab_decisions(search_response(WEMBY, RECONSIDERATION, OVERLAND))

    assert [item.source_id for item in items] == ["97752244-EXA_26", "92082396-CAN_53"]
    wemby = items[0]
    assert wemby.title == "Wemby Corporation: Refusal Affirmed (on both grounds)"
    assert wemby.canonical_url == "https://ttab-reading-room.uspto.gov/ttab-document/legal-proceeding/97752244/decision/EXA_26.pdf"
    assert wemby.source_item_url == "https://ttabvue.uspto.gov/ttabvue/v?pno=97752244&pty=EXA"
    assert wemby.media_type == "application/pdf"
    assert wemby.published_at.startswith("2026-")


def test_a_redesignation_as_precedential_changes_the_fingerprint():
    before = parse_ttab_decisions(search_response(WEMBY))[0]
    after = parse_ttab_decisions(search_response({**WEMBY, "precedentCitableIndicator": "Y"}))[0]

    assert after.title.endswith("[precedential]")
    assert before.source_id == after.source_id and before.fingerprint != after.fingerprint


def test_every_decision_type_is_kept_when_final_decisions_only_is_off():
    items = parse_ttab_decisions(search_response(WEMBY, RECONSIDERATION), final_decisions_only=False)

    assert [item.source_id for item in items] == ["97752244-EXA_26", "99176400-EXA_15"]


@pytest.mark.parametrize("body", [b"<html>maintenance</html>", json.dumps({"error": "x"}).encode(),
                                  search_response({**WEMBY, "documentId": "not-a-document"})])
def test_error_pages_and_malformed_decisions_are_refused(body):
    with pytest.raises(ValueError):
        parse_ttab_decisions(body)


def test_search_body_filters_on_decision_date_and_sorts_on_issue_date():
    body = json.loads(ttab_search_body(NOW, 30, 100))

    assert body["dateRangeData"]["decisionDate"] == {"from": "2026-09-21", "to": "2026-10-21"}
    assert body["sortDataBag"] == [{"issueDate": "desc"}]
    assert body["recordTotalQuantity"] == 100


def test_a_decision_lists_its_other_addresses_for_matching_earlier_references():
    assert ttab_document_aliases("/legal-proceeding/91287216/decision/OPP_17.pdf") == (
        "https://ttab-reading-room.uspto.gov/ttab-document//legal-proceeding/91287216/decision/OPP_17.pdf",
        "https://ttabvue.uspto.gov/ttabvue/ttabvue-91287216-OPP-17.pdf")
    assert parse_ttab_decisions(search_response(WEMBY))[0].aliases[1] == "https://ttabvue.uspto.gov/ttabvue/ttabvue-97752244-EXA-26.pdf"


def test_the_precedential_recheck_asks_only_for_precedential_decisions_over_its_own_window():
    body = json.loads(ttab_search_body(NOW, 180, 100, precedential_only=True))

    assert body["parameterData"] == {"precedentCitableIndicator": "Y"}
    assert body["dateRangeData"]["decisionDate"]["from"] == "2026-04-24"


# --- collection --------------------------------------------------------------------------------------

@pytest.mark.parametrize("change, message", [
    ({"precedentialLookbackDays": 20}, "precedentialLookbackDays"),
    ({"precedentialLookbackDays": 400}, "precedentialLookbackDays"),
    ({"sourceUrl": "https://news.ycombinator.com/rss"}, "ttab-reading-room.uspto.gov"),
    ({"sourceType": "carrier-pigeon"}, "sourceType"),
    ({"lookbackDays": 400}, "lookbackDays")])
def test_ttab_config_is_validated_for_its_own_source(change, message):
    with pytest.raises(ValueError, match=message):
        _validate_config({**TTAB_CONFIG, **change})


def test_collection_posts_the_search_and_records_pdf_discoveries():
    table, requests = FakeTable(), []
    table.put_item(TTAB_CONFIG)

    def fetch(url, body):
        requests.append((url, json.loads(body)))
        return search_response(WEMBY, RECONSIDERATION, OVERLAND)

    result = run_collection(DynamoStore(table), "ttab", fetch=fetch, now=NOW)

    assert result["status"] == "complete" and result["new"] == 2
    assert requests[0][0] == TTAB_DECISIONS_URL and requests[0][1]["sortDataBag"] == [{"issueDate": "desc"}]
    discovery = table.by_prefix("DISC#97752244-EXA_26#")[0]
    assert discovery["mediaType"] == "application/pdf" and discovery["routing"] == "collected"
    assert discovery["gsi1pk"] == "ROUTING#ttab#collected"


def test_the_recheck_brings_in_older_precedential_decisions_and_orders_on_motions():
    table, requests = FakeTable(), []
    table.put_item({**TTAB_CONFIG, "precedentialLookbackDays": 180})
    motion = decision("/legal-proceeding/92063134/decision/CAN_107.pdf", 92063134, "Philip Morris USA Inc. v. IP Services",
                      "Motion to Dismiss Denied", category="Decision on Motion", precedential="Y", kind="CAN")
    older = {**WEMBY, "precedentCitableIndicator": "Y"}

    def fetch(url, body):
        payload = json.loads(body)
        requests.append(payload["parameterData"])
        return search_response(older, motion, motion) if payload["parameterData"] else search_response(OVERLAND, RECONSIDERATION)

    result = run_collection(DynamoStore(table), "ttab", fetch=fetch, now=NOW)

    assert requests == [{}, {"precedentCitableIndicator": "Y"}]
    assert result["new"] == 3
    assert table.by_prefix("DISC#92063134-CAN_107#")[0]["title"].endswith("[precedential]")
    assert table.by_prefix("DISC#97752244-EXA_26#")[0]["aliases"][1] == "https://ttabvue.uspto.gov/ttabvue/ttabvue-97752244-EXA-26.pdf"


def test_a_later_redesignation_is_collected_as_a_new_revision():
    table = FakeTable()
    table.put_item(TTAB_CONFIG)
    run_collection(DynamoStore(table), "ttab", fetch=lambda url, body: search_response(WEMBY), now=NOW)
    later = run_collection(DynamoStore(table), "ttab", fetch=lambda url, body: search_response({**WEMBY, "precedentCitableIndicator": "Y"}),
                           now=NOW + 2 * DAY)

    assert later["revised"] == 1
    assert [row["sk"] for row in table.by_prefix("DISC#97752244-EXA_26#")] == ["DISC#97752244-EXA_26#000001", "DISC#97752244-EXA_26#000002"]


# --- direct routing ----------------------------------------------------------------------------------

def collected_table():
    table = FakeTable()
    table.put_item(TTAB_CONFIG)
    run_collection(DynamoStore(table), "ttab", fetch=lambda url, body: search_response(WEMBY, OVERLAND), now=NOW)
    return table


def test_direct_config_needs_no_cyclotron_and_refuses_feedback():
    config = validate_router_config(direct_router_config())
    assert config["decisions"] == "direct" and config["cyclotron"] is None and config["feedback"] is False
    with pytest.raises(ValueError, match="feedback"):
        validate_router_config(direct_router_config(feedback=True))
    with pytest.raises(ValueError, match="decisions"):
        validate_router_config(direct_router_config(decisions="coin-flip"))


def test_direct_dry_run_records_what_it_would_deliver_without_writing():
    table, delivery = collected_table(), Delivery()
    table.put_item(direct_router_config(mode="dry-run"))

    result = run_router(RouterStore(table), "ttab", now=NOW + 60, cyclotron=None, deliver=delivery,
                        appsync=lambda endpoint: object(),
                        context_receipt=lambda client, publication: {"contextHash": "h", "reason": None})

    assert result["counts"]["dryRunValidated"] == 2 and delivery.calls == []
    route = table.by_prefix("ROUTE#97752244-EXA_26#")[0]
    assert route["dryRun"]["requests"]["distinctive"] == {"direct": True, "wouldDeliver": True}


def test_direct_live_delivers_every_item_once_and_queues_no_feedback():
    table, delivery = collected_table(), Delivery()
    table.put_item(direct_router_config())

    def run(now):
        return run_router(RouterStore(table), "ttab", now=now, cyclotron=None, deliver=delivery,
                          appsync=lambda endpoint: object(),
                          context_receipt=lambda client, publication: {"contextHash": "h", "reason": None})

    first, second = run(NOW + 60), run(NOW + 120)

    assert first["counts"]["routed"] == 2 and second["counts"]["examined"] == 0
    assert sorted(call[:2] for call in delivery.calls) == [("distinctive", "92082396-CAN_53"), ("distinctive", "97752244-EXA_26")]
    route = table.by_prefix("ROUTE#97752244-EXA_26#")[0]
    assert route["decision"]["system"] == "direct" and route["itemId"] == "ttab-97752244-EXA_26"
    assert all("gsi1pk" not in row for row in table.by_prefix("DELIV#"))


def test_direct_delivery_records_the_monitor_rule_and_the_pdf(monkeypatch):
    captured, real_intake = {}, monitoring_intake.ReferenceIntake

    class RecordingIntake:
        def __init__(self, client, monitor, *, auth_mode):
            captured["monitor"] = monitor

        def __call__(self, item, provenance):
            captured.update(item=item, provenance=provenance)
            return {"referenceId": "reference-1", "referenceLineageId": "reference", "provenanceMessageId": "m"}

    monkeypatch.setattr(monitoring_intake, "ReferenceIntake", RecordingIntake)
    table = collected_table()
    disc = table.by_prefix("DISC#97752244-EXA_26#")[0]
    config = validate_router_config(direct_router_config())
    publication = config["publications"][0]

    mr.deliver_reference(object(), publication, DynamoStore._clean(disc),
                         {"decisionId": "direct-ttab-97752244-EXA_26-000001", "output": "ttab-direct", "label": "include"}, config)

    assert captured["monitor"].id == "ttab" and captured["monitor"].source_name == "TTAB Reading Room"
    assert captured["monitor"].binding["sourceUrl"] == TTAB_DECISIONS_URL
    assert captured["item"].media_type == "application/pdf"
    assert captured["provenance"]["machineDecision"]["system"] == "direct"
    note = real_intake._machine_decision_note(captured["provenance"])
    assert "no machine relevance decision" in note
