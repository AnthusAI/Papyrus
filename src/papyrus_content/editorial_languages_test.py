"""The site's languages and a Story's language (features_backend/editorial-languages.feature has the narrative). No network, no model."""
from __future__ import annotations

import humanus
import pytest

from papyrus_content.editorial_languages import (LanguageNotEnabled, canonical, languages_served, site_language, site_languages, starter_packs_for,
                                                 story_language)

MOM = {"languages": {"primary": "en", "enabled": ["en", "es-419", "zh-CN"]}}


def test_tags_are_kept_in_humanus_spelling():
    assert site_languages(MOM) == {"primary": "en", "enabled": ["en", "es-419", "zh-Hans"]}
    assert canonical("*") == "*"


def test_a_base_language_request_means_the_variant_the_site_enabled():
    assert site_language("es", MOM) == "es-419"
    assert site_language("zh-SG", MOM) == "zh-Hans"


def test_a_language_the_site_does_not_write_in_is_refused_naming_it():
    with pytest.raises(LanguageNotEnabled, match="does not write in es "):
        site_language("es", {"languages": {"primary": "en", "enabled": ["en", "zh-Hans"]}})


def test_a_language_without_a_humanus_pack_is_refused_naming_it():
    with pytest.raises(humanus.UnsupportedLanguageError, match="'ko'"):
        site_languages({"languages": {"primary": "en", "enabled": ["en", "ko"]}})


def test_the_primary_language_must_be_enabled():
    with pytest.raises(ValueError, match="primary language es"):
        site_languages({"languages": {"primary": "es", "enabled": ["en"]}})


def test_settings_without_languages_are_refused_rather_than_read_as_english():
    with pytest.raises(ValueError, match="languages"):
        site_languages({})


def test_a_saved_story_is_written_in_its_own_language_and_a_new_one_in_the_primary():
    assert story_language({"id": "story-v1", "language": "en"}, MOM) == "en"
    assert story_language(None, MOM) == "en"


def test_a_saved_row_without_a_language_is_refused_never_read_as_the_primary():
    from papyrus_content.item_language import ItemLanguageMissing

    with pytest.raises(ItemLanguageMissing, match="papyrus stories languages"):
        story_language({"id": "story-v1"}, MOM)


def test_a_saved_language_the_site_does_not_write_in_is_refused():
    with pytest.raises(LanguageNotEnabled, match="zh-Hans"):
        story_language({"id": "story-v1--zh-Hans", "language": "zh-Hans"}, {"languages": {"primary": "en", "enabled": ["en"]}})


def test_policy_languages_served_least_specific_first():
    assert languages_served("es-419") == ("*", "es", "es-419")
    assert languages_served("zh-CN") == ("*", "zh-Hans")


def test_a_variant_brings_its_base_languages_starter_packs_then_its_own():
    assert starter_packs_for("es-419") == ("typography-es", "ai-writing-tells-es", "word-choice-es-419")
    assert starter_packs_for("zh-Hans") == ("typography-zh-hans", "translationese-zh-hans", "ai-writing-tells-zh-hans")
