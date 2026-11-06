"""The persistent word index (``papyrus_knowledge_query.reference_words``): the stream consumer, the one-time backfill and the table shape. Synthetic data."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from papyrus_content.reference_word_backfill import backfill_words  # noqa: E402
from papyrus_knowledge_query import reference_words as rw  # noqa: E402
from procedures.newsroom.tests.test_reference_search import FakeDynamo, FakeSite, row  # noqa: E402


def typed(item):
    """A Reference row in the DynamoDB Streams wire format."""
    def value(v):
        if v is None:
            return {"NULL": True}
        if isinstance(v, bool):
            return {"BOOL": v}
        if isinstance(v, (int, float)):
            return {"N": str(v)}
        if isinstance(v, list):
            return {"L": [value(x) for x in v]}
        return {"S": str(v)}
    return {key: value(v) for key, v in item.items()}


def record(old=None, new=None, sequence="1"):
    images = {"SequenceNumber": sequence}
    if old is not None:
        images["OldImage"] = typed(old)
    if new is not None:
        images["NewImage"] = typed(new)
    return {"eventName": "MODIFY", "dynamodb": images}


def test_words_come_from_title_authors_address_and_id_and_the_noise_of_an_address_is_left_out():
    words = rw.row_words(row("a", "Café Sound", authors=["Ada Hinton"], source="https://www.example.com/blog/post-7.html", external="ext-9"))
    assert {"cafe", "sound", "ada", "hinton", "example", "blog", "post", "7", "ext", "9"} <= words
    assert not words & {"https", "www", "com", "html"}
    assert rw.row_words(row("a", "Archived", state=None)) == set()   # in no feed: no words
    assert rw.row_words({**row("a", "Old"), "versionState": "superseded"}) == set()


def test_the_table_shape_a_word_is_in_the_shard_of_its_first_two_letters_and_a_pointer_in_a_shard_no_word_can_have():
    assert rw.shard_of("sound") == "so" and rw.shard_of("a") == "a" and rw.entry_of("sound", "L1") == "sound#L1"
    assert rw.pointer_key("abc123") == {"shard": "~ab", "entry": "abc123"}


def test_the_stream_handler_writes_a_new_reference_and_writes_nothing_for_a_vote():
    site = FakeSite([])
    created = row("a", "Sound of silence", state="unrated")
    result = rw.stream_handler({"Records": [record(None, created)]}, writer=site.writer)
    assert result == {"batchItemFailures": []}
    assert ("so", "sound#a") in site.dynamo.tables[FakeDynamo.WORDS] and ("~a", "a") in site.dynamo.tables[FakeDynamo.WORDS]
    site.dynamo.requests.clear()
    voted = {**created, "feedStateKey": "c#rated", "curationStatus": "accepted", "starRating": 4, "predictedAcceptProbability": 0.8}
    rw.stream_handler({"Records": [record(created, voted)]}, writer=site.writer)
    assert site.dynamo.requests == []   # a vote changes no word, so nothing is written or deleted


def test_a_failing_record_is_reported_alone_so_the_rest_of_the_batch_is_kept():
    class Flaky:
        def __init__(self):
            self.seen = []

        def apply_change(self, old, new):
            self.seen.append(new["title"])
            if new["title"] == "Boom":
                raise RuntimeError("throttled")
            return {"put": 1, "deleted": 0}

    flaky = Flaky()
    batch = {"Records": [record(None, row("a", "Fine"), "10"), record(None, row("b", "Boom"), "11"), record(None, row("c", "Also fine"), "12")]}
    assert rw.stream_handler(batch, writer=flaky) == {"batchItemFailures": [{"itemIdentifier": "11"}]}
    assert flaky.seen == ["Fine", "Boom", "Also fine"]


def test_numbers_from_dynamodb_become_plain_numbers():
    assert rw.plain({"a": Decimal("4"), "b": [Decimal("0.5")], "c": "x"}) == {"a": 4, "b": [0.5], "c": "x"}


def test_the_population_is_one_describe_table_and_is_cached():
    site = FakeSite([row(f"r{n}", f"Story {n}") for n in range(5)])
    assert site.source.population() == 5 and site.source.population() == 5
    assert site.source.requests == 1


# --- the one-time backfill ----------------------------------------------------------------------------------------------------------------------

class FakeClient:
    def __init__(self, rows):
        self.rows, self.asked = rows, []

    def list_by_index(self, index_name, key_value, **_):
        assert index_name == "referencesByCurationStatusKey"
        self.asked.append(key_value)
        status = key_value.rsplit("#", 1)[1]
        return [candidate for candidate in self.rows if candidate["curationStatus"] == status]


def backfill_rows():
    return [row("p", "Pending sound", state="unrated"), row("a", "Accepted sound", state="rated", curationStatus="accepted"),
            row("r", "Rejected sound", state="rated", curationStatus="rejected"), row("x", "Archived sound", state=None)]


def test_the_backfill_previews_by_default_and_writes_nothing():
    site = FakeSite([])
    result = backfill_words(FakeClient(backfill_rows()), site.writer, corpus_id="c")
    assert result["dryRun"] and result["scanned"] == 4 and result["toIndex"] == 3 and result["withoutWords"] == 1 and result["written"] == 0
    assert site.dynamo.tables[FakeDynamo.WORDS] == {}


def test_the_backfill_writes_every_state_and_a_second_run_writes_nothing():
    site = FakeSite([])
    client = FakeClient(backfill_rows())
    first = backfill_words(client, site.writer, corpus_id="c", dry_run=False)
    assert first["written"] == 3 and client.asked[:3] == ["c#pending", "c#accepted", "c#rejected"]   # partition reads by status, never a scan
    puts = [operation for operation, _table in site.dynamo.requests if operation == "put_item"]
    second = backfill_words(client, site.writer, corpus_id="c", dry_run=False)
    assert second["written"] == 0 and second["alreadyIndexed"] == 3
    assert [operation for operation, _table in site.dynamo.requests if operation == "put_item"] == puts
