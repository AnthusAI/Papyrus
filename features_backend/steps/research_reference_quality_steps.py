"""Steps for research-reference-quality.feature: no network; fake pages, fake PDF metadata, no model."""
import json
from types import SimpleNamespace
from unittest import mock

from behave import given, then, when

from papyrus_content import multi_search_research as ms
from papyrus_content import newsroom_context_pack
from papyrus_content.web_search import SearchHit

PROVIDER = SimpleNamespace(name="gemini")


@given('a search result titled "{title}" at "{url}"')
def step_result(context, title, url):
    if not hasattr(context, "hits"):
        context.hits = []
    context.hits.append((SearchHit(url, title, "snippet"), len(context.hits) + 1))


@when("the results are merged into sources")
def step_merge(context):
    run = SimpleNamespace(name="gemini", hits=[("query", hit, rank) for hit, rank in context.hits])
    context.sources = ms.merge_hits([run], [{"query": "query", "purpose": "p"}])


def source_at(context, url):
    found = [source for source in context.sources if source["url"] == url]
    assert found, [source["url"] for source in context.sources]
    return found[0]


@then('the source at "{url}" is titled "{title}"')
def step_titled(context, url, title):
    assert source_at(context, url)["title"] == title, source_at(context, url)["title"]


@then("there are {count:d} sources")
def step_count(context, count):
    assert len(context.sources) == count, [source["url"] for source in context.sources]


@then('the source at "{url}" was found by {count:d} results')
def step_found_by(context, url, count):
    assert len(source_at(context, url)["snippets"]) >= 1
    assert sum(1 for hit, _ in context.hits if ms.source_key(hit.url) == ms.source_key(url)) == count


@given('a source titled "{title}" at "{url}"')
def step_source(context, title, url):
    if not hasattr(context, "read_list"):
        context.read_list, context.page_titles, context.pdf_titles = [], {}, {}
    context.read_list.append({"index": len(context.read_list) + 1, "url": url, "title": title, "providers": ["p"], "purposes": [], "queries": ["q"], "snippets": []})


@given('the page at "{url}" has the title "{title}"')
def step_page_title(context, url, title):
    context.page_titles[url] = title


@given('the PDF at "{url}" has the metadata title "{title}"')
def step_pdf_title(context, url, title):
    context.pdf_titles[url] = title


@when("the run reads the sources")
def step_read(context):
    def fetch(url):
        if url in context.page_titles:
            return f"<html><head><title>{context.page_titles[url]}</title></head><body><p>{'A readable paragraph about the subject. ' * 20}</p></body></html>"
        if url in context.pdf_titles:
            return b"%PDF-1.4 fake"
        return None

    def recording(url):
        content = fetch(url)
        if isinstance(content, bytes):
            context.last_pdf = url         # one PDF per scenario, so the fake metadata is looked up by the address the run last opened
        return content

    with mock.patch.object(ms.pdf_text, "metadata_title", side_effect=lambda data: context.pdf_titles.get(context.last_pdf)), \
         mock.patch.object(ms, "pdf_text_up_to", return_value=("Some text of the paper.", True)):
        ms.read_sources(context.read_list, "brief", recording)
    context.sources = context.read_list


# --- what the context pack says about a Reference's note -------------------------------------------------------------------------

def reference(context, **fields):
    row = {"id": f"reference-{len(getattr(context, 'rows', []))}", "title": "A title", "sourceUri": "https://example.org/a", **fields}
    context.rows = [*getattr(context, "rows", []), row]
    context.row = row


@given('a Reference filed pending by a research run with the note "{note}"')
def step_pending(context, note):
    reference(context, curationStatus="pending", curationStatusReason=note, metadata=json.dumps({"ingestion_rationale": note}) if note.startswith("Found by") else "{}")


@given('a Reference rejected by the Cyclotron with the note "{note}"')
def step_cyclotron_rejected(context, note):
    reference(context, curationStatus="rejected", curationStatusReason=note, curationActorKind="cyclotron",
              metadata=json.dumps({"ingestion_rationale": "Found by perplexity (undecidability proof): Confused deputy"}))


@given('a Reference accepted by an editor with the note "{note}"')
def step_accepted(context, note):
    reference(context, curationStatus="accepted", curationStatusReason=note, curationActorKind="human", metadata="{}")


@given('a Reference reopened by an editor after an earlier vote with the note "{note}"')
def step_reopened(context, note):
    reference(context, curationStatus="pending", curationStatusReason=note, curationActorKind="human", metadata="{}")


@given('a Reference accepted by an editor whose only note is the discovery note "{note}"')
def step_accepted_discovery(context, note):
    reference(context, curationStatus="accepted", curationStatusReason=note, curationActorKind="human", metadata=json.dumps({"ingestion_rationale": note}))


@when("the Reference is written for the context pack")
def step_written(context):
    context.block = newsroom_context_pack.reference_text(SimpleNamespace(), context.row, summary=False)


@then('the Reference\'s note is labelled "{label}"')
def step_label(context, label):
    assert any(line.startswith(f"{label}: ") for line in context.block.splitlines()), context.block


@then('the Reference\'s text does not contain "{text}"')
def step_text_without(context, text):
    assert text not in context.block, context.block


@then("the Reference with the editor's reason ranks ahead of the one with the discovery note")
def step_rank(context):
    discovery, editor = context.rows
    assert newsroom_context_pack.reference_rank(editor) < newsroom_context_pack.reference_rank(discovery)
