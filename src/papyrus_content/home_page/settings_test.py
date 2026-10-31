import pytest

from papyrus_content.home_page.export import PUBLIC_REFERENCE_FIELDS
from papyrus_content.home_page.settings import HomePageSettings, home_page_settings_from_mapping
from papyrus_content.projection.plugins import is_plugin_runtime_key
from papyrus_content.projection.standard.config import standard_settings_from_mapping


def test_an_empty_block_has_the_documented_defaults():
    settings = home_page_settings_from_mapping({})
    assert settings == HomePageSettings()
    assert (settings.layout, settings.per_section) == ("latest", 4)
    assert settings.references.fields == PUBLIC_REFERENCE_FIELDS
    assert (settings.references.default_count, settings.references.recommended_threshold) == (6, 0.5)
    assert (settings.threads.enabled, settings.threads.authors, settings.threads.anonymous_label) == (False, "handle", "Editor")
    assert (settings.freshness.debounce_seconds, settings.freshness.interval_hours, settings.freshness.purge) == (300, None, False)


def test_every_setting_is_read():
    settings = home_page_settings_from_mapping({
        "layout": "sections", "perSection": 3,
        "references": {"corpus": "knowledge-corpus-x", "fields": ["title", "key", "status"], "defaultCount": 9, "recommendedThreshold": 0.7},
        "threads": {"enabled": True, "authors": "anonymous", "anonymousLabel": "Staff"},
        "freshness": {"debounceSeconds": 60, "intervalHours": 6, "purge": True},
    })
    assert (settings.layout, settings.per_section) == ("sections", 3)
    assert settings.references.fields == ("key", "status", "title")
    assert settings.references.corpus == "knowledge-corpus-x"
    assert settings.threads.enabled and settings.threads.authors == "anonymous" and settings.threads.anonymous_label == "Staff"
    assert settings.freshness.interval_hours == 6 and settings.freshness.purge


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"colour": "red"}, "Unknown homePage settings: colour"),
        ({"references": {"limit": 3}}, "Unknown homePage.references settings: limit"),
        ({"threads": {"order": "x"}}, "Unknown homePage.threads settings: order"),
        ({"freshness": {"every": 1}}, "Unknown homePage.freshness settings: every"),
        ({"layout": "grid"}, "homePage.layout must be one of"),
        ({"references": {"fields": ["title", "key", "status", "curationStatusUpdatedBy"]}}, "not public: curationStatusUpdatedBy"),
        ({"references": {"fields": ["title"]}}, "must include key, status"),
        ({"references": {"recommendedThreshold": 2}}, "recommendedThreshold"),
        ({"references": {"defaultCount": 0}}, "defaultCount"),
        ({"threads": {"anonymousLabel": "a@b.test"}}, "anonymousLabel"),
        ({"freshness": {"purge": "yes"}}, "purge"),
    ],
)
def test_a_wrong_setting_is_a_build_error_that_names_it(raw, message):
    with pytest.raises(ValueError, match=message):
        home_page_settings_from_mapping(raw)


def test_the_standard_settings_hold_none_without_the_key_and_parse_it_with_the_key():
    base = {"site": {"name": "Example"}}
    assert standard_settings_from_mapping(base).home_page is None
    sectioned = {**base, "urls": {"sections": {"essays": {}}}}
    assert standard_settings_from_mapping({**sectioned, "homePage": {"layout": "sections"}}).home_page.layout == "sections"
    with pytest.raises(ValueError, match="needs urls.sections"):
        standard_settings_from_mapping({**base, "homePage": {"layout": "sections"}})
    with pytest.raises(ValueError, match="Unknown homePage settings: nope"):
        standard_settings_from_mapping({**base, "homePage": {"nope": 1}})


def test_reconcile_never_calls_a_home_page_data_file_an_orphan():
    assert is_plugin_runtime_key("_data/home-page/references.json")
    assert is_plugin_runtime_key("updates/_data/home-page/references.json")
    assert not is_plugin_runtime_key("_data/home-pagex.json")


def test_the_threads_author_policy_accepts_handle_and_none():
    from papyrus_content.home_page.settings import home_page_settings_from_mapping

    assert home_page_settings_from_mapping({"threads": {"enabled": True, "authors": "none"}}).threads.authors == "none"
    assert home_page_settings_from_mapping({"threads": {"authors": "handle"}}).threads.authors == "handle"
