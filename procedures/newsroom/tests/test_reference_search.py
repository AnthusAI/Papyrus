"""The References page search (``papyrus_knowledge_query.reference_search``): the word index, the meaning lane, fusion and the cursor.

Everything runs against a fake DynamoDB (a word table and a Reference table that count requests) and a fake vector index, with synthetic data.
"""
from __future__ import annotations

import re
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from papyrus_knowledge_query import cuts, lambda_handler, reference_search as rs, reference_words  # noqa: E402


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


class ConditionalCheckFailed(Exception):
    pass


class FakeTable:
    def __init__(self, dynamo, name):
        self.dynamo, self.name = dynamo, name
        self.items = dynamo.tables.setdefault(name, {})

    def query(self, KeyConditionExpression, ExpressionAttributeValues, ExpressionAttributeNames=None, ExclusiveStartKey=None):
        # DynamoDB refuses a key condition that names a reserved word (shard is one) without an alias; the live backend failed this way, so the fake does too.
        for reserved in ("shard", "entry"):
            bare = re.sub(r"#\w+", "", KeyConditionExpression)
            assert reserved not in bare.split(), f"bare {reserved!r} in the key condition: DynamoDB would reject it"
        assert KeyConditionExpression == "#shard = :s AND begins_with(#entry, :p)"
        assert ExpressionAttributeNames == {"#shard": "shard", "#entry": "entry"}
        shard, prefix = ExpressionAttributeValues[":s"], ExpressionAttributeValues[":p"]
        keys = sorted(key for key in self.items if key[0] == shard and key[1].startswith(prefix))
        if ExclusiveStartKey:
            keys = [key for key in keys if key > (ExclusiveStartKey["shard"], ExclusiveStartKey["entry"])]
        page, more = keys[:self.dynamo.page], len(keys) > self.dynamo.page
        self.dynamo.record("query", self.name, len(page))
        return {"Items": [dict(self.items[key]) for key in page],
                "LastEvaluatedKey": {"shard": page[-1][0], "entry": page[-1][1]} if more else None}

    def _guard(self, key, version):
        held = self.items.get(key)
        if held is not None and not int(held["versionNumber"]) <= version:
            raise ConditionalCheckFailed()

    def put_item(self, Item, ConditionExpression, ExpressionAttributeValues):
        key = (Item["shard"], Item["entry"])
        self._guard(key, ExpressionAttributeValues[":v"])
        self.items[key] = dict(Item)
        self.dynamo.record("put_item", self.name, 0)

    def delete_item(self, Key, ConditionExpression, ExpressionAttributeValues):
        key = (Key["shard"], Key["entry"])
        self._guard(key, ExpressionAttributeValues[":v"])
        self.items.pop(key, None)
        self.dynamo.record("delete_item", self.name, 0)

    def get_item(self, Key):
        self.dynamo.record("get_item", self.name, 0)
        held = self.items.get((Key["shard"], Key["entry"]))
        return {"Item": dict(held)} if held else {}

    def scan(self, **_kwargs):
        raise AssertionError("a search must never scan a table")


class FakeDynamo:
    """Two tables in memory, the word table and the Reference table, that count every request and every item a request returned.
    There is no scan: asking for one fails the test."""

    WORDS, REFERENCES = "words", "references"

    def __init__(self, page=1000):
        self.tables, self.page, self.requests, self.items_read = {self.WORDS: {}, self.REFERENCES: {}}, page, [], 0

    def record(self, operation, table, items):
        self.requests.append((operation, table))
        if operation in ("query", "batch_get_item"):
            self.items_read += items

    def Table(self, name):
        return FakeTable(self, name)

    def batch_get_item(self, RequestItems):
        responses = {}
        for name, spec in RequestItems.items():
            assert len(spec["Keys"]) <= 100
            table = self.tables[name]
            found = [dict(table[(key["shard"], key["entry"])] if "shard" in key else table[key["id"]])
                     for key in spec["Keys"] if ((key["shard"], key["entry"]) if "shard" in key else key["id"]) in table]
            responses[name] = found
            self.record("batch_get_item", name, len(found))
        return {"Responses": responses, "UnprocessedKeys": {}}

    def describe_table(self, TableName):
        return {"Table": {"ItemCount": len(self.tables[TableName])}}


class FakeSite:
    """A site of Reference rows with its word index written the way the stream consumer writes it, and a word source reading both tables."""

    def __init__(self, rows, page=1000):
        self.dynamo = FakeDynamo(page=page)
        self.writer = reference_words.WordWriter(FakeTable(self.dynamo, FakeDynamo.WORDS), conflict_errors=(ConditionalCheckFailed,))
        self.source = reference_words.DynamoWordSource(self.dynamo, self.dynamo, word_table=FakeDynamo.WORDS, reference_table=FakeDynamo.REFERENCES)
        self.rows = {}
        for candidate in rows:
            self.change(None, candidate)
        self.dynamo.requests.clear()
        self.dynamo.items_read = 0

    def change(self, old, new):
        """A Reference row changing (the stream record), the word rows following."""
        if new is not None:
            self.dynamo.tables[FakeDynamo.REFERENCES][new["id"]] = new
            self.rows[new["lineageId"]] = new
        self.writer.apply_change(old, new)

    def index(self):
        """An in-memory index of the indexed rows, for tests of the ranking itself."""
        index = rs.ReferenceWordIndex()
        for candidate in self.dynamo.tables[FakeDynamo.REFERENCES].values():
            index.upsert(candidate)
        return index


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
    return rs.search_references({"query": query, "show": show, **extra}, words=site.source if site else None, vectors=vectors)


def titles(result):
    return [item["reference"]["title"] for item in result["items"]]


# --- the word index -------------------------------------------------------------------------------------------------------------------------

def test_a_reference_in_no_feed_has_no_words_and_the_others_are_found_by_exact_word_and_by_prefix():
    site = FakeSite([row("a", "Alpha"), row("b", "Beta"), row("c", "Gamma", state=None), row("d", "Delta sound"), row("e", "Epsilon")])
    assert titles(search(site, None, "gamma")) == []   # in no feed: archived, or not the current version
    assert titles(search(site, None, "sound")) == ["Delta sound"]
    assert titles(search(site, None, "alp")) == ["Alpha"]   # a term of three letters also matches the start of a longer word
    assert titles(search(site, None, "al")) == []   # two letters match whole words only


def test_an_exact_word_in_a_title_is_never_missing_however_many_other_results_there_are():
    sound = row("sound", "I discovered a sound that leaks your exact location", state="unrated")
    crowd = [row(f"other{n}", f"Another story about location tracking {n}", state="rated", curationStatus="accepted") for n in range(40)]
    site = FakeSite(crowd + [sound], page=5)   # a word's lookup spans several pages here
    related = [(f"other{n}", 0.1 + n / 1000) for n in range(40)]
    result = search(site, FakeVectors(related + smooth_tail()), "sound")
    assert result["items"][0]["reference"]["title"] == "I discovered a sound that leaks your exact location"
    assert result["items"][0]["matchedBy"] == ["keyword"] and "title" in result["items"][0]["matchedFields"]


def test_a_new_reference_a_changed_title_and_an_archived_reference_follow_the_stream():
    site = FakeSite([row("a", "Old title")])
    assert titles(search(site, None, "fresh")) == []
    site.change(site.rows["a"], row("a", "Fresh title"))   # the same row, a new title
    assert titles(search(site, None, "fresh")) == ["Fresh title"] and titles(search(site, None, "old")) == []
    site.change(None, row("n", "Newly arrived"))
    assert titles(search(site, None, "newly")) == ["Newly arrived"]
    site.change(site.rows["n"], row("n", "Newly arrived", state=None))   # archived: no feed key
    assert titles(search(site, None, "newly")) == []


def test_a_vote_or_a_star_writes_no_word_rows():
    site = FakeSite([row("a", "Alpha story", state="unrated")])
    before = {key: dict(value) for key, value in site.dynamo.tables[FakeDynamo.WORDS].items()}
    site.change(site.rows["a"], {**site.rows["a"], "feedStateKey": "c#rated", "curationStatus": "accepted", "starRating": 4})
    assert site.dynamo.tables[FakeDynamo.WORDS] == before
    assert [operation for operation, _table in site.dynamo.requests if operation in ("put_item", "delete_item")] == []


def test_a_new_version_replaces_the_words_and_an_older_versions_late_event_never_undoes_it():
    v1 = row("a", "Alpha story", version=1)
    site = FakeSite([v1])
    v2 = row("a", "Beta story", version=2)
    site.change(None, v2)                                 # the new version arrives first
    site.change(v1, {**v1, "versionState": "superseded"})   # then the old version's change to superseded, late
    assert titles(search(site, None, "beta")) == ["Beta story"] and titles(search(site, None, "alpha")) == []
    assert titles(search(site, None, "story")) == ["Beta story"]   # the shared word still points at the new version
    assert site.dynamo.tables[FakeDynamo.WORDS][("~a", "a")]["referenceId"] == "a-v2"


def test_a_search_reads_only_the_rows_its_words_matched_never_the_table():
    site = FakeSite([row(f"r{n}", f"Story number {n} about {'sound' if n % 50 == 0 else 'filler'}") for n in range(300)], page=1000)
    result = search(site, None, "sound")
    assert len(result["items"]) == 6
    operations = {operation for operation, _table in site.dynamo.requests}
    assert operations <= {"query", "batch_get_item"}   # no scan exists in the fake: asking for one fails
    assert site.dynamo.items_read == 6 + 6              # six word rows, then the six Reference rows they pointed at; not 300
    assert len(site.dynamo.requests) <= 2


def test_a_meaning_match_the_words_did_not_find_is_read_through_its_pointer_row():
    site = FakeSite([row("m", "Unrelated headline"), row("w", "Agent memory")])
    result = search(site, FakeVectors([("m", 0.1)] + smooth_tail()), "agent memory")
    assert titles(result) == ["Agent memory", "Unrelated headline"]
    assert [item["matchedBy"] for item in result["items"]] == [["keyword"], ["meaning"]]


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


def test_any_word_match_outranks_a_match_found_only_by_meaning_and_a_strong_one_leads_the_partial_ones():
    words = [rs.WordHit("some", rs.SOME_TERMS, 1, 4, 1), rs.WordHit("all", rs.ALL_TERMS_ACROSS_FIELDS, 2, 4, 1)]
    fused = rs.fuse(words, [("m1", 0.9), ("m2", 0.8), ("some", 0.7)])
    assert [entry.lineage_id for entry in fused] == ["all", "some", "m1", "m2"]
    assert fused[0].strong and not fused[1].strong
    alone = rs.fuse([rs.WordHit("some", rs.SOME_TERMS, 1, 4, 1)], [("m1", 0.9)])
    assert [entry.lineage_id for entry in alone] == ["some", "m1"]   # words alone still above a better meaning rank
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
    index = site.index()
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
    seen, cursor, pages = [], None, 0
    while True:
        extra = {"cursor": cursor} if cursor else {}
        result = rs.search_references({"query": "shared topic", "limit": 7, **extra}, words=site.source, vectors=None)
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
        search(site, None, "alpha", show="archived")


def test_each_status_can_be_asked_for_on_its_own():
    site = FakeSite([row("p", "Shared pending", state="unrated"), row("a", "Shared accepted", state="rated", curationStatus="accepted"),
                     row("r", "Shared rejected", state="rated", curationStatus="rejected")])
    assert titles(search(site, None, "shared", show="unrated")) == ["Shared pending"]
    assert titles(search(site, None, "shared", show="accepted")) == ["Shared accepted"]
    assert titles(search(site, None, "shared", show="rejected")) == ["Shared rejected"]
    assert sorted(titles(search(site, None, "shared", show="all"))) == ["Shared accepted", "Shared pending", "Shared rejected"]
    vectors = FakeVectors([("r", 0.1)])
    search(site, vectors, "shared", show="rejected")
    assert vectors.filters[0]["$and"][1] == {"curationStatus": {"$in": ["rejected"]}}


# --- sort and minimum stars --------------------------------------------------------------------------------------------------------------------

def starred_site():
    return FakeSite([
        row("a", "Topic alpha", arrival="2026-11-01T10:00:00.000Z", starRating=5),
        row("b", "Topic beta", arrival="2026-11-02T10:00:00.000Z", starRating=3),
        row("c", "Topic gamma", arrival="2026-11-03T10:00:00.000Z"),
        row("d", "Topic delta", arrival="2026-11-04T10:00:00.000Z", starRating=5),
        row("e", "Topic epsilon", arrival="2026-11-05T10:00:00.000Z", starRating=2),
    ], page=10)


def test_relevance_is_the_default_and_keeps_the_fused_order():
    site = starred_site()
    assert titles(search(site, None, "topic")) == titles(search(site, None, "topic", sort="relevance"))


def test_newest_orders_by_arrival_and_quality_by_stars_then_arrival_with_unstarred_last():
    site = starred_site()
    assert titles(search(site, None, "topic", sort="newest")) == ["Topic epsilon", "Topic delta", "Topic gamma", "Topic beta", "Topic alpha"]
    assert titles(search(site, None, "topic", sort="quality")) == ["Topic delta", "Topic alpha", "Topic beta", "Topic epsilon", "Topic gamma"]   # 5 5 3 2 then none


def test_a_minimum_keeps_that_many_stars_or_more_and_drops_the_unstarred():
    site = starred_site()
    assert titles(search(site, None, "topic", sort="newest", minStars=4)) == ["Topic delta", "Topic alpha"]
    assert titles(search(site, None, "topic", sort="newest", minStars=3)) == ["Topic delta", "Topic beta", "Topic alpha"]
    assert titles(search(site, None, "topic", sort="quality", minStars=5)) == ["Topic delta", "Topic alpha"]
    assert titles(search(site, None, "topic", minStars=5)) != []   # relevance order with a minimum is allowed too


@pytest.mark.parametrize("bad", [1, 2, 6, "x", 3.5, True, float("nan")])
def test_a_minimum_other_than_three_four_or_five_is_refused(bad):
    with pytest.raises(rs.SearchError):
        search(starred_site(), None, "topic", minStars=bad)


def test_an_unknown_sort_is_refused_and_an_empty_minimum_is_none():
    with pytest.raises(rs.SearchError):
        search(starred_site(), None, "topic", sort="stars")
    assert len(search(starred_site(), None, "topic", minStars=None)["items"]) == 5
    assert len(search(starred_site(), None, "topic", minStars="")["items"]) == 5


def test_real_floats_and_absent_values_do_not_break_the_order():
    site = FakeSite([
        row("a", "Topic alpha", arrival="2026-11-01T10:00:00.000Z", starRating=4.0),   # a float that is a whole number is 4
        row("b", "Topic beta", arrival="2026-11-02T10:00:00.000Z", starRating=float("nan")),
        row("c", "Topic gamma", arrival="2026-11-03T10:00:00.000Z", starRating=4.5),
        row("d", "Topic delta", arrival="2026-11-04T10:00:00.000Z", starRating=None),
        row("e", "Topic epsilon", arrival="2026-11-05T10:00:00.000Z", starRating=5.0),
        row("f", "Topic zeta", arrival=None, updated="2026-11-06T10:00:00.000Z", feedArrivalAt=None, createdAt=None),   # no arrival at all
    ], page=10)
    # 5.0 and 4.0 are stars; NaN, 4.5 and null are none, which sort last newest first, a row with no arrival at all after them.
    assert titles(search(site, None, "topic", sort="quality")) == ["Topic epsilon", "Topic alpha", "Topic delta", "Topic gamma", "Topic beta", "Topic zeta"]
    assert titles(search(site, None, "topic", sort="quality", minStars=4)) == ["Topic epsilon", "Topic alpha"]
    assert len(search(site, None, "topic", sort="newest")["items"]) == 6
    assert rs.stars_of({"starRating": 4.0}) == 4 and rs.stars_of({"starRating": 4.5}) == 0 and rs.stars_of({"starRating": float("inf")}) == 0
    assert rs.stars_of({"starRating": "4"}) == 4 and rs.stars_of({"starRating": True}) == 0 and rs.stars_of({}) == 0


def test_a_cursor_from_another_ordering_or_minimum_is_refused():
    cursor = rs.encode_cursor(24, "topic", "all", "quality", 4)
    assert rs.decode_cursor(cursor, "topic", "all", "quality", 4) == 24
    for other in (("relevance", 4), ("newest", 4), ("quality", None), ("quality", 5)):
        with pytest.raises(rs.SearchError):
            rs.decode_cursor(cursor, "topic", "all", *other)


def test_paging_through_a_quality_search_never_repeats_or_skips():
    site = FakeSite([row(f"r{n}", f"Shared topic {n}", arrival=f"2026-11-01T10:{n:02d}:00.000Z", starRating=(n % 5) + 1) for n in range(20)], page=10)
    seen, cursor = [], None
    while True:
        extra = {"cursor": cursor} if cursor else {}
        result = rs.search_references({"query": "shared topic", "limit": 4, "sort": "quality", "minStars": 3, **extra}, words=site.source, vectors=None)
        seen += [(item["reference"]["starRating"], item["reference"]["feedArrivalAt"]) for item in result["items"]]
        cursor = result["nextCursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 12 and seen == sorted(seen, reverse=True)


# --- one lane failing --------------------------------------------------------------------------------------------------------------------------

def test_a_meaning_failure_still_returns_the_word_results_with_its_status():
    site = FakeSite([row("a", "Agent memory")], page=10)
    result = search(site, FakeVectors(error=RuntimeError("OPENAI_API_KEY is required for S3VectorsProvider embeddings")), "agent memory")
    assert titles(result) == ["Agent memory"]
    assert result["lanes"]["keyword"] == {"status": "ok"}
    assert result["lanes"]["meaning"] == {"status": "failed", "message": "Meaning search is not set up for this site."}


def test_a_word_failure_still_returns_the_meaning_results():
    site = FakeSite([row("a", "Agent memory")], page=10)

    class Broken:
        def lookup(self, term):
            raise RuntimeError("DynamoDB is down")

    result = rs.search_references({"query": "agent memory"}, words=Broken(), vectors=FakeVectors([("a", 0.1)]))
    assert result["items"] == [] and result["lanes"]["keyword"]["status"] == "failed" and result["lanes"]["meaning"] == {"status": "ok"}
    assert site  # the meaning match has no row to show when the word table cannot be read: it is left out, not invented


def test_both_lanes_failing_returns_no_cards_and_two_failed_statuses():
    result = rs.search_references({"query": "agent"}, words=None, vectors=None)
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
        semantic = None

    monkeypatch.setattr(lambda_handler, "build_environment_services", lambda event: Services())
    monkeypatch.setattr(reference_words.DynamoWordSource, "from_environment", classmethod(lambda cls: site.source))
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


# --- the Captured filter -----------------------------------------------------------------------------------------------------------------------

def captured_site():
    return FakeSite([
        row("a", "Topic alpha", arrival="2026-11-01T10:00:00.000Z", captureState="full"),
        row("b", "Topic beta", arrival="2026-11-02T10:00:00.000Z", captureState="thin"),
        row("c", "Topic gamma", arrival="2026-11-03T10:00:00.000Z"),
        row("d", "Topic delta", arrival="2026-11-04T10:00:00.000Z", captureState="running"),
        row("e", "Topic epsilon", arrival="2026-11-05T10:00:00.000Z", captureState="full"),
    ], page=10)


def test_captured_yes_keeps_only_full_and_no_keeps_thin_none_running_and_empty():
    site = captured_site()
    assert sorted(titles(search(site, None, "topic", captured="yes"))) == ["Topic alpha", "Topic epsilon"]
    assert sorted(titles(search(site, None, "topic", captured="no"))) == ["Topic beta", "Topic delta", "Topic gamma"]
    assert len(search(site, None, "topic", captured="any")["items"]) == 5
    assert len(search(site, None, "topic")["items"]) == 5
    assert len(search(site, None, "topic", captured=None)["items"]) == 5


def test_captured_combines_with_the_sort_and_a_minimum():
    site = FakeSite([row("a", "Topic alpha", starRating=5, captureState="full"), row("b", "Topic beta", starRating=5), row("c", "Topic gamma", starRating=2)], page=10)
    assert titles(search(site, None, "topic", sort="quality", minStars=5, captured="no")) == ["Topic beta"]


def test_an_unknown_captured_choice_is_refused():
    with pytest.raises(rs.SearchError):
        search(captured_site(), None, "topic", captured="maybe")


def test_the_cursor_belongs_to_one_captured_choice():
    site = captured_site()
    page = search(site, None, "topic", captured="no", limit=2)
    assert page["nextCursor"]
    assert len(search(site, None, "topic", captured="no", limit=2, cursor=page["nextCursor"])["items"]) == 1
    with pytest.raises(rs.SearchError):
        search(site, None, "topic", captured="yes", limit=2, cursor=page["nextCursor"])
    with pytest.raises(rs.SearchError):
        search(site, None, "topic", limit=2, cursor=page["nextCursor"])
    # a cursor made before the filter existed is still valid for "any"
    old = rs.encode_cursor(2, "topic", "all")
    assert rs.decode_cursor(old, "topic", "all", "relevance", None, "any") == 2


def test_reviewed_accepted_checks_the_status_because_the_feed_state_cannot_tell_accepted_from_rejected():
    site = FakeSite([
        row("a", "Topic alpha", state="rated"),
        row("b", "Topic beta", state="rated", curationStatus="rejected"),
        row("c", "Topic gamma", state="unrated"),
    ], page=10)
    assert sorted(titles(search(site, None, "topic", show="accepted"))) == ["Topic alpha"]
    assert sorted(titles(search(site, None, "topic", show="rated"))) == ["Topic alpha", "Topic beta"]
    assert rs.MEANING_STATUSES["accepted"] == ["accepted"]
    page = search(site, None, "topic", show="all", limit=1)
    with pytest.raises(rs.SearchError):
        search(site, None, "topic", show="accepted", limit=1, cursor=page["nextCursor"])
