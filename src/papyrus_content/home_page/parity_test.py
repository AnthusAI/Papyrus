"""The parity report: identical pages, differences with their first differing card, and the rounding tier named as such. Offline."""
from __future__ import annotations

from papyrus_content.home_page.parity import DIFFERENT, ROUNDING_TIER, cards_of, compare_pages


def card(title: str, percent: int | None) -> str:
    text = f"<span>{percent}% confidence</span>" if percent is not None else ""
    return f'<li><article class="home-page-tile"><h3 class="home-page-title"><a href="/x">{title}</a></h3>{text}</article></li>'


def page(*cards: str) -> str:
    return "<main>" + "".join(cards) + "</main>"


def test_identical_pages_are_counted_and_the_report_is_ok():
    same = page(card("A", 90), card("B", 80))
    report = compare_pages({"front/index.html": same}, {"front/index.html": same})
    assert report["identical"] == 1 and report["differing"] == [] and report["ok"] is True


def test_two_cards_swapped_inside_one_rounding_tier_are_classed_as_such():
    report = compare_pages({"p": page(card("A", 90), card("B", 90))}, {"p": page(card("B", 90), card("A", 90))})
    assert [item["kind"] for item in report["differing"]] == [ROUNDING_TIER] and report["ok"] is True


def test_cards_swapped_across_tiers_are_a_difference_with_the_first_differing_card_named():
    report = compare_pages({"p": page(card("A", 90), card("B", 80))}, {"p": page(card("B", 80), card("A", 90))})
    (item,) = report["differing"]
    assert item["kind"] == DIFFERENT and "card 1" in item["first"] and "'A'" in item["first"] and report["ok"] is False


def test_a_missing_card_or_a_page_only_one_side_made_is_not_ok():
    assert compare_pages({"p": page(card("A", 90))}, {"p": page(card("A", 90), card("B", 80))})["differing"][0]["kind"] == DIFFERENT
    assert compare_pages({"p": page(card("A", 90))}, {})["missing"] == ["p"]


def test_a_difference_outside_the_cards_is_never_a_rounding_tier():
    report = compare_pages({"p": page(card("A", 90), card("B", 90)) + "<footer>1</footer>"}, {"p": page(card("B", 90), card("A", 90)) + "<footer>2</footer>"})
    assert report["differing"][0]["kind"] == DIFFERENT


def test_the_cards_are_found_in_a_rendered_page():
    assert len(cards_of(page(card("A", 1), card("B", 2)))) == 2
