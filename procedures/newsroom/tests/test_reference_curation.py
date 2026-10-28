"""Curation before review: capture, completeness signals, summary, GROBID, idempotency, editor corrections, the backfill. No network."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from unittest import mock

import pytest

from curation_support import (ARTICLE_PARAGRAPHS, NOW, TEI, Explorer, Grobid, MemoryClient, Summarizer, article_html, page, paper_pdf,
                              reference, services)
from pdf_fixtures import make_pdf
from papyrus_content import reference_capture, reference_curation as curation
from papyrus_content.reference_curation_store import CurationError, apply_editor_correction, correct_reference_capture, read_card
from papyrus_content.reference_grobid import GrobidUnavailable, parse_tei, resolve_grobid_url

ARTICLE_URL = "https://news.example.org/r1"
ROOT = Path(__file__).resolve().parents[3]


def curated(pages, *, ref=None, **kwargs):
    ref = ref or reference()
    client = MemoryClient([ref])
    svc = services(client, pages=pages, **kwargs)
    return client, svc, ref, curation.curate_reference(client, ref, services=svc)


# --- capture and signals -------------------------------------------------------------------------------------------------------------


def test_capture_reads_the_whole_article_and_skips_navigation_and_footer():
    capture = reference_capture.capture_source(ARTICLE_URL, explorer=Explorer({ARTICLE_URL: page(article_html())}))
    assert capture.ok and capture.source_kind == "html"
    assert capture.text.startswith("# County adopts transit plan")
    assert all(paragraph in capture.text for paragraph in ARTICLE_PARAGRAPHS)
    assert "Copyright and legal boilerplate" not in capture.text and "long menu" not in capture.text


def test_signals_are_facts_not_a_verdict():
    html = article_html(footer="<p>Subscribe to continue reading this article with a digital account today.</p>",
                        description="Board adopts transit plan after a long meeting and a vote on Tuesday night.",
                        extra_head='<script type="application/ld+json">{"@type":"NewsArticle","wordCount":1200,"isAccessibleForFree":false}</script>')
    capture = reference_capture.capture_source(ARTICLE_URL, explorer=Explorer({ARTICLE_URL: page(html)}))
    signals = capture.signals
    assert signals["wordCount"] > 80 and signals["declaredWordCount"] == 1200 and signals["wordCountRatioToDeclared"] < 0.5
    assert signals["structuredAccessibleForFree"] is False
    assert {"id": "subscribe_to_continue", "inTail": True} in signals["paywallMarkers"]
    assert signals["endingPattern"] == "sentence_end" and signals["endsWithTerminalPunctuation"] is True
    assert not any(key in signals for key in ("complete", "isComplete", "verdict"))


def test_an_ellipsis_ending_and_a_truncated_response_are_recorded():
    html = article_html(paragraphs=ARTICLE_PARAGRAPHS[:-1] + ["The board expects to ask voters for a sales tax in the next election and then…"])
    capture = reference_capture.capture_source(ARTICLE_URL, explorer=Explorer({ARTICLE_URL: page(html, truncated=True)}))
    assert capture.signals["endingPattern"] == "ellipsis" and capture.signals["responseTruncated"] is True


def test_a_pdf_is_read_page_by_page_and_keeps_its_bytes_for_grobid():
    url = "https://papers.example.org/paper.pdf"
    capture = reference_capture.capture_source(url, explorer=Explorer({url: page(paper_pdf(), "application/pdf")}))
    assert capture.ok and capture.source_kind == "pdf" and capture.pdf_bytes
    assert capture.signals["pdfPageCount"] == 4 and "Introduction" in capture.text
    assert capture.paper["isPaper"] and "paper_structure" in capture.paper["basis"]


def test_an_arxiv_abstract_page_is_captured_from_its_pdf():
    explorer = Explorer({"https://arxiv.org/pdf/2601.01234": page(paper_pdf(), "application/pdf")})
    capture = reference_capture.capture_source("https://arxiv.org/abs/2601.01234", explorer=explorer)
    assert explorer.asked == ["https://arxiv.org/pdf/2601.01234"]
    assert capture.ok and capture.paper["arxivId"] == "2601.01234" and "arxiv" in capture.paper["basis"]


def test_a_page_that_points_at_its_pdf_with_citation_pdf_url_is_captured_from_the_pdf():
    head = ('<meta name="citation_title" content="Steering"><meta name="citation_author" content="Lovelace, Ada">'
            '<meta name="citation_pdf_url" content="/files/paper.pdf">')
    explorer = Explorer({ARTICLE_URL: page(article_html(extra_head=head)), "https://news.example.org/files/paper.pdf": page(paper_pdf(), "application/pdf")})
    capture = reference_capture.capture_source(ARTICLE_URL, explorer=explorer)
    assert capture.source_kind == "pdf" and capture.via == "citation_pdf_url" and "citation_meta" in capture.paper["basis"]


JOURNAL_URL = "https://journal.example.org/article/view/42"
JOURNAL_PDF = "https://journal.example.org/article/download/42/paper.pdf"
BLURB = "A peer-reviewed record of the contemporary biodiversity crisis."


def landing_page(*, head="", body="", description=BLURB):
    return (f"<html><head><title>Record</title><meta name='description' content='{description}'>{head}</head>"
            f"<body><header><p>Journal of Things and the site menu that is not content</p></header>{body}</body></html>")


def capture_landing(html, *, pdf_urls=(JOURNAL_PDF,)):
    explorer = Explorer({JOURNAL_URL: page(html), **{url: page(paper_pdf(), "application/pdf") for url in pdf_urls}})
    return reference_capture.capture_source(JOURNAL_URL, explorer=explorer), explorer


def test_a_thin_landing_page_follows_its_citation_pdf_url_and_records_where_the_text_came_from():
    capture, _ = capture_landing(landing_page(head=f'<meta name="citation_pdf_url" content="{JOURNAL_PDF}">'))
    assert capture.ok and capture.source_kind == "pdf" and "Introduction" in capture.text
    assert capture.via == "citation_pdf_url" and capture.full_text_url == JOURNAL_PDF and capture.destination_url == JOURNAL_PDF


def test_a_thin_landing_page_follows_a_link_rel_alternate_pdf_when_there_is_no_citation_meta():
    capture, _ = capture_landing(landing_page(head=f'<link rel="alternate" type="application/pdf" href="{JOURNAL_PDF}">'))
    assert capture.via == "alternate_pdf" and capture.full_text_url == JOURNAL_PDF and "Introduction" in capture.text


def test_a_thin_landing_page_follows_a_same_site_pdf_anchor_and_a_full_text_label():
    capture, _ = capture_landing(landing_page(body=f'<p><a href="{JOURNAL_PDF}">Download</a></p>'))
    assert capture.via == "linked_pdf" and capture.full_text_url == JOURNAL_PDF
    labelled = "https://journal.example.org/article/pdf/42"
    capture, _ = capture_landing(landing_page(body=f'<p><a href="{labelled}">Full Text (PDF)</a></p>'), pdf_urls=(labelled,))
    assert capture.via == "full_text_link" and capture.full_text_url == labelled and "Introduction" in capture.text


def test_the_standard_signals_come_first_and_another_site_s_anchors_are_not_followed():
    other = "https://elsewhere.example.net/ad.pdf"
    html = landing_page(head=f'<meta name="citation_pdf_url" content="{JOURNAL_PDF}">', body=f'<a href="{other}">PDF</a>')
    links = reference_capture.full_text_links(html, JOURNAL_URL, {"citation_pdf_url": JOURNAL_PDF})
    assert links == [(JOURNAL_PDF, "citation_pdf_url")]
    capture, explorer = capture_landing(landing_page(body=f'<a href="{other}">PDF</a>'), pdf_urls=(other,))
    assert not capture.full_text_url and capture.text == BLURB and other not in explorer.asked


def test_a_page_with_a_real_article_keeps_its_own_text_even_though_it_links_a_pdf():
    capture, explorer = capture_landing(article_html(footer=f'<a href="{JOURNAL_PDF}">PDF</a>'))
    assert capture.source_kind == "html" and capture.full_text_url is None and JOURNAL_PDF not in explorer.asked


def test_an_unreadable_full_text_link_leaves_the_blurb_capture_in_place():
    capture, _ = capture_landing(landing_page(head=f'<link rel="alternate" type="application/pdf" href="{JOURNAL_PDF}">'), pdf_urls=())
    assert capture.ok and capture.text == BLURB and capture.full_text_url is None


def test_the_capture_card_records_the_full_text_url_and_the_backfill_counts_short_bodies():
    html = landing_page(head=f'<meta name="citation_pdf_url" content="{JOURNAL_PDF}">')
    client = MemoryClient([reference("j", sourceUri=JOURNAL_URL), reference("s", sourceUri="https://news.example.org/s")])
    pages = {JOURNAL_URL: page(html), JOURNAL_PDF: page(paper_pdf(), "application/pdf"), "https://news.example.org/s": page(article_html())}
    result = curation.curate_corpus(client, corpus_id="knowledge-corpus-site", status="pending", services=services(client, pages=pages))
    assert client.card("j-v1")["capture"]["fullTextUrl"] == JOURNAL_PDF and "fullTextUrl" not in client.card("s-v1")["capture"]
    assert result["counts"]["shortBodies"] == 1 and result["counts"]["curated"] == 2


@pytest.mark.parametrize("failure,transient", [("blocked", False), ("timeout", True), ("http_5xx", True), ("http_4xx", False)])
def test_a_source_that_cannot_be_read_fails_with_a_typed_reason(failure, transient):
    capture = reference_capture.capture_source(ARTICLE_URL, explorer=Explorer({ARTICLE_URL: failure}))
    assert (capture.ok, capture.failure, capture.transient) == (False, failure, transient)


# --- the pipeline --------------------------------------------------------------------------------------------------------------------


def test_a_delivered_reference_gets_text_signals_and_a_summary_before_review():
    client, svc, ref, result = curated({ARTICLE_URL: page(article_html())})
    card = client.card(ref["id"])
    assert result["outcome"] == "curated" and card["status"] == "ready"
    assert card["capture"]["status"] == "completed" and card["capture"]["textSortKey"] == "curation-text"
    assert svc.store.text(ref, "curation-text").startswith("# County adopts transit plan")
    assert card["signals"]["wordCount"] > 80 and card["summary"]["text"].startswith("Transit plan adopted")
    assert card["summary"]["model"] == "gpt-6-luna"
    assert json.loads(svc.store.text(ref, "metadata"))["summary"] == card["summary"]["text"]
    assert ref["curationStatus"] == "pending" and client.get_record("Reference", ref["id"])["curationStatus"] == "pending"


def test_a_reference_that_cannot_be_captured_is_marked_so_not_silently_pending():
    client, svc, ref, result = curated({ARTICLE_URL: "blocked"})
    card = client.card(ref["id"])
    assert result["status"] == "capture_failed" and card["capture"] == {**card["capture"], "status": "failed", "reason": "blocked", "transient": False}
    assert card["summary"]["reason"] == "no_text" and "curation-text" not in svc.store.writes


def test_a_research_paper_gets_grobid_fields():
    url = "https://arxiv.org/abs/2601.01234"
    ref = reference(sourceUri=url)
    client, svc, ref, result = curated({"https://arxiv.org/pdf/2601.01234": page(paper_pdf(), "application/pdf")}, ref=ref,
                                       grobid_url="http://grobid.test:8070", grobid=Grobid())
    card = client.card(ref["id"])
    assert card["grobid"]["status"] == "completed" and card["grobid"]["authorCount"] == 2 and card["grobid"]["referenceCount"] == 1
    fields = json.loads(svc.store.text(ref, "curation-grobid"))
    assert fields["title"] == "Steering Feeds With Editor Feedback" and fields["authors"][0]["name"] == "Ada Lovelace"
    assert [s["heading"] for s in fields["sections"]] == ["Introduction", "Method"] and fields["references"][0]["doi"] == "10.1/feeds"
    assert svc.store.text(ref, "curation-grobid-tei").startswith("<?xml")


def test_a_paper_without_a_grobid_service_is_a_typed_skip_and_the_rest_still_runs():
    url = "https://arxiv.org/abs/2601.01234"
    client, svc, ref, result = curated({"https://arxiv.org/pdf/2601.01234": page(paper_pdf(), "application/pdf")}, ref=reference(sourceUri=url))
    card = client.card(ref["id"])
    assert card["grobid"] == {"status": "skipped", "reason": "grobid_not_configured"}
    assert card["status"] == "ready"


def test_a_page_that_is_not_a_paper_skips_grobid_as_not_a_paper():
    client, svc, ref, _ = curated({ARTICLE_URL: page(article_html())}, grobid_url="http://grobid.test", grobid=Grobid())
    assert client.card(ref["id"])["grobid"] == {"status": "skipped", "reason": "not_a_paper"}
    assert svc.grobid_post.calls == 0


def test_a_busy_grobid_is_retried_by_the_next_run():
    url = "https://arxiv.org/abs/2601.01234"
    pages = {"https://arxiv.org/pdf/2601.01234": page(paper_pdf(), "application/pdf")}
    ref = reference(sourceUri=url)
    client = MemoryClient([ref])
    svc = services(client, pages=pages, grobid_url="http://grobid.test", grobid=Grobid(status=503))
    curation.curate_reference(client, ref, services=svc)
    assert client.card(ref["id"])["grobid"]["reason"] == "grobid_busy"
    svc.grobid_post = Grobid()
    again = curation.curate_reference(client, ref, services=svc)
    assert again["outcome"] == "curated" and client.card(ref["id"])["grobid"]["status"] == "completed"
    assert svc.summarizer.calls and len(svc.summarizer.calls) == 1   # the finished summary is not redone


def test_a_second_run_changes_nothing():
    client, svc, ref, _ = curated({ARTICLE_URL: page(article_html())})
    writes, bodies = client.writes, list(svc.store.writes)
    again = curation.curate_reference(client, ref, services=svc)
    assert again["outcome"] == "already_curated" and client.writes == writes and svc.store.writes == bodies
    assert len(svc.summarizer.calls) == 1


def test_a_permanent_capture_failure_is_not_retried_but_a_transient_one_is():
    ref = reference()
    client = MemoryClient([ref])
    svc = services(client, pages={ARTICLE_URL: "http_4xx"})
    curation.curate_reference(client, ref, services=svc)
    assert curation.curate_reference(client, ref, services=svc)["outcome"] == "already_curated"
    flaky = reference("r2")
    client2 = MemoryClient([flaky])
    svc2 = services(client2, pages={"https://news.example.org/r2": "timeout"})
    curation.curate_reference(client2, flaky, services=svc2)
    svc2.explorer.pages["https://news.example.org/r2"] = page(article_html())
    assert curation.curate_reference(client2, flaky, services=svc2)["outcome"] == "curated"
    assert client2.card(flaky["id"])["status"] == "ready"


def test_without_a_model_key_the_summary_is_a_typed_skip_and_a_later_run_fills_it_in():
    ref = reference()
    client = MemoryClient([ref])
    svc = services(client, pages={ARTICLE_URL: page(article_html())}, summarizer=None)
    curation.curate_reference(client, ref, services=svc)
    card = client.card(ref["id"])
    assert card["status"] == "degraded" and card["summary"]["reason"] == "openai_not_configured"
    assert curation.curate_reference(client, ref, services=svc)["outcome"] == "already_curated"
    svc.summarizer = Summarizer()
    curation.curate_reference(client, ref, services=svc)
    assert client.card(ref["id"])["status"] == "ready"
    assert len(svc.summarizer.calls) == 1


def test_a_failed_model_call_is_retried():
    ref = reference()
    client = MemoryClient([ref])
    svc = services(client, pages={ARTICLE_URL: page(article_html())}, summarizer=Summarizer(fail_with="model_failed"))
    curation.curate_reference(client, ref, services=svc)
    assert client.card(ref["id"])["summary"]["reason"] == "model_failed"
    svc.summarizer = Summarizer()
    assert curation.curate_reference(client, ref, services=svc)["outcome"] == "curated"
    assert client.card(ref["id"])["status"] == "ready"


def test_a_running_lease_keeps_a_second_runner_out_until_it_expires():
    ref = reference()
    client = MemoryClient([ref])
    svc = services(client, pages={ARTICLE_URL: page(article_html())})
    card = curation_card_running(ref, NOW)
    from papyrus_content.reference_curation_store import write_card
    write_card(client, ref, card, NOW)
    assert curation.curate_reference(client, ref, services=svc)["outcome"] == "in_progress"
    svc.now = lambda: NOW + timedelta(hours=1)
    assert curation.curate_reference(client, ref, services=svc)["outcome"] == "curated"


def curation_card_running(ref, now):
    from papyrus_content.reference_curation_store import iso, new_card
    return {**new_card(ref), "status": "running", "startedAt": iso(now)}


def test_an_existing_summary_is_kept_unless_forced():
    ref = reference()
    client = MemoryClient([ref])
    svc = services(client, pages={ARTICLE_URL: page(article_html())})
    svc.store.write(ref, "metadata", "metadata.json", "application/json", json.dumps({"summary": "Earlier summary."}), NOW)
    curation.curate_reference(client, ref, services=svc)
    assert client.card(ref["id"])["summary"] == {"status": "skipped", "reason": "already_present", "text": "Earlier summary."}
    assert svc.summarizer.calls == []


def test_the_summary_model_is_gpt_6_luna_with_the_source_voice_prompt_of_the_procedure():
    tac = (ROOT / "procedures/newsroom/reference_summarization.tac").read_text()
    assert curation.SUMMARY_MODEL == "gpt-6-luna" and curation.SUMMARY_PROMPT_VERSION in tac
    for line in curation.SUMMARY_INSTRUCTIONS.strip().splitlines():
        assert line.strip() in tac, line
    for line in curation.SUMMARY_MESSAGE.splitlines()[:21]:
        if line.strip() and "{" not in line:
            assert line.strip() in tac, line


def test_the_summarizer_posts_to_the_responses_api_with_gpt_6_luna():
    seen = {}

    def transport(url, headers, payload):
        seen.update(url=url, payload=payload)
        return {"output_text": "  Direct summary.  ", "usage": {"input_tokens": 10, "output_tokens": 5}}

    made = curation.openai_summarizer("key", transport=transport)({"text": "x" * 130_000, "title": "T", "sourceUri": "https://x.test/a"})
    assert seen["payload"]["model"] == "gpt-6-luna" and made["text"] == "Direct summary." and made["inputTruncated"] is True


# --- editor corrections --------------------------------------------------------------------------------------------------------------


def test_an_editor_correction_is_a_new_version_that_keeps_the_original_and_leaves_a_label():
    client, svc, ref, _ = curated({ARTICLE_URL: page(article_html())})
    original = svc.store.text(ref, "curation-text")
    result = apply_editor_correction(client, ref, editor="editor-1", text="The full article, pasted by an editor.", assessment="incomplete",
                                     note="Paywall cut it off", now=NOW + timedelta(minutes=5), store=svc.store)
    card = client.card(ref["id"])
    assert svc.store.text(ref, "curation-text") == original
    assert svc.store.text(ref, "curation-edit-0001-text") == "The full article, pasted by an editor."
    assert card["current"]["textSortKey"] == "curation-edit-0001-text" and card["status"] == "ready"
    edit = card["edits"][0]
    assert (edit["provenance"], edit["editedBy"], edit["originalSortKey"]) == ("edited by editor", "editor-1", "curation-text")
    label = card["labels"][0]
    assert label["assessment"] == "incomplete" and label["originalSignals"]["wordCount"] > 80 and label["originalTextSha256"]
    assert card["summary"]["stale"] is True and result["summaryStale"] is True


def test_a_stale_summary_is_rewritten_from_the_corrected_text_and_the_capture_is_never_redone_over_it():
    client, svc, ref, _ = curated({ARTICLE_URL: page(article_html())})
    apply_editor_correction(client, ref, editor="e", text="Corrected full text.", assessment="incorrect", store=svc.store)
    svc.summarizer = Summarizer("Corrected summary.")
    svc.explorer.asked.clear()
    result = curation.curate_reference(client, ref, services=svc)
    assert result["outcome"] == "curated" and svc.explorer.asked == []
    assert svc.summarizer.calls[0]["text"] == "Corrected full text."
    assert client.card(ref["id"])["summary"]["text"] == "Corrected summary." and "stale" not in client.card(ref["id"])["summary"]
    assert curation.curate_reference(client, ref, services=svc, force=True)["outcome"] == "curated"
    assert svc.explorer.asked == [] and svc.store.text(ref, "curation-edit-0001-text") == "Corrected full text."


def test_grobid_fields_can_be_corrected_over_the_extracted_ones():
    url = "https://arxiv.org/abs/2601.01234"
    client, svc, ref, _ = curated({"https://arxiv.org/pdf/2601.01234": page(paper_pdf(), "application/pdf")}, ref=reference(sourceUri=url),
                                  grobid_url="http://g.test", grobid=Grobid())
    apply_editor_correction(client, ref, editor="e", grobid={"title": "Steering Feeds with Editor Feedback", "authors": [{"name": "Ada Lovelace"}]},
                            store=svc.store)
    card = client.card(ref["id"])
    fixed = json.loads(svc.store.text(ref, "curation-edit-0001-grobid"))
    assert fixed["title"] == "Steering Feeds with Editor Feedback" and len(fixed["references"]) == 1 and fixed["abstract"]
    assert card["current"]["grobidSortKey"] == "curation-edit-0001-grobid" and card["edits"][0]["correctedFields"] == ["authors", "title"]
    assert json.loads(svc.store.text(ref, "curation-grobid"))["title"] == "Steering Feeds With Editor Feedback"
    assert curation.curate_reference(client, ref, services=svc, force=False)["outcome"] == "already_curated"


def test_text_pasted_for_a_reference_that_could_not_be_captured_makes_it_readable():
    client, svc, ref, _ = curated({ARTICLE_URL: "blocked"})
    apply_editor_correction(client, ref, editor="e", text="Pasted text of the blocked article.", assessment="incomplete", store=svc.store)
    assert client.card(ref["id"])["label" + "s"][0]["originalCaptureStatus"] == "failed"
    curation.curate_reference(client, ref, services=svc)
    card = client.card(ref["id"])
    assert card["status"] == "ready" and svc.summarizer.calls[0]["text"] == "Pasted text of the blocked article."


@pytest.mark.parametrize("arguments,message", [
    ({"referenceId": "r1-v1"}, "Provide corrected text"),
    ({"referenceId": "r1-v1", "text": "x"}, "needs an assessment"),
    ({"referenceId": "r1-v1", "text": "x", "assessment": "perfect"}, "assessment must be"),
    ({"referenceId": "r1-v1", "grobid": {"nope": 1}}, "Unsupported GROBID"),
    ({"referenceId": "r1-v1", "assessment": "complete", "editor": "someone"}, "editor is taken from"),
])
def test_bad_corrections_are_refused(arguments, message):
    client = MemoryClient([reference()])
    with pytest.raises(CurationError, match=message):
        correct_reference_capture(client, arguments, {"username": "editor-1"}, store=services(client).store)


def test_the_appsync_action_records_the_signed_in_editor_and_an_assessment_alone_is_a_label():
    client = MemoryClient([reference()])
    store = services(client).store
    result = correct_reference_capture(client, {"referenceId": "r1-v1", "assessment": "complete"}, {"username": "google_123"}, store=store)
    assert result["ok"] and result["label"]["labeledBy"] == "google_123" and result["edits"] == []
    with pytest.raises(CurationError, match="not found"):
        correct_reference_capture(client, {"referenceId": "missing", "assessment": "complete"}, {"username": "e"}, store=store)


# --- an editor uploads the PDF --------------------------------------------------------------------------------------------------------


def uploaded(pdf, **options):
    client = MemoryClient([reference(), reference("other")])
    store = services(client).store
    return client, store, store.upload("r1-v1", pdf, **options)


def test_text_from_an_uploaded_pdf_is_stored_like_pasted_text_and_marked_as_from_a_pdf():
    client, store, attachment_id = uploaded(paper_pdf())
    result = correct_reference_capture(client, {"referenceId": "r1-v1", "pdfAttachmentId": attachment_id, "assessment": "incomplete"},
                                       {"username": "editor-1"}, now=lambda: NOW, store=store)
    card = client.card("r1-v1")
    text = store.text(client.get_record("Reference", "r1-v1"), "curation-edit-0001-text")
    assert "steered by retrieval" in text  # the PDF's pages, joined as the capture joins them
    edit = card["edits"][0]
    assert (edit["via"], edit["pdfAttachmentId"], edit["pdfPageCount"], edit["provenance"]) == ("editor_pdf", attachment_id, 4, "edited by editor")
    assert card["current"] == {"textSortKey": "curation-edit-0001-text", "textVia": "editor_pdf"}
    assert card["labels"][0]["assessment"] == "incomplete" and result["edits"][0]["via"] == "editor_pdf"
    assert card["paper"]["isPaper"] is True, "the card says whether it is a paper, so `papyrus references curate` can decide on GROBID"


def test_pasting_text_after_a_pdf_upload_clears_the_pdf_mark():
    client, store, attachment_id = uploaded(paper_pdf())
    correct_reference_capture(client, {"referenceId": "r1-v1", "pdfAttachmentId": attachment_id, "assessment": "incomplete"}, {"username": "e"}, store=store)
    correct_reference_capture(client, {"referenceId": "r1-v1", "text": "Typed by hand.", "assessment": "incomplete"}, {"username": "e"}, store=store)
    assert "textVia" not in client.card("r1-v1")["current"]


@pytest.mark.parametrize("make,message", [
    (lambda: uploaded(b"<html>not a pdf</html>"), "not a PDF"),
    (lambda: uploaded(paper_pdf(), media_type="application/pdf", name="x")[:2] + ("missing-id",), "not uploaded to this Reference"),
    (lambda: uploaded(b"%PDF-1.4 " + b"x" * 8_000_100), "larger than we read"),
    (lambda: uploaded(make_pdf([[""]])), "looks like a scan"),
    (lambda: uploaded(b"%PDF-1.4 damaged beyond repair"), "could not be read"),
])
def test_an_unusable_pdf_is_refused_in_words(make, message):
    client, store, attachment_id = make()
    with pytest.raises(CurationError, match=message):
        correct_reference_capture(client, {"referenceId": "r1-v1", "pdfAttachmentId": attachment_id, "assessment": "incomplete"}, {"username": "e"}, store=store)
    assert client.card("r1-v1") is None, "a refused upload changes nothing"


def test_a_pdf_uploaded_to_another_reference_is_refused():
    client = MemoryClient([reference(), reference("other")])
    store = services(client).store
    foreign = store.upload("other-v1", paper_pdf())
    with pytest.raises(CurationError, match="not uploaded to this Reference"):
        correct_reference_capture(client, {"referenceId": "r1-v1", "pdfAttachmentId": foreign, "assessment": "incomplete"}, {"username": "e"}, store=store)


def test_an_uploaded_pdf_still_needs_an_assessment_and_cannot_be_sent_with_text():
    client, store, attachment_id = uploaded(paper_pdf())
    with pytest.raises(CurationError, match="needs an assessment"):
        correct_reference_capture(client, {"referenceId": "r1-v1", "pdfAttachmentId": attachment_id}, {"username": "e"}, store=store)
    with pytest.raises(CurationError, match="not both"):
        correct_reference_capture(client, {"referenceId": "r1-v1", "pdfAttachmentId": attachment_id, "text": "x", "assessment": "incomplete"}, {"username": "e"}, store=store)


# --- the backfill --------------------------------------------------------------------------------------------------------------------


def corpus_client():
    refs = [reference("a"), reference("b"), reference("c", curationStatus="accepted"), reference("d", corpusId="knowledge-corpus-other"),
            reference("e", versionState="superseded")]
    return MemoryClient(refs)


def test_the_backfill_curates_pending_references_of_the_corpus_and_a_second_run_is_a_no_op():
    client = corpus_client()
    pages = {f"https://news.example.org/{name}": page(article_html()) for name in "abcde"}
    svc = services(client, pages=pages)
    first = curation.curate_corpus(client, corpus_id="knowledge-corpus-site", status="pending", services=svc)
    assert first["counts"]["considered"] == 2 and first["counts"]["curated"] == 2 and first["counts"]["ready"] == 2
    writes = client.writes
    second = curation.curate_corpus(client, corpus_id="knowledge-corpus-site", status="pending", services=svc)
    assert second["counts"]["alreadyCurated"] == 2 and second["counts"]["curated"] == 0 and client.writes == writes


def test_the_backfill_dry_run_reads_cards_and_touches_nothing():
    client = corpus_client()
    result = curation.curate_corpus(client, corpus_id="knowledge-corpus-site", status="pending", dry_run=True)
    assert result["counts"]["planned"] == 2 and client.writes == 0 and result["dryRun"] is True
    assert result["items"][0]["planned"] == {"capture": True, "summary": True, "grobid": True}


def test_the_backfill_limit_stops_after_that_many_curations():
    client = corpus_client()
    svc = services(client, pages={f"https://news.example.org/{name}": page(article_html()) for name in "ab"})
    result = curation.curate_corpus(client, corpus_id="knowledge-corpus-site", limit=1, services=svc)
    assert result["counts"]["curated"] == 1 and result["counts"]["limited"] == 1


def test_the_cli_command_is_registered_and_dry_run_prints_counts(capsys):
    client = corpus_client()
    with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(client, {})):
        curation.references_curate(["--corpus", "site", "--dry-run"])
    assert "planned=2" in capsys.readouterr().out
    from papyrus_content.cli import PORTED_COMMANDS
    assert "references:curate" in PORTED_COMMANDS


def test_grobid_url_resolution_is_explicit_and_a_missing_service_is_none():
    assert resolve_grobid_url({}) is None
    assert resolve_grobid_url({"BIBLICUS_GROBID_URL": "http://g:8070"}) == "http://g:8070"


def test_tei_that_is_not_tei_is_a_typed_failure():
    with pytest.raises(GrobidUnavailable) as caught:
        parse_tei("not xml")
    assert caught.value.reason == "grobid_parse_failed"
    assert parse_tei(TEI)["doi"] == "10.1234/steer.2026"


def test_the_procedure_runs_the_tool_through_tactus():
    pytest.importorskip("tactus")
    from papyrus_content import procedure_runner_child as child

    with mock.patch("papyrus_content.reference_curation.curate_reference_by_id", return_value={"outcome": "curated", "status": "ready"}) as tool:
        outcome = child.run(ROOT / "procedures/newsroom/reference_curation.tac", {"reference_id": "r1-v1"})
    assert outcome["success"] and outcome["toolsUsed"] == ["papyrus_curate_reference"] and tool.call_args.args == ("r1-v1",)
    assert outcome["output"]["result"]["status"] == "ready"


def test_a_router_trigger_for_the_procedure_validates():
    from papyrus_content.monitoring_router import validate_procedure_triggers

    triggers = validate_procedure_triggers("anth-us", {"openaiKeyParameter": "/amplify/shared/x/OPENAI_API_KEY", "procedureTriggers": [
        {"procedureKey": "papyrus.reference.curate", "input": {"reference_id": "{referenceId}"}}]})
    assert triggers[0]["procedureKey"] == "papyrus.reference.curate"


def test_a_delivery_starts_curation_without_waiting_for_it_and_the_started_request_curates_the_reference():
    """The router only records and starts (asynchronously); the request it starts is what curates the delivered Reference."""
    from test_monitoring_router import Delivery
    from test_procedure_runner import KEY_PARAMETER, route, triggered_table

    trigger = {"procedureKey": "papyrus.reference.curate", "input": {"reference_id": "{referenceId}"}}
    table, delivery, started = triggered_table(procedureTriggers=[trigger]), Delivery(), []
    result = route(table, delivery, started)
    assert result["counts"]["delivered"] == 2 and result["counts"]["proceduresStarted"] == 2 and len(started) == 2
    request = started[0]
    assert request["procedureKey"] == "papyrus.reference.curate" and request["openaiKeyParameter"] == KEY_PARAMETER
    reference_id = request["input"]["reference_id"]
    assert reference_id in delivery.references.values()
    client = MemoryClient([reference(sourceUri=ARTICLE_URL, id=reference_id, lineageId=reference_id)])
    outcome = curation.curate_reference_by_id(reference_id, client=client, services=services(client, pages={ARTICLE_URL: page(article_html())}))
    assert outcome["outcome"] == "curated" and outcome["status"] == "ready"


def test_the_content_actions_lambda_serves_the_correction_action():
    import importlib.util

    from curation_support import MemoryStore

    path = ROOT / "amplify/functions/content-actions/handler.py"
    spec = importlib.util.spec_from_file_location("content_actions_handler_for_curation", path)
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)
    client = MemoryClient([reference()])
    event = {"fieldName": "correctReferenceCapture", "identity": {"username": "editor-one"},
             "arguments": {"input": json.dumps({"referenceId": "r1-v1", "text": "Pasted.", "assessment": "incomplete"})}}
    with mock.patch.object(handler, "create_authoring_client", return_value=(client, {})), \
            mock.patch("papyrus_content.reference_curation_store.AttachmentStore", MemoryStore):
        accepted = handler.handler(event, None)
        refused = handler.handler({**event, "arguments": {"input": json.dumps({"referenceId": "r1-v1"})}}, None)
    assert accepted["ok"] and accepted["edits"][0]["editedBy"] == "editor-one" and accepted["edits"][0]["provenance"] == "edited by editor"
    assert refused["ok"] is False and refused["errors"][0]["code"] == "correction-rejected"
