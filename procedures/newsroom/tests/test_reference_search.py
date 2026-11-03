"""The References page search (``papyrus_knowledge_query.reference_search``): the word index, the meaning lane, fusion and the cursor.

Everything runs against a fake GraphQL list and a fake vector index, with synthetic data.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from papyrus_knowledge_query import cuts, lambda_handler, reference_search as rs  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_cache():
    rs.clear_meaning_cache()
    yield
    rs.clear_meaning_cache()


def row(lineage, title, *, authors=None, state="unrated", source=None, external=None, updated="2026-11-01T10:00:00.000Z", version=1, arrival=None, **extra):
    return {
        "id": f"{lineage}-v{version}", "lineageId": lineage, "versionNumber": version, "versionState": "current", "corpusId": "c",
        "externalItemId": external or f"ext-{lineage}", "title": title, "authors": authors or [], "sourceUri": source or f"https://example.test/{lineage}",
        "feedStateKey": None if state is None else f"c#{state}", "feedArrivalAt": arrival or updated, "updatedAt": updated,
        "curationStatus": {"unrated": "pending", "rated": "accepted"}.get(state, "pending"), **extra,
    }


class FakeSite:
    """A GraphQL endpoint holding Reference rows: pages of ``page`` rows, ascending by updatedAt, honouring the ``updatedAt.ge`` condition."""

    def __init__(self, rows, page=2):
        self.rows, self.page, self.calls = list(rows), page, []

    def graphql(self, query, variables):
        assert "listReferencesByVersionStateAndUpdatedAt" in query and variables["versionState"] == "current"
        self.calls.append(variables)
        rows = sorted(self.rows, key=lambda candidate: candidate["updatedAt"])
        bound = (variables.get("updatedAt") or {}).get("ge")
        if bound:
            rows = [candidate for candidate in rows if candidate["updatedAt"] >= bound]
        start = int(variables.get("nextToken") or 0)
        chunk = rows[start:start + self.page]
        more = start + self.page < len(rows)
        return {"listReferencesByVersionStateAndUpdatedAt": {"items": chunk, "nextToken": str(start + self.page) if more else None}}


class FakeVectors:
    def __init__(self, matches=None, error=None):
        self.matches, self.error, self.filters, self.top_ks, self.embedded = matches or [], error, [], [], []

    def embed_text(self, text):
        self.embedded.append(text)
        if self.error:
            raise self.error
        return [0.1, 0.2]

    def query_by_vector(self, vector, top_k, metadata_filter):
        self.top_ks.append(top_k)
        self.filters.append(metadata_filter)
        return [{"key": f"k-{lineage}", "distance": distance, "metadata": {"lineageId": lineage, "vectorKind": "reference_summary"}} for lineage, distance in self.matches]


def search(site, vectors, query, show="all", **extra):
    return rs.search_references({"query": query, "show": show, **extra}, graphql=site.graphql if site else None, vectors=vectors, index=rs.ReferenceWordIndex())


def titles(result):
    return [item["reference"]["title"] for item in result["items"]]


# --- the word index -------------------------------------------------------------------------------------------------------------------------

def test_the_first_query_reads_every_page_and_drops_references_in_no_feed():
    site = FakeSite([row("a", "Alpha"), row("b", "Beta"), row("c", "Gamma", state=None), row("d", "Delta"), row("e", "Epsilon")])
    index = rs.ReferenceWordIndex()
    assert index.refresh(site.graphql) == 5
    assert len(index) == 4   # the one with no feedStateKey is in no feed
    assert len(site.calls) == 3 and index.built_in_ms is not None   # three pages of two, and the cold build was timed


def test_later_queries_read_only_rows_changed_since_the_last_read():
    site = FakeSite([row("a", "Alpha", updated="2026-11-01T10:00:00.000Z"), row("b", "Beta", updated="2026-11-01T11:00:00.000Z")])
    index = rs.ReferenceWordIndex()
    index.refresh(site.graphql)
    site.calls.clear()
    site.rows.append(row("c", "Newly arrived", updated="2026-11-01T11:00:30.000Z"))
    assert index.refresh(site.graphql) == 2   # the overlap re-reads the last row, plus the new one
    assert site.calls[0]["updatedAt"] == {"ge": "2026-11-01T10:58:00.000Z"}   # watermark less the two-minute overlap
    assert [hit.lineage_id for hit in index.search("newly arrived", "all")] == ["c"]


def test_a_reference_updated_a_moment_ago_is_found_under_its_new_words():
    site = FakeSite([row("a", "Old title", updated="2026-11-01T10:00:00.000Z")])
    index = rs.ReferenceWordIndex()
    index.refresh(site.graphql)
    assert index.search("fresh", "all") == []
    site.rows[0] = row("a", "Fresh title", updated="2026-11-01T10:00:05.000Z", version=2)
    index.refresh(site.graphql)
    assert [hit.lineage_id for hit in index.search("fresh", "all")] == ["a"] and index.search("old", "all") == []


def test_an_archived_reference_leaves_the_index_and_an_older_version_never_replaces_a_newer_one():
    site = FakeSite([row("a", "Alpha story", updated="2026-11-01T10:00:00.000Z", version=2)])
    index = rs.ReferenceWordIndex()
    index.refresh(site.graphql)
    index.upsert(row("a", "Stale alpha", version=1))
    assert index.row("a")["title"] == "Alpha story"
    site.rows[0] = row("a", "Alpha story", state=None, updated="2026-11-01T10:05:00.000Z", version=2)
    index.refresh(site.graphql)
    assert index.search("alpha", "all") == []


def test_word_matches_come_in_the_order_exact_phrase_all_in_title_all_across_fields_partial():
    site = FakeSite([
        row("partial", "Memory for robots", updated="2026-11-01T10:00:01.000Z"),
        row("fields", "Notes on recall", authors=["Agent Memory Lab"], updated="2026-11-01T10:00:02.000Z"),
        row("titleall", "Memory in the agent loop", updated="2026-11-01T10:00:03.000Z"),
        row("phrase", "Long agent memory systems", updated="2026-11-01T10:00:04.000Z"),
    ], page=10)
    result = search(site, None, "agent memory")
    assert [item["reference"]["lineageId"] for item in result["items"]] == ["phrase", "titleall", "fields", "partial"]
    assert result["items"][0]["matchedFields"] == ["title"]
    assert result["items"][2]["matchedFields"] == ["authors"]   # "Notes on recall" holds neither word; the author line holds both

    assert result["lanes"]["keyword"] == {"status": "ok"}


def test_authors_urls_ids_accents_and_word_beginnings_are_searched():
    site = FakeSite([
        row("author", "A study", authors=["Zoë Q. Álvarez"]),
        row("url", "Another", source="https://arxiv.example.org/abs/2411.01234"),
        row("id", "Third", external="doi:10.1000/xyz123"),
    ], page=10)
    assert search(site, None, "zoe alvarez")["items"][0]["reference"]["lineageId"] == "author"
    assert search(site, None, "2411.01234")["items"][0]["reference"]["lineageId"] == "url"
    assert search(site, None, "xyz123")["items"][0]["reference"]["lineageId"] == "id"
    assert search(site, None, "alvar")["items"][0]["matchedFields"] == ["authors"]   # the beginning of a word, as one types it
    assert search(site, None, "xy")["items"] == []   # under three characters a term must match a whole word


def test_show_limits_the_words_lane_to_unrated_or_rated():
    site = FakeSite([row("u", "Shared word", state="unrated"), row("r", "Shared word again", state="rated")], page=10)
    assert [item["reference"]["lineageId"] for item in search(site, None, "shared", show="unrated")["items"]] == ["u"]
    assert [item["reference"]["lineageId"] for item in search(site, None, "shared", show="rated")["items"]] == ["r"]
    assert len(search(site, None, "shared", show="all")["items"]) == 2


# --- the meaning lane ------------------------------------------------------------------------------------------------------------------------

def test_the_meaning_lane_asks_for_summary_vectors_in_the_shown_states_and_cuts_at_the_knee():
    site = FakeSite([row(name, f"Unrelated {name}", state="rated") for name in "abcdef"], page=10)
    matches = [("a", 0.05), ("b", 0.08), ("c", 0.12), ("d", 0.50), ("e", 0.52), ("f", 0.55)]   # similarity falls off a cliff after the third
    vectors = FakeVectors(matches)
    result = search(site, vectors, "ideas about thinking machines", show="rated")
    assert [item["reference"]["lineageId"] for item in result["items"]] == ["a", "b", "c"]
    assert all(item["matchedBy"] == ["meaning"] and item["matchedFields"] == [] for item in result["items"])
    assert vectors.top_ks == [100]
    assert vectors.filters[0] == {"$and": [{"vectorKind": {"$eq": "reference_summary"}}, {"curationStatus": {"$in": ["accepted", "rejected"]}}]}


def test_the_meaning_lane_dedupes_by_lineage_and_ignores_references_in_no_feed():
    site = FakeSite([row("a", "Unrelated a"), row("gone", "Unrelated gone", state=None)], page=10)
    result = search(site, FakeVectors([("a", 0.1), ("a", 0.2), ("gone", 0.15), ("missing", 0.3)]), "meaning only")
    assert [item["reference"]["lineageId"] for item in result["items"]] == ["a"]


def test_meaning_results_follow_the_show_choice_even_if_a_vector_is_stale():
    site = FakeSite([row("u", "Unrelated u", state="unrated"), row("r", "Unrelated r", state="rated")], page=10)
    result = search(site, FakeVectors([("u", 0.1), ("r", 0.11)]), "meaning only", show="unrated")
    assert [item["reference"]["lineageId"] for item in result["items"]] == ["u"]


# --- fusion -----------------------------------------------------------------------------------------------------------------------------------

def test_a_match_on_both_lanes_ranks_first_and_says_so_and_strong_word_matches_beat_meaning_only():
    site = FakeSite([
        row("both", "Agent memory, revisited", updated="2026-11-01T10:00:01.000Z"),
        row("words", "Agent memory in brief", updated="2026-11-01T10:00:02.000Z"),
        row("meaning", "Recollection in software", updated="2026-11-01T10:00:03.000Z"),
    ], page=10)
    vectors = FakeVectors([("meaning", 0.05), ("both", 0.06), ("far1", 0.5), ("far2", 0.51)])   # two near, then a cliff
    result = search(site, vectors, "agent memory")
    assert [item["reference"]["lineageId"] for item in result["items"]] == ["both", "words", "meaning"]
    assert [item["matchedBy"] for item in result["items"]] == [["keyword", "meaning"], ["keyword"], ["meaning"]]


def test_a_partial_word_match_does_not_outrank_a_better_meaning_rank_but_a_strong_one_always_does():
    words = [rs.WordHit("some", rs.SOME_TERMS, 1, 4, 1), rs.WordHit("all", rs.ALL_TERMS_ACROSS_FIELDS, 2, 4, 1)]
    fused = rs.fuse(words, [("m1", 0.9), ("m2", 0.8), ("some", 0.7)])
    assert [entry.lineage_id for entry in fused] == ["all", "some", "m1", "m2"]
    assert fused[0].strong and not fused[1].strong
    assert fused[1].score == pytest.approx(1 / 61 + 1 / 63)   # 'some' is words rank 1 and meaning rank 3: reciprocal rank fusion, k = 60


# --- long questions: meaning above partial words ---------------------------------------------------------------------------------------------------

QUESTION = "why do neural networks forget earlier training"


def forgetting_site():
    """A site where generic title words are everywhere: 40 'neural networks' titles and 20 'training' titles, a few real answers."""
    rows = [row(f"generic{n}", f"Neural networks for task {n}", updated=f"2026-11-01T10:{n:02d}:00.000Z") for n in range(40)]
    rows += [row(f"training{n}", f"Training tips number {n}", updated=f"2026-11-01T11:{n:02d}:00.000Z") for n in range(20)]
    rows += [
        row("wide", "Wide Neural Networks Forget Less Catastrophically", updated="2026-11-01T12:00:00.000Z"),
        row("interference", "Interference between old and new tasks in continual learning", updated="2026-11-01T12:01:00.000Z"),
        row("replay", "Replay buffers keep earlier lessons alive", updated="2026-11-01T12:02:00.000Z"),
        row("unrelated", "A history of the telegraph", updated="2026-11-01T12:03:00.000Z"),
    ]
    return FakeSite(rows, page=100)


def smooth_tail(start=0.50, end=0.40, count=60):
    """Distances for far neighbours (not Reference rows in the index) falling off smoothly, as real neighbour lists do."""
    return [(f"far{n}", 1 - (start - (start - end) * (1 - math.exp(-n / 10)))) for n in range(count)]


def test_the_largest_drop_cut_keeps_one_hit_of_a_realistic_neighbour_list_and_the_search_cut_keeps_the_bend():
    # One hit stands clear, then the scores fall smoothly: the shape of a real neighbour list for a question.
    similarities = [0.62] + [0.50 - 0.10 * (1 - math.exp(-n / 15)) for n in range(99)]
    assert cuts.knee_cut_count(similarities) == 1   # why the meaning lane contributed one card, the one the words lane already had
    kept = cuts.search_cut_count(similarities)
    assert 5 < kept < len(similarities)
    # The cliff and plateau cases still cut where one expects, and a flat or tiny list is kept whole.
    assert cuts.search_cut_count([0.95, 0.92, 0.88, 0.5, 0.48, 0.45]) == 3
    assert cuts.search_cut_count([0.9] * 5 + [0.3] * 5) == 5
    assert cuts.search_cut_count([0.5] * 8) == 8 and cuts.search_cut_count([0.5, 0.4]) == 2 and cuts.search_cut_count([]) == 0


def test_a_long_question_ranks_meaning_matches_above_single_common_word_title_matches():
    site = forgetting_site()
    matches = [("interference", 0.30), ("replay", 0.32), ("wide", 0.33)] + smooth_tail(start=0.50)
    result = search(site, FakeVectors(matches), QUESTION)
    ids = [item["reference"]["lineageId"] for item in result["items"]]
    assert set(ids[:3]) == {"wide", "interference", "replay"} and ids[0] == "wide"   # words and meaning together, then meaning alone
    assert result["items"][0]["matchedBy"] == ["keyword", "meaning"]
    assert [item["matchedBy"] for item in result["items"][1:3]] == [["meaning"], ["meaning"]]
    assert not any(lineage.startswith(("generic", "training")) for lineage in ids)   # "neural", "networks" and "training" alone are not an answer
    assert result["lanes"]["meaning"] == {"status": "ok"}


def test_a_partial_match_covering_few_of_a_long_querys_distinctive_terms_is_dropped_and_rare_terms_weigh_more():
    site = forgetting_site()
    index = rs.ReferenceWordIndex()
    index.refresh(site.graphql)
    hits = {hit.lineage_id: hit for hit in index.search(QUESTION, "all")}
    assert "generic0" not in hits and "training0" not in hits and "wide" in hits and hits["wide"].coverage >= rs.PARTIAL_COVERAGE_FLOOR
    # A short query keeps every partial match, but the rarer word ranks above the common one.
    ordered = [hit.lineage_id for hit in index.search("neural forget", "all")]
    assert ordered[0] == "wide" and "generic0" in ordered   # "wide" holds both, the generic ones only the common word
    assert index.search("neural replay", "all")[0].lineage_id == "replay"   # one rare word outweighs one word in most titles


def test_question_words_are_not_searched_but_a_query_of_only_them_still_is():
    assert rs.query_terms(QUESTION) == ["neural", "networks", "forget", "earlier", "training"]
    assert rs.query_terms("why do") == ["why", "do"]


def test_an_exact_title_phrase_and_all_terms_in_title_or_author_rank_above_meaning_matches():
    site = FakeSite([
        row("both", "Goodbye telegraph", authors=["Ada Hinton"], updated="2026-11-01T10:00:01.000Z"),
        row("phrase", "Hinton goodbye", updated="2026-11-01T10:00:02.000Z"),
        row("meaning", "Unrelated", updated="2026-11-01T10:00:03.000Z"),
    ], page=10)
    result = search(site, FakeVectors([("meaning", 0.1)] + smooth_tail()), "hinton goodbye")
    assert [item["reference"]["lineageId"] for item in result["items"]] == ["phrase", "both", "meaning"]


def test_a_one_word_author_search_is_unchanged_by_the_meaning_lane():
    authored = [row(f"hinton{n}", f"Paper {n}", authors=["Geoffrey Hinton"], updated=f"2026-11-01T10:0{n}:00.000Z") for n in range(7)]
    site = FakeSite(authored + [row("other", "Boltzmann machines"), row("sem", "Learning representations")], page=100)
    words_only = search(site, None, "Hinton")
    with_meaning = search(site, FakeVectors([("sem", 0.2), ("other", 0.21)] + smooth_tail()), "Hinton")
    assert [i["reference"]["lineageId"] for i in words_only["items"]] == [f"hinton{n}" for n in range(6, -1, -1)]
    assert all("authors" in i["matchedFields"] for i in words_only["items"])   # the test ids also put "hinton" in each link
    assert [i["reference"]["lineageId"] for i in with_meaning["items"]][:7] == [i["reference"]["lineageId"] for i in words_only["items"]]
    assert [i["reference"]["lineageId"] for i in with_meaning["items"]][7:] == ["sem", "other"]   # meaning only after every author match


def test_a_long_question_with_meaning_down_still_returns_the_word_results_that_cover_it():
    result = search(forgetting_site(), FakeVectors(error=RuntimeError("connection reset by peer")), QUESTION)
    assert titles(result) == ["Wide Neural Networks Forget Less Catastrophically"]   # the generic single-word title matches stay out
    assert result["lanes"]["keyword"] == {"status": "ok"} and result["lanes"]["meaning"]["status"] == "failed"


# --- the cursor and the page -------------------------------------------------------------------------------------------------------------------

def test_paging_never_repeats_a_card_and_ends():
    site = FakeSite([row(f"r{n}", f"Shared topic {n}", updated=f"2026-11-01T10:{n:02d}:00.000Z") for n in range(30)], page=10)
    index = rs.ReferenceWordIndex()
    seen, cursor, pages = [], None, 0
    while True:
        extra = {"cursor": cursor} if cursor else {}
        result = rs.search_references({"query": "shared topic", "limit": 7, **extra}, graphql=site.graphql, vectors=None, index=index)
        seen += [item["reference"]["lineageId"] for item in result["items"]]
        pages += 1
        cursor = result["nextCursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 30 and pages == 5


def test_a_cursor_from_another_search_or_a_garbled_one_is_refused():
    cursor = rs.encode_cursor(24, "agent memory", "all")
    assert rs.decode_cursor(cursor, "agent memory", "all") == 24
    assert rs.decode_cursor(cursor, "  Agent   Memory ", "all") == 24   # the same search, spelled differently
    with pytest.raises(rs.SearchError):
        rs.decode_cursor(cursor, "another query", "all")
    with pytest.raises(rs.SearchError):
        rs.decode_cursor(cursor, "agent memory", "rated")
    with pytest.raises(rs.SearchError):
        rs.decode_cursor("not-a-cursor", "agent memory", "all")


def test_limit_show_and_empty_queries():
    site = FakeSite([row("a", "Alpha")], page=10)
    assert search(site, None, "   ")["items"] == []
    assert search(site, None, "the of")["items"] == []   # only stop words: they are searched as they are, and nothing holds them
    with pytest.raises(rs.SearchError):
        search(site, None, "alpha", show="rejected")


# --- one lane failing --------------------------------------------------------------------------------------------------------------------------

def test_a_meaning_failure_still_returns_the_word_results_with_its_status():
    site = FakeSite([row("a", "Agent memory")], page=10)
    result = search(site, FakeVectors(error=RuntimeError("OPENAI_API_KEY is required for S3VectorsProvider embeddings")), "agent memory")
    assert titles(result) == ["Agent memory"]
    assert result["lanes"]["keyword"] == {"status": "ok"}
    assert result["lanes"]["meaning"] == {"status": "failed", "message": "Meaning search is not set up for this site."}


def test_a_word_failure_still_returns_the_meaning_results():
    site = FakeSite([row("a", "Agent memory")], page=10)

    def broken(query, variables):
        raise RuntimeError("AppSync is down")

    index = rs.ReferenceWordIndex()
    index.upsert(row("a", "Unrelated"))
    result = rs.search_references({"query": "agent memory"}, graphql=broken, vectors=FakeVectors([("a", 0.1)]), index=index)
    assert titles(result) == ["Unrelated"] and result["lanes"]["keyword"]["status"] == "failed" and result["lanes"]["meaning"] == {"status": "ok"}


def test_both_lanes_failing_returns_no_cards_and_two_failed_statuses():
    result = rs.search_references({"query": "agent"}, graphql=None, vectors=None, index=rs.ReferenceWordIndex())
    assert result["items"] == [] and result["lanes"]["keyword"]["status"] == "failed" and result["lanes"]["meaning"]["status"] == "failed"


# --- the Lambda ---------------------------------------------------------------------------------------------------------------------------------

def test_only_editors_and_admins_may_search():
    rs.require_editor({"arguments": {}})   # a call with no identity is a local run, not AppSync
    rs.require_editor({"identity": {"groups": ["editor"]}})
    rs.require_editor({"identity": {"groups": ["reader", "admin"]}})
    for identity in ({"groups": ["reader"]}, {"groups": []}, {"groups": None}, {}):
        with pytest.raises(rs.SearchError, match="Not Authorized"):
            rs.require_editor({"identity": identity})


def test_the_lambda_answers_searchReferences_by_field_name_and_everything_else_as_knowledgeQuery(monkeypatch):
    site = FakeSite([row("a", "Agent memory")], page=10)

    class Services:
        graph = type("Graph", (), {"graphql": staticmethod(site.graphql)})()
        semantic = None

    monkeypatch.setattr(lambda_handler, "build_environment_services", lambda event: Services())
    monkeypatch.setattr(rs, "_index", rs.ReferenceWordIndex())
    monkeypatch.setattr(lambda_handler, "run_knowledge_query", lambda payload, services: {"asked": "knowledgeQuery"})
    event = {"info": {"fieldName": "searchReferences"}, "identity": {"groups": ["editor"]}, "arguments": {"input": '{"query": "agent memory"}'}}
    result = lambda_handler.handler(event)
    assert titles(result) == ["Agent memory"] and result["lanes"]["meaning"]["status"] == "failed"
    assert lambda_handler.handler({"info": {"fieldName": "knowledgeQuery"}, "arguments": {"input": "{}"}}) == {"asked": "knowledgeQuery"}
    # Amplify's Lambda resolvers send the field at the top of the event, with no `info`.
    top_level = {"fieldName": "searchReferences", "identity": {"claims": {"cognito:groups": ["editor"]}}, "arguments": event["arguments"]}
    assert titles(lambda_handler.handler(top_level)) == ["Agent memory"]
    assert lambda_handler.handler({"fieldName": "knowledgeQuery", "arguments": {"input": "{}"}}) == {"asked": "knowledgeQuery"}
    with pytest.raises(rs.SearchError):
        lambda_handler.handler({**event, "identity": {"groups": ["reader"]}})
