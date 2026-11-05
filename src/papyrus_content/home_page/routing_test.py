"""A change reaches only the blocks it can alter, and it is decided from the change alone (no request). Offline."""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

from papyrus_content.home_page.indexed import IndexReader
from papyrus_content.home_page.routing import Coordinate, block_touched, card_hash, touched_blocks
from papyrus_content.home_page.settings import home_page_settings_from_mapping
from procedures.newsroom.tests.home_page_index_support import CORPUS, IndexedClient, make_corpus

AS_OF = date(2026, 11, 5)
SETTINGS = home_page_settings_from_mapping({"references": {"corpus": CORPUS, "source": "index"}})


def state_of(attributes: dict, count: int = 3, rows=None) -> dict:
    reader = IndexReader(IndexedClient(rows if rows is not None else make_corpus()), CORPUS, SETTINGS)
    block = reader.block(attributes, AS_OF)
    block.ensure(count)
    return block.state()


def change(**fields) -> Coordinate:
    return Coordinate(identifier=fields.pop("identifier", "other-v1"), **fields)


def test_the_hash_the_trigger_computes_is_the_hash_the_router_knows():
    spec = importlib.util.spec_from_file_location("home_page_trigger_handler", Path(__file__).resolve().parents[3] / "amplify" / "plugins" / "home-page" / "function" / "handler.py")
    trigger = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trigger)
    values = {"title": "A", "cardImage": "https://img.example.org/a.jpg", "medium": "video"}
    assert trigger.card_hash({name: {"S": value} for name, value in values.items()}) == card_hash(values)


def test_a_change_to_a_row_the_block_pulled_always_touches_it():
    state = state_of({"select": "recent"})
    assert block_touched(state, change(identifier=state["ids"][0], hash0="a", hash1="b"), as_of=AS_OF)


def test_a_row_that_is_in_no_partition_touches_nothing():
    state = state_of({"select": "recent"})
    assert not block_touched(state, change(feed0=None, feed1=None), as_of=AS_OF)


def test_a_recommended_row_does_not_reach_a_recent_block_and_an_accepted_row_does_not_reach_a_recommended_one():
    recent, recommended = state_of({"select": "recent"}), state_of({"select": "recommended"})
    pending = change(feed1="c#recommended#2026-11-05", order1="p0.990000#2026-11-05T09:00:00.000Z#x")
    accepted = change(feed1="c#accepted", order1="p0.990000#2026-11-05T09:00:00.000Z#x", accepted1="2026-11-05T11:00:00.000Z")
    assert not block_touched(recent, pending, as_of=AS_OF) and block_touched(recommended, pending, as_of=AS_OF)
    assert block_touched(recent, accepted, as_of=AS_OF) and not block_touched(recommended, accepted, as_of=AS_OF)


def test_a_recent_block_is_reached_by_a_row_accepted_after_its_last_row_and_not_by_one_accepted_before_it():
    state = state_of({"select": "recent"})
    frontier = state["frontier"]["acceptedAt"]
    assert block_touched(state, change(feed1="c#accepted", order1="n#2026-11-05T10:00:00.000Z#x", accepted1="2999-01-01T00:00:00.000Z"), as_of=AS_OF)
    assert not block_touched(state, change(feed1="c#accepted", order1="n#2000-01-01T00:00:00.000Z#x", accepted1="2000-01-01T00:00:00.000Z"), as_of=AS_OF), frontier


def test_a_confident_block_is_reached_by_a_surer_row_a_starred_row_and_not_by_a_less_sure_one():
    state = state_of({"select": "confident"})
    assert block_touched(state, change(feed1="c#accepted", order1="p1.000000#2026-11-05T09:00:00.000Z#x"), as_of=AS_OF)
    assert block_touched(state, change(feed1="c#accepted", order1="p0.010000#2026-11-05T09:00:00.000Z#x", stars1=5), as_of=AS_OF)
    assert not block_touched(state, change(feed1="c#accepted", order1="p0.010000#2026-11-05T09:00:00.000Z#x"), as_of=AS_OF)
    assert not block_touched(state, change(feed1="c#accepted", order1="p0.010000#2026-11-05T09:00:00.000Z#x", stars1=1), as_of=AS_OF)


def test_a_recommended_block_ignores_a_row_under_its_last_card():
    state = state_of({"select": "recommended"})
    assert block_touched(state, change(feed1="c#recommended#2026-11-05", order1="p0.999999#2026-11-05T09:00:00.000Z#x"), as_of=AS_OF)
    assert not block_touched(state, change(feed1="c#recommended#2026-11-05", order1="p0.500000#2026-11-05T09:00:00.000Z#x"), as_of=AS_OF)


def test_a_block_that_came_up_short_is_reached_by_any_row_it_could_show():
    state = state_of({"select": "recommended"}, count=10_000)
    assert state["short"]
    assert block_touched(state, change(feed1="c#recommended#2026-11-05", order1="p0.500000#2026-11-05T09:00:00.000Z#x"), as_of=AS_OF)


def test_a_windowed_block_is_reached_by_a_row_in_its_windows_and_not_by_an_older_one():
    state = state_of({"select": "recent", "bucket": "week"})
    assert block_touched(state, change(feed1="c#accepted", order1="p0.999999#2026-11-05T09:00:00.000Z#x", accepted1="2026-11-05T09:00:00.000Z"), as_of=AS_OF)
    assert not block_touched(state, change(feed1="c#accepted", order1="n#2026-11-05T09:00:00.000Z#x", accepted1="2026-11-05T09:00:00.000Z"), as_of=AS_OF), "an unscored row sorts last in its window"
    assert not block_touched(state, change(feed1="c#accepted", order1="p0.999999#2025-01-01T09:00:00.000Z#x", accepted1="2025-01-01T09:00:00.000Z"), as_of=AS_OF)


def test_a_block_of_one_medium_ignores_a_row_of_another():
    state = state_of({"select": "recent", "medium": "video"}, count=1)
    other = change(feed1="c#accepted", order1="n#2026-11-05T09:00:00.000Z#x", accepted1="2999-01-01T00:00:00.000Z", medium1=None)
    video = change(feed1="c#accepted", order1="n#2026-11-05T09:00:00.000Z#x", accepted1="2999-01-01T00:00:00.000Z", medium1="video")
    assert not block_touched(state, other, as_of=AS_OF) and block_touched(state, video, as_of=AS_OF)


def test_a_block_with_no_remembered_state_is_touched_and_the_others_are_not():
    states = {"known": state_of({"select": "recent"})}
    quiet = change(feed1="c#recommended#2026-11-05", order1="p0.600000#2026-11-05T09:00:00.000Z#x")
    assert touched_blocks(states, ["known", "never-run"], [quiet], as_of=AS_OF) == {"never-run"}
    assert touched_blocks(states, ["known"], [], as_of=AS_OF) == set()


def test_the_coordinate_travels_through_json():
    coordinate = Coordinate("r-v1", "c#accepted", None, "n#2026#r", None, 3, None, "a", None, "video", None, "h", None)
    assert Coordinate.from_json(coordinate.to_json()) == coordinate
