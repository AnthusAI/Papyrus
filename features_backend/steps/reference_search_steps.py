"""Steps for the References page search (``papyrus_knowledge_query.reference_search``). Synthetic data, in-memory site and vector index."""
import re
import shlex
import sys
import tempfile
from pathlib import Path

import pytest
from behave import given, when, then

from papyrus_knowledge_query import reference_search as rs
from procedures.newsroom.tests.test_monitoring_view_cli import Env, graphql_answer
from procedures.newsroom.tests.test_reference_search import FakeSite, FakeVectors, row

UNRATED_ROW = "Persistent notebooks for agents"


def _site(context, rows, page=100, vectors=None):
    rs.clear_meaning_cache()
    context.site = FakeSite(rows, page=page)
    context.vectors = vectors


def _search(context, query, show="all", **extra):
    context.result = rs.search_references({"query": query, "show": show, **extra}, words=context.site.source if context.site else None, vectors=context.vectors)
    return context.result


def _ids(result):
    return [item["reference"]["lineageId"] for item in result["items"]]


@given('a site with an unrated, an accepted and a rejected Reference, the rejected one by "Marta Okafor"')
def three_states(context):
    _site(context, [
        row("rejected", "Notes on tool use in practice", state="rated", authors=["Marta Okafor"], curationStatus="rejected"),
        row("accepted", "Retrieval for long documents", state="rated", curationStatus="accepted"),
        row("unrated", UNRATED_ROW, state="unrated"),
    ])


@when('an editor searches all References for "{query}"')
def search_all(context, query):
    _search(context, query)


@when('an editor searches unrated References for "{query}"')
def search_unrated(context, query):
    _search(context, query, show="unrated")


STAR_TITLES = ["alpha", "beta", "gamma", "delta", "epsilon"]


@given("a site of five References that share a word, with stars of 5, 3, none, 5 and 2 and arrivals one day apart, oldest first")
def star_site(context):
    stars = [5, 3, None, 5, 2]
    _site(context, [
        row(name, f"Topic {name}", arrival=f"2026-11-0{number}T10:00:00.000Z", starRating=rating)
        for number, (name, rating) in enumerate(zip(STAR_TITLES, stars), start=1)
    ])


@when('an editor searches all References for "{query}" ordered newest first')
def search_newest(context, query):
    _search(context, query, sort="newest")


@when('an editor searches all References for "{query}" ordered by quality')
def search_quality(context, query):
    _search(context, query, sort="quality")


@when('an editor searches all References for "{query}" ordered newest first with at least {stars:d} stars')
def search_newest_minimum(context, query, stars):
    _search(context, query, sort="newest", minStars=stars)


@when('an editor searches all References for "{query}" ordered by quality with at least {stars:d} stars, two at a time')
def search_quality_paged(context, query, stars):
    context.paged = {"query": query, "sort": "quality", "minStars": stars}
    context.first_page = _search(context, query, sort="quality", minStars=stars, limit=2)


@then("the results are the five References, latest arrival first")
def results_newest(context):
    assert _ids(context.result) == ["epsilon", "delta", "gamma", "beta", "alpha"], _ids(context.result)


@then("the results are the two 5-star References newest first, then 3 stars, then 2 stars, then the one with no stars")
def results_quality(context):
    assert _ids(context.result) == ["delta", "alpha", "beta", "epsilon", "gamma"], _ids(context.result)


@then("the results are the two 5-star References, newest first")
def results_five(context):
    assert _ids(context.result) == ["delta", "alpha"], _ids(context.result)


@then("a minimum of 2 stars is refused, because only 3, 4 and 5 are minimums")
def minimum_refused(context):
    with pytest.raises(rs.SearchError):
        _search(context, "topic", minStars=2)


@then("the next page continues that ordering")
def next_page_continues(context):
    cursor = context.first_page["nextCursor"]
    assert _ids(context.first_page) == ["delta", "alpha"] and cursor
    second = _search(context, context.paged["query"], sort="quality", minStars=3, limit=2, cursor=cursor)
    assert _ids(second) == ["beta"] and second["nextCursor"] is None, _ids(second)


@then("the same cursor is refused for another ordering or minimum")
def cursor_refused_elsewhere(context):
    cursor = context.first_page["nextCursor"]
    for extra in ({"sort": "newest", "minStars": 3}, {"sort": "quality", "minStars": 4}, {"sort": "quality"}):
        with pytest.raises(rs.SearchError):
            _search(context, context.paged["query"], limit=2, cursor=cursor, **extra)


@then("the rejected Reference is the only result, found by words in its authors")
def only_rejected(context):
    assert _ids(context.result) == ["rejected"]
    item = context.result["items"][0]
    assert item["matchedBy"] == ["keyword"] and item["matchedFields"] == ["authors"]
    assert item["reference"]["curationStatus"] == "rejected"


@then("it carries its whole record, so the page can draw an ordinary card")
def whole_record(context):
    reference = context.result["items"][0]["reference"]
    for name in ("id", "lineageId", "title", "authors", "sourceUri", "curationStatus", "feedStateKey", "versionNumber"):
        assert name in reference, name


@then("the unrated Reference is the only result, found by words in its title")
def only_unrated(context):
    assert _ids(context.result) == ["unrated"]
    assert context.result["items"][0]["matchedFields"] == ["title"]


@then("choosing rated References instead finds nothing for that word")
def rated_finds_nothing(context):
    assert _search(context, "notebooks", show="rated")["items"] == []


@given('a site where a Reference about agent recall has no words in common with "long-term remembering"')
def recall_site(context):
    vectors = FakeVectors([("recall", 0.05), ("far1", 0.6), ("far2", 0.61), ("far3", 0.62)])
    _site(context, [row("recall", "Recall in assistants that run for months", state="rated")], vectors=vectors)


@then("that Reference is a result, found by meaning and not by words")
def found_by_meaning(context):
    assert _ids(context.result) == ["recall"]
    item = context.result["items"][0]
    assert item["matchedBy"] == ["meaning"] and item["matchedFields"] == []


@then("the vector index was asked for summary vectors in the unrated, accepted and rejected states, at most 100")
def asked_filter(context):
    assert context.vectors.top_ks == [100]
    assert context.vectors.filters == [{"$and": [{"vectorKind": {"$eq": "reference_summary"}}, {"curationStatus": {"$in": ["pending", "accepted", "rejected"]}}]}]


@given("a site with one Reference whose title has the words and whose summary has the meaning, one with only the words, and one with only the meaning")
def both_site(context):
    vectors = FakeVectors([("meaning", 0.05), ("both", 0.06), ("far1", 0.5), ("far2", 0.51)])
    _site(context, [
        row("both", "Agent memory, revisited", updated="2026-11-01T10:00:01.000Z"),
        row("words", "Agent memory in brief", updated="2026-11-01T10:00:02.000Z"),
        row("meaning", "Recollection in software", updated="2026-11-01T10:00:03.000Z"),
    ], vectors=vectors)


@then("the Reference found both ways is first and says it was found by words and by meaning")
def both_first(context):
    assert _ids(context.result)[0] == "both" and context.result["items"][0]["matchedBy"] == ["keyword", "meaning"]


@then("the Reference found only by words is next, and the one found only by meaning is last")
def words_then_meaning(context):
    assert _ids(context.result) == ["both", "words", "meaning"]
    assert [item["matchedBy"] for item in context.result["items"][1:]] == [["keyword"], ["meaning"]]


@given("a site where the vector index cannot be reached")
def vectors_down(context):
    _site(context, [row("unrated", UNRATED_ROW)], vectors=FakeVectors(error=RuntimeError("connection reset by peer")))


@then("the word results are returned")
def word_results(context):
    assert _ids(context.result) == ["unrated"]


@then("the answer says the word search worked and the meaning search failed, in a sentence that is safe to show")
def lanes_say(context):
    lanes = context.result["lanes"]
    assert lanes["keyword"] == {"status": "ok"}
    assert lanes["meaning"] == {"status": "failed", "message": "Meaning search could not be reached."}
    assert "connection reset" not in str(lanes)


@given("a site where neither the References nor the vector index can be reached")
def all_down(context):
    rs.clear_meaning_cache()
    context.site, context.vectors = None, FakeVectors(error=RuntimeError("down"))


@then("no cards are returned and both searches are reported as failed")
def nothing(context):
    assert context.result["items"] == []
    assert context.result["lanes"]["keyword"]["status"] == context.result["lanes"]["meaning"]["status"] == "failed"


@given("a site with 60 References that share a phrase")
def sixty(context):
    _site(context, [row(f"r{n:02d}", f"Shared phrase number {n}", updated=f"2026-11-01T10:{n:02d}:00.000Z", state=("rated", "unrated")[n % 2]) for n in range(60)], page=25)


@when("an editor reads every page of 24 for that phrase, following the cursor each time")
def read_pages(context):
    seen, cursor, pages = [], None, 0
    while True:
        result = _search(context, "shared phrase", **({"cursor": cursor} if cursor else {}))
        seen += _ids(result)
        pages += 1
        cursor = result["nextCursor"]
        if not cursor:
            break
    context.seen, context.pages, context.cursor = seen, pages, rs.encode_cursor(24, "shared phrase", "all")


@then("every Reference appears exactly once and the last page has no cursor")
def exactly_once(context):
    assert len(context.seen) == len(set(context.seen)) == 60 and context.pages == 3 and context.result["nextCursor"] is None


@then("a cursor from a different search or show choice is refused")
def foreign_cursor(context):
    for query, show in (("another phrase", "all"), ("shared phrase", "rated")):
        with pytest.raises(rs.SearchError):
            rs.search_references({"query": query, "show": show, "cursor": context.cursor}, words=context.site.source if context.site else None, vectors=None)


@given("a site whose word table follows its References")
def follows(context):
    _site(context, [row("z", "Settled", updated="2026-11-01T09:00:00.000Z"), row("a", "Old title", updated="2026-11-01T10:00:00.000Z")], page=100)


@when("a Reference's title changes and an editor searches for its new title")
def title_changes(context):
    old = context.site.rows["a"]
    context.site.change(old, row("a", "Fresh title", updated="2026-11-01T10:30:05.000Z", version=2))   # the stream record: a new version of the same lineage
    context.site.change(old, {**old, "versionState": "superseded"})
    context.fresh = _search(context, "fresh")


@then("it is found under the new title and not the old one")
def new_title(context):
    assert _ids(context.fresh) == ["a"] and _search(context, "old")["items"] == []


@given("a site with 300 References, six of which share one word")
def three_hundred(context):
    _site(context, [row(f"r{n}", f"Story number {n} about {'sound' if n % 50 == 0 else 'filler'}") for n in range(300)])


@when("an editor searches for that word")
def search_that_word(context):
    _search(context, "sound")


@then("six cards are returned")
def six_cards(context):
    assert len(context.result["items"]) == 6


@then("the search read six word rows and the six Reference rows they pointed at, and nothing else")
def only_matched(context):
    assert context.site.dynamo.items_read == 12 and {operation for operation, _table in context.site.dynamo.requests} <= {"query", "batch_get_item"}


@given('a site where a video\'s title holds the word "sound" among many other results the meaning search prefers')
def sound_site(context):
    from procedures.newsroom.tests.test_reference_search import smooth_tail

    others = [row(f"other{n}", f"Another story about location tracking {n}", state="rated", curationStatus="accepted") for n in range(40)]
    _site(context, others + [row("sound", "I discovered a sound that leaks your exact location", state="unrated")],
          vectors=FakeVectors([(f"other{n}", 0.1 + n / 1000) for n in range(40)] + smooth_tail()), page=5)


@then("the video is the first result, found by words in its title")
def video_first(context):
    first = context.result["items"][0]
    assert first["reference"]["lineageId"] == "sound" and first["matchedBy"] == ["keyword"] and "title" in first["matchedFields"]


@given("the search is asked for through an Amplify resolver by an editor")
def amplify_event(context):
    context.event = {"fieldName": "searchReferences", "identity": {"claims": {"cognito:groups": ["editor"]}}, "arguments": {"input": "{}"}}


@then("the search runs instead of the knowledge query")
def search_runs(context):
    from papyrus_knowledge_query import lambda_handler, reference_search

    assert lambda_handler._field_name(context.event) == "searchReferences"
    reference_search.require_editor(context.event)


@given("the search is asked for by someone in the reader group")
def reader(context):
    context.event = {"info": {"fieldName": "searchReferences"}, "identity": {"groups": ["reader"]}}


@then("the search is refused with a Not Authorized message")
def refused(context):
    with pytest.raises(rs.SearchError, match="Not Authorized"):
        rs.require_editor(context.event)


@then("the deployed schema allows only the editor and admin groups to ask, and no guest or identity-pool access")
def schema_groups(context):
    for name in ("schema.ts", "resource.ts"):
        source = (context.repo_root / "amplify" / "data" / name).read_text()
        block = source[source.index("  searchReferences: a"):]
        block = block[: block.index("\n\n")]
        assert 'allow.groups(categoryWriteGroups)' in block and ".query()" in block, name
        assert "guest" not in block and "authenticated" not in block and "publicApiKey" not in block, name
    assert re.search(r'const categoryWriteGroups = \["editor", "admin"\];', (context.repo_root / "amplify/data/schema.ts").read_text())


@given("a signed-in editor with no AWS credentials and no AWS library, who can search References")
def signed_in(context):
    temporary = tempfile.TemporaryDirectory()
    context.add_cleanup(temporary.cleanup)
    context.monkeypatch = pytest.MonkeyPatch()
    context.add_cleanup(context.monkeypatch.undo)
    context.env = Env(Path(temporary.name), context.monkeypatch)
    from procedures.newsroom.tests.test_references_search_cli import RESULT
    context.env.answer = graphql_answer("searchReferences", RESULT)


@when('the editor searches References from the command line with "papyrus {command}"')
def run_cli(context, command):
    words = shlex.split(command)
    assert words[:2] == ["references", "search"]
    context.cli = context.env.run(words[1:], context.monkeypatch, group=("references",))


@then("the command succeeds and lists each Reference with how it matched")
def lists(context):
    code, out, err = context.cli
    assert code == 0 and err == "" and "Matched: title, author and meaning" in out and "Matched: meaning" in out


@then("every request sent was a query, never a mutation, and carried the editor's sign-in token and no AWS signature")
def queries_only(context):
    assert context.env.requests
    for _method, body, headers in context.env.requests:
        assert body["query"].lstrip().startswith("query ") and "mutation" not in body["query"].lower()
        assert headers["Authorization"] and not [name for name in headers if name.lower().startswith("x-amz")]
    assert not [name for name in ("boto3", "botocore") if sys.modules.get(name) is not None]


QUESTION = "why do neural networks forget earlier training"


@given('a site of 60 References with common title words, and three that answer "{query}" by meaning')
def forgetting_site(context, query):
    from procedures.newsroom.tests.test_reference_search import forgetting_site as build, smooth_tail

    context.question = query
    site = build()
    _site(context, list(site.rows.values()), vectors=FakeVectors([("interference", 0.30), ("replay", 0.32), ("wide", 0.33)] + smooth_tail()))


@given("the vector index cannot be reached")
def question_vectors_down(context):
    context.vectors = FakeVectors(error=RuntimeError("connection reset by peer"))


@then("the answers come first, the one found by words and meaning leading and the other two found by meaning")
def answers_first(context):
    ids = _ids(context.result)
    assert ids[0] == "wide" and set(ids[:3]) == {"wide", "interference", "replay"}
    assert [item["matchedBy"] for item in context.result["items"][:3]] == [["keyword", "meaning"], ["meaning"], ["meaning"]]


@then('no Reference that only shares "neural", "networks" or "training" in its title is listed')
def no_generic(context):
    assert not [lineage for lineage in _ids(context.result) if lineage.startswith(("generic", "training"))]


@then("only the Reference whose title covers most of the question's distinctive words is returned, and the meaning search is reported as failed")
def only_covering(context):
    assert _ids(context.result) == ["wide"] and context.result["lanes"]["meaning"]["status"] == "failed"


@given("a site with 7 Hinton papers and two other References the meaning search would add")
def hinton_site(context):
    from procedures.newsroom.tests.test_reference_search import smooth_tail

    rows = [row(f"hinton{n}", f"Paper {n}", authors=["Geoffrey Hinton"], updated=f"2026-11-01T10:0{n}:00.000Z") for n in range(7)]
    rows += [row("other", "Boltzmann machines"), row("sem", "Learning representations")]
    _site(context, rows, vectors=FakeVectors([("sem", 0.2), ("other", 0.21)] + smooth_tail()))
    context.words_only = rs.search_references({"query": "Hinton", "show": "all"}, words=context.site.source if context.site else None, vectors=None)


@then("the 7 author matches come first in the same order as with the word search alone")
def authors_first(context):
    assert _ids(context.result)[:7] == _ids(context.words_only) and len(_ids(context.words_only)) == 7


@then("the meaning matches follow them")
def meaning_follows(context):
    assert _ids(context.result)[7:] == ["sem", "other"]
