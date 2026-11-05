import random

import pytest

from .chunks import bounds, chunk_name, split

KEYS = [f"k{number:05d}" for number in range(5000)]


def signature(chunks):
    return {(chunk.name, chunk.keys, chunk.next) for chunk in chunks}


def test_every_key_is_in_exactly_one_chunk_in_order_and_each_chunk_names_the_next():
    chunks = split(KEYS, 48)
    assert [key for chunk in chunks for key in chunk.keys] == KEYS
    assert [chunk.next for chunk in chunks[:-1]] == [chunk.name for chunk in chunks[1:]] and chunks[-1].next is None
    assert all(chunk.name == chunk_name(chunk.keys[0]) for chunk in chunks)


def test_chunks_stay_between_the_bounds_and_average_the_target():
    minimum, maximum, _window = bounds(48)
    sizes = [len(chunk.keys) for chunk in split(KEYS, 48)]
    assert all(minimum <= size <= maximum for size in sizes[:-1]) and sizes[-1] <= maximum
    assert 36 <= sum(sizes) / len(sizes) <= 60


def test_an_empty_list_and_a_short_list():
    assert split([], 48) == []
    only = split(["a", "b"], 48)
    assert len(only) == 1 and only[0].keys == ("a", "b") and only[0].next is None


@pytest.mark.parametrize("position", [0, 1, 7, 2500, 4999])
def test_inserting_one_key_changes_a_few_chunks_not_every_chunk_after_it(position):
    before = signature(split(KEYS, 48))
    keys = list(KEYS)
    keys.insert(position, "inserted")
    changed = signature(split(keys, 48)) - before
    assert 1 <= len(changed) <= 5 and len(before) > 80


def test_removing_or_moving_a_key_changes_a_few_chunks():
    before = signature(split(KEYS, 48))
    removed = list(KEYS)
    del removed[1234]
    assert len(signature(split(removed, 48)) - before) <= 5
    generator = random.Random(3)
    for _ in range(40):
        moved = list(KEYS)
        key = moved.pop(generator.randrange(len(moved)))
        moved.insert(generator.randrange(len(moved)), key)
        assert len(signature(split(moved, 48)) - before) <= 10


def test_a_chunk_that_is_not_touched_keeps_its_name():
    before = {chunk.keys[0]: chunk.name for chunk in split(KEYS, 48)}
    keys = list(KEYS)
    keys.insert(10, "inserted")
    after = {chunk.keys[0]: chunk.name for chunk in split(keys, 48)}
    assert sum(1 for first, name in before.items() if after.get(first) == name) >= len(before) - 3
