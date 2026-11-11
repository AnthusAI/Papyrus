"""The Python usage sender sends exactly what the Prospectus TypeScript sender sends (message version 1)."""
import json
import uuid

import pytest

from papyrus_cost_usage import SiteUsage, UsageError, UsageSender, site_usage_product, usage_queue_url

# A made-up Account UUID, derived so no identifier is written into the repository.
OWNER = str(uuid.uuid5(uuid.NAMESPACE_URL, "https://accounts.example.test/owner"))
QUEUE = "https://sqs.us-east-1.amazonaws.com/111122223333/prospectus-usage-papyrus-dataparade"
NOV_9_2026 = 1_794_182_400_000  # 2026-11-09T00:00:00Z


def sender(sent, now=lambda: NOV_9_2026):
    return UsageSender(product="papyrus-dataparade", app="papyrus", deployment="dataparade", queue_url=QUEUE,
                       send=lambda url, body: sent.append((url, body)), now=now)


def test_message_matches_the_typescript_sender_field_for_field():
    sent = []
    usage = sender(sent)
    usage.record(OWNER, [{"itemKind": "openai.tokens.input", "quantity": 10}])
    usage.record(OWNER, [{"itemKind": "openai.tokens.input", "quantity": 5}, {"itemKind": "jev.tokens", "quantity": 0}])
    usage.flush()
    [(url, body)] = sent
    message = json.loads(body)
    assert url == QUEUE
    assert list(message) == ["version", "operationId", "accountId", "app", "deployment", "day", "items"]
    assert message["day"] == 20261109
    assert message["items"] == [{"itemKind": "openai.tokens.input", "quantity": 15}]


def test_one_message_per_utc_day():
    sent, clock = [], [NOV_9_2026 - 1]
    usage = sender(sent, now=lambda: clock[0])
    usage.record(OWNER, [{"itemKind": "jev.tokens", "quantity": 1}])
    clock[0] = NOV_9_2026
    usage.record(OWNER, [{"itemKind": "jev.tokens", "quantity": 2}])
    usage.flush()
    assert sorted(json.loads(body)["day"] for _, body in sent) == [20261108, 20261109]


def test_nothing_recorded_sends_nothing():
    sent = []
    sender(sent).flush()
    assert sent == []


@pytest.mark.parametrize("items", [
    [{"itemKind": "tokens", "quantity": 1}],
    [{"itemKind": "openai.tokens.input", "quantity": -1}],
    [{"itemKind": "openai.tokens.input", "quantity": 1.5}],
    [{"itemKind": "openai.tokens.input", "quantity": True}],
    [{"itemKind": "openai.tokens.input", "quantity": 2**53}],
])
def test_invalid_items_raise(items):
    with pytest.raises(UsageError):
        sender([]).record(OWNER, items)


def test_account_must_be_a_lower_case_uuid_or_owner():
    with pytest.raises(UsageError):
        sender([]).record(OWNER.upper(), [{"itemKind": "jev.tokens", "quantity": 1}])
    sent = []
    usage = sender(sent)
    usage.record("owner", [{"itemKind": "jev.tokens", "quantity": 1}])
    usage.flush()
    assert json.loads(sent[0][1])["accountId"] == "owner"


def test_owner_needs_a_deployment():
    no_deployment = UsageSender(product="cyclotron", app="cyclotron", queue_url=QUEUE.replace("papyrus-dataparade", "cyclotron"), send=lambda *_: None)
    with pytest.raises(UsageError):
        no_deployment.record("owner", [{"itemKind": "jev.tokens", "quantity": 1}])


def test_a_papyrus_site_sends_as_papyrus_site():
    with pytest.raises(UsageError):
        UsageSender(product="papyrus", app="papyrus", deployment="dataparade", queue_url=QUEUE)


def test_queue_url_and_product():
    assert usage_queue_url(site_usage_product("dataparade"), "111122223333") == QUEUE
    with pytest.raises(UsageError):
        usage_queue_url("papyrus-dataparade", "1234")
    with pytest.raises(UsageError):
        site_usage_product("Data Parade")


def test_site_usage_reports_as_owner_unless_given_a_verified_account():
    sent = []
    usage = SiteUsage.from_environment({"PROSPECTUS_USAGE_QUEUE_URL": QUEUE, "PAPYRUS_SITE_ID": "dataparade"},
                                       send=lambda url, body: sent.append(body))
    usage.record_humanus_check({"usage": {"classifierInputTokens": 7}})
    usage.record_humanus_check({"findings": []})
    usage.flush()
    [body] = sent
    assert json.loads(body)["accountId"] == "owner"
    assert json.loads(body)["items"] == [{"itemKind": "jev.tokens", "quantity": 7}]
    usage.record_openai({"prompt_tokens": 3}, account_id=OWNER)
    usage.flush()
    assert json.loads(sent[1])["accountId"] == OWNER


def test_site_usage_refuses_a_queue_url_without_its_site():
    with pytest.raises(UsageError):
        SiteUsage.from_environment({"PROSPECTUS_USAGE_QUEUE_URL": QUEUE})
