"""An accepted Reference's tile shows its stars by shape and in words (features_backend/home-page-reference-stars.feature)."""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

from behave import then

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from features_backend.steps.home_page_references_steps import STYLESHEET, one_grid, titles_of  # noqa: E402

STAR_ICON = 'data-icon="star"'


def card_of(context, select: str, path: str, title: str) -> str:
    cards = one_grid(context, path, select)["cards"]
    found = [card for card, name in zip(cards, titles_of(cards)) if name == title]
    assert len(found) == 1, (title, titles_of(cards))
    return found[0]


@then('the "{select}" grid on "{path}" shows "{title}" with {stars:d} stars')
def shows_stars(context, select: str, path: str, title: str, stars: int) -> None:
    card = card_of(context, select, path, title)
    assert f'<article class="home-page-tile" data-status="accepted" data-stars="{stars}">' in card, card
    assert f'<span class="home-page-stars" data-stars="{stars}">' in card, card
    assert card.count(STAR_ICON) == 5 and card.count("home-page-star--filled") == stars, "filled stars for each star given, outlined for the rest"
    assert f'<span class="home-page-visually-hidden">{stars} of 5 stars</span>' in card, card
    assert "gauge" not in card, "a person's rating stands in for the prediction"


@then('the "{select}" grid on "{path}" shows "{title}" with no stars')
def shows_no_stars(context, select: str, path: str, title: str) -> None:
    card = card_of(context, select, path, title)
    assert "home-page-stars" not in card and "data-stars" not in card and STAR_ICON not in card and "stars" not in html.unescape(re.sub(r"<[^>]+>", " ", card)), card


@then('the "{select}" grid on "{path}" shows "{title}" with its confidence')
def shows_confidence(context, select: str, path: str, title: str) -> None:
    card = card_of(context, select, path, title)
    assert 'data-icon="gauge"' in card and "% confidence" in card, card


@then("the home-page stylesheet fills a star by shape and draws no border around it")
def stylesheet_draws_stars(context) -> None:
    rules = [line for line in STYLESHEET.read_text(encoding="utf-8").splitlines() if line.startswith(".home-page-star")]
    assert ".home-page-star--filled { fill: currentColor; }" in rules, rules
    assert not [line for line in rules if "border" in line or "outline" in line], rules
