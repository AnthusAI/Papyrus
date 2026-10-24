"""The Monitoring page's read path: scoping, permissions, usage, empty and error states, read-only access."""
import json

import pytest

import monitoring_view_fixture as fx
from papyrus_content import monitoring_view as mv
from papyrus_content.monitoring_view import Forbidden, monitoring_overview


def overview(groups=("editor",), endpoint=fx.APP_ANTH, scope="publication", store=None):
    return monitoring_overview(store or fx.FakeViewStore(), groups=list(groups), site_endpoint=endpoint, scope=scope, now=fx.NOW)


def test_editor_overview_is_scoped_to_the_viewing_publication():
    result = overview()
    assert result["scope"] == {"mode": "publication", "publicationId": "anth-us", "site": "anth.us", "canViewAll": False}
    titles = [i["title"] for i in result["items"]]
    assert titles == ["Fresh Show HN", "Broken request", "Quantum paper on arXiv", "Phishing kit leaks"]
    assert result["hiddenNotRelevant"] == 1
    undecided = next(i for i in result["items"] if i["title"] == "Fresh Show HN")
    assert undecided["routing"] == "collected" and undecided["relevance"][0]["relevant"] is None
    broken = next(i for i in result["items"] if i["title"] == "Broken request")
    assert broken["routing"] == "error" and "bad title" in broken["routingNote"]


def test_items_are_newest_first_by_observation():
    observed = [i["observedAt"] for i in overview(groups=("admin",), scope="all")["items"]]
    assert observed == sorted(observed, reverse=True)


def test_admin_sees_every_publication_and_may_scope_down():
    everything = overview(groups=("admin",), scope="all")
    assert everything["scope"]["mode"] == "all" and everything["scope"]["canViewAll"] is True
    assert len(everything["items"]) == 5 and everything["hiddenNotRelevant"] == 0
    own = overview(groups=("admin",), scope="publication")
    assert own["scope"]["mode"] == "publication" and own["scope"]["canViewAll"] is True


def test_confidence_and_delivery_states():
    result = overview(groups=("admin",), scope="all")
    quantum = next(i for i in result["items"] if i["title"] == "Quantum paper on arXiv")
    by_pub = {r["publicationId"]: r for r in quantum["relevance"]}
    assert by_pub["anth-us"]["confidence"] == 0.91 and by_pub["anth-us"]["delivery"]["state"] == "delivered"
    assert by_pub["p-apyr-us"]["relevant"] is False and by_pub["p-apyr-us"]["delivery"]["state"] == "not_applicable"
    assert by_pub["threat-intelligence"]["confidence"] is None and by_pub["threat-intelligence"]["delivery"]["referenceId"] == "ref-2"


@pytest.mark.parametrize("groups", [[], ["reader"], ["guest"], ["viewer", "author"]])
def test_only_editors_and_admins_may_read(groups):
    with pytest.raises(Forbidden):
        overview(groups=groups)


def test_editor_may_not_ask_for_the_whole_pipeline():
    with pytest.raises(Forbidden):
        overview(groups=("editor",), scope="all")


def test_unknown_scope_is_refused_as_bad_request():
    with pytest.raises(ValueError):
        overview(scope="everything")


def test_usage_counts_decisions_by_utc_day_against_configured_ceilings():
    usage = overview()["usage"]
    assert (usage["decisionsToday"], usage["decisionsTotal"], usage["day"]) == (2, 3, "2026-10-21")
    assert usage["ceilings"] == {"decisionsTotal": 300, "decisionsPerDay": 100, "items": 300}


def test_no_ceilings_configured_still_reports_usage():
    table = [r for r in fx.rows() if r["sk"] != "CONFIG#router"]
    router = next(r for r in fx.rows() if r["sk"] == "CONFIG#router")
    router.pop("ceilings")
    result = overview(store=fx.FakeViewStore(table + [router]))
    assert result["usage"]["ceilings"] is None and result["usage"]["decisionsTotal"] == 3


def test_publication_outside_the_router_gets_a_notice_not_data_about_others():
    result = overview(endpoint="https://other.appsync-api.us-east-1.amazonaws.com/graphql")
    assert result["scope"]["publicationId"] is None and result["notice"] == "publication_not_routed"
    assert all(i["relevance"] == [] for i in result["items"]) and len(result["items"]) == 5


def test_empty_table_is_an_empty_state():
    result = overview(store=fx.FakeViewStore([]))
    assert result["state"] == "empty" and result["feeds"] == [] and result["runs"] == [] and result["items"] == []
    assert result["router"] is None


def test_router_runs_and_dry_run_modes_are_reported():
    result = overview()
    run = result["routerRuns"][0]
    assert run["status"] == "stopped" and run["counts"]["decided"] == 1 and run["feedback"]["sent"] == 1
    assert result["router"] == {"mode": "live", "feedback": True, "enabled": True, "maxItemsPerRun": 5}


def test_response_is_json_and_leaks_nothing_private():
    text = json.dumps(overview(groups=("admin",), scope="all"))
    for marker in fx.SECRET_MARKERS:
        assert marker not in text


# --- the Lambda boundary ------------------------------------------------------------------------

class ReadOnlyTable:
    """A table that has only the two read calls the grant allows; anything else raises AttributeError."""

    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def get_item(self, Key, ConsistentRead=False):
        self.calls.append("get_item")
        row = next((r for r in self.rows if (r["pk"], r["sk"]) == (Key["pk"], Key["sk"])), None)
        return {"Item": row} if row else {}

    def query(self, **kwargs):
        self.calls.append("query")
        prefix = kwargs["ExpressionAttributeValues"][":prefix"]
        rows = sorted((r for r in self.rows if r["sk"].startswith(prefix)), key=lambda r: r["sk"], reverse=not kwargs.get("ScanIndexForward", True))
        if "Limit" in kwargs:
            rows = rows[: kwargs["Limit"]]
        return {"Items": rows}


def test_table_store_uses_only_get_item_and_query():
    table = ReadOnlyTable(fx.rows())
    result = monitoring_overview(mv.TableViewStore(table), groups=["admin"], site_endpoint=fx.APP_ANTH, scope="all", now=fx.NOW)
    assert len(result["items"]) == 5 and set(table.calls) == {"get_item", "query"}


def event(groups, scope="publication", field="monitoringOverview", **arguments):
    return {"info": {"fieldName": field}, "arguments": {"scope": scope, **arguments},
            "identity": {"groups": groups, "sub": "u1"}}


def test_handler_refuses_non_editors_before_touching_the_table():
    opened = []
    out = mv.handle(event(["reader"]), env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.APP_ANTH}, store_factory=lambda: opened.append(1))
    assert out["error"] == "forbidden" and opened == []


def test_handler_reports_not_configured_when_the_table_is_unknown():
    out = mv.handle(event(["editor"]), env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.APP_ANTH}, store_factory=lambda: None)
    assert out == {"state": "not_configured"}


def test_handler_returns_unavailable_when_the_read_fails():
    class Broken:
        def get(self, sk):
            raise RuntimeError("AccessDeniedException secret-table-detail")
    out = mv.handle(event(["editor"]), env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.APP_ANTH}, store_factory=lambda: Broken())
    assert out == {"state": "unavailable"}


def test_handler_serves_an_editor_from_the_site_endpoint():
    out = mv.handle(event(["editor"]), env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.APP_ANTH}, store_factory=lambda: fx.FakeViewStore())
    assert out["state"] == "ready" and out["scope"]["publicationId"] == "anth-us"


def test_handler_accepts_cognito_group_claims_as_a_list_only():
    out = mv.handle({**event(["editor"]), "identity": {"groups": None}}, env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.APP_ANTH}, store_factory=lambda: fx.FakeViewStore())
    assert out["error"] == "forbidden"


def test_router_run_reports_publications_waiting_for_classifier():
    from papyrus_content.monitoring_view import _router_run
    run = _router_run({"runId": "r", "status": "complete", "waitingForClassifier": ["data-parade"]})
    assert run["waitingForClassifier"] == ["data-parade"]
    assert _router_run({"runId": "r"})["waitingForClassifier"] == []


def email_rows(destination=("anth-us",)):
    receipt_id = "EMAIL#" + "a" * 64
    return [
        {"pk": fx.PK, "sk": "EMAILINDEX#2026-10-21T02:30:00Z#" + "a" * 64,
         "receiptId": receipt_id, "destinationPublicationIds": list(destination)},
        {"pk": fx.PK, "sk": receipt_id, "status": "queued", "emailTrustMode": "data-only",
         "emailDestinationPublicationIds": list(destination), "observedAt": "2026-10-21T02:30:00Z",
         "subject": "Newsletter", "sender": "envelope@example.net", "headerFrom": "forged@example.net",
         "warnings": ["ses_authentication_unverified"], "linkCount": 2, "processedCount": 2,
         "sesDiagnostics": {"verdicts": {"spf": "FAIL", "dkim": "PASS", "dmarc": "FAIL", "spam": "PASS", "virus": "PASS"}}},
        {"pk": fx.PK, "sk": "EMAILDETAIL#" + "a" * 64 + "#BODY#0000", "text": "Read as plain text\n", "ttl": 123},
        {"pk": fx.PK, "sk": "EMAILDETAIL#" + "a" * 64 + "#LINKS#0000",
         "json": '[{"url":"https://example.org/article","title":"Article"}]', "ttl": 123},
    ]


def test_email_submission_list_is_scoped_to_this_publication_and_contains_signals():
    store = fx.FakeViewStore(fx.rows() + email_rows())
    result = overview(store=store)
    assert len(result["emailSubmissions"]) == 1
    item = result["emailSubmissions"][0]
    assert item["subject"] == "Newsletter" and item["linkCount"] == 2
    assert item["verdicts"]["spf"] == "FAIL" and item["warnings"] == ["ses_authentication_unverified"]
    assert "https://example.org/article" not in json.dumps(result)


def test_email_submission_details_are_editor_only_and_publication_scoped():
    store = fx.FakeViewStore(fx.rows() + email_rows())
    receipt_id = "EMAIL#" + "a" * 64
    event = {"info": {"fieldName": "monitoringEmailSubmission"}, "arguments": {"receiptId": receipt_id},
             "identity": {"groups": ["editor"]}}
    result = mv.handle(event, env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.APP_ANTH}, store_factory=lambda: store)
    assert result["safeBodyText"] == "Read as plain text\n"
    assert result["candidateLinks"] == [{"url": "https://example.org/article", "title": "Article"}]
    assert result["sourceMaterialIsUntrusted"] is True
    denied = mv.handle(event, env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.APP_PAPYRUS}, store_factory=lambda: store)
    assert denied == {"error": "forbidden"}
    refused = mv.handle({**event, "identity": {"groups": ["reader"]}},
                        env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.APP_ANTH}, store_factory=lambda: store)
    assert refused == {"error": "forbidden"}
