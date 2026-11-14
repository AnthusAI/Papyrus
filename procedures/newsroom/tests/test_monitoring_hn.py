import sqlite3
from pathlib import Path

import pytest

from papyrus_content.monitoring import Monitor, collect, parse_hn_feed


FEED = b'''<rss><channel>
<item><title>Real-shaped AI source</title><link>https://example.org/paper?utm_source=hn</link><comments>https://news.ycombinator.com/item?id=123</comments><pubDate>Mon, 19 Oct 2026 10:00:00 +0000</pubDate></item>
<item><title>Security source</title><link>https://example.org/security</link><comments>https://news.ycombinator.com/item?id=124</comments></item>
</channel></rss>'''


def monitor(tmp_path, **changes):
    return Monitor(**{**dict(id="hn", publication="publication-a", corpus_id="knowledge-corpus-a",
                             endpoint="https://example.appsync-api.us-east-1.amazonaws.com/graphql",
                             state=tmp_path / "checkpoint.sqlite3", interval_seconds=900), **changes})


class Intake:
    def __init__(self, fail_once=None):
        self.calls = []
        self.fail_once = fail_once

    def __call__(self, item, provenance):
        self.calls.append((item, provenance))
        if item.source_id == self.fail_once:
            self.fail_once = None
            raise ValueError("intake unavailable")
        return {"referenceId": "reference-" + item.canonical_url.rsplit("/", 1)[-1].split("?")[0],
                "referenceLineageId": "lineage-" + item.source_id}


def test_repeat_revisions_and_distinct_discoveries(tmp_path):
    m, intake = monitor(tmp_path), Intake()
    first = collect(m, intake, fetch=lambda: FEED, now=1000)
    again = collect(m, intake, fetch=lambda: FEED, now=1001, force=True)
    revised = collect(m, intake, fetch=lambda: FEED.replace(b"AI source", b"AI update"), now=1002, force=True)
    assert len(first["discoveries"]) == 2
    assert again["unchanged"] == 2 and again["discoveries"] == []
    assert len(revised["discoveries"]) == 1 and revised["discoveries"][0]["revision"] == 2
    assert revised["discoveries"][0]["referenceId"] == first["discoveries"][0]["referenceId"]
    assert len(intake.calls) == 3
    p = intake.calls[0][1]
    assert p["publication"] == m.publication and p["monitorId"] == "hn"
    assert p["sourceItemUrl"] == "https://news.ycombinator.com/item?id=123"
    assert p["observedAt"] and p["fingerprint"] and p["sourceUrl"]
    assert "utm_source" not in intake.calls[0][0].canonical_url
    assert "curationStatus" not in revised and "label" not in revised


def test_interruption_keeps_success_and_retries_only_failed_item(tmp_path):
    m, intake = monitor(tmp_path), Intake(fail_once="124")
    first = collect(m, intake, fetch=lambda: FEED, now=1000)
    assert first["status"] == "partial" and len(first["errors"]) == 1
    second = collect(m, intake, fetch=lambda: FEED, now=1001, force=True)
    assert second["status"] == "complete" and second["unchanged"] == 1
    assert [x[0].source_id for x in intake.calls] == ["123", "124", "124"]


def test_explicit_batch_selection_reports_missing_items(tmp_path):
    result = collect(monitor(tmp_path, source_ids=("123", "999")), Intake(), fetch=lambda: FEED, now=1000)
    assert result["status"] == "partial"
    assert [row["sourceId"] for row in result["discoveries"]] == ["123"]
    assert result["errors"][0]["stage"] == "selection"
    assert result["errors"][0]["sourceId"] == "999"


def test_due_checkpoint_survives_new_process_and_fetch_failure(tmp_path):
    m, intake = monitor(tmp_path), Intake()
    collect(m, intake, fetch=lambda: FEED, now=1000)
    def not_due():
        raise AssertionError("fetch before due")
    assert collect(monitor(tmp_path), intake, fetch=not_due, now=1200)["status"] == "not_due"
    failed = collect(m, intake, fetch=lambda: (_ for _ in ()).throw(ValueError("source down")), now=1900)
    assert failed["status"] == "failed" and failed["errors"][0]["stage"] == "fetch"
    assert len(intake.calls) == 2


def test_checkpoint_refuses_changed_publication_or_endpoint(tmp_path):
    collect(monitor(tmp_path), Intake(), fetch=lambda: FEED, now=1000)
    for changes in [{"publication": "other"}, {"endpoint": "https://other.example/graphql"}, {"corpus_id": "other"}]:
        with pytest.raises(ValueError, match="binding"):
            collect(monitor(tmp_path, **changes), Intake(), fetch=lambda: FEED, now=2000)


def test_different_hn_items_can_share_one_canonical_reference(tmp_path):
    feed = FEED.replace(b"https://example.org/security", b"https://example.org/paper")
    result = collect(monitor(tmp_path), Intake(), fetch=lambda: feed, now=1000)
    assert len(result["discoveries"]) == 2
    assert len({x["referenceId"] for x in result["discoveries"]}) == 1
    assert len({x["sourceId"] for x in result["discoveries"]}) == 2


@pytest.mark.parametrize("feed", [b"not xml", b"<!DOCTYPE rss><rss/>", b"<html/>"])
def test_invalid_feed_cannot_look_like_successful_empty_collection(feed):
    with pytest.raises(ValueError):
        parse_hn_feed(feed)


def test_intake_must_supply_a_real_receipt(tmp_path):
    result = collect(monitor(tmp_path), lambda *_: {}, fetch=lambda: FEED, now=1000)
    assert result["status"] == "partial" and len(result["errors"]) == 2
    assert result["discoveries"] == []


def test_a_local_config_that_still_has_a_limit_loads_and_ignores_it_with_one_log_line(tmp_path, capsys):
    import json
    from papyrus_content.monitoring_commands import load_monitor
    path = tmp_path / "hn.json"
    path.write_text(json.dumps({"schemaVersion": 1, "monitorId": "hn", "publication": "example", "corpusId": "c",
                                "endpoint": "https://example.appsync-api.us-east-1.amazonaws.com/graphql",
                                "state": "hn.sqlite3", "intervalSeconds": 900, "limit": 10}))

    monitor = load_monitor(str(path))

    assert not hasattr(monitor, "limit")
    assert json.loads(capsys.readouterr().out) == {"monitor": "ignored_retired_config", "fields": ["limit"]}
