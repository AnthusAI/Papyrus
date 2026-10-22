"""The Newsletter panel's operations: authorization from claims, the membership counters on every transition, recount, masking.

Placeholders only (@example.com). The counters are checked two ways: against explicit numbers, and against ``recount``, which
rebuilds them from the rows, so a transition that forgets its counter fails whichever way it is written.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from papyrus_content.newsletter import addresses, ops_proxy, panel, records
from papyrus_content.newsletter.handler import ACTIONS
from papyrus_content.newsletter.issues_test import ADMIN, EDITOR, NOBODY, Rig, rig, scheduled_issue  # noqa: F401
from papyrus_content.newsletter.manage import MANAGE_ACTIONS, mask
from papyrus_content.newsletter.manage_test import alarm, ses_event, sns
from papyrus_content.newsletter.newsletter_test import OTHER, READER, START
from papyrus_content.newsletter.store import SITE_COUNT_ID, Conflict, iso, membership_row, profile_key

LIST_IDS = ["weekly", "alerts-a"]
ZERO = {"confirmed": 0, "pending": 0, "unsubscribed": 0}


def subscribe(rig: Rig, email: str = READER, lists: Any = ("weekly",), *, confirm: bool = True) -> str:
    rig.harness.now += 4000
    rig.harness.subscribe(email, lists=lists)
    if confirm:
        rig.harness.confirm()
    return addresses.hid(rig.harness.keys.hash, email)


def manage(rig: Rig, action: str, email: str = READER, **fields: Any) -> dict[str, Any]:
    from papyrus_content.newsletter import links

    token = links.make_manage_token(addresses.hid(rig.harness.keys.hash, email), rig.harness.keys)
    return rig.harness.service.dispatch({"action": action, "token": token, **fields})["body"]


def live(rig: Rig) -> dict[str, dict[str, int]]:
    out = {}
    for count_id in [SITE_COUNT_ID, *LIST_IDS]:
        row = {name: value for name, value in rig.harness.store.get_counts(count_id).items() if name not in ("seeded", "seededAt")}
        out[count_id] = {**ZERO, **row} if count_id != SITE_COUNT_ID else {**ZERO, "suppressed": 0, **row}
    return out


def assert_counters_true(rig: Rig) -> dict[str, dict[str, int]]:
    """The incremental counters equal what a scan of the rows says."""
    before = live(rig)
    rig.harness.store.recount(LIST_IDS, rig.harness.now)
    after = live(rig)
    assert before == after
    return after


def overview(rig: Rig, identity: dict[str, Any] | None = ADMIN) -> dict[str, Any]:
    return rig.call("panel_overview", identity)


# -- authorization -----------------------------------------------------------------------------------------------------


STAFF_ACTIONS = {"panel_overview": {}, "panel_deliveries": {"issueId": "abc"}}
ADMIN_ACTIONS = {"panel_subscribers": {}, "panel_export": {}, "panel_erase": {"email": READER}, "panel_resume": {}}


@pytest.mark.parametrize("action", sorted({**STAFF_ACTIONS, **ADMIN_ACTIONS}))
def test_nobody_and_a_missing_identity_are_forbidden(rig: Rig, action: str) -> None:
    for identity in (NOBODY, None, {"groups": "admin"}, {"groups": [7]}):
        assert rig.call(action, identity)["error"] == "forbidden"


@pytest.mark.parametrize("action", sorted(ADMIN_ACTIONS))
def test_editors_cannot_use_admin_operations_and_nothing_changes(rig: Rig, action: str) -> None:
    hid = subscribe(rig)
    rig.harness.service.dispatch(sns(alarm("papyrus-newsletter-example-bounce-rate")))
    before = rig.harness.items()
    result = rig.call(action, EDITOR, **ADMIN_ACTIONS[action])
    assert result == {"ok": False, "error": "forbidden", "message": "This needs a different role."}
    assert rig.harness.items() == before and rig.harness.profile()["pk"].endswith(hid)
    assert rig.harness.ses.sending == [False]


@pytest.mark.parametrize("action", ["panel_overview"])
def test_editors_and_admins_may_read_the_overview(rig: Rig, action: str) -> None:
    assert rig.call(action, EDITOR)["ok"] and rig.call(action, ADMIN)["ok"]


def test_the_group_comes_from_the_forwarded_claims_not_the_input(rig: Rig) -> None:
    result = rig.call("panel_subscribers", EDITOR, groups=["admin"], claims={"cognito:groups": ["admin"]})
    assert result["error"] == "forbidden"


def test_the_proxy_maps_every_panel_operation_to_a_real_action() -> None:
    dispatchable = set(ACTIONS) | set(MANAGE_ACTIONS) | set(panel.PANEL_ACTIONS)
    assert set(ops_proxy.FIELD_ACTIONS.values()) <= dispatchable
    for name in ("Overview", "Subscribers", "Export", "Erase", "Resume", "IssueDeliveries"):
        assert f"newsletter{name}" in ops_proxy.FIELD_ACTIONS
    assert "recount" not in ops_proxy.FIELD_ACTIONS.values(), "recount is an operator action, not an AppSync operation"


def test_the_proxy_forwards_claims_for_a_panel_operation() -> None:
    sent: list[dict[str, Any]] = []

    class Lambda:
        def invoke(self, **kwargs: Any) -> dict[str, Any]:
            sent.append(json.loads(kwargs["Payload"]))
            body = json.dumps({"statusCode": 200, "body": {"ok": True}}).encode()
            return {"Payload": type("P", (), {"read": lambda self: body})()}

    event = {"info": {"fieldName": "newsletterErase"}, "arguments": {"input": json.dumps({"email": READER})},
             "identity": {"username": "u", "sub": "s", "groups": ["admin"], "claims": {"email": "admin@example.com"}}}
    assert ops_proxy.handle(event, client=Lambda(), environment={"NEWSLETTER_FUNCTION_NAME": "f"}) == {"ok": True}
    assert sent[0]["action"] == "panel_erase" and sent[0]["identity"]["groups"] == ["admin"]


# -- counters: every transition ----------------------------------------------------------------------------------------


def test_signup_confirmation_and_a_second_list(rig: Rig) -> None:
    subscribe(rig, lists=("weekly",), confirm=False)
    counts = assert_counters_true(rig)
    assert counts["weekly"]["pending"] == 1 and counts[SITE_COUNT_ID]["pending"] == 1
    rig.harness.confirm()
    counts = assert_counters_true(rig)
    assert counts["weekly"] == {**ZERO, "confirmed": 1} and counts[SITE_COUNT_ID]["confirmed"] == 1 and counts[SITE_COUNT_ID]["pending"] == 0
    rig.harness.now += 4000
    rig.harness.subscribe(READER, lists=("weekly", "alerts-a"))  # a confirmed subscriber asking for one more list
    counts = assert_counters_true(rig)
    assert counts["alerts-a"]["pending"] == 1 and counts["weekly"]["confirmed"] == 1 and counts[SITE_COUNT_ID]["confirmed"] == 1
    rig.harness.confirm()
    counts = assert_counters_true(rig)
    assert counts["alerts-a"] == {**ZERO, "confirmed": 1}


def test_a_pending_signup_that_changes_its_lists_drops_the_stale_pending_row(rig: Rig) -> None:
    subscribe(rig, lists=("weekly",), confirm=False)
    rig.harness.now += 4000
    rig.harness.subscribe(READER, lists=("alerts-a",))
    counts = assert_counters_true(rig)
    assert counts["weekly"] == ZERO and counts["alerts-a"]["pending"] == 1 and counts[SITE_COUNT_ID]["pending"] == 1


def test_unsubscribing_from_one_list_then_all_then_signing_up_again(rig: Rig) -> None:
    subscribe(rig, lists=("weekly", "alerts-a"))
    assert manage(rig, "unsubscribe", list="alerts-a")["status"] == "unsubscribed"
    counts = assert_counters_true(rig)
    assert counts["alerts-a"]["unsubscribed"] == 1 and counts["weekly"]["confirmed"] == 1 and counts[SITE_COUNT_ID]["confirmed"] == 1
    manage(rig, "unsubscribe")
    counts = assert_counters_true(rig)
    assert counts[SITE_COUNT_ID] == {**ZERO, "unsubscribed": 1, "suppressed": 0} and counts["weekly"]["unsubscribed"] == 1
    manage(rig, "unsubscribe")  # idempotent: no second count
    assert assert_counters_true(rig)[SITE_COUNT_ID]["unsubscribed"] == 1
    rig.harness.now += 4000
    rig.harness.subscribe(READER, lists=("weekly",))  # unsubscribed and asking again: a fresh double opt-in
    counts = assert_counters_true(rig)
    assert counts[SITE_COUNT_ID] == {**ZERO, "pending": 1, "suppressed": 0} and counts["weekly"]["pending"] == 1


def test_preferences_move_lists_between_buckets(rig: Rig) -> None:
    subscribe(rig, lists=("weekly", "alerts-a"))
    manage(rig, "update_preferences", lists=["weekly"])
    counts = assert_counters_true(rig)
    assert counts["alerts-a"]["unsubscribed"] == 1 and counts["alerts-a"]["confirmed"] == 0
    manage(rig, "update_preferences", lists=[])
    assert assert_counters_true(rig)[SITE_COUNT_ID]["unsubscribed"] == 1
    manage(rig, "update_preferences", lists=["alerts-a"])
    counts = assert_counters_true(rig)
    assert counts[SITE_COUNT_ID]["confirmed"] == 1 and counts["alerts-a"]["confirmed"] == 1 and counts["alerts-a"]["unsubscribed"] == 0


def test_suppression_counts_once_and_clears_on_a_deliberate_resubscribe(rig: Rig) -> None:
    hid = subscribe(rig, lists=("weekly",))
    event = sns(ses_event("Bounce", hid, bounce={"bounceType": "Permanent"}))
    rig.harness.service.dispatch(event)
    counts = assert_counters_true(rig)
    assert counts[SITE_COUNT_ID]["suppressed"] == 1 and counts[SITE_COUNT_ID]["unsubscribed"] == 1 and counts["weekly"]["unsubscribed"] == 1
    rig.harness.service.dispatch(event)  # a repeated notification
    assert assert_counters_true(rig)[SITE_COUNT_ID]["suppressed"] == 1
    manage(rig, "update_preferences", lists=["weekly"])
    counts = assert_counters_true(rig)
    assert counts[SITE_COUNT_ID]["suppressed"] == 0 and counts[SITE_COUNT_ID]["confirmed"] == 1


def test_a_manual_suppression_is_counted_and_removed(rig: Rig) -> None:
    hid = addresses.hid(rig.harness.keys.hash, READER)
    records.put_suppression(rig.harness.store, hid, "manual", START)
    assert assert_counters_true(rig)[SITE_COUNT_ID]["suppressed"] == 1
    records.delete_suppression(rig.harness.store, hid)
    records.delete_suppression(rig.harness.store, hid)
    assert assert_counters_true(rig)[SITE_COUNT_ID]["suppressed"] == 0


def test_erasure_by_token_and_by_address_takes_the_subscriber_out_of_every_count(rig: Rig) -> None:
    hid = subscribe(rig, lists=("weekly", "alerts-a"))
    subscribe(rig, OTHER, lists=("weekly",), confirm=False)
    records.put_suppression(rig.harness.store, hid, "complaint", START)
    assert manage(rig, "delete_subscriber")["status"] == "deleted"
    counts = assert_counters_true(rig)
    assert counts[SITE_COUNT_ID] == {**ZERO, "pending": 1, "suppressed": 0} and counts["alerts-a"] == ZERO and counts["weekly"]["pending"] == 1
    assert rig.call("panel_erase", ADMIN, email=OTHER) == {"ok": True, "removed": 3}
    assert assert_counters_true(rig)[SITE_COUNT_ID] == {**ZERO, "suppressed": 0}


def test_a_failed_conditional_write_changes_no_counter(rig: Rig) -> None:
    subscribe(rig, lists=("weekly",))
    store = rig.harness.store
    before = live(rig)
    profile = rig.harness.profile()
    profile["status"] = "unsubscribed"
    with pytest.raises(Conflict):
        store.save(profile, int(profile["rev"]) + 5, [membership_row(profile["pk"].removeprefix("SUB#"), "weekly", "unsubscribed", START)])
    with pytest.raises(Conflict):
        store.save({**profile_key(profile["pk"].removeprefix("SUB#")), "status": "pending"}, None, [])
    assert live(rig) == before == assert_counters_true(rig)


def test_the_unmeasured_gap_is_healed_by_recount(rig: Rig) -> None:
    subscribe(rig, lists=("weekly",))
    store = rig.harness.store
    store.client.put_item(TableName="newsletter", Item={"pk": {"S": "COUNT#weekly"}, "sk": {"S": "COUNT"}, "confirmed": {"N": "9"}, "pending": {"N": "-3"}})
    assert live(rig)["weekly"]["confirmed"] == 9
    result = rig.api.dispatch({"action": "recount"})["body"]
    assert result["status"] == "recounted" and result["lists"]["weekly"] == {**ZERO, "confirmed": 1}
    assert live(rig)["weekly"] == {**ZERO, "confirmed": 1}


def test_recount_ignores_pending_rows_whose_time_to_live_has_passed(rig: Rig) -> None:
    subscribe(rig, lists=("weekly",), confirm=False)
    assert rig.harness.store.recount(LIST_IDS, rig.harness.now)["site"]["pending"] == 1
    assert rig.harness.store.recount(LIST_IDS, rig.harness.now + 31 * 24 * 3600)["site"]["pending"] == 0


# -- overview ----------------------------------------------------------------------------------------------------------


def test_overview_reports_lists_totals_suppressed_pause_and_events_without_addresses(rig: Rig) -> None:
    hid = subscribe(rig, lists=("weekly", "alerts-a"))
    subscribe(rig, OTHER, lists=("weekly",), confirm=False)
    rig.harness.service.dispatch(sns(ses_event("Complaint", hid, issue="i1", list_id="weekly")))
    rig.harness.service.dispatch(sns(alarm("papyrus-newsletter-example-bounce-rate")))
    body = overview(rig, EDITOR)
    assert body["ok"] and [item["id"] for item in body["lists"]] == ["weekly", "alerts-a"]
    weekly = body["lists"][0]
    assert weekly == {"id": "weekly", "name": "Weekly roundup", "kind": "roundup", "confirmed": 0, "pending": 1, "unsubscribed": 1, "timezone": "America/New_York"}
    assert body["totals"] == {"confirmed": 0, "pending": 1, "unsubscribed": 1} and body["suppressed"] == 1
    assert body["paused"]["paused"] is True and "bounce-rate" in body["paused"]["reason"]
    assert [(e["type"], e.get("issue"), e.get("list")) for e in body["events"]] == [("Complaint", "i1", "weekly")]
    text = json.dumps(body)
    assert "@" not in text and hid not in text and "example.com" not in text


def test_overview_counts_subscribers_that_existed_before_the_counters(rig: Rig) -> None:
    store = rig.harness.store
    hid = addresses.hid(rig.harness.keys.hash, READER)
    from papyrus_content.newsletter.store import _ser

    store.client.put_item(TableName="newsletter", Item=_ser({**profile_key(hid), "email": READER, "status": "confirmed", "createdAt": iso(START)}))
    store.client.put_item(TableName="newsletter", Item=_ser(membership_row(hid, "weekly", "subscribed", START, profile_confirmed=True)))
    assert store.get_counts(SITE_COUNT_ID) == {}
    subscribe(rig, OTHER, lists=("weekly",), confirm=False)  # an ordinary write now starts the counters without the old data
    assert store.get_counts(SITE_COUNT_ID).get("confirmed", 0) == 0
    body = overview(rig)
    assert body["totals"] == {"confirmed": 1, "pending": 1, "unsubscribed": 0} and body["lists"][0]["confirmed"] == 1


def test_overview_keeps_the_last_hundred_events_newest_first(rig: Rig) -> None:
    hid = addresses.hid(rig.harness.keys.hash, READER)
    for index in range(105):
        records.put_event(rig.harness.store, message_id=f"m{index:03d}", event_type="Delivery", hid=hid, issue="i1", list_id="weekly", detail="", now=START + index)
    events = overview(rig)["events"]
    assert len(events) == 100 and events[0]["at"] > events[-1]["at"] and events[0]["at"] == iso(START + 104)
    assert set(events[0]) == {"type", "at", "issue", "list"}


def test_a_fresh_site_shows_zeroes_and_not_paused(rig: Rig) -> None:
    body = overview(rig)
    assert body["totals"] == ZERO and body["suppressed"] == 0 and body["paused"] == {"paused": False} and body["events"] == []


# -- subscribers, export, erase, resume --------------------------------------------------------------------------------


def test_subscribers_lists_addresses_for_admins_with_paging_and_filters(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    subscribe(rig, "a@example.com", lists=("weekly", "alerts-a"))
    subscribe(rig, "b@example.com", lists=("alerts-a",), confirm=False)
    subscribe(rig, "c@example.com", lists=("weekly",))
    manage(rig, "unsubscribe", "c@example.com")
    everyone = rig.call("panel_subscribers", ADMIN)
    assert everyone["ok"] and "cursor" not in everyone
    assert {row["email"] for row in everyone["subscribers"]} == {"a@example.com", "b@example.com", "c@example.com"}
    first = next(row for row in everyone["subscribers"] if row["email"] == "a@example.com")
    assert first["status"] == "confirmed" and first["lists"] == [{"id": "alerts-a", "status": "subscribed"}, {"id": "weekly", "status": "subscribed"}]
    assert first["confirmedAt"] and first["createdAt"]
    assert [row["email"] for row in rig.call("panel_subscribers", ADMIN, status="pending")["subscribers"]] == ["b@example.com"]
    assert {row["email"] for row in rig.call("panel_subscribers", ADMIN, listId="alerts-a")["subscribers"]} == {"a@example.com", "b@example.com"}
    assert rig.call("panel_subscribers", ADMIN, status="bogus")["error"] == "bad_request"
    assert rig.call("panel_subscribers", ADMIN, listId="nope")["error"] == "bad_request"

    monkeypatch.setattr(panel, "SUBSCRIBER_PAGE", 2)
    seen, cursor = [], None
    for _ in range(5):
        page = rig.call("panel_subscribers", ADMIN, **({"cursor": cursor} if cursor else {}))
        assert len(page["subscribers"]) <= 2
        seen += [row["email"] for row in page["subscribers"]]
        cursor = page.get("cursor")
        if not cursor:
            break
    assert sorted(seen) == ["a@example.com", "b@example.com", "c@example.com"]
    assert rig.call("panel_subscribers", ADMIN, cursor="not-a-cursor")["ok"]


def test_a_filtered_page_keeps_looking_past_profiles_that_do_not_match(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(panel, "SCAN_WINDOW", 2)
    for index in range(5):
        subscribe(rig, f"s{index}@example.com", lists=("weekly",))
    subscribe(rig, "z@example.com", lists=("alerts-a",))
    result = rig.call("panel_subscribers", ADMIN, listId="alerts-a")
    assert [row["email"] for row in result["subscribers"]] == ["z@example.com"]


def test_cursors_reject_anything_but_a_primary_key() -> None:
    good = panel.encode_cursor({"pk": {"S": "SUB#x"}, "sk": {"S": "PROFILE"}, "extra": {"S": "y"}})
    assert panel.decode_cursor(good) is None
    for bad in (None, "", 5, "!!!", panel.encode_cursor({"pk": {"S": "x"}}), panel.encode_cursor({"pk": {"N": "1"}, "sk": {"S": "b"}})):
        assert panel.decode_cursor(bad) is None
    key = {"pk": {"S": "SUB#x"}, "sk": {"S": "PROFILE"}}
    assert panel.decode_cursor(panel.encode_cursor(key)) == key


def test_export_has_confirmed_and_pending_with_consent_and_no_network_data(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    subscribe(rig, "a@example.com", lists=("weekly", "alerts-a"))
    subscribe(rig, "b@example.com", lists=("weekly",), confirm=False)
    subscribe(rig, "c@example.com", lists=("weekly",))
    manage(rig, "unsubscribe", "c@example.com")
    result = rig.call("panel_export", ADMIN)
    rows = {row["email"]: row for row in result["rows"]}
    assert set(rows) == {"a@example.com", "b@example.com"}
    assert rows["a@example.com"]["lists"] == "alerts-a:subscribed;weekly:subscribed" and rows["a@example.com"]["status"] == "confirmed"
    assert rows["a@example.com"]["consentWording"] == "Send me the weekly email." and rows["a@example.com"]["consentConfirmedAt"]
    assert rows["b@example.com"]["status"] == "pending" and rows["b@example.com"]["consentConfirmedAt"] == ""
    assert rows["a@example.com"]["consentFormId"] == "newsletter" and rows["a@example.com"]["consentPageUrl"].startswith("https://")
    text = json.dumps(result)
    assert "198.51.100" not in text and "203.0.113" not in text and "ua/1" not in text

    monkeypatch.setattr(panel, "EXPORT_PAGE", 1)
    first = rig.call("panel_export", ADMIN)
    second = rig.call("panel_export", ADMIN, cursor=first["cursor"])
    assert len(first["rows"]) == len(second["rows"]) == 1 and first["rows"] != second["rows"]


def test_erase_by_address_removes_the_subscriber_and_validates_the_address(rig: Rig) -> None:
    hid = subscribe(rig, lists=("weekly",))
    other = subscribe(rig, OTHER, lists=("weekly",))
    assert rig.call("panel_erase", ADMIN, email="not an address")["error"] == "bad_request"
    assert rig.call("panel_erase", ADMIN)["error"] == "bad_request"
    assert rig.call("panel_erase", ADMIN, email=READER.upper())["ok"]  # addresses are normalised
    assert rig.harness.store.get_profile(hid) is None and rig.harness.store.get_profile(other) is not None
    assert rig.call("panel_erase", ADMIN, email=READER) == {"ok": True, "removed": 2}  # idempotent: the key rows are deleted again


def test_resume_turns_sending_back_on(rig: Rig) -> None:
    rig.harness.service.dispatch(sns(alarm("papyrus-newsletter-example-bounce-rate")))
    assert overview(rig)["paused"]["paused"] is True
    assert rig.call("panel_resume", ADMIN) == {"ok": True, "paused": False}
    assert rig.harness.ses.sending == [False, True]
    assert overview(rig)["paused"]["paused"] is False


# -- delivery history --------------------------------------------------------------------------------------------------


def test_deliveries_mask_addresses_for_editors_and_show_them_to_admins(rig: Rig) -> None:
    issue_id = scheduled_issue(rig, members=3)
    rig.fire(issue_id)
    rig.drain()
    gone = addresses.hid(rig.harness.keys.hash, "reader0@example.com")
    rig.harness.store.client.delete_item(TableName="newsletter", Key={"pk": {"S": f"SUB#{gone}"}, "sk": {"S": "PROFILE"}})
    editor = rig.call("panel_deliveries", EDITOR, issueId=issue_id)
    admin = rig.call("panel_deliveries", ADMIN, issueId=issue_id)
    assert editor["ok"] and len(editor["deliveries"]) == 3
    editor_text = json.dumps(editor)
    assert "reader1@example.com" not in editor_text and "r***@example.com" in editor_text and "(erased)" in editor_text
    assert {row["address"] for row in admin["deliveries"]} == {"reader1@example.com", "reader2@example.com", "(erased)"}
    assert {row["status"] for row in admin["deliveries"]} == {"sent"} and all(row["at"] for row in admin["deliveries"])
    assert mask("reader1@example.com") == "r***@example.com"


def test_deliveries_page_and_refuse_unknown_issues_and_foreign_cursors(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    issue_id = scheduled_issue(rig, members=3)
    rig.fire(issue_id)
    rig.drain()
    monkeypatch.setattr(panel, "DELIVERY_PAGE", 2)
    first = rig.call("panel_deliveries", ADMIN, issueId=issue_id)
    second = rig.call("panel_deliveries", ADMIN, issueId=issue_id, cursor=first["cursor"])
    assert len(first["deliveries"]) == 2 and len(second["deliveries"]) == 1 and "cursor" not in second
    foreign = panel.encode_cursor({"pk": {"S": "SUB#abc"}, "sk": {"S": "PROFILE"}})
    assert len(rig.call("panel_deliveries", ADMIN, issueId=issue_id, cursor=foreign)["deliveries"]) == 2
    for bad in ("missing", "bad id!", 5, None):
        assert rig.call("panel_deliveries", ADMIN, issueId=bad)["error"] == "not_found"
