"""The preferences save: a cadence inside a held family is a move, joining a family asks for consent (PPY-2f9b22). Caducus's in-memory fakes; nothing is sent."""

from __future__ import annotations

from papyrus_content.notifications.notifications_test import CONSENT, Site
from papyrus_content.notifications.preferences import consent_by_family

ADDRESS = "reader@alpha.example.test"
BASE = {"description": "", "approval": "admin"}
LISTS = (
    {**BASE, "id": "every-item", "name": "Every new story", "family": "new-stories", "cadence": "each", "rule": {}},
    {**BASE, "id": "daily", "name": "Daily summary", "family": "new-stories", "cadence": "daily", "sendAt": {"time": "06:00"}, "timeZone": "America/New_York", "rule": {}},
    {**BASE, "id": "weekly", "name": "Weekly newsletter", "cadence": "weekly", "sendAt": {"day": "monday", "time": "04:00"}, "timeZone": "America/New_York", "rule": {}},
)


def site_with(*joined: str) -> tuple[Site, str]:
    site = Site("alpha", readers=0, lists=LISTS)
    token = site.join(ADDRESS, [joined[0]])
    for list_id in joined[1:]:
        token = site.join(ADDRESS, [list_id])
    site.mailer.calls.clear()
    return site, token


def save(site: Site, token: str, lists: list[str], **fields):
    answer = site.act("update_preferences", token=token, lists=lists, ip="203.0.113.9", **fields)
    site.play_queue()
    return answer


def held(site: Site, token: str) -> list[str]:
    return sorted(view["id"] for view in site.act("preferences_state", token=token)["body"]["lists"] if view["subscribed"])


def test_a_cadence_inside_a_held_family_is_saved_without_a_confirmation() -> None:
    site, token = site_with("every-item")
    assert save(site, token, ["daily"])["body"] == {"status": "saved", "lists": ["daily"]}
    assert held(site, token) == ["daily"] and site.mailer.calls == []


def test_a_new_family_waits_for_a_confirmation_and_is_not_on_before_it() -> None:
    site, token = site_with("every-item")
    answer = save(site, token, ["every-item", "weekly"], consent=CONSENT, formId="notifications-preferences")
    assert answer["statusCode"] == 202 and answer["body"] == {"status": "check_email", "lists": ["every-item"], "confirming": ["weekly"]}
    assert held(site, token) == ["every-item"]
    assert [call["subject"] for call in site.mailer.calls] == ["Confirm your subscription to Alpha News"]


def test_without_the_sites_consent_wording_nothing_changes() -> None:
    site, token = site_with("every-item")
    for fields in ({}, {"consent": "Sign me up."}):
        assert save(site, token, ["every-item", "weekly"], **fields)["body"]["status"] == "invalid_consent"
    assert held(site, token) == ["every-item"] and site.mailer.calls == []


def test_a_bad_token_is_invalid() -> None:
    site, _ = site_with("every-item")
    assert save(site, "not-a-token", ["weekly"], consent=CONSENT)["body"]["status"] == "invalid"


def test_a_reader_suppressed_for_a_bounce_lifts_it_with_their_own_opt_in() -> None:
    """Caducus sends no confirmation to a bounced address, so their own choice on their manage page is what lifts it."""
    site, token = site_with("every-item")
    key = site.runtime.keys.recipient(ADDRESS)
    site.runtime.audience.provider_event(key, "bounced")
    assert save(site, token, ["weekly"])["body"]["status"] == "saved"
    assert held(site, token) == ["weekly"] and site.runtime.audience.suppression(key) is None


def test_consent_evidence_is_grouped_by_family() -> None:
    site, _ = site_with("weekly", "every-item")
    evidence = consent_by_family(site.runtime.audience, ADDRESS)
    assert sorted(evidence) == ["new-stories", "weekly"]
    assert [record["wording"] for record in evidence["weekly"]] == [CONSENT]
    assert evidence["new-stories"][0]["lists"] == ["every-item"]
