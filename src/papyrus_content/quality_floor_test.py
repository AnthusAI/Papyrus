import pytest

from papyrus_content.quality_floor import DEFAULT_FLOOR_STARS, QualitySettings, meets_floor, quality_settings_from_mapping


def test_a_quality_block_with_no_number_is_the_default_floor_of_three():
    assert quality_settings_from_mapping({}).floor_stars == DEFAULT_FLOOR_STARS == 3


def test_a_site_may_raise_the_floor_to_five_and_never_lower_it_below_one():
    assert quality_settings_from_mapping({"floorStars": 5}).floor_stars == 5
    assert quality_settings_from_mapping({"floorStars": 1}).floor_stars == 1
    for refused in (0, 6, -1, 3.5, "3", True, None):
        with pytest.raises(ValueError, match="floorStars"):
            quality_settings_from_mapping({"floorStars": refused})


def test_an_unknown_key_or_a_block_that_is_not_an_object_is_refused():
    with pytest.raises(ValueError, match="Unknown quality settings: floor_stars"):
        quality_settings_from_mapping({"floor_stars": 3})
    with pytest.raises(ValueError, match="quality must be an object"):
        quality_settings_from_mapping(3)


def test_without_a_quality_block_there_is_no_floor():
    assert QualitySettings().floor_stars is None


def test_unrated_never_qualifies_and_a_rating_qualifies_at_the_floor_or_above():
    assert meets_floor(None, 3) is False
    assert meets_floor(0, 1) is False
    assert meets_floor(2, 3) is False
    assert meets_floor(3, 3) is True
    assert meets_floor(5, 4) is True


def test_with_no_floor_everything_qualifies():
    assert meets_floor(None, None) and meets_floor(0, None) and meets_floor(1, None)
