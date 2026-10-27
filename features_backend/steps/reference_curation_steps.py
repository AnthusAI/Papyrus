"""Steps for features_backend/reference-curation-before-review.feature. Everything is in memory: no network, no AWS, no model."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT / "src", REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from curation_support import (  # noqa: E402
    NOW, MemoryClient, Grobid, Summarizer, article_html, page, paper_pdf, reference, services as build_services,
)
from papyrus_content import reference_curation as curation  # noqa: E402
from papyrus_content.reference_curation_store import apply_editor_correction  # noqa: E402

ARTICLE_URL = "https://news.example.org/r1"
ARXIV_URL = "https://arxiv.org/abs/2601.01234"
ARXIV_PDF = "https://arxiv.org/pdf/2601.01234"


def svc(context):
    if getattr(context, "services", None) is None:
        context.services = build_services(context.client, pages=context.pages, summarizer=context.summarizer,
                                          grobid_url=context.grobid_url, grobid=context.grobid)
    return context.services


def curate(context, **kwargs):
    context.result = curation.curate_reference(context.client, context.ref, services=svc(context), **kwargs)
    return context.result


def card(context):
    found = context.client.card(context.ref["id"])
    assert found is not None, "the Reference has no curation card"
    return found


@given("a site with a pending Reference whose source is a news article")
def _(context):
    context.ref = reference()
    context.client = MemoryClient([context.ref])
    context.pages = {ARTICLE_URL: page(article_html())}
    context.summarizer = None
    context.grobid_url = context.grobid = context.services = None


@given("a model that summarizes in source voice")
def _(context):
    context.summarizer = Summarizer()


@given('the source refuses the request as "{failure}"')
def _(context, failure):
    context.pages[ARTICLE_URL] = failure


def _paper(context, *, grobid: bool):
    context.ref = reference(sourceUri=ARXIV_URL)
    context.client = MemoryClient([context.ref])
    context.pages = {ARXIV_PDF: page(paper_pdf(), "application/pdf")}
    context.grobid_url, context.grobid = ("http://grobid.test:8070", Grobid()) if grobid else (None, None)
    context.services = None


@given("the Reference is an arXiv paper and a GROBID service is available")
def _(context):
    _paper(context, grobid=True)


@given("the Reference is an arXiv paper and no GROBID service is configured")
def _(context):
    _paper(context, grobid=False)


@given("the curation procedure has run for the Reference")
def _(context):
    curate(context)


@given('the editor "{editor}" pasted the full text "{text}" and labeled the capture "{assessment}"')
def _(context, editor, text, assessment):
    apply_editor_correction(context.client, context.ref, editor=editor, text=text, assessment=assessment, store=svc(context).store, now=NOW)


@when("the router delivers the Reference and the curation procedure it started runs")
def _(context):
    from test_monitoring_router import Delivery
    from test_procedure_runner import route, triggered_table

    trigger = {"procedureKey": "papyrus.reference.curate", "input": {"reference_id": "{referenceId}"}}
    table, delivery, started = triggered_table(procedureTriggers=[trigger]), Delivery(), []
    route(table, delivery, started)
    reference_id = started[0]["input"]["reference_id"]
    context.ref = reference(id=reference_id, lineageId=reference_id, sourceUri=ARTICLE_URL)
    context.client = MemoryClient([context.ref])
    context.services = None
    context.card_when_routing_returned = context.client.card(reference_id)
    context.result = curation.curate_reference_by_id(reference_id, client=context.client, services=svc(context))


@when("the curation procedure runs for the Reference")
def _(context):
    curate(context)


@when("a GROBID service becomes available and the curation procedure runs again")
def _(context):
    svc(context).grobid_url, svc(context).grobid_post = "http://grobid.test:8070", Grobid()
    curate(context)


@when('the editor "{editor}" pastes the full text "{text}" and labels the capture "{assessment}"')
def _(context, editor, text, assessment):
    context.original_text = svc(context).store.text(context.ref, "curation-text")
    context.correction = apply_editor_correction(context.client, context.ref, editor=editor, text=text, assessment=assessment,
                                                 store=svc(context).store, now=NOW)


@then("the router did not wait for the curation")
def _(context):
    assert context.card_when_routing_returned is None


@then('the Reference\'s curation card is "{status}"')
def _(context, status):
    assert card(context)["status"] == status, card(context)["status"]


@then("the card holds the article's full text with its word count")
def _(context):
    current = card(context)
    stored = svc(context).store.text(context.ref, current["capture"]["textSortKey"])
    assert stored.startswith("# County adopts transit plan") and current["signals"]["wordCount"] == current["capture"]["wordCount"] > 80


@then("the card holds the completeness signals as facts and no completeness verdict")
def _(context):
    signals = card(context)["signals"]
    assert {"wordCount", "metaDescriptionWordCount", "paywallMarkers", "endingPattern", "endsWithTerminalPunctuation"} <= set(signals)
    assert not ({"complete", "isComplete", "verdict", "completeness"} & (set(signals) | set(card(context))))


@then('the card holds a summary written by "{model}"')
def _(context, model):
    summary = card(context)["summary"]
    assert summary["status"] == "completed" and summary["text"] and summary["model"] == model


@then("the Reference is still pending")
def _(context):
    assert context.client.get_record("Reference", context.ref["id"])["curationStatus"] == "pending"


@then('the capture failure is "{failure}" and the card holds no text')
def _(context, failure):
    current = card(context)
    assert current["capture"]["reason"] == failure and not current["current"].get("textSortKey")


@then("the card holds GROBID fields with {authors:d} authors, {sections:d} sections and {references:d} reference")
def _(context, authors, sections, references):
    grobid = card(context)["grobid"]
    assert (grobid["status"], grobid["authorCount"], grobid["sectionCount"], grobid["referenceCount"]) == ("completed", authors, sections, references)


@then("the GROBID title, authors, abstract, sections and references are stored with the Reference")
def _(context):
    fields = json.loads(svc(context).store.text(context.ref, card(context)["grobid"]["fieldsSortKey"]))
    assert fields["title"] and fields["authors"] and fields["abstract"] and fields["sections"] and fields["references"]


@then('the card says GROBID was skipped as "{reason}"')
def _(context, reason):
    assert card(context)["grobid"] == {"status": "skipped", "reason": reason}


@then("the model was asked for a summary only once")
def _(context):
    assert len(context.summarizer.calls) == 1


@then("the original captured text is unchanged")
def _(context):
    assert svc(context).store.text(context.ref, "curation-text") == context.original_text


@then('the correction is stored as version {number:d} "{provenance}" by "{editor}"')
def _(context, number, provenance, editor):
    edit = card(context)["edits"][number - 1]
    assert (edit["n"], edit["provenance"], edit["editedBy"]) == (number, provenance, editor)
    assert svc(context).store.text(context.ref, edit["sortKey"]) == "The complete article, pasted by an editor."


@then("the card shows the correction as the current text")
def _(context):
    assert card(context)["current"]["textSortKey"] == "curation-edit-0001-text"


@then('the label records that the original capture was "{assessment}" with its signals')
def _(context, assessment):
    label = card(context)["labels"][0]
    assert label["assessment"] == assessment and label["originalSignals"]["wordCount"] > 80 and label["originalTextSha256"]


@then("the summary is marked stale until the next curation run")
def _(context):
    assert card(context)["summary"]["stale"] is True


@then('the model summarized "{text}"')
def _(context, text):
    assert context.summarizer.calls[-1]["text"] == text


@then("the source was not fetched again")
def _(context):
    assert svc(context).explorer.asked.count(ARTICLE_URL) == 1


# --- the backfill ------------------------------------------------------------------------------------------------------------------------


@given("a corpus with {pending:d} pending References, {accepted:d} accepted Reference and {other:d} Reference in another corpus")
def _(context, pending, accepted, other):
    rows = [reference(f"p{n}") for n in range(pending)] + [reference(f"a{n}", curationStatus="accepted") for n in range(accepted)] \
        + [reference(f"o{n}", corpusId="knowledge-corpus-other") for n in range(other)]
    context.client = MemoryClient(rows)
    context.pages = {row["sourceUri"]: page(article_html()) for row in rows}
    context.summarizer, context.grobid_url, context.grobid, context.services = Summarizer(), None, None, None


@when("the backfill runs for the pending References")
def _(context):
    context.writes_before = context.client.writes
    context.backfill = curation.curate_corpus(context.client, corpus_id="knowledge-corpus-site", status="pending", services=svc(context))


@when("the backfill runs for the pending References again")
def _(context):
    context.writes_before = context.client.writes
    context.backfill = curation.curate_corpus(context.client, corpus_id="knowledge-corpus-site", status="pending", services=svc(context))


@when("the backfill runs as a dry run")
def _(context):
    context.writes_before = context.client.writes
    context.backfill = curation.curate_corpus(context.client, corpus_id="knowledge-corpus-site", status="pending", dry_run=True)


@then("{count:d} References were curated and the others were left alone")
def _(context, count):
    assert context.backfill["counts"]["curated"] == count
    assert {row["referenceId"] for row in context.client.tables["ReferenceAttachment"].values()} == {"p0-v1", "p1-v1"}


@then("no Reference was curated and nothing was written")
def _(context):
    assert context.backfill["counts"]["curated"] == 0 and context.client.writes == context.writes_before


@then("it plans {count:d} References and writes nothing")
def _(context, count):
    assert context.backfill["counts"]["planned"] == count and context.client.writes == context.writes_before
