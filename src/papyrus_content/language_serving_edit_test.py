"""Editing and describing the serving keys of the languages setting (the console form and `papyrus editorial languages` share these)."""
import pytest

from papyrus_content.language_serving import describe_serving, edit_serving

STORED = {"primary": "en", "enabled": ["en", "es-419", "zh-Hans"], "futureKey": 1}


def test_public_adds_the_primary_and_keeps_every_other_key():
    assert edit_serving(STORED, public=["es-419"]) == {**STORED, "public": ["en", "es-419"]}


def test_public_of_only_the_primary_is_no_key():
    assert "public" not in edit_serving({**STORED, "public": ["en", "es-419"]}, public=[])


def test_prefix_and_slug_edits_merge_and_an_empty_value_returns_the_default():
    edited = edit_serving(STORED, prefixes={"es-419": "latam"}, slugs={"zh-Hans": "pinyin"})
    assert edited["prefixes"] == {"es-419": "latam"} and edited["slugs"] == {"zh-Hans": "pinyin"}
    assert "prefixes" not in edit_serving(edited, prefixes={"es-419": ""})


@pytest.mark.parametrize("edits,message", [
    ({"prefixes": {"es-419": "zh"}}, "would both be served under /zh/"),
    ({"slugs": {"es-419": "shortest"}}, "is not one of translated, characters, pinyin, primary"),
    ({"public": ["es"]}, "which the site does not write in"),
])
def test_an_edit_the_projection_would_refuse_is_refused(edits, message):
    with pytest.raises(ValueError, match=message):
        edit_serving(STORED, **edits)


def test_an_unreadable_language_is_a_value_error_naming_it():
    with pytest.raises(ValueError, match="fr"):
        edit_serving(STORED, public=["fr"])


def test_describe_gives_effective_and_default_values_or_the_refusal():
    description = describe_serving(STORED)
    rows = {row["tag"]: row for row in description["languages"]}
    assert rows["en"]["primary"] and rows["en"]["public"] and rows["en"]["prefix"] == ""
    assert rows["es-419"]["defaultPrefix"] == "es" and rows["es-419"]["slugPolicy"] == "translated" and not rows["es-419"]["public"]
    assert rows["zh-Hans"]["defaultSlugPolicy"] == "characters"
    refused = describe_serving({**STORED, "public": ["es-419"]})
    assert refused["ok"] is False and "must include the primary language en" in refused["message"]
