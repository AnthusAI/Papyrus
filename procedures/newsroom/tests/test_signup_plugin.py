"""The signup plugin's one guest operation: validation, abuse limits, idempotency, and its AWS adapters."""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from signup_fixtures import (  # noqa: E402
    PLACEHOLDER_ADDRESS,
    START_SECONDS,
    FakeSignupBackend,
    signup_handler,
    valid_arguments,
)

ACCEPTED = signup_handler.STATUS_ACCEPTED
INVALID = signup_handler.STATUS_INVALID
THROTTLED = signup_handler.STATUS_THROTTLED
EXPIRED = signup_handler.STATUS_EXPIRED


class ValueValidationTests(unittest.TestCase):
    def test_ordinary_addresses_are_valid(self) -> None:
        for value in ["a@b.co", "first.last+tag@sub.example.test", "x_y@example-site.test", "O'Neil@example.test"]:
            self.assertTrue(signup_handler.valid_value(value), value)

    def test_everything_else_is_not(self) -> None:
        bad = [
            "", "plain", "@example.test", "a@", "a@b", "a b@example.test", "a@exa mple.test", "a@@example.test",
            "a@example..test", "a@-example.test", "a@example-.test", "a@example.test.", "a@example.test\n",
            "a\x00@example.test", "=cmd@example.test", "+1@example.test", "-1@example.test", "@evil.test",
            "a" * 65 + "@example.test", "a@" + "b" * 64 + ".test", "a@" + ("b" * 60 + ".") * 5 + "test",
            "a@example.test" + "t" * 300, "ａ@example.test", "a@exämple.test", "<script>@example.test",
            "a@example.test, b@example.test", "a@example.test;b@example.test",
        ]
        for value in bad:
            self.assertFalse(signup_handler.valid_value(value), repr(value))

    def test_the_domain_is_lowercased_for_identity_and_storage_but_the_local_part_is_not(self) -> None:
        self.assertEqual(signup_handler.normalized_value("Reader@Example.TEST"), "Reader@example.test")


class SubmissionTests(unittest.TestCase):
    def test_a_valid_submission_is_stored(self) -> None:
        backend = FakeSignupBackend()
        self.assertEqual(backend.submit(valid_arguments())["status"], ACCEPTED)
        entry = next(iter(backend.entries.values()))
        self.assertEqual(set(entry), {"id", "form", "value", "submittedAt"})
        self.assertEqual((entry["form"], entry["value"]), ("newsletter", "reader@example.test"))
        self.assertTrue(entry["submittedAt"].endswith("Z"))

    def test_repeating_a_submission_changes_nothing_and_answers_the_same(self) -> None:
        backend = FakeSignupBackend()
        first = backend.submit(valid_arguments())
        second = backend.submit(valid_arguments(value="reader@EXAMPLE.test"))
        self.assertEqual(first, second)
        self.assertEqual(len(backend.entries), 1)

    def test_the_same_address_on_another_form_is_a_separate_entry(self) -> None:
        backend = FakeSignupBackend(forms=("newsletter", "events"))
        backend.submit(valid_arguments())
        backend.submit(valid_arguments(form="events"))
        self.assertEqual(len(backend.entries), 2)

    def test_the_honeypot_is_answered_like_success_and_stores_nothing(self) -> None:
        backend = FakeSignupBackend()
        self.assertEqual(backend.submit(valid_arguments(website="http://spam.example.test"))["status"], ACCEPTED)
        self.assertEqual(backend.entries, {})

    def test_a_form_submitted_faster_than_a_person_can_fill_it_stores_nothing(self) -> None:
        backend = FakeSignupBackend()
        just_now = str(int((START_SECONDS - 0.5) * 1000))
        self.assertEqual(backend.submit(valid_arguments(renderedAt=just_now))["status"], ACCEPTED)
        self.assertEqual(backend.entries, {})

    def test_a_form_older_than_a_day_asks_for_a_reload(self) -> None:
        backend = FakeSignupBackend()
        stale = str(int((START_SECONDS - 25 * 3600) * 1000))
        self.assertEqual(backend.submit(valid_arguments(renderedAt=stale))["status"], EXPIRED)
        self.assertEqual(backend.entries, {})

    def test_a_timestamp_from_the_future_is_treated_as_too_fast(self) -> None:
        backend = FakeSignupBackend()
        future = str(int((START_SECONDS + 3600) * 1000))
        self.assertEqual(backend.submit(valid_arguments(renderedAt=future))["status"], ACCEPTED)
        self.assertEqual(backend.entries, {})


class AbuseTests(unittest.TestCase):
    def assert_rejected(self, arguments: dict, status: str = INVALID) -> None:
        backend = FakeSignupBackend()
        self.assertEqual(backend.submit(arguments)["status"], status, arguments)
        self.assertEqual(backend.entries, {}, arguments)

    def test_unknown_or_malformed_forms_are_rejected(self) -> None:
        for form in ["other", "", "Newsletter", "news letter", "../x", "newsletter\n", "n" * 41, "x" * 100000, None]:
            self.assert_rejected(valid_arguments(form=form))

    def test_oversized_arguments_are_rejected_before_anything_else(self) -> None:
        self.assert_rejected(valid_arguments(value="a@" + "b" * 5000 + ".test"))
        self.assert_rejected(valid_arguments(website="x" * 5000))
        self.assert_rejected(valid_arguments(renderedAt="1" * 5000))

    def test_wrong_types_are_rejected(self) -> None:
        for field, junk in [("value", 12), ("value", ["a@example.test"]), ("value", {"a": 1}), ("form", 7), ("website", 1), ("renderedAt", 5)]:
            self.assert_rejected(valid_arguments(**{field: junk}))

    def test_missing_or_garbled_fields_are_rejected(self) -> None:
        self.assert_rejected({})
        self.assert_rejected({"form": "newsletter"})
        self.assert_rejected(valid_arguments(renderedAt="yesterday"))
        self.assert_rejected(valid_arguments(renderedAt=""))
        self.assert_rejected(valid_arguments(renderedAt="nan"))

    def test_spreadsheet_formulas_are_not_addresses(self) -> None:
        for value in ["=HYPERLINK(\"http://x\")@example.test", "+cmd@example.test", "-2+3@example.test", "@SUM(A1)@example.test"]:
            self.assert_rejected(valid_arguments(value=value))

    def test_nothing_is_written_for_any_rejected_request(self) -> None:
        backend = FakeSignupBackend()
        for number in range(15):
            backend.submit(valid_arguments(value=f"not-an-address-{number}"), address=f"203.0.113.{number}", identity_id=None)
        self.assertEqual(backend.entries, {})

    def test_the_twenty_first_request_in_a_minute_from_one_address_is_throttled(self) -> None:
        backend = FakeSignupBackend()
        statuses = [
            backend.submit(valid_arguments(value=f"person{number}@example.test"), identity_id=f"identity-{number}")["status"]
            for number in range(25)
        ]
        self.assertEqual(statuses[:20], [ACCEPTED] * 20)
        self.assertEqual(statuses[20:], [THROTTLED] * 5)
        self.assertEqual(len(backend.entries), 20)

    def test_invalid_requests_count_toward_the_limit(self) -> None:
        backend = FakeSignupBackend()
        for number in range(20):
            backend.submit(valid_arguments(value="junk"), identity_id=f"identity-{number}")
        self.assertEqual(backend.submit(valid_arguments(), identity_id="fresh")["status"], THROTTLED)

    def test_one_identity_is_limited_sooner_than_one_address(self) -> None:
        backend = FakeSignupBackend()
        statuses = [backend.submit(valid_arguments(value=f"p{number}@example.test"))["status"] for number in range(8)]
        self.assertEqual(statuses, [ACCEPTED] * 5 + [THROTTLED] * 3)

    def test_other_addresses_are_not_affected_by_one_address_being_throttled(self) -> None:
        backend = FakeSignupBackend()
        for number in range(25):
            backend.submit(valid_arguments(), address="198.51.100.7", identity_id=None)
        self.assertEqual(backend.submit(valid_arguments(value="other@example.test"), address="198.51.100.8")["status"], ACCEPTED)

    def test_the_limit_starts_over_in_the_next_minute(self) -> None:
        backend = FakeSignupBackend()
        for number in range(25):
            backend.submit(valid_arguments(), identity_id=None)
        self.assertEqual(backend.submit(valid_arguments(value="later@example.test"), identity_id=None)["status"], THROTTLED)
        backend.now += 61
        later = valid_arguments(value="later@example.test", renderedAt=str(int((backend.now - 60) * 1000)))
        self.assertEqual(backend.submit(later, identity_id=None)["status"], ACCEPTED)

    def test_a_guest_without_an_identity_is_still_limited_by_address(self) -> None:
        backend = FakeSignupBackend()
        statuses = [backend.submit(valid_arguments(value=f"p{n}@example.test"), identity_id=None)["status"] for n in range(22)]
        self.assertEqual(statuses.count(THROTTLED), 2)


class CallerAddressTests(unittest.TestCase):
    def test_the_last_source_address_is_the_caller(self) -> None:
        self.assertEqual(signup_handler.caller_address({"sourceIp": ["6.6.6.6", "198.51.100.7"]}), "198.51.100.7")

    def test_a_sender_cannot_choose_its_own_address_by_prepending(self) -> None:
        forged = signup_handler.caller_address({"sourceIp": ["1.1.1.1", "2.2.2.2", "198.51.100.7"]})
        self.assertEqual(forged, signup_handler.caller_address({"sourceIp": ["198.51.100.7"]}))

    def test_missing_addresses_share_one_bucket(self) -> None:
        for identity in (None, {}, {"sourceIp": []}, {"sourceIp": None}):
            self.assertEqual(signup_handler.caller_address(identity), "unknown")


class SettingsTests(unittest.TestCase):
    def test_settings_come_from_the_environment(self) -> None:
        settings = signup_handler.settings_from_environment(
            {"PAPYRUS_SIGNUP_FORMS": "news, events,", "PAPYRUS_SIGNUP_ADDRESS_LIMIT": "30"}
        )
        self.assertEqual(settings.forms, frozenset({"news", "events"}))
        self.assertEqual((settings.address_limit, settings.identity_limit), (30, 5))

    def test_no_forms_configured_means_every_submission_is_rejected(self) -> None:
        backend = FakeSignupBackend(forms=())
        self.assertEqual(backend.submit(valid_arguments())["status"], INVALID)


class AwsAdapterTests(unittest.TestCase):
    def test_counting_hits_adds_one_and_sets_an_expiry(self) -> None:
        client = mock.Mock()
        client.update_item.return_value = {"Attributes": {"hits": {"N": "4"}}}
        count_hit = signup_handler.counting_hits("rate-table", client)
        self.assertEqual(count_hit("address#abc#1", 300), 4)
        arguments = client.update_item.call_args.kwargs
        self.assertEqual(arguments["TableName"], "rate-table")
        self.assertEqual(arguments["Key"], {"pk": {"S": "address#abc#1"}})
        self.assertIn("ADD hits :one", arguments["UpdateExpression"])
        self.assertIn("expiresAt", arguments["UpdateExpression"])

    def stored(self, payload: dict) -> bool:
        credentials = mock.Mock()
        credentials.get_frozen_credentials.return_value = mock.Mock(access_key="AKIAEXAMPLE", secret_key="secret", token="token")
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        with mock.patch("boto3.Session") as session, mock.patch("urllib.request.urlopen", return_value=response) as opener:
            session.return_value.get_credentials.return_value = credentials
            store_entry = signup_handler.storing_entries("https://api.example.test/graphql", "us-east-1")
            result = store_entry({"id": "i", "form": "newsletter", "value": "a@example.test", "submittedAt": "2026-01-01T00:00:00.000Z"})
        request = opener.call_args.args[0]
        self.assertIn("AWS4-HMAC-SHA256", request.get_header("Authorization"))
        self.assertEqual(json.loads(request.data)["variables"]["input"]["form"], "newsletter")
        return result

    def test_a_created_entry_reports_true(self) -> None:
        self.assertTrue(self.stored({"data": {"createSignupEntry": {"id": "i"}}}))

    def test_an_existing_entry_reports_false(self) -> None:
        self.assertFalse(self.stored({"errors": [{"errorType": "DynamoDB:ConditionalCheckFailedException", "message": "The conditional request failed"}]}))

    def test_any_other_error_is_raised(self) -> None:
        with self.assertRaises(RuntimeError):
            self.stored({"errors": [{"errorType": "Unauthorized", "message": "Not Authorized to access createSignupEntry"}]})

    def test_the_handler_reads_its_inputs_from_the_appsync_event(self) -> None:
        environment = {
            "PAPYRUS_SIGNUP_FORMS": "newsletter",
            "PAPYRUS_SIGNUP_RATE_TABLE": "rate-table",
            "PAPYRUS_GRAPHQL_ENDPOINT": "https://api.example.test/graphql",
            "AWS_REGION": "us-east-1",
        }
        stored: list[dict] = []
        with mock.patch.dict("os.environ", environment), \
                mock.patch.object(signup_handler, "counting_hits", return_value=lambda key, lifetime: 1), \
                mock.patch.object(signup_handler, "storing_entries", return_value=lambda entry: stored.append(entry) or True), \
                mock.patch.object(signup_handler.time, "time", return_value=START_SECONDS):
            outcome = signup_handler.handler(
                {
                    "arguments": valid_arguments(),
                    "identity": {"cognitoIdentityId": "us-east-1:identity", "sourceIp": [PLACEHOLDER_ADDRESS]},
                }
            )
        self.assertEqual(outcome["status"], ACCEPTED)
        self.assertEqual(len(stored), 1)


if __name__ == "__main__":
    unittest.main()
