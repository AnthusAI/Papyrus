"""The public audience with cadence families, on Caducus's in-memory fakes (behaviour: features_backend/cadence-family.feature)."""
from datetime import datetime, timedelta, timezone

import pytest

from .notifications_test import Site

LISTS = (
    {"id": "each", "name": "Every story", "description": "", "family": "new-stories", "rule": {}, "approval": "admin"},
    {"id": "daily", "name": "Daily", "description": "", "family": "new-stories", "rule": {"sections": ["digest"]}, "approval": "admin"},
    {"id": "weekly", "name": "Weekly", "description": "", "rule": {"sections": ["digest"]}, "approval": "admin"},
)
ADDRESS = "reader@example.test"


@pytest.fixture
def site() -> Site:
    return Site("alpha", readers=0, lists=LISTS)


def lists_of(site: Site, address: str = ADDRESS) -> list[str]:
    audience = site.runtime.audience
    return sorted(audience.subscribed_lists(audience._keys.recipient(address)))


def save(site: Site, token: str, lists: list[str]) -> dict:
    return site.act("update_preferences", token=token, lists=lists)


def test_two_new_lists_of_one_family_are_refused_before_anything_is_mailed(site):
    answer = site.subscribe(ADDRESS, ["each", "daily"])
    assert (answer["statusCode"], answer["body"]["status"]) == (400, "one_cadence_per_family")
    assert site.mailer.calls == []


def test_a_new_list_of_a_family_moves_the_reader_off_the_old_one(site):
    token = site.join(ADDRESS, ["each"])
    assert save(site, token, ["each", "daily"])["body"]["status"] == "saved"
    assert lists_of(site) == ["daily"]


def test_adding_two_lists_of_one_family_in_one_save_is_refused_and_changes_nothing(site):
    token = site.join(ADDRESS, ["weekly"])
    answer = save(site, token, ["weekly", "each", "daily"])
    assert answer["body"]["status"] == "one_cadence_per_family"
    assert lists_of(site) == ["weekly"]


def test_confirming_a_list_of_a_family_the_reader_already_holds_moves_them(site):
    site.join(ADDRESS, ["each"])
    site.join(ADDRESS, ["daily"])
    assert lists_of(site) == ["daily"]


def test_a_list_alone_in_its_family_is_unaffected_by_a_choice_in_another(site):
    token = site.join(ADDRESS, ["weekly"])
    save(site, token, ["weekly", "each"])
    save(site, token, ["weekly", "each", "daily"])
    assert lists_of(site) == ["daily", "weekly"]


def test_a_site_without_families_still_lets_a_reader_hold_every_list():
    plain = Site("beta", readers=0)
    token = plain.join(ADDRESS, ["stories"])
    assert plain.act("update_preferences", token=token, lists=["stories", "security"])["body"]["status"] == "saved"
    assert lists_of(plain) == ["security", "stories"]


def test_an_import_naming_two_lists_of_a_family_is_refused(site):
    assert site.runtime.audience.import_subscriber(ADDRESS, ["each", "daily"], {"confirmedAt": "2026-11-01T00:00:00Z"}, "old-system") == "refused"
    assert lists_of(site) == []


def test_an_import_of_one_list_is_imported(site):
    assert site.runtime.audience.import_subscriber(ADDRESS, ["daily"], {"confirmedAt": "2026-11-01T00:00:00Z"}, "old-system") == "imported"
    assert lists_of(site) == ["daily"]


def test_a_membership_records_when_the_reader_joined_and_keeps_it_while_they_stay(site):
    site.clock.now = datetime(2026, 11, 3, 15, tzinfo=timezone.utc)
    token = site.join(ADDRESS, ["weekly"])
    site.clock.now += timedelta(days=1)
    save(site, token, ["weekly", "each"])
    audience, key = site.runtime.audience, site.runtime.audience._keys.recipient(ADDRESS)
    assert audience.since(key, "weekly") == datetime(2026, 11, 3, 15, tzinfo=timezone.utc)
    assert audience.since(key, "each") == datetime(2026, 11, 4, 15, tzinfo=timezone.utc)
    assert audience.since(key, "daily") is None


def test_leaving_and_rejoining_begins_a_new_membership(site):
    site.clock.now = datetime(2026, 11, 3, 15, tzinfo=timezone.utc)
    token = site.join(ADDRESS, ["daily", "weekly"])
    save(site, token, ["weekly"])
    site.clock.now += timedelta(days=2)
    save(site, token, ["daily", "weekly"])
    audience, key = site.runtime.audience, site.runtime.audience._keys.recipient(ADDRESS)
    assert audience.since(key, "daily") == datetime(2026, 11, 5, 15, tzinfo=timezone.utc)


def test_the_subscriber_page_as_of_a_moment_holds_only_the_members_by_then(site):
    site.clock.now = datetime(2026, 11, 3, 15, tzinfo=timezone.utc)
    site.join("early@example.test", ["daily"])
    site.clock.now += timedelta(days=2)
    site.join("late@example.test", ["daily"])
    audience = site.runtime.audience
    everyone, _ = audience.subscriber_page("daily", None)
    by_then, _ = audience.subscriber_page("daily", None, as_of=datetime(2026, 11, 4, tzinfo=timezone.utc))
    assert len(everyone) == 2
    assert by_then == [audience._keys.recipient("early@example.test")]


def test_a_one_click_link_of_the_list_a_reader_left_leaves_the_list_they_chose(site):
    token = site.join(ADDRESS, ["each"])
    site.publish("Rates held steady", "news")
    site.play_queue()
    mail = site.mailer.calls[-1]
    save(site, token, ["each", "daily"])
    url = mail["headers"]["List-Unsubscribe"].strip("<>")
    query = dict(part.split("=", 1) for part in url.split("?", 1)[1].split("&"))
    assert site.act("unsubscribe", token=query["t"], list=query.get("l"))["body"]["status"] == "unsubscribed"
    assert lists_of(site) == ["daily"]
    audience = site.runtime.audience
    assert audience.suppression(audience._keys.recipient(ADDRESS)) is None
