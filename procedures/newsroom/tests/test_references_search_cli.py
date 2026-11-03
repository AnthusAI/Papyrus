"""`papyrus references search`: read-only, signed-in, no AWS. Synthetic data, no network, no keychain."""
import json
import sys

import pytest

from procedures.newsroom.tests.test_monitoring_view_cli import Env, FakeResponse, graphql_answer

RESULT = {
    "items": [
        {"reference": {"lineageId": "ref-1", "title": "Agent memory, revisited", "feedStateKey": "c#rated"}, "matchedBy": ["keyword", "meaning"], "matchedFields": ["title", "authors"]},
        {"reference": {"lineageId": "ref-2", "title": "Recollection in software", "feedStateKey": "c#unrated"}, "matchedBy": ["meaning"], "matchedFields": []},
    ],
    "nextCursor": "cursor-2",
    "lanes": {"keyword": {"status": "ok"}, "meaning": {"status": "ok"}},
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    found = Env(tmp_path, monkeypatch)
    found.answer = graphql_answer("searchReferences", RESULT)
    return found


def test_search_sends_one_query_with_the_signed_in_token_and_prints_how_each_reference_matched(env, monkeypatch):
    code, out, err = env.run(["search", "agent", "memory", "--show", "rated", "--limit", "5", "--cursor", "c-1"], monkeypatch, group=("references",))
    assert code == 0 and err == ""
    assert len(env.requests) == 1
    _method, body, headers = env.requests[0]
    assert "searchReferences" in body["query"]
    assert json.loads(body["variables"]["input"]) == {"query": "agent memory", "show": "rated", "limit": 5, "cursor": "c-1"}
    assert headers["Authorization"] and not [name for name in headers if name.lower().startswith("x-amz")]
    assert "Matched: title, author and meaning" in out and "Matched: meaning" in out and "Agent memory, revisited" in out
    assert "Next page: --cursor cursor-2" in out
    assert not any(name.startswith("boto") for name in sys.modules if sys.modules[name] is not None)


def test_search_writes_nothing_every_request_is_a_query(env, monkeypatch):
    for argv in (["search", "agent memory"], ["search", "agent", "--json"], ["search", "agent", "--show", "unrated", "--cursor", "c"]):
        code, _out, _err = env.run(argv, monkeypatch, group=("references",))
        assert code == 0
    assert env.requests
    for _method, body, _headers in env.requests:
        assert body["query"].lstrip().startswith("query ") and "mutation" not in body["query"].lower()
        assert set(body) == {"query", "variables"}


def test_json_prints_exactly_the_response_and_defaults_ask_for_all_references(env, monkeypatch):
    code, out, _ = env.run(["search", "agent memory", "--json"], monkeypatch, group=("references",))
    assert code == 0 and json.loads(out) == RESULT
    assert json.loads(env.requests[0][1]["variables"]["input"]) == {"query": "agent memory", "show": "all", "limit": 24}


def test_one_lane_down_is_said_and_the_results_still_print(env, monkeypatch):
    env.answer = graphql_answer("searchReferences", {**RESULT, "lanes": {"keyword": {"status": "ok"}, "meaning": {"status": "failed", "message": "Meaning search is not set up for this site."}}})
    code, out, _ = env.run(["search", "agent"], monkeypatch, group=("references",))
    assert code == 0 and "Meaning search unavailable: Meaning search is not set up for this site." in out and "Agent memory, revisited" in out


def test_both_lanes_down_is_one_line_and_a_failure(env, monkeypatch):
    down = {"status": "failed", "message": "x"}
    env.answer = graphql_answer("searchReferences", {"items": [], "nextCursor": None, "lanes": {"keyword": down, "meaning": down}})
    code, out, err = env.run(["search", "agent"], monkeypatch, group=("references",))
    assert code == 2 and out == "" and len(err.strip().splitlines()) == 1


def test_a_user_who_is_not_an_editor_is_refused_in_one_line(env, monkeypatch):
    env.answer = lambda request: FakeResponse(200, json.dumps({"data": None, "errors": [{"message": "Not Authorized", "errorType": "Unauthorized"}]}))
    code, out, err = env.run(["search", "agent"], monkeypatch, group=("references",))
    assert code == 2 and out == "" and len(err.strip().splitlines()) == 1 and "editors and admins" in err


def test_signed_out_is_one_line_and_nothing_is_sent(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, signed_in=False)
    code, out, err = env.run(["search", "agent"], monkeypatch, group=("references",))
    assert code != 0 and out == "" and env.requests == []
    assert len(err.strip().splitlines()) == 1 and "papyrus login" in err and "Traceback" not in err


def test_limit_out_of_range_is_refused_before_anything_is_sent(env, monkeypatch):
    code, _out, err = env.run(["search", "agent", "--limit", "500"], monkeypatch, group=("references",))
    assert code == 2 and "--limit" in err and env.requests == []
