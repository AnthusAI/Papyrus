"""The Monitoring page's read path: scoping, permissions, usage, empty and error states, read-only access."""
import json
import io
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import monitoring_view_fixture as fx
from papyrus_content import monitoring_view as mv
from papyrus_content.monitoring_view import Forbidden, monitoring_overview


def overview(groups=("editor",), endpoint=fx.APP_ANTH, scope="publication", store=None, email_store=None):
    return monitoring_overview(store or fx.FakeViewStore(), groups=list(groups), site_endpoint=endpoint,
                               scope=scope, now=fx.NOW, email_store=email_store)


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


def test_usage_counts_decisions_by_utc_day_without_showing_retired_ceilings():
    usage = overview()["usage"]
    assert (usage["decisionsToday"], usage["decisionsTotal"], usage["day"]) == (2, 3, "2026-10-21")
    assert "ceilings" not in usage


def test_legacy_ceilings_are_ignored_and_usage_is_still_reported():
    table = [r for r in fx.rows() if r["sk"] != "CONFIG#router"]
    router = next(r for r in fx.rows() if r["sk"] == "CONFIG#router")
    router["ceilings"] = {"decisionsTotal": 300, "decisionsPerDay": 100, "items": 300}
    result = overview(store=fx.FakeViewStore(table + [router]))
    assert "ceilings" not in result["usage"] and result["usage"]["decisionsTotal"] == 3


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


def test_bounded_decision_history_marks_truncated_counts_as_lower_bounds():
    class PagedTable:
        def __init__(self, pages):
            self.pages, self.calls = pages, 0

        def query(self, **_kwargs):
            index = self.calls
            self.calls += 1
            response = {"Items": [{"decision": {"decidedAt": "2026-10-21T12:00:00Z"}}]}
            if index < self.pages - 1:
                response["LastEvaluatedKey"] = {"pk": "MONITOR#hn", "sk": f"ROUTE#{index:06d}"}
            return response

    times, complete = mv.TableViewStore(PagedTable(mv.MAX_DECISION_PAGES + 1)).decision_times()
    assert len(times) == mv.MAX_DECISION_PAGES and not complete

    times, complete = mv.TableViewStore(PagedTable(3)).decision_times()
    assert len(times) == 3 and complete


def event(groups, scope="publication", field="monitoringOverview", **arguments):
    return {"info": {"fieldName": field}, "arguments": {"scope": scope, **arguments},
            "identity": {"groups": groups, "sub": "u1"}}


def test_handler_refuses_non_editors_before_touching_the_table():
    opened = []
    out = mv.handle(event(["reader"]), env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.APP_ANTH}, store_factory=lambda *_: opened.append(1))
    assert out["error"] == "forbidden" and opened == []


def test_handler_reports_not_configured_when_the_table_is_unknown():
    out = mv.handle(event(["editor"]), env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.APP_ANTH}, store_factory=lambda *_: None)
    assert out == {"state": "not_configured"}


def test_handler_returns_unavailable_when_the_read_fails():
    class Broken:
        def get(self, sk):
            raise RuntimeError("AccessDeniedException secret-table-detail")
    out = mv.handle(event(["editor"]), env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.APP_ANTH}, store_factory=lambda *_: Broken())
    assert out == {"state": "unavailable"}


def test_handler_serves_an_editor_from_the_site_endpoint():
    out = mv.handle(event(["editor"]), env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.APP_ANTH}, store_factory=fx.only_hn(fx.FakeViewStore()))
    assert out["state"] == "ready" and out["scope"]["publicationId"] == "anth-us"


def test_handler_accepts_cognito_group_claims_as_a_list_only():
    out = mv.handle({**event(["editor"]), "identity": {"groups": None}}, env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.APP_ANTH}, store_factory=fx.only_hn(fx.FakeViewStore()))
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


def test_email_submissions_can_use_the_receiver_partition_without_switching_the_main_monitor():
    email_pk = "MONITOR#p-apyr-us-email"
    main_store = fx.FakeViewStore(fx.rows())
    email_router = next(row for row in fx.rows() if row["sk"] == "CONFIG#router").copy()
    email_router["pk"] = email_pk
    email_table = [email_router, *email_rows(("p-apyr-us",))]
    for row in email_table:
        row["pk"] = email_pk
    email_store = fx.FakeViewStore(email_table)

    result = overview(endpoint=fx.APP_PAPYRUS, store=main_store, email_store=email_store)

    assert [item["subject"] for item in result["emailSubmissions"]] == ["Newsletter"]
    assert result["router"]["mode"] == "live"
    assert main_store.newest("EMAILINDEX#", 10) == []


def test_email_detail_uses_configured_receiver_partition_and_keeps_auth_checks():
    email_pk = "MONITOR#p-apyr-us-email"
    main_store = fx.FakeViewStore(fx.rows())
    email_router = next(row for row in fx.rows() if row["sk"] == "CONFIG#router").copy()
    email_router["pk"] = email_pk
    email_table = [email_router, *email_rows(("p-apyr-us",))]
    for row in email_table:
        row["pk"] = email_pk
    email_store = fx.FakeViewStore(email_table)
    receipt_id = "EMAIL#" + "a" * 64
    detail_event = event(["editor"], field="monitoringEmailSubmission", receiptId=receipt_id)
    env = {"PAPYRUS_GRAPHQL_ENDPOINT": fx.APP_PAPYRUS, "PAPYRUS_EMAIL_MONITOR_ID": "p-apyr-us-email"}

    result = mv.handle(detail_event, env=env, store_factory=lambda: main_store,
                       email_store_factory=lambda: email_store)

    assert result["safeBodyText"] == "Read as plain text\n"
    assert result["candidateLinks"] == [{"url": "https://example.org/article", "title": "Article"}]
    assert mv.configured_email_monitor_id(env) == "p-apyr-us-email"
    with pytest.raises(ValueError, match="invalid configured email monitor id"):
        mv.configured_email_monitor_id({"PAPYRUS_EMAIL_MONITOR_ID": "MONITOR#hn"})


def test_default_email_store_factory_uses_the_server_configured_partition(monkeypatch):
    class FakeSSM:
        class exceptions:
            class ParameterNotFound(Exception):
                pass

        def get_parameter(self, *, Name):
            assert Name == mv.TABLE_PARAMETER
            return {"Parameter": {"Value": "monitoring-table"}}

    table = object()
    fake_boto3 = SimpleNamespace(
        client=lambda service, **_kwargs: FakeSSM() if service == "ssm" else None,
        resource=lambda service, **_kwargs: SimpleNamespace(Table=lambda name: table if name == "monitoring-table" else None)
        if service == "dynamodb" else None,
    )
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    mv._table_name_cache.clear()
    try:
        store = mv.default_email_store_factory({"PAPYRUS_EMAIL_MONITOR_ID": "p-apyr-us-email"})()
    finally:
        mv._table_name_cache.clear()
    assert isinstance(store, mv.TableViewStore)
    assert store.pk == "MONITOR#p-apyr-us-email"


def test_email_submission_details_are_editor_only_and_publication_scoped():
    store = fx.FakeViewStore(fx.rows() + email_rows())
    receipt_id = "EMAIL#" + "a" * 64
    event = {"info": {"fieldName": "monitoringEmailSubmission"}, "arguments": {"receiptId": receipt_id},
             "identity": {"groups": ["editor"]}}
    result = mv.handle(event, env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.APP_ANTH}, store_factory=fx.only_hn(store))
    assert result["safeBodyText"] == "Read as plain text\n"
    assert result["candidateLinks"] == [{"url": "https://example.org/article", "title": "Article"}]
    assert result["sourceMaterialIsUntrusted"] is True


def test_email_article_redirect_resolution_is_an_explicit_scoped_editor_action():
    store = fx.FakeViewStore(fx.rows() + email_rows())
    receipt_id = "EMAIL#" + "a" * 64
    receipt = store.get(receipt_id)
    receipt["status"] = "pending_review"
    store.table[receipt_id] = receipt
    details_key = "EMAILDETAIL#" + "a" * 64 + "#LINKS#0000"
    store.table[details_key]["json"] = (
        '[{"url":"https://link.mail.beehiiv.com/ss/c/article-token",'
        '"title":"Story","resolutionStatus":"unresolved"}]'
    )
    calls = []
    event = {"info": {"fieldName": "monitoringResolveEmailArticleLink"},
             "arguments": {"receiptId": receipt_id, "candidateIndex": 0},
             "identity": {"groups": ["editor"]}}
    with patch.object(mv, "monitoring_email_resolve_article_link", return_value={"resolved": True}) as dispatched:
        result = mv.handle(event, env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.APP_ANTH}, store_factory=fx.only_hn(store))
    assert result == {"resolved": True} and dispatched.call_args.kwargs["candidate_index"] == 0

    result = mv.monitoring_email_resolve_article_link(
        store, groups=["editor"], site_endpoint=fx.APP_ANTH, receipt_id=receipt_id,
        candidate_index=0, resolver=lambda url: calls.append(url) or "https://news.example.org/story",
    )
    assert result == {"url": "https://news.example.org/story", "title": "Story", "resolved": True}
    assert calls == ["https://link.mail.beehiiv.com/ss/c/article-token"]
    assert store.get(f"EMAILRESOLVED#{'a' * 64}#000000")["sourceUri"] == "https://news.example.org/story"
    repeated = mv.monitoring_email_resolve_article_link(
        store, groups=["editor"], site_endpoint=fx.APP_ANTH, receipt_id=receipt_id,
        candidate_index=0, resolver=lambda url: calls.append("duplicate:" + url) or "https://wrong.example/",
    )
    assert repeated == result and calls == ["https://link.mail.beehiiv.com/ss/c/article-token"]


def test_email_redirect_resolver_never_follows_actions_or_out_of_scope_receipts():
    store = fx.FakeViewStore(fx.rows() + email_rows())
    receipt_id = "EMAIL#" + "a" * 64
    store.table[receipt_id]["status"] = "pending_review"
    store.table["EMAILDETAIL#" + "a" * 64 + "#LINKS#0000"]["json"] = (
        '[{"url":"https://link.mail.beehiiv.com/ss/c/unsubscribe?unsubscribe=true",'
        '"title":"Unsubscribe","resolutionStatus":"unresolved"}]'
    )
    calls = []
    result = mv.monitoring_email_resolve_article_link(
        store, groups=["editor"], site_endpoint=fx.APP_ANTH, receipt_id=receipt_id,
        candidate_index=0, resolver=lambda url: calls.append(url) or "https://news.example.org/story",
    )
    assert result == {"error": "not_resolvable"} and calls == []
    with pytest.raises(Forbidden):
        mv.monitoring_email_resolve_article_link(
            store, groups=["editor"], site_endpoint=fx.APP_PAPYRUS, receipt_id=receipt_id,
            candidate_index=0, resolver=lambda url: calls.append(url),
        )
    assert calls == []


def test_email_redirect_and_persistence_failures_remain_fail_closed():
    store = fx.FakeViewStore(fx.rows() + email_rows())
    receipt_id = "EMAIL#" + "a" * 64
    store.table[receipt_id]["status"] = "pending_review"
    store.table["EMAILDETAIL#" + "a" * 64 + "#LINKS#0000"]["json"] = (
        '[{"url":"https://link.mail.beehiiv.com/ss/c/article-token",'
        '"title":"Story","resolutionStatus":"unresolved"}]'
    )

    def failed_request(_url):
        raise OSError("network unavailable")

    result = mv.monitoring_email_resolve_article_link(
        store, groups=["editor"], site_endpoint=fx.APP_ANTH, receipt_id=receipt_id,
        candidate_index=0, resolver=failed_request,
    )
    assert result == {"error": "resolution_failed", "reason": "redirect_request_failed"}

    with patch.object(store, "record_email_resolution", side_effect=ValueError("write conflict")):
        result = mv.monitoring_email_resolve_article_link(
            store, groups=["editor"], site_endpoint=fx.APP_ANTH, receipt_id=receipt_id,
            candidate_index=0, resolver=lambda _url: "https://news.example.org/story",
        )
    assert result == {"error": "resolution_failed", "reason": "resolution_not_recorded"}
    assert store.get(f"EMAILRESOLVED#{'a' * 64}#000000") is None


def test_production_beehiiv_resolver_pins_public_addresses_and_sends_head_without_reading_body():
    tracker = "https://link.mail.beehiiv.com/ss/c/article-token"
    requests, destinations, files, hostnames = [], [], [], []
    responses = [
        (b"HTTP/1.1 302 Found\r\nLocation: https://news.example.org/story?utm_source=mail\r\n"
         b"Content-Length: 4\r\n\r\nBODY"),
        b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nBODY",
    ]

    class FakeSocket:
        def __init__(self, response):
            self.response = response

        def sendall(self, data):
            requests.append(data.decode("ascii"))

        def makefile(self, *_args, **_kwargs):
            class TrackingStream(io.BytesIO):
                position_before_close = None
                body_start = None

                def close(self):
                    self.position_before_close = self.tell()
                    self.body_start = self.getvalue().index(b"BODY")
                    super().close()

            stream = TrackingStream(self.response)
            files.append(stream)
            return stream

        def close(self):
            return None

        def shutdown(self, *_args):
            return None

    class FakeContext:
        def wrap_socket(self, raw, *, server_hostname):
            hostnames.append(server_hostname)
            return raw

    def getaddrinfo(host, *_args, **_kwargs):
        return [(2, 1, 6, "", ("93.184.216.34", 443))]

    def connect(address, *, timeout):
        destinations.append((address, timeout))
        return FakeSocket(responses.pop(0))

    with patch.object(mv.socket, "getaddrinfo", side_effect=getaddrinfo), \
            patch.object(mv.socket, "create_connection", side_effect=connect), \
            patch.object(mv.ssl, "create_default_context", return_value=FakeContext()):
        result = mv._resolve_beehiiv_article(tracker)

    assert result == "https://news.example.org/story"
    assert [destination[0] for destination in destinations] == [("93.184.216.34", 443)] * 2
    assert hostnames == ["link.mail.beehiiv.com", "news.example.org"]
    assert len(requests) == 2 and all(request.startswith("HEAD ") for request in requests)
    assert all("Cookie:" not in request and "Authorization:" not in request for request in requests)
    assert all(stream.position_before_close == stream.body_start for stream in files)


# --- the page shows only monitors routed to this site -----------------------------------------------

APP_DISTINCTIVE = "https://dist9.appsync-api.us-east-1.amazonaws.com/graphql"


def stores():
    return {"hn": fx.FakeViewStore(), "ttab": fx.FakeViewStore(fx.ttab_rows(APP_DISTINCTIVE)),
            "huggingface": fx.FakeViewStore(fx.ttab_rows(fx.APP_PAPYRUS, monitor="huggingface")),
            "p-apyr-us-email": fx.FakeViewStore()}


def site_overview(endpoint, groups=("editor",), scope="publication"):
    return mv.monitoring_site_overview(stores(), groups=list(groups), site_endpoint=endpoint, scope=scope, now=fx.NOW)


def test_a_site_sees_only_the_monitors_routed_to_it():
    result = site_overview(APP_DISTINCTIVE)
    assert {i["monitorId"] for i in result["items"]} == {"ttab"}
    titles = [i["title"] for i in result["items"]]
    assert titles == ["Decision on a mark"] and "Fresh Show HN" not in titles
    assert [f["id"] for f in result["feeds"]] == ["ttab"]
    assert all(r["monitorId"] == "ttab" for r in result["runs"])
    assert result["scope"]["publicationId"] == "distinctive"
    assert result["items"][0]["routing"] == "collected"


def test_other_monitors_are_named_but_their_items_are_not_returned():
    result = site_overview(APP_DISTINCTIVE)
    assert sorted(result["otherMonitors"]) == ["hn", "huggingface"]
    payload = json.dumps(result)
    assert "Fresh Show HN" not in payload and "Quantum paper" not in payload and "Model release" not in payload


def test_a_site_routed_by_two_monitors_sees_both():
    result = site_overview(fx.APP_PAPYRUS)
    assert {i["monitorId"] for i in result["items"]} == {"hn", "huggingface"}
    assert result["otherMonitors"] == ["ttab"]
    observed = [i["observedAt"] for i in result["items"]]
    assert observed == sorted(observed, reverse=True)


def test_a_site_no_monitor_routes_to_gets_the_notice_and_no_items():
    result = site_overview("https://nobody.appsync-api.us-east-1.amazonaws.com/graphql")
    assert result["items"] == [] and result["notice"] == "publication_not_routed"
    assert sorted(result["otherMonitors"]) == ["hn", "huggingface", "ttab"]


def test_an_admin_may_still_read_every_monitor():
    result = site_overview(APP_DISTINCTIVE, groups=("admin",), scope="all")
    assert {i["monitorId"] for i in result["items"]} == {"hn", "ttab", "huggingface"}
    assert result["otherMonitors"] == []


def test_handler_reads_each_listed_monitor_through_the_same_read_only_store():
    asked = []

    def factory(monitor_id="hn"):
        asked.append(monitor_id)
        return stores()[monitor_id]
    out = mv.handle(event(["editor"]), env={"PAPYRUS_GRAPHQL_ENDPOINT": APP_DISTINCTIVE}, store_factory=factory)
    assert asked == ["hn", "ttab", "huggingface", "p-apyr-us-email"] and [i["monitorId"] for i in out["items"]] == ["ttab"]
    asked.clear()
    mv.handle(event(["editor"]), env={"PAPYRUS_GRAPHQL_ENDPOINT": APP_DISTINCTIVE, "PAPYRUS_MONITORING_MONITOR_IDS": "ttab, hn"},
              store_factory=factory)
    assert asked == ["ttab", "hn"]
