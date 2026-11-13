"""The order of a Reference snapshot is worked out once per document, selection, filter and day (PPY-3acc8d), and never leaks between documents."""

from __future__ import annotations

import unittest
from datetime import date

from papyrus_content.projection.standard import home_page_blocks


def record(number: int, section: str = "Tools") -> dict:
    stamp = f"2026-11-0{1 + number % 7}T{number % 24:02d}:00:00.000Z"
    return {"key": f"{number:06x}", "status": "accepted", "acceptedAt": stamp, "arrivedAt": stamp, "section": section, "rank": number}


class OrderCacheTest(unittest.TestCase):
    def test_the_same_document_gives_the_same_order_and_each_caller_its_own_list(self) -> None:
        document = {"references": [record(number) for number in range(50)]}
        attributes = {"select": "recent", "bucket": "week"}
        first = home_page_blocks.candidates_of(document, attributes, {}, date(2026, 11, 8))
        first.clear()   # a caller that changes its list changes nobody else's
        second = home_page_blocks.candidates_of(document, attributes, {}, date(2026, 11, 8))
        self.assertEqual(len(second), 50)

    def test_a_new_document_or_another_filter_is_ordered_afresh(self) -> None:
        old = {"references": [record(number) for number in range(10)]}
        new = {"references": [record(number, "Law") for number in range(10, 30)]}
        day = date(2026, 11, 8)
        self.assertEqual(len(home_page_blocks.candidates_of(old, {"select": "recent", "section": "Tools"}, {}, day)), 10)
        self.assertEqual(len(home_page_blocks.candidates_of(new, {"select": "recent", "section": "Tools"}, {}, day)), 0)
        self.assertEqual(len(home_page_blocks.candidates_of(new, {"select": "recent", "section": "Law"}, {}, day)), 20)

    def test_a_document_that_grew_in_place_is_not_served_from_the_old_order(self) -> None:
        document = {"references": [record(number) for number in range(5)]}
        self.assertEqual(len(home_page_blocks.ordered(document["references"], "recent")), 5)
        document["references"].append(record(99))
        self.assertEqual(len(home_page_blocks.ordered(document["references"], "recent")), 6)
