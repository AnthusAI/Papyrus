"""The publication-date-only backfill: one stage, no summary, no card. In-memory fakes, no network."""

from __future__ import annotations

import json
from unittest import mock

from curation_support import NOW, MemoryClient, article_html, page, reference
from papyrus_content import reference_curation as curation
from papyrus_content.reference_curation_store import new_card, read_card, write_card
from papyrus_content.link_exploration import Exploration

OG = "<meta property='article:published_time' content='2026-10-28T09:30:00Z'>"


class Pages:
    """A capture-path explorer over a table of addresses; counts fetches."""

    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def __call__(self, url, context=None, **kwargs):
        self.asked.append(url)
        found = self.pages.get(url)
        if found is None:
            return Exploration(False, None, failure="timeout", direct_failure="timeout")
        return Exploration(True, url, None, "direct", readable=False, response=found if kwargs.get("keep_response") else None)


def run(references, pages, *, dry_run=False, workers=1):
    client = MemoryClient(references)
    explorer = Pages(pages)
    result = curation.backfill_publication_dates(client, corpus_id="knowledge-corpus-site", dry_run=dry_run, workers=workers, explorer=explorer,
                                                 now=lambda: NOW)
    return client, explorer, result


def stored(client, name):
    return client.get_record("Reference", f"{name}-v1")


def card_date(client, name):
    card = read_card(client, {"id": f"{name}-v1"})
    return (card or {}).get("publicationDate")


def test_page_with_og_date_gets_it():
    client, _, result = run([reference("a")], {"https://news.example.org/a": page(article_html(extra_head=OG))})
    row = stored(client, "a")
    assert row["sourcePublishedAt"] == "2026-10-28"
    assert card_date(client, "a")["source"] == "og:article:published_time"
    assert result["counts"]["resolved"] == 1 and result["counts"]["resolvedBySource"] == {"og:article:published_time": 1}
    assert len(client.tables["ReferenceAttachment"]) == 1 and not client.tables["ModelAttachment"]
    assert read_card(client, row)["capture"] == {"status": "not_run"}


def test_existing_date_is_recorded_as_monitor_without_a_fetch():
    client, explorer, result = run([reference("b", sourcePublishedAt="2026-10-01")], {})
    row = stored(client, "b")
    assert row["sourcePublishedAt"] == "2026-10-01"
    assert card_date(client, "b")["source"] == "monitor"
    assert result["counts"]["keptMonitorDate"] == 1 and explorer.asked == []


def test_already_resolved_is_skipped():
    ref = reference("c")
    client = MemoryClient([ref])
    card = new_card(ref)
    card["publicationDate"] = {"source": "pdf", "precision": "day", "resolvedAt": "2026-10-01T00:00:00Z"}
    write_card(client, ref, card, NOW)
    writes = client.writes
    explorer = Pages({})
    result = curation.backfill_publication_dates(client, corpus_id="knowledge-corpus-site", explorer=explorer, now=lambda: NOW)
    assert result["counts"]["alreadyResolved"] == 1 and client.writes == writes and explorer.asked == []


def test_fetch_failure_is_counted_and_nothing_written():
    client, _, result = run([reference("d")], {})
    assert result["counts"]["fetchFailures"] == 1 and client.writes == 0


def test_page_without_a_date_is_unknown_and_pdfs_and_non_http_are_skipped():
    refs = [reference("e"), reference("f", sourceUri="https://news.example.org/paper.pdf"), reference("g", sourceUri="mailto:x@example.org")]
    client, _, result = run(refs, {"https://news.example.org/e": page(article_html())})
    counts = result["counts"]
    assert (counts["scanned"], counts["unknown"], counts["skippedPdf"]) == (2, 1, 1) and client.writes == 0


def test_dry_run_reports_and_writes_nothing():
    client, _, result = run([reference("h"), reference("i", sourcePublishedAt="2026-10-01")],
                            {"https://news.example.org/h": page(article_html(extra_head=OG))}, dry_run=True)
    assert client.writes == 0 and not stored(client, "h").get("sourcePublishedAt")
    would = {item["referenceId"]: (item["date"], item["source"], item["precision"]) for item in result["items"]}
    assert would == {"h-v1": ("2026-10-28", "og:article:published_time", "day"), "i-v1": ("2026-10-01", "monitor", "day")}


def test_second_run_does_nothing_more():
    refs = [reference("j")]
    client = MemoryClient(refs)
    pages = Pages({"https://news.example.org/j": page(article_html(extra_head=OG))})
    for _ in range(2):
        curation.backfill_publication_dates(client, corpus_id="knowledge-corpus-site", explorer=pages, now=lambda: NOW)
    assert client.writes == 2 and len(pages.asked) == 1   # the Reference and its card, once


def test_empty_corpus_says_so(capsys):
    client = MemoryClient([])
    with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(client, {})):
        curation.references_backfill_publication_dates(["--corpus-id", "knowledge-corpus-nothing"])
    assert "No current http(s) References found in corpus knowledge-corpus-nothing" in capsys.readouterr().out
