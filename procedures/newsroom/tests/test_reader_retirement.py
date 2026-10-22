"""The Prospectus retired-subject poll: parsing, the HTTP client, deleting and re-keying, the cursor and the scheduled run (moto)."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content.projection.writers import LocalDirectoryWriter  # noqa: E402
from papyrus_content.reader_steering.retirement import (  # noqa: E402
    CURSOR_KEY,
    HttpRetirementPoll,
    ReaderTableNames,
    RetiredPage,
    RetiredSubject,
    RetirementPollError,
    RetirementReport,
    apply_retirements,
    parse_page,
    run_retirement_poll,
)
from papyrus_content.reader_steering.task import retirement_poll_from_environment  # noqa: E402
from reader_fixtures import TABLE_NAMES, ReaderBackend, ScriptedRetirementPoll, run_snapshot, subject_for  # noqa: E402
from reader_privacy import identity_leaks  # noqa: E402

ALICE, BOB, CAROL = subject_for("alice"), subject_for("bob"), subject_for("carol")
NAMES = ReaderTableNames(profile=TABLE_NAMES["profile"], handle=TABLE_NAMES["handle"], vote=TABLE_NAMES["vote"], state=TABLE_NAMES["rate"], submission=TABLE_NAMES["submission"])


def deleted(subject: str) -> RetiredSubject:
    return RetiredSubject(subject, "deleted", None, "2026-10-21T14:00:00Z")


def merged(subject: str, survivor: str) -> RetiredSubject:
    return RetiredSubject(subject, "merged", survivor, "2026-10-21T14:00:00Z")


def reader(backend: ReaderBackend, subject: str, handle: str | None = None) -> str:
    reader_id = backend.call(subject, "me")["body"]["readerId"]
    if handle:
        backend.call(subject, "handle", {"handle": handle})
    return reader_id


def vote(backend: ReaderBackend, subject: str, item: str, dimension: str, value: int | None = None, on: bool = True) -> None:
    if value is None:
        backend.call(subject, "vote", {"subject": item, "dimension": dimension, "on": on})
    else:
        backend.call(subject, "rating", {"subject": item, "dimension": dimension, "value": value})


def apply(backend: ReaderBackend, *records: RetiredSubject) -> RetirementReport:
    report = RetirementReport(enabled=True)
    apply_retirements(backend.resource, NAMES, records, report)
    return report


class ParsingTests(unittest.TestCase):
    def test_a_page_is_parsed_and_validated(self) -> None:
        page = parse_page(
            {
                "retired": [
                    {"siteSubject": ALICE, "reason": "deleted", "retiredAt": "2026-10-21T14:00:00Z"},
                    {"siteSubject": BOB, "reason": "merged", "survivingSiteSubject": CAROL, "retiredAt": "2026-10-21T14:00:00Z"},
                ],
                "cursor": "next",
                "more": True,
            }
        )
        self.assertEqual(page.retired, (deleted(ALICE), merged(BOB, CAROL)))
        self.assertEqual((page.cursor, page.more), ("next", True))
        self.assertEqual(parse_page({"retired": [], "cursor": "", "more": "yes"}), RetiredPage((), None, False))

    def test_a_malformed_record_stops_the_poll(self) -> None:
        for record in (
            {"siteSubject": "person-1", "reason": "deleted"},
            {"siteSubject": ALICE, "reason": "vanished"},
            {"siteSubject": ALICE, "reason": "merged"},
            {"siteSubject": ALICE, "reason": "merged", "survivingSiteSubject": "x"},
            {"siteSubject": ALICE, "reason": "merged", "survivingSiteSubject": ALICE},
        ):
            with self.assertRaises(RetirementPollError, msg=record):
                parse_page({"retired": [record]})


class HttpClientTests(unittest.TestCase):
    def test_it_sends_the_secret_and_the_cursor_to_the_site_route(self) -> None:
        seen = []

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def opener(request, timeout):
            seen.append((request.full_url, request.get_header("X-papyrus-reader-poll-secret"), request.get_method(), timeout))
            return Response(b'{"retired": [], "cursor": "c2", "more": false}')

        poll = HttpRetirementPoll("https://reader.example.test/", "poll value", opener=opener)
        self.assertEqual(poll.fetch(None).cursor, "c2")
        poll.fetch("a b/=")
        self.assertEqual(seen[0][:3], ("https://reader.example.test/api/reader/retired", "poll value", "GET"))
        self.assertEqual(seen[1][0], "https://reader.example.test/api/reader/retired?since=a+b%2F%3D")
        self.assertTrue(poll.enabled)

    def test_failures_become_poll_errors_without_the_secret(self) -> None:
        def failing(status):
            def opener(request, timeout):
                raise urllib.error.HTTPError(request.full_url, status, "x", {}, io.BytesIO(b'{"error": "unauthorized", "message": "no"}'))

            return opener

        with self.assertRaisesRegex(RetirementPollError, "401 unauthorized") as caught:
            HttpRetirementPoll("https://reader.example.test", "poll value", opener=failing(401)).fetch(None)
        self.assertNotIn("poll value", str(caught.exception))
        with self.assertRaises(RetirementPollError):
            HttpRetirementPoll("https://reader.example.test", "poll value", opener=lambda request, timeout: (_ for _ in ()).throw(urllib.error.URLError("down"))).fetch(None)
        for origin, secret in (("http://reader.example.test", "x"), ("https://reader.example.test", "")):
            with self.assertRaises(RetirementPollError):
                HttpRetirementPoll(origin, secret)

    def test_the_environment_builds_the_client_only_when_fully_configured(self) -> None:
        class Ssm:
            def get_parameter(self, Name, WithDecryption):
                assert (Name, WithDecryption) == ("/papyrus/reader/poll", True)
                return {"Parameter": {"Value": "poll value\n"}}

        configured = {"PAPYRUS_READER_POLL_URL": "https://reader.example.test", "PAPYRUS_READER_POLL_SECRET_PARAMETER": "/papyrus/reader/poll"}
        self.assertTrue(retirement_poll_from_environment(configured, Ssm()).enabled)
        self.assertFalse(retirement_poll_from_environment({}, Ssm()).enabled)
        self.assertFalse(retirement_poll_from_environment({"PAPYRUS_READER_POLL_URL": "https://reader.example.test"}, Ssm()).enabled)


class DeletedTests(unittest.TestCase):
    def test_a_deleted_subject_loses_profile_handle_votes_and_ratings_and_nobody_else_does(self) -> None:
        with ReaderBackend() as backend:
            alice_id = reader(backend, ALICE, "quiet-fox")
            bob_id = reader(backend, BOB, "loud-owl")
            for who in (ALICE, BOB):
                vote(backend, who, "item-one", "up")
                vote(backend, who, "item-one", "used-it")
                vote(backend, who, "item-one", "real", 4)
            report = apply(backend, deleted(ALICE))
            self.assertEqual(report.deleted, 1)
            self.assertIsNone(backend.table("profile").get_item(Key={"id": ALICE}).get("Item"))
            self.assertIsNone(backend.table("handle").get_item(Key={"id": "quiet-fox"}).get("Item"))
            remaining = backend.votes()
            self.assertEqual(sorted(row["id"] for row in remaining), sorted(f"item-one#{bob_id}#{dimension}" for dimension in ("up", "used-it", "real")))
            self.assertFalse(any(row["readerId"] == alice_id for row in remaining))
            self.assertIsNotNone(backend.table("profile").get_item(Key={"id": BOB}).get("Item"))
            self.assertIsNotNone(backend.table("handle").get_item(Key={"id": "loud-owl"}).get("Item"))

    def test_the_handle_is_free_again_and_a_repeat_changes_nothing(self) -> None:
        with ReaderBackend() as backend:
            reader(backend, ALICE, "quiet-fox")
            apply(backend, deleted(ALICE))
            self.assertEqual(apply(backend, deleted(ALICE), deleted(ALICE)).deleted, 0, "ensure dropped: nothing left to drop")
            self.assertEqual(backend.call(BOB, "handle", {"handle": "quiet-fox"})["statusCode"], 200)
            self.assertEqual(apply(backend, deleted(CAROL)).deleted, 0, "an unknown subject is not an error")


class MergedTests(unittest.TestCase):
    def test_without_a_surviving_profile_the_profile_is_re_keyed_with_its_votes_and_handle(self) -> None:
        with ReaderBackend() as backend:
            alice_id = reader(backend, ALICE, "quiet-fox")
            vote(backend, ALICE, "item-one", "up")
            vote(backend, ALICE, "item-one", "real", 5)
            report = apply(backend, merged(ALICE, BOB))
            self.assertEqual(report.merged, 1)
            self.assertIsNone(backend.table("profile").get_item(Key={"id": ALICE}).get("Item"))
            moved = backend.table("profile").get_item(Key={"id": BOB})["Item"]
            self.assertEqual((moved["siteSubject"], moved["readerId"], moved["handle"]), (BOB, alice_id, "quiet-fox"))
            self.assertEqual(len(backend.votes()), 2, "votes are keyed by readerId, which did not change")
            answer = backend.call(BOB, "me", {"subjects": ["item-one"]})["body"]
            self.assertEqual((answer["readerId"], answer["handle"]), (alice_id, "quiet-fox"))
            self.assertEqual(apply(backend, merged(ALICE, BOB)).merged, 0, "a repeat changes nothing")

    def test_with_a_surviving_profile_votes_merge_and_the_newer_row_wins_per_subject_and_dimension(self) -> None:
        with ReaderBackend() as backend:
            old_id = reader(backend, ALICE, "old-name")
            survivor_id = reader(backend, BOB, "kept-name")
            vote(backend, BOB, "item-one", "real", 2)
            backend.now += 100
            vote(backend, ALICE, "item-one", "real", 5)
            backend.now += 100
            vote(backend, ALICE, "item-one", "useful", 3)
            backend.now += 100
            vote(backend, BOB, "item-one", "useful", 1)
            vote(backend, ALICE, "item-two", "up")
            backend.now += 100
            vote(backend, BOB, "item-one", "up")
            vote(backend, ALICE, "item-one", "up")
            apply(backend, merged(ALICE, BOB))
            values = {row["id"]: int(row["value"]) for row in backend.votes()}
            self.assertEqual(
                values,
                {
                    f"item-one#{survivor_id}#real": 5,
                    f"item-one#{survivor_id}#useful": 1,
                    f"item-two#{survivor_id}#up": 1,
                    f"item-one#{survivor_id}#up": 1,
                },
                "the newer rating wins each conflict; non-conflicting rows move over",
            )
            self.assertFalse(any(row["readerId"] == old_id for row in backend.votes()))
            profile = backend.table("profile").get_item(Key={"id": BOB})["Item"]
            self.assertEqual((profile["readerId"], profile["handle"]), (survivor_id, "kept-name"), "the survivor keeps its own handle")
            self.assertIsNone(backend.table("handle").get_item(Key={"id": "old-name"}).get("Item"), "the retired handle is freed")
            self.assertIsNone(backend.table("profile").get_item(Key={"id": ALICE}).get("Item"))

    def test_the_survivor_adopts_the_handle_when_it_has_none_and_the_stricter_state(self) -> None:
        with ReaderBackend() as backend:
            old_id = reader(backend, ALICE, "old-name")
            survivor_id = reader(backend, BOB)
            backend.table("profile").update_item(Key={"id": ALICE}, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":s": "banned"})
            apply(backend, merged(ALICE, BOB))
            profile = backend.table("profile").get_item(Key={"id": BOB})["Item"]
            self.assertEqual((profile["handle"], profile["state"], profile["readerId"]), ("old-name", "banned", survivor_id))
            self.assertEqual(backend.table("handle").get_item(Key={"id": "old-name"})["Item"]["readerId"], survivor_id)
            self.assertNotEqual(old_id, survivor_id)

    def test_a_chain_of_merges_in_one_page_ends_at_the_last_survivor(self) -> None:
        with ReaderBackend() as backend:
            alice_id = reader(backend, ALICE, "quiet-fox")
            vote(backend, ALICE, "item-one", "up")
            apply(backend, merged(ALICE, BOB), merged(BOB, CAROL))
            self.assertIsNone(backend.table("profile").get_item(Key={"id": BOB}).get("Item"))
            self.assertEqual(backend.table("profile").get_item(Key={"id": CAROL})["Item"]["readerId"], alice_id)
            self.assertEqual(len(backend.votes()), 1)


class PollRunTests(unittest.TestCase):
    def test_pages_are_followed_and_the_cursor_is_saved_and_reused(self) -> None:
        with ReaderBackend() as backend:
            reader(backend, ALICE)
            reader(backend, BOB)
            poll = ScriptedRetirementPoll(RetiredPage((deleted(ALICE),), "c1", True), RetiredPage((deleted(BOB),), "c2", False))
            report = run_retirement_poll(poll, backend.resource, NAMES)
            self.assertEqual((report.pages, report.deleted, report.cursor_saved, report.error), (2, 2, True, None))
            self.assertEqual(poll.asked, [None, "c1"], "the second request carries the first cursor")
            self.assertEqual(backend.table("rate").get_item(Key={"pk": CURSOR_KEY})["Item"]["cursor"], "c2")
            later = ScriptedRetirementPoll(RetiredPage((), "c2", False))
            run_retirement_poll(later, backend.resource, NAMES)
            self.assertEqual(later.asked, ["c2"], "the next run starts from the stored cursor")

    def test_a_failure_keeps_the_last_applied_cursor_and_reports_the_error(self) -> None:
        with ReaderBackend() as backend:
            reader(backend, ALICE)
            poll = ScriptedRetirementPoll(RetiredPage((deleted(ALICE),), "c1", True), RetirementPollError("down"))
            report = run_retirement_poll(poll, backend.resource, NAMES)
            self.assertEqual((report.deleted, report.error), (1, "RetirementPollError"))
            self.assertEqual(backend.table("rate").get_item(Key={"pk": CURSOR_KEY})["Item"]["cursor"], "c1")

    def test_a_disabled_poll_does_nothing(self) -> None:
        with ReaderBackend() as backend:
            from papyrus_content.reader_steering.retirement import DisabledRetirementPoll

            report = run_retirement_poll(DisabledRetirementPoll(), backend.resource, NAMES)
            self.assertEqual((report.enabled, report.pages), (False, 0))
            self.assertIsNone(backend.table("rate").get_item(Key={"pk": CURSOR_KEY}).get("Item"))

    def test_the_page_limit_ends_a_runaway_poll(self) -> None:
        with ReaderBackend() as backend:
            poll = ScriptedRetirementPoll(*[RetiredPage((), f"c{number}", True) for number in range(60)])
            self.assertEqual(run_retirement_poll(poll, backend.resource, NAMES).pages, 50)


class ScheduledRunTests(unittest.TestCase):
    def snapshot(self, backend: ReaderBackend, directory: str, **arguments):
        store = LocalDirectoryWriter(Path(directory))
        return store, run_snapshot(backend, store, **arguments)

    def test_the_run_applies_retirements_before_it_writes_the_numbers(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            reader(backend, ALICE, "quiet-fox")
            reader(backend, BOB, "loud-owl")
            vote(backend, ALICE, "item-one", "up")
            vote(backend, BOB, "item-one", "up")
            poll = ScriptedRetirementPoll(RetiredPage((deleted(ALICE),), "c1", False))
            store, report = self.snapshot(backend, directory, retirement_poll=poll, poll_retirements=True)
            items = json.loads(store.get("_data/reader/items.json"))
            self.assertEqual(items["items"]["item-one"]["up"], 1, "the deleted reader's upvote is not counted")
            self.assertEqual(report.retirement_poll.deleted, 1)
            self.assertEqual(report.to_dict()["retirementPoll"], {"enabled": True, "pages": 1, "deleted": 1, "merged": 0, "cursorSaved": True, "error": None})
            self.assertEqual(identity_leaks(store.get("_data/reader/readers.json").decode()), [])

    def test_only_a_scheduled_run_polls(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            poll = ScriptedRetirementPoll()
            _, report = self.snapshot(backend, directory, retirement_poll=poll, poll_retirements=False)
            self.assertEqual((poll.asked, report.retirement_poll.enabled), ([], False), "a debounced run after a vote never polls")

    def test_a_poll_that_fails_never_stops_the_numbers(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            reader(backend, ALICE)
            vote(backend, ALICE, "item-one", "up")
            poll = ScriptedRetirementPoll(RetirementPollError("down"))
            store, report = self.snapshot(backend, directory, retirement_poll=poll, poll_retirements=True)
            self.assertEqual(json.loads(store.get("_data/reader/items.json"))["items"]["item-one"]["up"], 1)
            self.assertEqual(report.retirement_poll.error, "RetirementPollError")


if __name__ == "__main__":
    unittest.main()
