import pytest

from papyrus_content.item_stars import ITEM_STAR_FIELDS, assert_no_item_stars, carry_item_stars, item_stars


RATED = {"id": "a-v1", "starRating": 3, "starRatedAt": "2026-11-03T10:00:00Z", "starRatedBy": "an editor"}


def test_a_new_version_gets_the_rating_of_the_one_it_replaces():
    assert carry_item_stars(RATED, {"id": "a-v2"}) == {"id": "a-v2", "starRating": 3, "starRatedAt": "2026-11-03T10:00:00Z", "starRatedBy": "an editor"}


def test_an_unrated_story_gets_no_star_fields_at_all():
    assert carry_item_stars({"id": "a-v1", "starRating": None}, {"id": "a-v2"}) == {"id": "a-v2"}
    assert carry_item_stars(None, {"id": "a-v2"}) == {"id": "a-v2"}


def test_a_rating_the_new_version_already_has_is_kept():
    newer = {"id": "a-v2", "starRating": 5, "starRatedAt": "2026-11-03T11:00:00Z", "starRatedBy": "another editor"}
    assert carry_item_stars(RATED, dict(newer)) == newer


@pytest.mark.parametrize("value,expected", [(1, 1), (5, 5), (3.0, 3), (0, None), (6, None), (None, None), (True, None), ("4", None), (2.5, None)])
def test_item_stars_reads_only_a_whole_number_from_one_to_five(value, expected):
    assert item_stars({"starRating": value}) == expected


def test_the_guard_refuses_any_star_field_in_published_output():
    assert_no_item_stars({"id": "published-a", "title": "A"})
    for name in (*ITEM_STAR_FIELDS, "starRevision"):
        with pytest.raises(AssertionError, match="private"):
            assert_no_item_stars({"id": "published-a", name: None})


def test_a_cleared_rating_still_carries_its_revision_to_the_next_version():
    assert carry_item_stars({"starRating": None, "starRevision": "rev-1"}, {"id": "a-v2"}) == {"id": "a-v2", "starRevision": "rev-1"}
