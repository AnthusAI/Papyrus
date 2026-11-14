"""The one rule that gives an Item its language (``item_language``) and the message a row without one is refused with."""
from __future__ import annotations

import pytest

from papyrus_content.item_language import ItemLanguageMissing, item_language, item_language_group, with_item_language


def test_a_version_without_a_language_takes_the_one_of_the_version_it_follows():
    previous = {"id": "s-v1", "lineageId": "s--es-419", "language": "es-419", "languageGroupId": "s"}
    written = with_item_language({"id": "s--es-419-v2", "lineageId": "s--es-419"}, previous, "en")
    assert (written["language"], written["languageGroupId"]) == ("es-419", "s")


def test_a_story_with_no_earlier_version_starts_in_the_primary_language_as_its_own_group():
    written = with_item_language({"id": "s-v1", "lineageId": "s"}, None, "en")
    assert (written["language"], written["languageGroupId"]) == ("en", "s")


def test_a_language_named_by_the_writer_wins_over_the_earlier_version():
    written = with_item_language({"id": "s-v2", "lineageId": "s", "language": "zh-Hans", "languageGroupId": "s"}, {"language": "en", "languageGroupId": "s"}, "en")
    assert written["language"] == "zh-Hans"


def test_the_refusal_names_the_real_cause_and_the_command_that_repairs_the_row():
    with pytest.raises(ItemLanguageMissing) as raised:
        item_language({"id": "story-v4"})
    message = str(raised.value)
    assert "story-v4" in message and "older than 5.110.0" in message and "papyrus stories languages" in message
    with pytest.raises(ItemLanguageMissing, match="older than 5.110.0"):
        item_language_group({"id": "story-v4", "language": "en"})
