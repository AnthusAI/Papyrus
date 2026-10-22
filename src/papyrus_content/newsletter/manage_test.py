"""Preferences, unsubscribe, erasure, suppression from SES events, alarms and pause."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from papyrus_content.newsletter import links, records, tokens
from papyrus_content.newsletter.events import alarm_names
from papyrus_content.newsletter.newsletter_test import ORIGIN, OTHER, READER, Harness, aws, running_harness  # noqa: F401
from papyrus_content.newsletter.pause import is_paused
from papyrus_content.newsletter.suppression import is_suppressed

ISSUE = "issue0001"


def manage_token(aws: Harness, email: str = READER) -> str:
    return links.make_manage_token(aws.hid(email), aws.keys)


def subscribed(aws: Harness, email: str = READER, lists: Any = ("weekly", "alerts-a")) -> str:
    aws.now += 4000
    aws.subscribe(email, lists=lists)
    aws.confirm()
    return manage_token(aws, email)


def call(aws: Harness, action: str, **fields: Any) -> dict[str, Any]:
    return aws.service.dispatch({"action": action, **fields})


def add_ledger(aws: Harness, hid: str, issue: str = ISSUE, status: str = "sent") -> None:
    ser = {"pk": {"S": f"ISSUE#{issue}"}, "sk": {"S": f"SEND#{hid}"}, "status": {"S": status}, "gsiHid": {"S": hid}}
    aws.store.client.put_item(TableName="newsletter", Item=ser)
    aws.store.client.put_item(
        TableName="newsletter",
        Item={"pk": {"S": f"ISSUE#{issue}"}, "sk": {"S": "META"}, "counts": {"M": {"sent": {"N": "1"}}}},
    )


def ledger_status(aws: Harness, hid: str, issue: str = ISSUE) -> str | None:
    item = aws.store.client.get_item(TableName="newsletter", Key={"pk": {"S": f"ISSUE#{issue}"}, "sk": {"S": f"SEND#{hid}"}}).get("Item")
    return item["status"]["S"] if item else None


def counts(aws: Harness, issue: str = ISSUE) -> dict[str, int]:
    item = aws.store.client.get_item(TableName="newsletter", Key={"pk": {"S": f"ISSUE#{issue}"}, "sk": {"S": "META"}})["Item"]
    return {name: int(value["N"]) for name, value in item["counts"]["M"].items()}


def ses_event(kind: str, hid: str, *, issue: str = ISSUE, list_id: str = "weekly", site: str = "example", **extra: Any) -> dict[str, Any]:
    tags: dict[str, list[str]] = {"site": [site]}
    if hid:
        tags["sub"] = [hid]
    if issue:
        tags["issue"] = [issue]
    if list_id:
        tags["list"] = [list_id]
    return {"eventType": kind, "mail": {"messageId": "msg-1", "tags": tags}, **extra}


def sns(message: dict[str, Any]) -> dict[str, Any]:
    return {"Records": [{"EventSource": "aws:sns", "Sns": {"Message": json.dumps(message)}}]}


def event_rows(aws: Harness) -> list[dict[str, Any]]:
    return [item for item in aws.items() if item["pk"]["S"] == "EVENTS"]


# -- links -------------------------------------------------------------------------------------------------------------


def test_manage_links(aws: Harness) -> None:
    hid = aws.hid()
    urls = links.manage_urls(hid, keys=aws.keys, site_origin=ORIGIN + "/")
    assert set(urls) == {"manage_url", "unsubscribe_url"}
    manage = urlparse(urls["manage_url"])
    assert f"{manage.scheme}://{manage.netloc}{manage.path}" == f"{ORIGIN}/api/newsletter/preferences"
    token = parse_qs(manage.query)["t"][0]
    assert tokens.verify(aws.keys.token, token, "manage", aws.now).hid == hid
    assert urls["unsubscribe_url"] == f"{ORIGIN}/api/newsletter/unsubscribe?t={token}"
    per_list = links.manage_urls(hid, "alerts-a", keys=aws.keys, site_origin=ORIGIN)
    assert per_list["unsubscribe_url"].endswith(f"?t={token}&l=alerts-a")
    assert links.make_manage_token(hid, aws.keys) == token


def test_the_environment_supplies_keys_and_origin(aws: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    from papyrus_content.newsletter import keys as keys_module

    monkeypatch.setitem(keys_module._cache, "/p/key", aws.keys)
    monkeypatch.setenv("KEY_PARAMETER", "/p/key")
    monkeypatch.setenv("SITE_ORIGIN", ORIGIN)
    assert links.manage_urls(aws.hid())["manage_url"].startswith(f"{ORIGIN}/api/newsletter/preferences?t=v1.")


# -- preferences -------------------------------------------------------------------------------------------------------


def test_preferences_state_masks_the_address_and_flags_lists(aws: Harness) -> None:
    token = subscribed(aws, lists=["weekly"])
    state = call(aws, "preferences_state", token=token)
    assert state["statusCode"] == 200
    body = state["body"]
    assert body["email"] == "r***@example.com" and READER not in json.dumps(body)
    assert [(entry["id"], entry["subscribed"]) for entry in body["lists"]] == [("weekly", True), ("alerts-a", False), ("alerts-b", False)]


def test_preferences_refuse_bad_tokens_and_erased_subscribers(aws: Harness) -> None:
    token = subscribed(aws)
    assert call(aws, "preferences_state", token="nope")["body"] == {"status": "invalid"}
    confirm = tokens.issue(aws.keys.token, tokens.Claims(hid=aws.hid(), purpose="confirm", nonce="n", expires_at=int(aws.now) + 99))
    assert call(aws, "preferences_state", token=confirm)["statusCode"] == 400
    call(aws, "delete_subscriber", token=token)
    assert call(aws, "preferences_state", token=token)["body"] == {"status": "invalid"}
    assert call(aws, "update_preferences", token=token, lists=["weekly"])["body"] == {"status": "invalid"}


def test_update_preferences_sets_exactly_the_chosen_lists(aws: Harness) -> None:
    token = subscribed(aws)
    result = call(aws, "update_preferences", token=token, lists=["alerts-a", "alerts-b"])
    assert result["body"] == {"status": "saved", "lists": ["alerts-a", "alerts-b"]}
    rows = aws.store.memberships(aws.hid())
    assert {i: (r["status"], r.get("gsiList")) for i, r in rows.items()} == {
        "weekly": ("unsubscribed", None), "alerts-a": ("subscribed", "alerts-a"), "alerts-b": ("subscribed", "alerts-b"),
    }
    assert aws.profile()["status"] == "confirmed"
    sent = len(aws.ses.sent)
    call(aws, "update_preferences", token=token, lists=["alerts-a", "alerts-b"])
    assert len(aws.ses.sent) == sent, "re-subscribing needs no new opt-in email"


def test_choosing_no_lists_is_unsubscribing_from_everything(aws: Harness) -> None:
    token = subscribed(aws)
    call(aws, "update_preferences", token=token, lists=[])
    assert aws.profile()["status"] == "unsubscribed"
    assert all(row["status"] == "unsubscribed" and "gsiList" not in row for row in aws.store.memberships(aws.hid()).values())


def test_ticking_a_list_again_resubscribes_without_a_new_opt_in(aws: Harness) -> None:
    token = subscribed(aws)
    call(aws, "unsubscribe", token=token)
    assert aws.profile()["status"] == "unsubscribed"
    sent = len(aws.ses.sent)
    assert call(aws, "update_preferences", token=token, lists=["weekly"])["body"]["lists"] == ["weekly"]
    assert aws.profile()["status"] == "confirmed" and len(aws.ses.sent) == sent
    assert aws.store.memberships(aws.hid())["weekly"]["gsiList"] == "weekly"
    assert "resubscribed:weekly" in [entry["event"] for entry in aws.profile()["history"]]


@pytest.mark.parametrize("reason", ["bounce", "complaint"])
def test_a_deliberate_resubscribe_clears_our_suppression_and_ses(aws: Harness, reason: str) -> None:
    token = subscribed(aws)
    call(aws, "unsubscribe", token=token)
    records.put_suppression(aws.store, aws.hid(), reason, aws.now)
    aws.ses.on_suppression_list.add(READER)
    assert is_suppressed(aws.hid(), aws.store)
    call(aws, "update_preferences", token=token, lists=["weekly"])
    assert not is_suppressed(aws.hid(), aws.store)
    assert aws.ses.unsuppressed == [READER]


def test_saving_without_a_new_subscription_keeps_the_suppression(aws: Harness) -> None:
    token = subscribed(aws)
    records.put_suppression(aws.store, aws.hid(), "bounce", aws.now)
    call(aws, "unsubscribe", token=token)
    call(aws, "update_preferences", token=token, lists=[])
    assert is_suppressed(aws.hid(), aws.store) and aws.ses.unsuppressed == []


def test_a_manual_suppression_is_not_cleared_by_the_subscriber(aws: Harness) -> None:
    token = subscribed(aws)
    call(aws, "unsubscribe", token=token)
    records.put_suppression(aws.store, aws.hid(), "manual", aws.now)
    result = call(aws, "update_preferences", token=token, lists=["weekly"])
    assert result["body"] == {"status": "saved", "lists": []}
    assert is_suppressed(aws.hid(), aws.store) and aws.profile()["status"] == "unsubscribed"


def test_a_failing_ses_unsuppress_does_not_block_the_subscription(aws: Harness, capsys: pytest.CaptureFixture[str]) -> None:
    token = subscribed(aws)
    call(aws, "unsubscribe", token=token)
    records.put_suppression(aws.store, aws.hid(), "complaint", aws.now)

    def boom(address: str) -> bool:
        raise RuntimeError("denied")

    aws.service.mailer.delete_suppressed_destination = boom  # type: ignore[method-assign]
    assert call(aws, "update_preferences", token=token, lists=["weekly"])["body"]["status"] == "saved"
    printed = capsys.readouterr().out
    assert "ses_unsuppress_failed" in printed and READER not in printed


# -- unsubscribe -------------------------------------------------------------------------------------------------------


def test_unsubscribe_from_one_list_leaves_the_others(aws: Harness) -> None:
    token = subscribed(aws)
    result = call(aws, "unsubscribe", token=token, list="alerts-a")
    assert result["body"] == {"status": "unsubscribed", "scope": "list", "lists": [{"id": "alerts-a", "name": "Alerts *A*"}]}
    rows = aws.store.memberships(aws.hid())
    assert rows["alerts-a"]["status"] == "unsubscribed" and "gsiList" not in rows["alerts-a"]
    assert rows["weekly"]["status"] == "subscribed"
    assert aws.profile()["status"] == "confirmed"


def test_unsubscribe_from_the_last_list_unsubscribes_the_profile(aws: Harness) -> None:
    token = subscribed(aws, lists=["weekly"])
    call(aws, "unsubscribe", token=token, list="weekly")
    assert aws.profile()["status"] == "unsubscribed"


def test_unsubscribe_all_is_idempotent(aws: Harness) -> None:
    token = subscribed(aws)
    first = call(aws, "unsubscribe", token=token)
    assert first["body"]["scope"] == "all" and {entry["id"] for entry in first["body"]["lists"]} == {"weekly", "alerts-a"}
    snapshot = aws.profile()
    again = call(aws, "unsubscribe", token=token)
    assert again["statusCode"] == 200 and again["body"]["status"] == "unsubscribed"
    assert aws.profile() == snapshot, "the second call writes nothing"
    assert all(row["status"] == "unsubscribed" for row in aws.store.memberships(aws.hid()).values())
    members = aws.store.client.query(
        TableName="newsletter", IndexName="byList", KeyConditionExpression="gsiList = :l", ExpressionAttributeValues={":l": {"S": "weekly"}}
    )["Items"]
    assert members == []


def test_unsubscribe_edge_cases(aws: Harness) -> None:
    token = subscribed(aws)
    assert call(aws, "unsubscribe", token="junk") == {"statusCode": 400, "body": {"status": "invalid"}}
    assert call(aws, "unsubscribe", token=token, list="gone")["body"]["lists"] == []
    assert aws.profile()["status"] == "confirmed", "an unknown list changes nothing"
    call(aws, "delete_subscriber", token=token)
    assert call(aws, "unsubscribe", token=token)["statusCode"] == 200, "a one-click POST for an erased subscriber still succeeds"


# -- deletion ----------------------------------------------------------------------------------------------------------


def test_delete_removes_every_row_of_the_subscriber_and_only_theirs(aws: Harness) -> None:
    token = subscribed(aws)
    subscribed(aws, OTHER, lists=["weekly"])
    for issue in ("issue0001", "issue0002"):
        add_ledger(aws, aws.hid(), issue)
    add_ledger(aws, aws.hid(OTHER), "issue0001")
    records.put_suppression(aws.store, aws.hid(), "bounce", aws.now)
    assert call(aws, "delete_subscriber", token=token)["body"] == {"status": "deleted"}
    mine = [item for item in aws.items() if aws.hid() in json.dumps(item) and not item['pk']['S'].startswith('RATE#')]
    assert [item for item in mine if item["pk"]["S"] == "EVENTS"] == []
    assert mine == [], mine
    assert aws.store.get_profile(aws.hid(OTHER)) is not None
    assert ledger_status(aws, aws.hid(OTHER)) == "sent"
    assert call(aws, "delete_subscriber", token=token)["body"] == {"status": "deleted"}


def test_delete_handles_more_than_one_batch(aws: Harness) -> None:
    token = subscribed(aws)
    for number in range(60):
        add_ledger(aws, aws.hid(), f"issue{number:04d}")
    call(aws, "delete_subscriber", token=token)
    assert records.ledger_row_keys(aws.store, aws.hid()) == []
    assert [item for item in aws.items() if item["sk"]["S"].startswith("SEND#")] == []


def test_admin_erase_by_address(aws: Harness) -> None:
    subscribed(aws)
    add_ledger(aws, aws.hid())
    result = call(aws, "admin_erase", email="  " + READER.upper() + " ")
    assert result["statusCode"] == 200 and result["body"]["removed"] >= 5
    assert aws.store.get_profile(aws.hid()) is None and ledger_status(aws, aws.hid()) is None
    assert call(aws, "admin_erase", email="nope")["body"] == {"status": "invalid_email"}
    assert call(aws, "admin_erase")["statusCode"] == 400


# -- SES events --------------------------------------------------------------------------------------------------------


def test_a_permanent_bounce_suppresses_and_unsubscribes(aws: Harness) -> None:
    subscribed(aws)
    hid = aws.hid()
    add_ledger(aws, hid)
    result = aws.service.dispatch(sns(ses_event("Bounce", hid, bounce={"bounceType": "Permanent", "bounceSubType": "General"})))
    assert result["body"]["results"] == ["bounce"]
    suppression = records.get_suppression(aws.store, hid)
    assert suppression["reason"] == "bounce" and suppression["issue"] == ISSUE
    assert aws.profile()["status"] == "unsubscribed"
    assert all(row["status"] == "unsubscribed" for row in aws.store.memberships(hid).values())
    assert "suppressed:bounce" in [entry["event"] for entry in aws.profile()["history"]]
    assert ledger_status(aws, hid) == "bounced" and counts(aws)["bounced"] == 1
    aws.service.dispatch(sns(ses_event("Bounce", hid, bounce={"bounceType": "Permanent"})))
    assert counts(aws)["bounced"] == 1, "a duplicate notification counts once"


def test_a_transient_bounce_is_only_counted(aws: Harness) -> None:
    subscribed(aws)
    hid = aws.hid()
    add_ledger(aws, hid)
    aws.service.dispatch(sns(ses_event("Bounce", hid, bounce={"bounceType": "Transient"})))
    assert not is_suppressed(hid, aws.store) and aws.profile()["status"] == "confirmed"
    assert ledger_status(aws, hid) == "sent" and counts(aws)["softBounced"] == 1


def test_a_complaint_suppresses_and_counts(aws: Harness) -> None:
    subscribed(aws)
    hid = aws.hid()
    add_ledger(aws, hid)
    aws.service.dispatch(sns(ses_event("Complaint", hid, complaint={})))
    assert records.get_suppression(aws.store, hid)["reason"] == "complaint"
    assert aws.profile()["status"] == "unsubscribed"
    assert ledger_status(aws, hid) == "complained" and counts(aws)["complained"] == 1


def test_a_delivery_updates_the_ledger_and_counter_once(aws: Harness) -> None:
    subscribed(aws)
    hid = aws.hid()
    add_ledger(aws, hid)
    for _ in range(2):
        aws.service.dispatch(sns(ses_event("Delivery", hid)))
    assert ledger_status(aws, hid) == "delivered" and counts(aws)["delivered"] == 1
    assert aws.profile()["status"] == "confirmed"
    aws.service.dispatch(sns(ses_event("Complaint", hid)))
    aws.service.dispatch(sns(ses_event("Delivery", hid)))
    assert ledger_status(aws, hid) == "complained", "a late delivery never overwrites a complaint"
    assert counts(aws)["delivered"] == 1


def test_events_for_a_missing_ledger_row_or_issue_are_no_ops(aws: Harness) -> None:
    subscribed(aws)
    hid = aws.hid()
    aws.service.dispatch(sns(ses_event("Delivery", hid)))
    aws.service.dispatch(sns(ses_event("Delivery", hid, issue="")))
    assert ledger_status(aws, hid) is None
    assert [item for item in aws.items() if item["pk"]["S"].startswith("ISSUE#")] == []


def test_reject_and_rendering_failure_mark_the_ledger_failed(aws: Harness) -> None:
    subscribed(aws)
    hid = aws.hid()
    add_ledger(aws, hid)
    aws.service.dispatch(sns(ses_event("Reject", hid)))
    assert ledger_status(aws, hid) == "failed" and counts(aws)["failed"] == 1
    aws.service.dispatch(sns(ses_event("Rendering Failure", hid)))
    assert counts(aws)["failed"] == 1


def test_untagged_foreign_and_unknown_events_are_ignored(aws: Harness) -> None:
    subscribed(aws)
    hid = aws.hid()
    before = aws.items()
    for event in [
        ses_event("Bounce", "", bounce={"bounceType": "Permanent"}),
        ses_event("Bounce", "not-a-hid", bounce={"bounceType": "Permanent"}),
        ses_event("Bounce", hid, site="other", bounce={"bounceType": "Permanent"}),
        ses_event("Send", hid),
        ses_event("Open", hid),
        {"mail": {}},
        {"eventType": "Bounce"},
    ]:
        assert aws.service.dispatch(sns(event))["body"]["results"] == ["ignored"]
    assert not is_suppressed(hid, aws.store)
    assert [item for item in aws.items() if item["pk"]["S"] != "EVENTS"] == [item for item in before if item["pk"]["S"] != "EVENTS"]
    bad = {"Records": [{"EventSource": "aws:sns", "Sns": {"Message": "not json"}}, {"EventSource": "aws:sns"}, "x"]}
    assert aws.service.dispatch(bad)["body"]["results"] == ["unparseable"]


def test_a_bounce_of_a_confirmation_mail_suppresses_a_pending_address(aws: Harness) -> None:
    aws.subscribe()
    hid = aws.hid()
    aws.service.dispatch(sns(ses_event("Bounce", hid, issue="", list_id="", bounce={"bounceType": "Permanent"})))
    assert is_suppressed(hid, aws.store) and aws.profile()["status"] == "unsubscribed"
    aws.now += 4000
    sent = len(aws.ses.sent)
    aws.subscribe()
    assert len(aws.ses.sent) == sent, "a suppressed address gets no more confirmation mail"


def test_a_bounce_for_an_erased_subscriber_still_suppresses_the_id(aws: Harness) -> None:
    hid = aws.hid()
    aws.service.dispatch(sns(ses_event("Complaint", hid)))
    assert is_suppressed(hid, aws.store)


def test_the_event_log_has_no_address_and_expires(aws: Harness) -> None:
    subscribed(aws)
    hid = aws.hid()
    aws.service.dispatch(sns(ses_event("Delivery", hid)))
    aws.service.dispatch(sns(ses_event("DeliveryDelay", hid)))
    aws.service.dispatch(sns(ses_event("Bounce", hid, bounce={"bounceType": "Transient"})))
    rows = event_rows(aws)
    assert sorted(row["type"]["S"] for row in rows) == ["Bounce", "Delivery", "DeliveryDelay"]
    for row in rows:
        assert READER not in json.dumps(row) and int(row["expiresAt"]["N"]) == int(aws.now) + 90 * 86400
        assert set(row) <= {"pk", "sk", "type", "hid", "issue", "list", "detail", "expiresAt"}
        assert row["sk"]["S"].startswith("20")


# -- alarms and pause --------------------------------------------------------------------------------------------------


def alarm(name: str, state: str = "ALARM") -> dict[str, Any]:
    return {"AlarmName": name, "NewStateValue": state, "NewStateReason": "Threshold crossed"}


def test_an_alarm_pauses_sending_and_resume_restores_it(aws: Harness) -> None:
    bounce_alarm, _complaint = alarm_names("example")
    assert not is_paused(aws.store)
    result = aws.service.dispatch(sns(alarm(bounce_alarm)))
    assert result["body"]["results"] == ["paused"]
    assert aws.ses.sending == [False] and is_paused(aws.store)
    state = records.get_state(aws.store)
    assert state["paused"] is True and bounce_alarm in state["reason"] and state["pausedAt"]
    assert aws.service.dispatch(sns(alarm(bounce_alarm)))["body"]["results"] == ["already_paused"]
    assert aws.ses.sending == [False]
    assert call(aws, "resume_sending")["body"] == {"status": "resumed"}
    assert aws.ses.sending == [False, True] and not is_paused(aws.store)
    assert records.get_state(aws.store)["resumedAt"]


def test_only_our_alarms_in_the_alarm_state_pause(aws: Harness) -> None:
    bounce_alarm, complaint_alarm = alarm_names("example")
    for message in [alarm(bounce_alarm, "OK"), alarm(complaint_alarm, "INSUFFICIENT_DATA"), alarm("someone-elses-alarm")]:
        assert aws.service.dispatch(sns(message))["body"]["results"] == ["ignored"]
    assert aws.ses.sending == [] and not is_paused(aws.store)
    assert aws.service.dispatch(sns(alarm(complaint_alarm)))["body"]["results"] == ["paused"]


def test_the_alarm_names_are_the_ones_the_stack_creates() -> None:
    assert alarm_names("example") == ("papyrus-newsletter-example-bounce-rate", "papyrus-newsletter-example-complaint-rate")


# -- the operator script -----------------------------------------------------------------------------------------------


def test_simulate_builds_a_tagged_request_without_sending(capsys: pytest.CaptureFixture[str]) -> None:
    from papyrus_content.newsletter.__main__ import main, simulator_address

    class Client:
        sent: list[dict[str, Any]] = []

        def send_email(self, **kwargs: Any) -> dict[str, str]:
            self.sent.append(kwargs)
            return {"MessageId": "abc"}

    hid = "a" * 32
    base = ["simulate", "--site-id", "example", "--from-address", "newsletter@example.com", "--from-name", "Example", "--hid", hid]
    assert main([*base, "--outcome", "bounce", "--issue", "i1", "--list", "weekly"], Client()) == 0
    request = Client.sent[0]
    assert request["Destination"]["ToAddresses"] == [simulator_address("bounce")]
    assert request["ConfigurationSetName"] == "papyrus-example"
    assert request["EmailTags"] == [
        {"Name": "site", "Value": "example"}, {"Name": "sub", "Value": hid}, {"Name": "kind", "Value": "test"},
        {"Name": "issue", "Value": "i1"}, {"Name": "list", "Value": "weekly"},
    ]
    assert json.loads(capsys.readouterr().out)["messageId"] == "abc"
    assert main([*base, "--to", "reader@example.com", "--dry-run"], None) == 0
    assert json.loads(capsys.readouterr().out)["Destination"] == {"ToAddresses": ["reader@example.com"]}
    assert len(Client.sent) == 1
    assert main([*base[:-1], "short"], None) == 2
    assert "hid" in capsys.readouterr().err
    with pytest.raises(ValueError):
        simulator_address("nope")
