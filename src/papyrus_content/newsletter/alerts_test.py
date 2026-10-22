"""Publish-triggered alerts: rule matching, dedupe, instant and approved sending, and the worker leaving alert issues alone.

Placeholders only: reader addresses are @example.com and the sections ("rulings", "notes") are made-up test data.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from papyrus_content.newsletter.alerts import first_paragraph, rule_matches
from papyrus_content.newsletter.issues_test import ADMIN, EDITOR, LISTS, Rig, rig_context
from papyrus_content.newsletter.newsletter_test import START
from papyrus_content.newsletter.store import iso

ROUNDUP = LISTS[0]


def alert(list_id: str, rule: dict[str, Any] | None = None, approval: str = "admin", name: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"id": list_id, "name": name or list_id.title(), "description": "", "kind": "alert", "approval": approval}
    if rule is not None:
        entry["rule"] = rule
    return entry


@pytest.fixture
def rig():
    with rig_context() as value:
        value.last_issue = ""
        yield value


def configure(rig: Rig, *alerts: dict[str, Any], instant: bool = False) -> None:
    object.__setattr__(rig.settings, "lists", (ROUNDUP, *alerts))
    object.__setattr__(rig.settings, "instant_alerts", instant)


def publish(rig: Rig, lineage: str = "story-1", **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": f"published-{lineage}", "sourceItemId": f"item-{lineage}", "itemLineageId": lineage, "type": "article",
        "status": "published", "slug": "a-ruling", "section": "rulings", "title": "A *big* ruling", "publishedAt": iso(rig.now),
        "bodyMarkus": "The court decided today.\n\n- one\n- two\n",
        "metadata": json.dumps({"frontMatterYaml": 'tags: [breaking, courts]\ndescription: "What it means."\n'}),
    }
    row.update(overrides)
    rig.content.published_items[row["id"]] = row
    return row


def announce(rig: Rig, lineage: str = "story-1") -> dict[str, Any]:
    return rig.task("item-published", itemId=f"item-{lineage}", lineageId=lineage, publishedItemId=f"published-{lineage}")


def alerts_of(rig: Rig) -> list[dict[str, Any]]:
    return [row for row in rig.service.issues.list_all() if row["kind"] == "alert"]


# -- rules ---------------------------------------------------------------------------------------------------------------


def test_rule_matching_or_within_a_field_and_across_fields() -> None:
    match = lambda rule, **item: rule_matches(rule, **{"section": "rulings", "tags": ["breaking"], "item_type": "article", **item})  # noqa: E731
    assert match(None) and match({}) and match({"sections": []})
    assert match({"sections": ["rulings", "notes"]}) and not match({"sections": ["notes"]})
    assert match({"sections": ["Rulings"]}), "names compare without regard to case"
    assert match({"tags": ["breaking", "other"]}) and not match({"tags": ["other"]})
    assert match({"types": ["article"]}) and not match({"types": ["video"]})
    assert match({"sections": ["rulings"], "tags": ["breaking"], "types": ["article"]})
    assert not match({"sections": ["rulings"], "tags": ["other"]}), "every field present must match"
    assert not match({"sections": ["rulings"]}, section=None)
    assert not match({"tags": ["breaking"]}, tags=[])


def test_each_list_raises_an_alert_only_for_items_its_rule_matches(rig: Rig) -> None:
    configure(
        rig,
        alert("everything"),
        alert("by-section", {"sections": ["rulings"]}),
        alert("by-tag", {"tags": ["courts"]}),
        alert("by-type", {"types": ["video"]}),
        alert("narrow", {"sections": ["rulings"], "tags": ["other"]}),
    )
    publish(rig)
    result = announce(rig)
    assert sorted(entry["listId"] for entry in result["alerts"]) == ["by-section", "by-tag", "everything"]
    assert sorted(row["listId"] for row in alerts_of(rig)) == ["by-section", "by-tag", "everything"]


# -- the alert issue -----------------------------------------------------------------------------------------------------


def test_the_alert_issue_has_the_item_title_and_a_markus_body_and_no_item(rig: Rig) -> None:
    configure(rig, alert("rulings", {"sections": ["rulings"]}, name="Rulings"))
    publish(rig)
    announce(rig)
    (issue,) = alerts_of(rig)
    assert (issue["status"], issue["subject"], issue["sourceItemId"], issue["lineageId"]) == ("awaiting_approval", "A *big* ruling", "item-story-1", "story-1")
    assert "itemId" not in issue and rig.content.items == {}, "no Item is created"
    body = issue["bodyMarkus"]
    url = "https://news.example.com/rulings/a-ruling.html"
    assert f"## [A \\*big\\* ruling]({url})" in body
    assert "What it means." in body and "The court decided today." in body
    assert f"[Read it on Example News]({url})" in body
    assert "one" not in body, "only the first paragraph of prose, never a list"
    assert issue["preheader"] == "What it means."


def test_the_item_url_follows_the_site_url_style(rig: Rig) -> None:
    configure(rig, alert("rulings"))
    object.__setattr__(rig.settings, "item_url_style", "directory")
    publish(rig)
    announce(rig)
    assert "https://news.example.com/rulings/a-ruling/" in alerts_of(rig)[0]["bodyMarkus"]


def test_an_item_without_a_deck_or_prose_still_makes_a_link_and_a_read_it_line(rig: Rig) -> None:
    configure(rig, alert("rulings"))
    publish(rig, bodyMarkus="## Heading only\n", metadata="{}", section=None)
    announce(rig)
    body = alerts_of(rig)[0]["bodyMarkus"]
    assert "[A \\*big\\* ruling](https://news.example.com/a-ruling.html)" in body and "Read it on Example News" in body


def test_the_first_paragraph_skips_structure_and_clips_long_text() -> None:
    assert first_paragraph("# Title\n\nFirst real paragraph.\nOn two lines.\n\nSecond.") == "First real paragraph. On two lines."
    assert first_paragraph("> quote\n\n- list\n\n| a | b |\n") == ""
    assert first_paragraph("") == "" and first_paragraph(None) == ""
    long = ("Sentence number one is here. " * 40).strip()
    clipped = first_paragraph(long)
    assert clipped.endswith(".") and len(clipped) <= 600
    assert first_paragraph("x" * 700) == ""


def test_a_first_paragraph_that_will_not_render_is_left_out(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    import papyrus_content.newsletter.alerts as alerts

    real = alerts.render

    def picky(settings, name, source, address, **kwargs):  # noqa: ANN001, ANN003
        if "BROKEN" in source.markus:
            raise ValueError("cannot render")
        return real(settings, name, source, address, **kwargs)

    monkeypatch.setattr(alerts, "render", picky)
    configure(rig, alert("rulings"))
    publish(rig, bodyMarkus="BROKEN markup here.\n")
    announce(rig)
    (issue,) = alerts_of(rig)
    assert "BROKEN" not in issue["bodyMarkus"] and "Read it on" in issue["bodyMarkus"]


# -- dedupe ---------------------------------------------------------------------------------------------------------------


def test_a_repeated_event_a_republish_and_an_edit_never_alert_twice(rig: Rig) -> None:
    configure(rig, alert("rulings"))
    publish(rig)
    first = announce(rig)
    again = announce(rig)
    publish(rig, title="A corrected title", bodyMarkus="Changed words.\n")  # an edit, republished
    republished = announce(rig)
    assert len(first["alerts"]) == 1 and again["alerts"] == [] and republished["alerts"] == []
    assert len(alerts_of(rig)) == 1 and alerts_of(rig)[0]["subject"] == "A *big* ruling"


def test_a_different_item_alerts_again_and_each_list_dedupes_on_its_own(rig: Rig) -> None:
    configure(rig, alert("one"), alert("two", {"sections": ["notes"]}))
    publish(rig)
    announce(rig)
    publish(rig, "story-2", section="notes", slug="a-note")
    result = announce(rig, "story-2")
    assert sorted(entry["listId"] for entry in result["alerts"]) == ["one", "two"]
    assert len(alerts_of(rig)) == 3


def test_a_crash_between_the_dedupe_row_and_the_issue_is_finished_on_retry(rig: Rig) -> None:
    configure(rig, alert("rulings"))
    publish(rig)
    original = rig.service.issues.create
    rig.service.issues.create = lambda row: (_ for _ in ()).throw(RuntimeError("crash"))  # type: ignore[assignment]
    with pytest.raises(RuntimeError):
        announce(rig)
    rig.service.issues.create = original  # type: ignore[assignment]
    assert alerts_of(rig) == []
    assert len(announce(rig)["alerts"]) == 1 and len(alerts_of(rig)) == 1
    assert announce(rig)["alerts"] == []


def test_one_failing_list_does_not_stop_the_others_and_is_retried(rig: Rig) -> None:
    configure(rig, alert("broken"), alert("fine"))
    publish(rig)
    original = rig.service.issues.create

    def create(row: dict[str, Any]) -> bool:
        if row["listId"] == "broken":
            raise RuntimeError("crash")
        return original(row)

    rig.service.issues.create = create  # type: ignore[assignment]
    with pytest.raises(RuntimeError):
        announce(rig)
    assert [row["listId"] for row in alerts_of(rig)] == ["fine"]
    rig.service.issues.create = original  # type: ignore[assignment]
    assert [entry["listId"] for entry in announce(rig)["alerts"]] == ["broken"]


# -- what is ignored -------------------------------------------------------------------------------------------------------


def test_issue_type_items_unpublished_items_and_odd_events_raise_nothing(rig: Rig) -> None:
    configure(rig, alert("rulings"))
    publish(rig, "issue-1", type="newsletter_issue")
    assert announce(rig, "issue-1") == {"ok": True, "status": "ignored", "reason": "issue_type"}
    publish(rig, "draft-1", status="unpublished")
    assert announce(rig, "draft-1")["reason"] == "not_published"
    assert announce(rig, "missing")["reason"] == "not_published"
    assert rig.task("item-published", itemId="x", lineageId="bad lineage!")["reason"] == "bad_event"
    assert rig.task("item-published", lineageId="ok")["reason"] == "bad_event"
    assert alerts_of(rig) == []


def test_a_site_with_no_alert_lists_does_nothing(rig: Rig) -> None:
    configure(rig)
    publish(rig)
    assert announce(rig)["reason"] == "no_alert_lists"


def test_the_published_item_is_found_from_the_lineage_when_the_event_omits_its_id(rig: Rig) -> None:
    configure(rig, alert("rulings"))
    publish(rig)
    assert len(rig.task("item-published", itemId="item-story-1", lineageId="story-1")["alerts"]) == 1


# -- approval and sending --------------------------------------------------------------------------------------------------


def members(rig: Rig, list_id: str, count: int = 2) -> None:
    for number in range(count):
        rig.add_member(f"reader{number}@example.com", list_id=list_id)


def test_an_alert_waits_for_an_admin_and_nothing_is_mailed(rig: Rig) -> None:
    configure(rig, alert("rulings"), instant=True)
    members(rig, "rulings")
    publish(rig)
    (created,) = announce(rig)["alerts"]
    assert created["status"] == "awaiting_approval"
    assert rig.ses.sent == [] and rig.queue.batches == [] and rig.scheduler.created == []


def test_an_admin_approves_an_awaiting_alert_and_it_is_scheduled_with_its_hash(rig: Rig) -> None:
    configure(rig, alert("rulings"))
    publish(rig)
    (created,) = announce(rig)["alerts"]
    assert rig.call("issue_approve", EDITOR, issueId=created["issueId"])["error"] == "forbidden"
    approved = rig.approve(created["issueId"])
    assert approved["ok"], approved
    issue = rig.issue(created["issueId"])
    assert issue["status"] == "scheduled" and issue["approvedBy"] == "admin-user" and issue["contentHash"]
    assert len(rig.scheduler.created) == 1


def test_cancelling_an_alert_ends_it_rather_than_returning_it_to_draft(rig: Rig) -> None:
    configure(rig, alert("rulings"))
    publish(rig)
    (waiting,) = announce(rig)["alerts"]
    assert rig.call("issue_cancel", EDITOR, issueId=waiting["issueId"])["error"] == "forbidden"
    assert rig.call("issue_cancel", ADMIN, issueId=waiting["issueId"])["ok"]
    assert rig.issue(waiting["issueId"])["status"] == "cancelled"
    publish(rig, "story-2")
    (scheduled,) = announce(rig, "story-2")["alerts"]
    rig.approve(scheduled["issueId"])
    assert rig.call("issue_cancel", ADMIN, issueId=scheduled["issueId"])["ok"]
    issue = rig.issue(scheduled["issueId"])
    assert issue["status"] == "cancelled" and "contentHash" not in issue and rig.scheduler.deleted
    assert rig.call("issue_approve", ADMIN, issueId=scheduled["issueId"])["error"] == "invalid_state", "a cancelled alert stays cancelled"


def test_instant_approval_none_with_instant_alerts_sends_at_once_to_the_list_only(rig: Rig) -> None:
    configure(rig, alert("rulings", approval="none"), alert("other"), instant=True)
    members(rig, "rulings", 2)
    publish(rig)
    result = announce(rig)["alerts"]
    instant = next(entry for entry in result if entry["listId"] == "rulings")
    assert instant["status"] == "sending" and instant["instant"] is True
    issue = rig.issue(instant["issueId"])
    assert issue["approvedBy"] == "system:instant-alert" and issue["contentHash"] and issue["counts"]["queued"] == 2
    assert next(entry for entry in result if entry["listId"] == "other")["status"] == "awaiting_approval"
    assert rig.scheduler.created == [], "no schedule: the send starts directly"
    rig.last_issue = instant["issueId"]
    rig.drain()
    assert rig.issue(instant["issueId"])["status"] == "sent"
    assert len(rig.ses.sent) == 2
    message = rig.ses.sent[0]["Content"]["Simple"]
    assert message["Subject"]["Data"] == "A *big* ruling"
    assert "You get this because you subscribed to Rulings on Example News." in message["Body"]["Text"]["Data"]


def test_approval_none_without_instant_alerts_still_waits_for_an_admin(rig: Rig) -> None:
    configure(rig, alert("rulings", approval="none"), instant=False)
    members(rig, "rulings")
    publish(rig)
    (created,) = announce(rig)["alerts"]
    assert created["status"] == "awaiting_approval" and rig.queue.batches == []


def test_instant_sends_still_meet_the_postal_address_and_paused_guards(rig: Rig) -> None:
    configure(rig, alert("rulings", approval="none"), instant=True)
    members(rig, "rulings")
    rig.postal.value = None
    publish(rig)
    (blocked,) = announce(rig)["alerts"]
    assert blocked["status"] == "blocked" and rig.issue(blocked["issueId"])["note"] == "postal address missing"
    rig.postal.value = "1 Example Street, Example City"
    rig.service.compliance.is_paused = lambda: True  # type: ignore[assignment]
    publish(rig, "story-2")
    (paused,) = announce(rig, "story-2")["alerts"]
    assert paused["status"] == "blocked" and rig.issue(paused["issueId"])["note"] == "site paused"
    assert rig.ses.sent == [] and rig.queue.batches == []
    # A blocked alert is fixed at its cause, then approved by an admin.
    rig.service.compliance.is_paused = lambda: False  # type: ignore[assignment]
    assert rig.approve(blocked["issueId"])["ok"]


def test_an_alert_sends_to_its_own_list_with_the_alert_footer_in_the_html(rig: Rig) -> None:
    configure(rig, alert("rulings", name="Rulings"))
    members(rig, "rulings", 1)
    publish(rig)
    (created,) = announce(rig)["alerts"]
    rig.last_issue = created["issueId"]
    rig.approve(created["issueId"])
    rig.now += 3600
    assert rig.fire(created["issueId"])["status"] == "sending"
    rig.drain()
    html = rig.ses.sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert "subscribed to Rulings on Example News" in html and "1 Example Street" in html


def test_the_worker_completes_an_alert_without_publishing_an_item(rig: Rig) -> None:
    configure(rig, alert("rulings", approval="none"), instant=True)
    members(rig, "rulings", 3)
    publish(rig)
    (created,) = announce(rig)["alerts"]
    rig.last_issue = created["issueId"]
    rig.drain()
    issue = rig.issue(created["issueId"])
    assert issue["status"] == "sent" and "archiveUrl" not in issue
    assert rig.published_items == [], "no Item is published for an alert"


def test_an_alert_is_not_edited_after_approval_and_a_missing_item_does_not_block_it(rig: Rig) -> None:
    configure(rig, alert("rulings"))
    members(rig, "rulings", 1)
    publish(rig)
    (created,) = announce(rig)["alerts"]
    rig.approve(created["issueId"])
    rig.content.published_items.clear()  # the source item is unpublished before the send
    rig.now += 3600
    rig.fire(created["issueId"])
    assert rig.issue(created["issueId"])["status"] == "sending", "the alert body is on the issue, so it still sends"


def test_preview_and_test_send_work_for_an_alert(rig: Rig) -> None:
    configure(rig, alert("rulings", name="Rulings"))
    publish(rig)
    (created,) = announce(rig)["alerts"]
    preview = rig.call("issue_preview", EDITOR, issueId=created["issueId"])
    assert preview["ok"] and "subscribed to Rulings on Example News" in preview["html"]
    assert rig.call("issue_test_send", EDITOR, issueId=created["issueId"])["ok"]
    assert rig.ses.sent and rig.ses.sent[-1]["Content"]["Simple"]["Subject"]["Data"].startswith("[Test] ")
    assert rig.call("issue_get", EDITOR, issueId=created["issueId"])["issue"]["lineageId"] == "story-1"


def test_settings_read_instant_alerts_from_the_environment() -> None:
    from papyrus_content.newsletter.handler import Settings

    base = {
        "SITE_ID": "example", "SITE_ORIGIN": "https://news.example.com", "SENDING_DOMAIN": "example.com", "FROM_ADDRESS": "n@example.com",
        "FROM_NAME": "Example News", "CONFIGURATION_SET": "c", "LISTS_JSON": "[]", "THEME_JSON": "{}",
    }
    assert Settings.from_environment(base).instant_alerts is False
    assert Settings.from_environment({**base, "INSTANT_ALERTS": "true"}).instant_alerts is True
    assert Settings.from_environment({**base, "INSTANT_ALERTS": "false"}).instant_alerts is False
