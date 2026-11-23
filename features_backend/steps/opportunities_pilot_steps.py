from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from behave import then, when

from papyrus_content import opportunities


def run(context, args, *, offline=True):
    root = context.repo_root / "features_backend" / "fixtures" / "opportunities"
    base = ["--references", str(root / "references.json"), "--price-per-read", "0.005"]
    if offline:
        base += ["--posts", str(root / "recorded-search.json")]
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        context.opportunity_exit = opportunities.main([*base, *args])
    context.opportunity_error = err.getvalue()
    context.opportunity_result = json.loads(out.getvalue()) if out.getvalue() else {}


@when("I run the Opportunities command against a saved search with duplicate replies and an already cited source")
def offline_search(context):
    run(context, ["--max-reads", "10"])


@then("the review queue has two opportunities with their exact target, original source, and contribution")
def review_queue(context):
    assert context.opportunity_exit == 0, context.opportunity_error
    first, second = context.opportunity_result["opportunities"]
    assert first["target_url"] == "https://x.com/i/web/status/100"
    assert first["thread_url"] == first["target_url"]
    assert first["source_url"] == first["share_url"] == "https://example.org/municipal-access-logs"
    assert first["contribution_to_review"].startswith("An independently reviewed access log")
    assert second["target_url"] == "https://x.com/i/web/status/200"
    assert second["share_url"] == "https://publication.example.org/notes/audit-disclosures"
    assert second["source_url"] == "https://example.org/audit-disclosures"
    assert second["contribution_to_review"].startswith("A quarterly disclosure schedule")


@then("the run counts five read posts and does not follow the next page")
def read_receipt(context):
    result = context.opportunity_result
    assert result["post_reads"] == 5
    assert result["requested_post_limit"] == 10
    assert result["estimated_usd"] == "0.025"
    assert len(result["searches"]) == 1
    assert result["searches"][0]["more_available"] is True
    assert result["mode"] == "offline"


@when("I run the Opportunities command with a maximum of nine reads")
def small_budget(context):
    with patch.object(opportunities, "search_x") as search:
        with patch.dict(os.environ, {opportunities.TOKEN_ENV: "test-only"}):
            run(context, ["--max-reads", "9"], offline=False)
        search.assert_not_called()


@then("the command refuses without searching")
def refused(context):
    assert context.opportunity_exit == 2
    assert "at least 10 results" in context.opportunity_error


@when("I run the Opportunities command against a saved search with only an unrelated post")
def unrelated_search(context):
    query = "municipal access logs -is:retweet"
    root = context.repo_root / "features_backend" / "fixtures" / "opportunities"
    read = opportunities.load_input
    with patch.object(opportunities, "load_input", side_effect=lambda path: (
        {query: {"data": [{"id": "400", "text": "Lunch looks delicious."}]}}
        if path == root / "recorded-search.json" else read(path)
    )):
        run(context, ["--max-reads", "10"])


@then("the review queue is empty")
def no_candidates(context):
    assert context.opportunity_exit == 0, context.opportunity_error
    assert not context.opportunity_result["opportunities"]


@when("I run the live Opportunities command with a fake X transport")
def live_search(context):
    response = b'{"data":[],"meta":{"next_token":"not-followed"}}'
    with patch.object(opportunities, "build_opener") as build:
        with patch.dict(os.environ, {opportunities.TOKEN_ENV: "test-only"}):
            build.return_value.open.return_value = io.BytesIO(response)
            run(context, ["--max-reads", "10"], offline=False)
        build.return_value.open.assert_called_once()
        context.opportunity_request = build.return_value.open.call_args.args[0]


@then("it requests one Recent Search page of ten posts by GET and never sends a post")
def get_only(context):
    assert context.opportunity_exit == 0, context.opportunity_error
    assert context.opportunity_result["mode"] == "live"
    request = context.opportunity_request
    url = urlsplit(request.full_url)
    assert request.get_method() == "GET"
    assert (url.scheme, url.hostname, url.path) == ("https", "api.x.com", "/2/tweets/search/recent")
    assert parse_qs(url.query)["max_results"] == ["10"]
    assert request.get_header("Authorization") == "Bearer test-only"
