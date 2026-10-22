"""Tokens, addresses, keys and the double opt-in state machine, against moto's DynamoDB and a fake SES client."""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from typing import Any, Iterator

import boto3
import pytest
from moto import mock_aws

from papyrus_content.newsletter import addresses, rate, tokens
from papyrus_content.newsletter.handler import DEFAULT_WORDING, Newsletter, Settings
from papyrus_content.newsletter.keys import derive_keys, hkdf_sha256, load_keys
from papyrus_content.newsletter.mailer import Mailer, format_sender
from papyrus_content.newsletter.store import Store, iso

READER = "reader@example.com"
OTHER = "other@example.com"
START = 1_800_000_000.0
ORIGIN = "https://news.example.com"
LISTS = (
    {"id": "weekly", "name": "Weekly roundup", "description": "The week in review.", "kind": "roundup"},
    {"id": "alerts-a", "name": "Alerts *A*", "description": "", "kind": "alert"},
    {"id": "alerts-b", "name": "Alerts B", "description": "Breaking items.", "kind": "alert"},
)
THEME = {"accent": "#aa3300", "text": "#111111", "background": "#ffffff"}
SECRET = "x" * 40
AT = "@"


class FakeSes:
    class exceptions:  # noqa: N801 - mirrors boto3's client.exceptions
        class NotFoundException(Exception):
            pass

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail = False
        self.sending: list[bool] = []
        self.unsuppressed: list[str] = []
        self.on_suppression_list: set[str] = set()

    def put_configuration_set_sending_options(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["ConfigurationSetName"] == "papyrus-example"
        self.sending.append(kwargs["SendingEnabled"])
        return {}

    def delete_suppressed_destination(self, **kwargs: Any) -> dict[str, Any]:
        address = kwargs["EmailAddress"]
        if address not in self.on_suppression_list:
            raise self.exceptions.NotFoundException()
        self.on_suppression_list.discard(address)
        self.unsuppressed.append(address)
        return {}

    def send_email(self, **kwargs: Any) -> dict[str, str]:
        if self.fail:
            raise RuntimeError("ses down")
        self.sent.append(kwargs)
        return {"MessageId": f"m{len(self.sent)}"}


class Harness:
    def __init__(self, store: Store, ses: FakeSes) -> None:
        self.now = START
        self.store, self.ses = store, ses
        self.counter = 0
        settings = Settings(
            site_id="example",
            site_origin=ORIGIN,
            sending_domain="example.com",
            from_address="newsletter@example.com",
            from_name='Example "News"',
            configuration_set="papyrus-example",
            lists=LISTS,
            theme=THEME,
        )
        self.keys = derive_keys(SECRET)
        self.service = Newsletter(
            settings,
            store,
            self.keys,
            Mailer(
                from_name=settings.from_name,
                from_address=settings.from_address,
                configuration_set=settings.configuration_set,
                site_id="example",
                client=ses,
            ),
            clock=lambda: self.now,
            nonce=self._nonce,
        )

    def _nonce(self) -> str:
        self.counter += 1
        return f"nonce{self.counter}"

    def subscribe(self, email: str = READER, lists: Any = ("weekly",), **changes: Any) -> dict[str, Any]:
        event = {
            "action": "subscribe",
            "email": email,
            "lists": list(lists) if isinstance(lists, (list, tuple)) else lists,
            "page": "https://news.example.com/roundup/",
            "consent": "Send me the weekly email.",
            "formId": "newsletter",
            "honeypot": "",
            "renderedAt": int((self.now - 60) * 1000),
            "ip": "198.51.100.7",
            "userAgent": "test",
        }
        event.update(changes)
        return self.service.dispatch(event)

    def last_token(self) -> str:
        text = self.ses.sent[-1]["Content"]["Simple"]["Body"]["Text"]["Data"]
        return re.search(r"/api/newsletter/confirm\?t=([A-Za-z0-9_.-]+)", text).group(1)  # type: ignore[union-attr]

    def confirm(self, token: str | None = None) -> dict[str, Any]:
        return self.service.dispatch(
            {"action": "confirm", "token": self.last_token() if token is None else token, "ip": "203.0.113.9", "userAgent": "ua/1" + "x" * 400}
        )

    def hid(self, email: str = READER) -> str:
        return addresses.hid(self.keys.hash, email)

    def profile(self, email: str = READER) -> dict[str, Any]:
        profile = self.store.get_profile(self.hid(email))
        assert profile is not None
        return profile

    def items(self) -> list[dict[str, Any]]:
        return self.store.client.scan(TableName=self.store.table_name)["Items"]


@contextmanager
def running_harness() -> Iterator[Harness]:
    """A Harness over moto's DynamoDB with the plugin's table layout. Also used by features_backend/newsletter-double-opt-in.feature."""
    saved = {name: os.environ.get(name) for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION")}
    os.environ.update(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x", AWS_DEFAULT_REGION="us-east-1")
    try:
        with mock_aws():
            client = boto3.client("dynamodb")
            client.create_table(
                TableName="newsletter",
                BillingMode="PAY_PER_REQUEST",
                AttributeDefinitions=[
                    {"AttributeName": "pk", "AttributeType": "S"},
                    {"AttributeName": "sk", "AttributeType": "S"},
                    {"AttributeName": "gsiList", "AttributeType": "S"},
                    {"AttributeName": "gsiHid", "AttributeType": "S"},
                ],
                KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
                GlobalSecondaryIndexes=[
                    {
                        "IndexName": "byHid",
                        "KeySchema": [{"AttributeName": "gsiHid", "KeyType": "HASH"}],
                        "Projection": {"ProjectionType": "KEYS_ONLY"},
                    },
                    {
                        "IndexName": "byList",
                        "KeySchema": [{"AttributeName": "gsiList", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
                        "Projection": {"ProjectionType": "KEYS_ONLY"},
                    }
                ],
            )
            yield Harness(Store("newsletter", client), FakeSes())
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@pytest.fixture
def aws() -> Iterator[Harness]:
    with running_harness() as harness:
        yield harness


# -- addresses ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("address", ["reader@example.com", "a.b+tag@example.net", "o'brien@example.org", "x@a-b.example"])
def test_valid_addresses(address: str) -> None:
    assert addresses.is_valid(address)


@pytest.mark.parametrize(
    "address",
    ["", "reader", "reader@", "@example.com", "reader@example", "a b@example.com", "a..b@example.com", ".a@example.com",
     "a" + AT + "-example.com", "a" + AT + "example..com", "a" + AT + "example.com\n", "a" * 65 + AT + "example.com", "a@" + "b" * 250 + ".com",
     "READER@example.com", " reader@example.com", "a@@example.com", "a@exa_mple.com", None, 5],
)
def test_invalid_addresses(address: Any) -> None:
    assert not addresses.is_valid(address)


def test_normalize_trims_and_lowercases_the_whole_address() -> None:
    assert addresses.normalize("  " + READER.upper() + " \n") == "reader@example.com"


def test_hid_is_keyed_stable_and_case_blind() -> None:
    first, second = derive_keys(SECRET), derive_keys("y" * 40)
    assert addresses.hid(first.hash, READER.upper()) == addresses.hid(first.hash, READER)
    assert addresses.hid(first.hash, READER) != addresses.hid(second.hash, READER)
    assert addresses.hid(first.hash, READER) != addresses.hid(first.hash, OTHER)
    assert re.fullmatch(r"[0-9a-f]{32}", addresses.hid(first.hash, READER))
    assert addresses.ip_hash(first.hash, "198.51.100.7") != addresses.hid(first.hash, "198.51.100.7")


# -- keys --------------------------------------------------------------------------------------------------------------


def test_hkdf_matches_rfc_5869_case_one() -> None:
    okm = hkdf_sha256(bytes.fromhex("0b" * 22), bytes.fromhex("f0f1f2f3f4f5f6f7f8f9"), 42, salt=bytes.fromhex("000102030405060708090a0b0c"))
    assert okm.hex() == "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865"


def test_derived_keys_are_distinct_and_deterministic() -> None:
    keys = derive_keys(SECRET)
    assert keys.hash != keys.token and len(keys.hash) == len(keys.token) == 32
    assert derive_keys(SECRET) == keys
    with pytest.raises(ValueError):
        derive_keys("short")


def test_the_key_is_read_from_ssm_once_per_container() -> None:
    class Ssm:
        calls = 0

        def get_parameter(self, **kwargs: Any) -> dict[str, Any]:
            Ssm.calls += 1
            assert kwargs == {"Name": "/papyrus/cache-test/newsletter-key", "WithDecryption": True}
            return {"Parameter": {"Value": SECRET}}

    ssm = Ssm()
    assert load_keys("/papyrus/cache-test/newsletter-key", ssm) == load_keys("/papyrus/cache-test/newsletter-key", ssm)
    assert Ssm.calls == 1


# -- tokens ------------------------------------------------------------------------------------------------------------


def claims(**changes: Any) -> tokens.Claims:
    base = dict(hid="a" * 32, purpose="confirm", lists=("weekly",), nonce="n1", expires_at=int(START) + 100)
    base.update(changes)
    return tokens.Claims(**base)  # type: ignore[arg-type]


def test_token_round_trip_and_format() -> None:
    key = derive_keys(SECRET).token
    token = tokens.issue(key, claims())
    assert re.fullmatch(r"v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token)
    assert tokens.verify(key, token, "confirm", START) == claims()


def test_manage_token_has_no_expiry() -> None:
    key = derive_keys(SECRET).token
    token = tokens.issue(key, tokens.Claims(hid="b" * 32, purpose="manage"))
    assert tokens.verify(key, token, "manage", START + 10**9).hid == "b" * 32


def test_tampering_wrong_key_and_wrong_purpose_are_refused() -> None:
    key = derive_keys(SECRET).token
    token = tokens.issue(key, claims())
    version, payload, signature = token.split(".")
    forged = tokens.issue(derive_keys("z" * 40).token, claims())
    other_payload = tokens.issue(key, claims(hid="c" * 32)).split(".")[1]
    for bad in [f"{version}.{other_payload}.{signature}", f"{version}.{payload}.{signature[:-2]}AA", forged,
                f"v2.{payload}.{signature}", f"{version}.{payload}", f"{token}.extra", "", "v1..", "not a token", token + "é"]:
        with pytest.raises(tokens.InvalidToken):
            tokens.verify(key, bad, "confirm", START)
    with pytest.raises(tokens.InvalidToken):
        tokens.verify(key, token, "manage", START)
    with pytest.raises(tokens.InvalidToken):
        tokens.verify(key, None, "confirm", START)
    with pytest.raises(tokens.InvalidToken):
        tokens.verify(key, "v1." + "a" * 3000, "confirm", START)


def test_token_expiry_is_exclusive_of_the_deadline() -> None:
    key = derive_keys(SECRET).token
    token = tokens.issue(key, claims(expires_at=int(START)))
    assert tokens.verify(key, token, "confirm", START).expires_at == int(START)
    with pytest.raises(tokens.ExpiredToken):
        tokens.verify(key, token, "confirm", START + 1)


def test_unknown_purpose_cannot_be_issued() -> None:
    with pytest.raises(ValueError):
        tokens.issue(b"k" * 32, claims(purpose="unsubscribe"))


# -- mailer ------------------------------------------------------------------------------------------------------------


def test_sender_formatting() -> None:
    assert format_sender("Shipped", "n@x.example") == '"Shipped" <n@x.example>'
    assert format_sender('Say "hi"\r\nBcc: a@b.c', "n@x.example") == '"Say \\"hi\\" Bcc: a@b.c" <n@x.example>'
    assert format_sender("Café", "n@x.example").startswith("=?utf-8?")
    assert format_sender("  ", "n@x.example") == "n@x.example"


# -- subscribe and confirm ---------------------------------------------------------------------------------------------


def test_a_new_address_gets_one_confirmation_and_a_pending_record(aws: Harness) -> None:
    assert aws.subscribe(siteSubject="ss1_" + "A" * 43) == {"statusCode": 202, "body": {"status": "check_email"}}
    assert len(aws.ses.sent) == 1
    sent = aws.ses.sent[0]
    assert sent["FromEmailAddress"] == '"Example \\"News\\"" <newsletter@example.com>'
    assert sent["Destination"] == {"ToAddresses": [READER]}
    assert sent["ConfigurationSetName"] == "papyrus-example"
    assert sent["EmailTags"] == [
        {"Name": "site", "Value": "example"},
        {"Name": "kind", "Value": "confirm"},
        {"Name": "sub", "Value": aws.hid()},
    ]
    body = sent["Content"]["Simple"]["Body"]
    assert "Confirm subscription" in body["Html"]["Data"] and "Confirm subscription" in body["Text"]["Data"]
    assert "Weekly roundup" in body["Text"]["Data"] and "72 hours" in body["Text"]["Data"]
    assert f"{ORIGIN}/api/newsletter/confirm?t=v1." in body["Text"]["Data"]
    assert "Alerts" not in body["Text"]["Data"]

    profile = aws.profile()
    assert profile["status"] == "pending" and profile["email"] == READER and profile["confirmNonce"] == "nonce1"
    assert profile["siteSubject"] == "ss1_" + "A" * 43
    assert profile["consent"] == {
        "requestedAt": iso(START),
        "formId": "newsletter",
        "pageUrl": "https://news.example.com/roundup/",
        "wording": "Send me the weekly email.",
        "requestIpHash": addresses.ip_hash(aws.keys.hash, "198.51.100.7"),
    }
    assert profile["history"] == [{"at": iso(START), "event": "signup_requested"}]
    assert profile["expiresAt"] > START
    row = aws.store.memberships(aws.hid())["weekly"]
    assert row["status"] == "pending" and "gsiList" not in row


def test_wording_falls_back_to_the_server_default_and_is_capped(aws: Harness) -> None:
    aws.subscribe(consent="")
    assert aws.profile()["consent"]["wording"] == DEFAULT_WORDING.format(name='Example "News"')
    aws.now += 1000
    aws.subscribe(OTHER, consent="w" * 900, page="p" * 900)
    consent = aws.profile(OTHER)["consent"]
    assert len(consent["wording"]) == 500 and len(consent["pageUrl"]) == 500


def test_unknown_lists_are_dropped_and_a_comma_string_is_accepted(aws: Harness) -> None:
    aws.subscribe(lists="weekly, nope ,alerts-b,weekly")
    assert sorted(aws.store.memberships(aws.hid())) == ["alerts-b", "weekly"]
    assert aws.subscribe(OTHER, lists=["nope"]) == {"statusCode": 400, "body": {"status": "invalid_lists"}}
    assert aws.subscribe(OTHER, lists=[]) == {"statusCode": 400, "body": {"status": "invalid_lists"}}
    assert aws.subscribe(OTHER, lists=None) == {"statusCode": 400, "body": {"status": "invalid_lists"}}  # type: ignore[arg-type]
    assert len(aws.ses.sent) == 1


@pytest.mark.parametrize("email", ["not-an-address", "", "a@b", None, 7, "a b@example.com"])
def test_invalid_email_is_a_400_and_stores_nothing(aws: Harness, email: Any) -> None:
    assert aws.subscribe(email) == {"statusCode": 400, "body": {"status": "invalid_email"}}
    assert aws.ses.sent == [] and aws.items() == []


def test_the_address_is_normalized_so_case_does_not_make_a_second_subscriber(aws: Harness) -> None:
    aws.subscribe("  " + READER.upper() + " ")
    aws.now += 1000
    aws.subscribe(READER)
    assert aws.profile()["email"] == READER
    profiles = [item for item in aws.items() if item["sk"]["S"] == "PROFILE"]
    assert len(profiles) == 1


@pytest.mark.parametrize(
    "changes",
    [{"honeypot": "http://spam.example"}, {"renderedAt": None}, {"renderedAt": "soon"}, {"renderedAt_age": 1}, {"renderedAt_age": 25 * 3600}],
)
def test_bots_are_accepted_silently_and_nothing_happens(aws: Harness, changes: dict[str, Any]) -> None:
    changes = dict(changes)
    if "renderedAt_age" in changes:
        changes["renderedAt"] = int((aws.now - changes.pop("renderedAt_age")) * 1000)
    assert aws.subscribe(**changes) == {"statusCode": 202, "body": {"status": "check_email"}}
    assert aws.ses.sent == [] and aws.items() == []


def test_a_valid_looking_request_gets_the_same_answer_in_every_state(aws: Harness) -> None:
    answers = []
    answers.append(aws.subscribe())  # new
    answers.append(aws.subscribe(OTHER))
    aws.now += 4000  # past the per-address windows
    answers.append(aws.subscribe())  # pending: resend
    aws.confirm()
    aws.now += 4000
    answers.append(aws.subscribe())  # confirmed, nothing new
    answers.append(aws.subscribe(lists=["weekly", "alerts-a"]))  # confirmed, a new list
    # suppressed
    aws.store.client.put_item(
        TableName="newsletter",
        Item={"pk": {"S": f"SUPP#{aws.hid('gone@example.com')}"}, "sk": {"S": "SUPP"}, "reason": {"S": "bounce"}},
    )
    mails_before = len(aws.ses.sent)
    answers.append(aws.subscribe("gone@example.com"))
    assert len(aws.ses.sent) == mails_before
    # rate limited
    for _ in range(rate.IP_LIMIT):
        aws.subscribe("flood@example.com", ip="192.0.2.1")
    mails_before = len(aws.ses.sent)
    answers.append(aws.subscribe("flood@example.com", ip="192.0.2.1"))
    assert len(aws.ses.sent) == mails_before
    # mail cannot be sent
    aws.ses.fail = True
    answers.append(aws.subscribe("late@example.com"))
    assert all(answer == {"statusCode": 202, "body": {"status": "check_email"}} for answer in answers), answers


def test_a_suppressed_address_gets_no_mail_and_no_record(aws: Harness) -> None:
    aws.store.client.put_item(
        TableName="newsletter", Item={"pk": {"S": f"SUPP#{aws.hid()}"}, "sk": {"S": "SUPP"}, "reason": {"S": "complaint"}}
    )
    aws.subscribe()
    assert aws.ses.sent == [] and aws.store.get_profile(aws.hid()) is None


def test_confirming_subscribes_and_records_the_evidence(aws: Harness) -> None:
    aws.subscribe(lists=["weekly", "alerts-a"])
    result = aws.confirm()
    assert result["statusCode"] == 200 and result["body"]["status"] == "confirmed"
    assert result["body"]["lists"] == [{"id": "weekly", "name": "Weekly roundup"}, {"id": "alerts-a", "name": "Alerts *A*"}]
    manage = tokens.verify(aws.keys.token, result["body"]["manageToken"], "manage", aws.now)
    assert manage.hid == aws.hid()

    profile = aws.profile()
    assert profile["status"] == "confirmed" and "confirmNonce" not in profile and "expiresAt" not in profile
    assert profile["consent"]["confirmedAt"] == iso(START)
    assert profile["consent"]["confirmIp"] == "203.0.113.9"
    assert len(profile["consent"]["confirmUserAgent"]) == 300
    assert [entry["event"] for entry in profile["history"]] == ["signup_requested", "confirmed"]
    rows = aws.store.memberships(aws.hid())
    assert {list_id: (row["status"], row["gsiList"]) for list_id, row in rows.items()} == {
        "weekly": ("subscribed", "weekly"),
        "alerts-a": ("subscribed", "alerts-a"),
    }
    assert all("expiresAt" not in row for row in rows.values())
    members = aws.store.client.query(
        TableName="newsletter", IndexName="byList", KeyConditionExpression="gsiList = :l", ExpressionAttributeValues={":l": {"S": "weekly"}}
    )["Items"]
    assert [item["pk"]["S"] for item in members] == [f"SUB#{aws.hid()}"]


def test_a_confirmation_link_works_once(aws: Harness) -> None:
    aws.subscribe()
    token = aws.last_token()
    assert aws.confirm(token)["body"]["status"] == "confirmed"
    snapshot = aws.profile()
    assert aws.confirm(token) == {"statusCode": 410, "body": {"status": "expired"}}
    assert aws.profile() == snapshot


def test_a_resend_replaces_the_link_and_the_lists(aws: Harness) -> None:
    aws.subscribe(lists=["weekly", "alerts-a"])
    first = aws.last_token()
    aws.now += 4000
    aws.subscribe(lists=["alerts-b"])
    assert len(aws.ses.sent) == 2
    assert aws.confirm(first) == {"statusCode": 410, "body": {"status": "expired"}}
    assert sorted(aws.store.memberships(aws.hid())) == ["alerts-b"]
    result = aws.confirm()
    assert result["body"]["lists"] == [{"id": "alerts-b", "name": "Alerts B"}]
    assert [entry["event"] for entry in aws.profile()["history"]] == ["signup_requested", "confirmation_resent", "confirmed"]


def test_the_link_expires_after_72_hours(aws: Harness) -> None:
    aws.subscribe()
    token = aws.last_token()
    aws.now += tokens.CONFIRM_TOKEN_LIFETIME_SECONDS + 1
    assert aws.confirm(token) == {"statusCode": 410, "body": {"status": "expired"}}
    assert aws.profile()["status"] == "pending"


def test_a_tampered_or_foreign_link_is_invalid(aws: Harness) -> None:
    aws.subscribe()
    token = aws.last_token()
    assert aws.confirm(token[:-3] + "abc")["body"] == {"status": "invalid"}
    assert aws.confirm("garbage")["body"] == {"status": "invalid"}
    assert aws.confirm("")["body"] == {"status": "invalid"}
    manage = tokens.issue(aws.keys.token, tokens.Claims(hid=aws.hid(), purpose="manage"))
    assert aws.confirm(manage)["body"] == {"status": "invalid"}
    assert aws.profile()["status"] == "pending"


def test_a_link_for_a_list_the_site_no_longer_has_confirms_nothing(aws: Harness) -> None:
    aws.subscribe()
    token = tokens.issue(
        aws.keys.token,
        tokens.Claims(hid=aws.hid(), purpose="confirm", lists=("removed",), nonce="nonce1", expires_at=int(START) + 100),
    )
    assert aws.confirm(token)["body"] == {"status": "expired"}


def test_the_confirm_page_state_reads_without_changing_anything(aws: Harness) -> None:
    aws.subscribe(lists=["weekly"])
    before = aws.profile()
    token = aws.last_token()
    state = aws.service.dispatch({"action": "confirm_page_state", "token": token})
    assert state == {"statusCode": 200, "body": {"status": "ready", "lists": [{"id": "weekly", "name": "Weekly roundup"}]}}
    assert aws.service.dispatch({"action": "confirm_page_state", "token": token}) == state
    assert aws.profile() == before
    aws.confirm(token)
    assert aws.service.dispatch({"action": "confirm_page_state", "token": token})["body"] == {"status": "expired"}
    assert aws.service.dispatch({"action": "confirm_page_state", "token": "x"})["body"] == {"status": "invalid"}


def test_a_confirmed_subscriber_asking_for_a_new_list_confirms_only_that_list(aws: Harness) -> None:
    aws.subscribe(lists=["weekly"])
    aws.confirm()
    aws.now += 4000
    aws.subscribe(lists=["weekly", "alerts-b"])
    assert len(aws.ses.sent) == 2
    text = aws.ses.sent[-1]["Content"]["Simple"]["Body"]["Text"]["Data"]
    assert "Alerts B" in text and "Weekly roundup" not in text
    profile = aws.profile()
    assert profile["status"] == "confirmed" and profile["confirmNonce"]
    rows = aws.store.memberships(aws.hid())
    assert rows["weekly"]["status"] == "subscribed" and rows["alerts-b"]["status"] == "pending" and "gsiList" not in rows["alerts-b"]
    result = aws.confirm()
    assert result["body"]["lists"] == [{"id": "alerts-b", "name": "Alerts B"}]
    rows = aws.store.memberships(aws.hid())
    assert {row["status"] for row in rows.values()} == {"subscribed"} and rows["alerts-b"]["gsiList"] == "alerts-b"
    assert aws.profile()["consent"]["confirmedAt"] == iso(START + 4000 - 4000)  # the first consent evidence is kept


def test_a_confirmed_subscriber_asking_for_the_same_lists_gets_nothing(aws: Harness) -> None:
    aws.subscribe()
    aws.confirm()
    aws.now += 4000
    before = aws.profile()
    aws.subscribe()
    assert len(aws.ses.sent) == 1 and aws.profile() == before


def test_an_unsubscribed_address_starts_a_fresh_double_opt_in(aws: Harness) -> None:
    aws.subscribe()
    aws.confirm()
    profile = aws.profile()
    rev = profile["rev"]
    profile["status"] = "unsubscribed"
    aws.store.save(profile, rev)
    aws.now += 4000
    aws.subscribe(consent="Back again.")
    assert aws.profile()["status"] == "pending" and aws.profile()["consent"]["wording"] == "Back again."
    assert len(aws.ses.sent) == 2


def test_history_is_capped_at_fifty(aws: Harness) -> None:
    for step in range(60):
        aws.now += 4000
        aws.subscribe()
    history = aws.profile()["history"]
    assert len(history) == 50 and history[-1]["event"] == "confirmation_resent"


def test_pending_records_expire_and_confirmed_ones_do_not(aws: Harness) -> None:
    aws.subscribe()
    assert aws.profile()["expiresAt"] == int(START) + 30 * 24 * 3600
    assert aws.store.memberships(aws.hid())["weekly"]["expiresAt"] == int(START) + 30 * 24 * 3600
    aws.confirm()
    assert "expiresAt" not in aws.profile()


def test_limits_per_address_per_subscriber_and_per_site(aws: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    for number in range(rate.IP_LIMIT + 2):
        aws.subscribe(f"person{number}@example.com", ip="192.0.2.5")
    assert len(aws.ses.sent) == rate.IP_LIMIT
    aws.now += rate.IP_WINDOW_SECONDS
    aws.subscribe("person0@example.com", ip="192.0.2.5")
    assert len(aws.ses.sent) == rate.IP_LIMIT + 1

    sent = len(aws.ses.sent)
    for number in range(rate.SUBSCRIBER_LIMIT + 2):
        aws.now += rate.IP_WINDOW_SECONDS
        aws.subscribe("busy@example.com", ip=f"192.0.2.{20 + number}")
        if number >= rate.SUBSCRIBER_LIMIT:
            break
    assert len(aws.ses.sent) - sent <= rate.SUBSCRIBER_LIMIT

    monkeypatch.setattr(rate, "SITE_LIMIT", 2)
    aws.now += 2 * rate.SITE_WINDOW_SECONDS
    sent = len(aws.ses.sent)
    for number in range(5):
        aws.subscribe(f"site{number}@example.com", ip=f"198.18.0.{number}")
    assert len(aws.ses.sent) - sent == 2


def test_a_limited_request_logs_a_metric_line_without_personal_data(aws: Harness, capsys: pytest.CaptureFixture[str]) -> None:
    for number in range(rate.IP_LIMIT + 1):
        aws.subscribe(f"person{number}@example.com", ip="192.0.2.77")
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    metric = [line for line in lines if "SubscribeRateLimited" in line]
    assert metric and metric[0]["Scope"] == "ip" and metric[0]["Site"] == "example"


def test_no_address_or_visitor_ip_in_logs_counters_or_keys(aws: Harness, capsys: pytest.CaptureFixture[str]) -> None:
    aws.ses.fail = True
    aws.subscribe(ip="192.0.2.99")
    aws.ses.fail = False
    aws.now += 4000
    aws.subscribe(ip="192.0.2.99")
    aws.confirm()
    assert READER not in capsys.readouterr().out
    for item in aws.items():
        assert "192.0.2.99" not in json.dumps(item) and "reader" not in item["pk"]["S"]
    rates = [item for item in aws.items() if item["pk"]["S"].startswith("RATE#")]
    assert rates and all("expiresAt" in item for item in rates)


def test_a_concurrent_change_is_a_conflict_not_a_lost_update(aws: Harness) -> None:
    from papyrus_content.newsletter.store import Conflict

    aws.subscribe()
    stale = aws.store.get_profile(aws.hid())
    fresh = aws.store.get_profile(aws.hid())
    aws.store.save(fresh, fresh["rev"])
    with pytest.raises(Conflict):
        aws.store.save(stale, stale["rev"])
    with pytest.raises(Conflict):
        aws.store.save(
            {"pk": f"SUB#{aws.hid()}", "sk": "PROFILE", "email": READER, "status": "pending"}, None
        )


def test_unknown_actions_are_refused(aws: Harness) -> None:
    for event in [{}, {"action": "nope"}, {"action": 5}, {"action": "send_everything"}, {"action": "__init__"}]:
        assert aws.service.dispatch(event) == {"statusCode": 400, "body": {"status": "error", "error": "unknown_action"}}
