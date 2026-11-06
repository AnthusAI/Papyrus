"""Steps for features_backend/reference-capture-state.feature. Reuses the curation steps for the world (a site, a Reference, an editor's paste or
PDF); everything is in memory: no network, no AWS, no model."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT / "src", REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from curation_support import ARTICLE_PARAGRAPHS, NOW, MemoryClient, article_html, page, reference  # noqa: E402
from papyrus_content import reference_curation as curation  # noqa: E402
from papyrus_content.records import _feed_keys_for_new_version, apply_record_changes  # noqa: E402
from papyrus_content.reference_capture_state import sync_capture_state  # noqa: E402
from papyrus_content.reference_curation_store import apply_editor_correction, new_card, write_card  # noqa: E402
from papyrus_content.reference_feed_backfill import backfill_feed_keys  # noqa: E402
from papyrus_knowledge_query import reference_search as rs  # noqa: E402

ARTICLE_URL = "https://news.example.org/r1"
CORPUS = "knowledge-corpus-site"


def stored(context, which=None):
    ref = which or context.ref
    return context.client.tables["Reference"][ref["id"]]


def long_paragraphs(words: int, ending: str = "") -> list[str]:
    sentence = "The board reviewed the plan and the numbers behind it with great care and patience. "
    text = (sentence * (words // 14 + 1)).split()[:words]
    return [" ".join(text) + "." + (f" {ending}" if ending else "")]


@given("a site with a pending Reference whose source is a news article of {words:d} words")
def _(context, words):
    context.ref = reference()
    context.client = MemoryClient([context.ref])
    context.pages = {ARTICLE_URL: page(article_html(long_paragraphs(words)))}
    context.summarizer = context.grobid_url = context.grobid = context.services = None


@given('a site with a pending Reference whose source is a news article of {words:d} words ending with "{ending}"')
def _(context, words, ending):
    context.ref = reference()
    context.client = MemoryClient([context.ref])
    context.pages = {ARTICLE_URL: page(article_html(long_paragraphs(words, ending)))}
    context.summarizer = context.grobid_url = context.grobid = context.services = None


@then("the Reference has no capture state")
def _(context):
    assert not stored(context).get("captureState"), stored(context).get("captureState")
    assert not [1 for write in getattr(context.client, "capture_writes", [])], "a capture state was written"


@then('the Reference\'s capture state is "{state}"')
def _(context, state):
    assert stored(context).get("captureState") == state, stored(context).get("captureState")


@when("the curation procedure has started and not finished")
def _(context):
    card = context.client.card(context.ref["id"]) or new_card(context.ref)
    card["status"] = "running"
    write_card(context.client, context.ref, card, NOW)


@when('the editor labels the capture "{assessment}" without giving text')
def _(context, assessment):
    apply_editor_correction(context.client, context.ref, editor="editor-one", assessment=assessment, now=NOW)
    context.ref = stored(context)


@when("extracted text of {characters:d} characters is attached to the Reference")
def _(context, characters):
    _attach(context, context.ref, characters)


@when("extracted text of {characters:d} characters is attached to another Reference")
def _(context, characters):
    context.other = reference("r2")
    context.client.tables["Reference"][context.other["id"]] = copy.deepcopy(context.other)
    _attach(context, context.other, characters)


def _attach(context, ref, characters):
    expected = {"id": f"att-{ref['id']}", "referenceId": ref["id"], "referenceLineageId": ref["lineageId"], "role": "extracted_text",
                "sortKey": "002-text", "storagePath": f"s3://bucket/{ref['id']}.txt", "importedAt": "2026-10-01T00:00:00Z", "metadata": {"textLength": characters}}
    apply_record_changes(context.client, [{"modelName": "ReferenceAttachment", "action": "upsert", "expected": expected}])


@then('that Reference\'s capture state is "{state}"')
def _(context, state):
    assert stored(context, context.other).get("captureState") == state


@when("a new version of the Reference is imported")
def _(context):
    current = stored(context)
    context.new_version = {"id": "r1-v2", "lineageId": "r1", "versionNumber": 2, "corpusId": CORPUS, "curationStatus": "pending", "createdAt": "2026-10-28T00:00:00Z"}
    context.new_version.update(_feed_keys_for_new_version(context.new_version, current))


@then('the new version\'s capture state is "{state}"')
def _(context, state):
    assert context.new_version.get("captureState") == state


# --- the backfill ---------------------------------------------------------------------------------------------------------------------------


class BackfillClient(MemoryClient):
    def list_by_index(self, index_name, key_value, **kwargs):
        if index_name == "referencesByCurationStatusKey":
            return [copy.deepcopy(r) for r in self.tables["Reference"].values() if f"{r['corpusId']}#{r['curationStatus']}" == key_value]
        return super().list_by_index(index_name, key_value, **kwargs)

    def list_semantic_relations_by_subject_state(self, key):
        return []


def _card_row(ref, metadata):
    import json
    return {"id": f"card-{ref['id']}", "referenceId": ref["id"], "referenceLineageId": ref["lineageId"], "role": "curation", "sortKey": "003-curation",
            "metadata": json.dumps({"kind": "reference-curation", **metadata})}


@given("a corpus with a captured Reference, a thin Reference, a Reference with no capture and a Reference with a stale capture state")
def _(context):
    base = {"corpusId": CORPUS, "curationStatus": "accepted", "curationStatusKey": f"{CORPUS}#accepted", "createdAt": "2026-10-01T00:00:00Z", "predictionDecidedAt": "2026-10-01T00:00:00Z"}
    refs = {name: reference(name, **base) for name in ("full", "thin", "none", "stale")}
    refs["stale"]["captureState"] = "full"
    for name, ref in refs.items():
        ref.update({"feedStateKey": f"{CORPUS}#rated", "feedArrivalAt": "2026-10-01T00:00:00.000Z", "predictionSortKey": f"0.500000#2026-10-01T00:00:00.000Z#{ref['id']}"})
    context.client = BackfillClient(refs.values())
    context.refs = refs
    done = lambda words: {"status": "ready", "capture": {"status": "completed", "wordCount": words}, "signals": {"wordCount": words}, "current": {"textSortKey": "curation-text"}}
    for name, words in (("full", 900), ("thin", 80)):
        row = _card_row(refs[name], done(words))
        context.client.tables["ReferenceAttachment"][row["id"]] = row
    context.client.update_calls = []
    original = context.client.update_record
    def recording(model, row):
        context.client.update_calls.append(copy.deepcopy(row))
        original(model, row)
    context.client.update_record = recording


@when("the capture state backfill runs for that corpus")
def _(context):
    context.counts = backfill_feed_keys(context.client, corpus_id=CORPUS)


@when("the capture state backfill runs for that corpus again")
def _(context):
    context.client.update_calls.clear()
    context.counts = backfill_feed_keys(context.client, corpus_id=CORPUS)


@when("the capture state backfill runs for that corpus as a dry run")
def _(context):
    context.counts = backfill_feed_keys(context.client, corpus_id=CORPUS, dry_run=True)


@then("the backfill reports {count:d} capture states changed")
def _(context, count):
    assert context.counts["captureStatesChanged"] == count, context.counts


@then('the captured Reference is "full", the thin one "thin", and the stale one has no state')
def _(context):
    rows = context.client.tables["Reference"]
    assert rows[context.refs["full"]["id"]]["captureState"] == "full"
    assert rows[context.refs["thin"]["id"]]["captureState"] == "thin"
    assert not rows[context.refs["stale"]["id"]].get("captureState")


@then("the Reference with no capture was not written")
def _(context):
    assert all(call["id"] != context.refs["none"]["id"] for call in context.client.update_calls), context.client.update_calls


@then("nothing was written to any Reference")
def _(context):
    assert context.counts["dryRun"] is True and context.counts["written"] == 0
    assert context.client.update_calls == []


# --- search ---------------------------------------------------------------------------------------------------------------------------------


def Site(rows):
    """The shared in-memory site: the Reference rows and the word table written from them."""
    from procedures.newsroom.tests.test_reference_search import FakeSite

    return FakeSite(rows)


def _row(lineage, state):
    return {"id": f"{lineage}-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current", "corpusId": "c", "externalItemId": lineage,
            "title": f"Topic {lineage}", "authors": [], "sourceUri": f"https://example.test/{lineage}", "feedStateKey": "c#unrated",
            "feedArrivalAt": "2026-11-01T10:00:00.000Z", "updatedAt": "2026-11-01T10:00:00.000Z", "curationStatus": "pending",
            **({"captureState": state} if state else {})}


def _search(context, **extra):
    return rs.search_references({"query": "topic", "show": "all", **extra}, words=context.site.source, vectors=None)


@given("searchable References where two are full, one is thin, one is running and one has no capture state")
def _(context):
    context.site = Site([_row("a", "full"), _row("b", "full"), _row("c", "thin"), _row("d", "running"), _row("e", None)])


@when('an editor searches with Captured "{choice}"')
def _(context, choice):
    context.last_choice = choice
    context.found = {item["reference"]["lineageId"] for item in _search(context, captured=choice)["items"]}


@then("the results are the two full References")
def _(context):
    assert context.found == {"a", "b"}, context.found


@then("the results are the thin, running and empty References")
def _(context):
    assert context.found == {"c", "d", "e"}, context.found


@then('a search cursor made with Captured "no" is refused for Captured "yes"')
def _(context):
    cursor = _search(context, captured="no", limit=1)["nextCursor"]
    try:
        _search(context, captured="yes", limit=1, cursor=cursor)
    except rs.SearchError:
        return
    raise AssertionError("the cursor was accepted")


def _rated_row(lineage, status, state=None):
    return {**_row(lineage, state), "feedStateKey": "c#rated", "curationStatus": status}


@given("searchable References where one is accepted and not captured, one is accepted and captured, one is rejected and not captured, and one is pending")
def _(context):
    context.site = Site([_rated_row("a", "accepted", "none"), _rated_row("b", "accepted", "full"), _rated_row("c", "rejected", "none"), _row("d", "none")])


@when('an editor searches with Reviewed "{show}" and Captured "{choice}"')
def _(context, show, choice):
    context.found = {item["reference"]["lineageId"] for item in _search(context, show=show, captured=choice)["items"]}


@then("the results are only the accepted Reference that is not captured")
def _(context):
    assert context.found == {"a"}, context.found


@then("the results are both accepted References and no rejected one")
def _(context):
    assert context.found == {"a", "b"}, context.found


@then('a search cursor made with Reviewed "accepted" is refused for Reviewed "rated"')
def _(context):
    cursor = _search(context, show="accepted", limit=1)["nextCursor"]
    try:
        _search(context, show="rated", limit=1, cursor=cursor)
    except rs.SearchError:
        return
    raise AssertionError("the cursor was accepted")
