"""Monitors page their source until they meet items they already collected or the source has no more.

No item count, page count or request count limits a pass. Only real constraints do: the Lambda's time (the rest
is read by the next pass, from a resume cursor in STATE) and the source's rate limit (Retry-After is honoured).
"""
from email.utils import format_datetime
from datetime import datetime, timezone
import json

import pytest

from papyrus_content import monitoring_huggingface as hf
from papyrus_content.monitoring_cloud import DynamoStore, run_collection
from papyrus_content.monitoring_paging import Page, RateLimited, Reading, read_feed, retry_after_seconds

import test_monitoring_huggingface as th
from test_monitoring_router import FakeTable
from test_monitoring_ttab import NOW, TTAB_CONFIG, decision, search_response


class Clock(th.Clock):
    """A clock that also moves on its own: each page fetched costs `cost` seconds."""

    def __init__(self, cost=0):
        super().__init__()
        self.cost = cost

    def tick(self):
        self.now += self.cost


def decisions(count):
    """`count` decisions, newest first, as the Reading Room would list them."""
    return [decision(f"/legal-proceeding/{90000000 + n}/decision/EXA_{n}.pdf", 90000000 + n, f"Party {n}", "Refusal Affirmed",
                     issued=1791432000000 - n * 1000, kind="EXA") for n in range(count)]


class ReadingRoom:
    """A search that honours `recordStartNumber` and `recordTotalQuantity`, newest first. `calls` lists the offsets asked for."""

    def __init__(self, rows, clock=None, fail=None):
        self.rows, self.calls, self.clock, self.fail = rows, [], clock, fail or {}

    def __call__(self, url, body):
        payload = json.loads(body)
        start, size = payload["recordStartNumber"], payload["recordTotalQuantity"]
        self.calls.append((start, bool(payload["parameterData"])))
        if self.clock:
            self.clock.tick()
        if len(self.calls) in self.fail:
            raise self.fail[len(self.calls)]
        return search_response(*self.rows[start:start + size])


def ttab_table(**config):
    table = FakeTable()
    table.put_item({**TTAB_CONFIG, "pageSize": 100, **config})
    return table


def collect(table, server, now=NOW, **kwargs):
    return run_collection(DynamoStore(table), "ttab", fetch=server, now=now, force=True, **kwargs)


# --- the pieces --------------------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [("120", 120.0), ("0", 0.0), (None, None), ("", None), ("soon", None), ("-5", 0.0)])
def test_retry_after_in_seconds(value, expected):
    assert retry_after_seconds(value) == expected


def test_retry_after_as_a_http_date_is_the_seconds_until_then():
    when = datetime.fromtimestamp(5000, timezone.utc)

    assert retry_after_seconds(format_datetime(when, usegmt=True), now=lambda: 4970.0) == 30.0


def test_a_feed_stops_at_the_first_page_that_holds_a_collected_item():
    pages = {None: ([1, 2], 2), 2: ([3, 4], 4), 4: ([5, 6], 6)}
    seen_pages = []

    def process(rows):
        seen_pages.append(rows)
        return Page(unseen=sum(1 for r in rows if r > 2), seen=sum(1 for r in rows if r <= 2))

    left = read_feed(lambda cursor: pages[cursor], process, Reading(), [])

    assert seen_pages == [[1, 2]] and left == []              # page 1 already holds collected items: nothing newer is further out


def test_a_time_stop_leaves_the_cursor_and_the_next_pass_reads_the_head_then_the_gap():
    pages = {None: ([1], 1), 1: ([2], 2), 2: ([3], 3), 3: ([4], None)}
    clock, order = Clock(), []
    reading = Reading(2, clock=clock)

    def fetch(cursor):
        clock.now += 1.5
        return pages[cursor]

    def process(rows):
        order.append(rows[0])
        return Page(unseen=1)

    left = read_feed(fetch, process, reading, [])

    assert order == [1, 2] and left == [2] and reading.stopped_by == "time_budget"
    order.clear()
    done = {1, 2}                                              # what the first pass collected

    def again(rows):
        order.append(rows[0])
        return Page(unseen=int(rows[0] not in done), seen=int(rows[0] in done))

    assert read_feed(lambda cursor: pages[cursor], again, Reading(), left) == [] and order == [1, 3, 4]


def test_a_metric_sorted_feed_has_no_high_water_mark_and_reads_to_its_own_end():
    pages = {None: ([1], 1), 1: ([2], 2), 2: ([3], None)}
    asked = []

    def fetch(cursor):
        asked.append(cursor)
        return pages[cursor]

    read_feed(fetch, lambda rows: Page(seen=1), Reading(), [], stop_at_seen=False)

    assert asked == [None, 1, 2]


# --- a collector pass --------------------------------------------------------------------------------

def test_a_first_pass_reads_every_decision_however_many_pages_that_takes():
    table, server = ttab_table(), ReadingRoom(decisions(250))

    result = collect(table, server)

    assert result["new"] == 250 and result["itemCount"] == 250 and result["status"] == "complete"
    assert [call[0] for call in server.calls] == [0, 100, 200, 250]       # the last request finds the search empty
    assert len(table.by_prefix("DISC#")) == 250 and "resume" not in table.items[("MONITOR#ttab", "STATE")]


def test_a_later_pass_stops_at_the_high_water_mark_after_one_page():
    table = ttab_table()
    collect(table, ReadingRoom(decisions(250)))
    newer = [decision(f"/legal-proceeding/{91000000 + n}/decision/EXA_{n}.pdf", 91000000 + n, f"Newer {n}", "Refusal Affirmed",
                      issued=1792000000000 - n * 1000, kind="EXA") for n in range(30)]
    server = ReadingRoom(newer + decisions(250))

    result = collect(table, server, now=NOW + 86400)

    assert result["new"] == 30 and len(server.calls) == 1               # 30 new above the first collected decision; nothing below was read
    assert len(table.by_prefix("DISC#")) == 280


def test_a_pass_with_more_new_items_than_a_page_keeps_paging_until_it_meets_a_collected_one():
    table = ttab_table(pageSize=10)
    collect(table, ReadingRoom(decisions(20)))
    newer = [decision(f"/legal-proceeding/{91000000 + n}/decision/EXA_{n}.pdf", 91000000 + n, f"Newer {n}", "Refusal Affirmed",
                      issued=1792000000000 - n * 1000, kind="EXA") for n in range(25)]
    server = ReadingRoom(newer + decisions(20))

    result = collect(table, server, now=NOW + 86400)

    assert result["new"] == 25 and [call[0] for call in server.calls] == [0, 10, 20]


def test_when_the_time_reserve_is_reached_the_rest_is_read_by_the_next_pass():
    table, clock = ttab_table(pageSize=100), Clock(cost=30)             # each page costs 30 s of the 80 s a pass may read for
    server = ReadingRoom(decisions(450), clock=clock)

    first = collect(table, server, clock=clock, sleep=clock.sleep)

    assert first["new"] == 300 and first["read"]["stoppedBy"] == "time_budget" and first["status"] == "partial"
    assert any("stopped early: time_budget" in e["message"] for e in first["errors"])
    state = table.items[("MONITOR#ttab", "STATE")]
    assert state["resume"] == {"recent": [300]} and state["nextDueAt"] == int(NOW)        # due again at the next schedule tick

    server.calls.clear()
    second = collect(table, server, now=NOW + 900, clock=Clock(), sleep=Clock().sleep)
    assert second["new"] == 150 and second["status"] == "complete"
    assert [call[0] for call in server.calls] == [0, 300, 400, 450]       # the head (collected: stop), then the gap
    assert len(table.by_prefix("DISC#")) == 450 and "resume" not in table.items[("MONITOR#ttab", "STATE")]


def test_a_pass_that_is_not_forced_waits_for_nothing_after_it_completes():
    table = ttab_table()
    collect(table, ReadingRoom(decisions(5)))

    skipped = run_collection(DynamoStore(table), "ttab", fetch=ReadingRoom(decisions(5)), now=NOW + 10)

    assert skipped["status"] == "not_due"


def test_a_429_with_retry_after_is_waited_out_and_the_read_goes_on():
    table, clock = ttab_table(), Clock()
    server = ReadingRoom(decisions(150), clock=clock, fail={2: RateLimited("slow down", retry_after=25)})

    result = collect(table, server, clock=clock, sleep=clock.sleep)

    assert clock.slept == [25] and result["new"] == 150 and result["status"] == "complete"
    assert [call[0] for call in server.calls] == [0, 100, 100, 150]     # the limited page was asked for again


def test_a_429_that_outlasts_the_pass_stops_it_where_it_was_and_the_next_pass_continues():
    table, clock = ttab_table(pageSize=50), Clock()
    server = ReadingRoom(decisions(120), clock=clock, fail={3: RateLimited("slow down", retry_after=600)})

    first = collect(table, server, clock=clock, sleep=clock.sleep)

    assert first["new"] == 100 and first["read"]["stoppedBy"] == "rate_limited" and clock.slept == []
    assert table.items[("MONITOR#ttab", "STATE")]["resume"] == {"recent": [100]}
    second = collect(table, ReadingRoom(decisions(120)), now=NOW + 900)
    assert second["new"] == 20 and len(table.by_prefix("DISC#")) == 120


def test_a_server_that_ignores_the_offset_does_not_loop_forever():
    table = ttab_table(pageSize=10)
    rows, asked = decisions(10), []

    def server(url, body):
        asked.append(1)
        return search_response(*rows)

    result = collect(table, server)

    assert result["new"] == 10 and len(asked) == 2


def test_the_precedential_feed_is_read_in_full_even_when_the_recent_feed_just_collected_the_same_decisions():
    table = ttab_table(precedentialLookbackDays=180, pageSize=10)
    older = decisions(25)
    server_calls = []

    def server(url, body):
        payload = json.loads(body)
        server_calls.append((bool(payload["parameterData"]), payload["recordStartNumber"]))
        rows = older[:15] if not payload["parameterData"] else older
        return search_response(*rows[payload["recordStartNumber"]:payload["recordStartNumber"] + 10])

    result = collect(table, server)

    assert result["new"] == 25                       # the second feed met decisions the first feed had just collected and kept going
    assert (True, 20) in server_calls


# --- Hugging Face ------------------------------------------------------------------------------------

def test_hugging_face_pages_every_query_to_the_end_of_the_window_with_no_page_bound():
    table = th.configured()
    table.put_item({**th.CONFIG, "minLikes": 0, "pageSize": 1})           # twelve models, one to a page
    hub = th.tts_hub()

    result = th.run(table, hub)

    assert result["itemCount"] == 12 and len(hub.requests) >= 12 and len(table.by_prefix("DISC#")) == 12


def test_a_later_hugging_face_pass_stops_at_the_first_page_with_a_collected_model():
    table = th.configured()
    table.put_item({**th.CONFIG, "minLikes": 0, "pageSize": 3})
    th.run(table, th.tts_hub())
    hub = th.tts_hub()

    result = th.run(table, hub, now=th.NOW + th.DAY)

    assert result["unchanged"] == 3 and result["new"] == 0
    assert len(hub.requests) == 2                  # the author query (empty) and one page of the tag query


def test_a_rate_limited_hub_is_waited_out_by_the_collector_for_as_long_as_it_says():
    table, clock, calls = th.configured(), Clock(), []
    hub = th.tts_hub()

    def fetch(url):
        calls.append(url)
        if len(calls) == 2:
            raise hf.RateLimited("slow down", retry_after=30)
        return hub(url)

    result = run_collection(DynamoStore(table), "huggingface", fetch=fetch, now=th.NOW, clock=clock, sleep=clock.sleep)

    assert clock.slept == [30] and result["new"] == 1 and result["status"] == "complete"


def test_a_query_sorted_by_likes_reads_to_the_minimum_not_to_a_page_count():
    table = FakeTable()
    table.put_item({**th.CONFIG, "authors": [], "pipelineTags": ["text-generation"], "minLikes": 12000, "pageSize": 1,
                    "sort": "likes", "lookbackDays": 366})
    hub = th.liked_hub()

    result = th.run(table, hub, now=datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp())

    assert result["new"] == 1 and len(hub.requests) == 2      # the second model has 8597 likes: under the minimum, so the query is over
