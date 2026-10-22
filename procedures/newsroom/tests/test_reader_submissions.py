"""Reader submissions: the submit action, dedupe, similar warnings, limits, the snapshot, karma and the review signals."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content.projection.writers import LocalDirectoryWriter  # noqa: E402
from papyrus_content.reader_steering.review import parsed_signals  # noqa: E402
from papyrus_content.reader_steering.signals import submission_signals  # noqa: E402
from papyrus_content.reader_steering.snapshot import SUBMISSIONS_LISTED, SnapshotSettings, build_snapshot  # noqa: E402
from papyrus_content.reference_intake import IntakeError, canonical_source_url as intake_canonical_url  # noqa: E402
from reader_fixtures import START_SECONDS, ReaderBackend, reader_handler, run_snapshot, subject_for  # noqa: E402
from reader_privacy import scan_files  # noqa: E402

ALICE = subject_for("alice")
BOB = subject_for("bob")
CAROL = subject_for("carol")
LINK = "https://Example.com/post/1#intro"
CANONICAL = "https://example.com/post/1"


def ready(backend: ReaderBackend, subject: str, handle: str) -> str:
    backend.call(subject, "handle", {"handle": handle})
    return backend.call(subject, "me")["body"]["readerId"]


def submit(backend: ReaderBackend, subject: str = ALICE, **changes) -> dict:
    payload = {"url": LINK, "title": "A small tool", **changes}
    return backend.call(subject, "submit", {key: value for key, value in payload.items() if value is not None})


class CanonicalUrlTests(unittest.TestCase):
    def test_the_function_canonicalises_exactly_like_reference_intake(self) -> None:
        good = [
            "https://Example.com", "HTTP://EXAMPLE.com:80/a?b=1&a=2#frag", "https://example.com:443/", "https://example.com:8443/x",
            "https://bücher.example/straße", "https://[2001:db8::1]:8080/a", "https://example.com/Path/Case?Q=1", "http://a.b/c%20d",
        ]
        bad = ["", "ftp://example.com/", "javascript:alert(1)", "https://user:pw@example.com/", "https://example.com/a b", "example.com", "https://", None, 7, "x" * 4097]
        for url in good:
            self.assertEqual(reader_handler.canonical_source_url(url), intake_canonical_url(url), url)
        for url in bad:
            with self.assertRaises(IntakeError):
                intake_canonical_url(url)
            with self.assertRaises(reader_handler.InvalidUrl):
                reader_handler.canonical_source_url(url)


class SubmitTests(unittest.TestCase):
    def test_a_submission_is_public_pending_and_stored_with_the_readers_public_id_only(self) -> None:
        with ReaderBackend() as backend:
            reader_id = ready(backend, ALICE, "quiet-fox")
            answer = submit(backend, note="Worked well for me.")
            self.assertEqual(answer["statusCode"], 201)
            body = answer["body"]
            self.assertEqual((body["url"], body["state"], body["extraction"], body["similar"]), (CANONICAL, "pending", "pending", []))
            self.assertRegex(body["subject"], r"^sub-[0-9a-f]{24}$")
            (stored,) = backend.submissions()
            self.assertEqual(stored["id"], body["subject"])
            self.assertEqual((stored["canonicalUrl"], stored["domain"], stored["readerId"], stored["state"]), (CANONICAL, "example.com", reader_id, "pending"))
            self.assertEqual((stored["kind"], stored["note"], stored["extractionState"], stored["__typename"]), ("link", "Worked well for me.", "pending", "ReaderSubmission"))
            self.assertEqual(stored["similar"], [])
            self.assertNotIn(ALICE, json.dumps(answer, default=str) + json.dumps(stored, default=str))

    def test_a_handle_is_needed_before_the_first_submission(self) -> None:
        with ReaderBackend() as backend:
            answer = submit(backend)
            self.assertEqual((answer["statusCode"], answer["body"]["error"]), (422, "handle_required"))
            self.assertEqual(backend.submissions(), [])

    def test_banned_and_limited_readers_cannot_submit(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            for state, error in (("banned", "reader_banned"), ("limited", "reader_limited")):
                backend.table("profile").update_item(Key={"id": ALICE}, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":s": state})
                answer = submit(backend)
                self.assertEqual((answer["statusCode"], answer["body"]["error"]), (403, error))
            self.assertEqual(backend.submissions(), [])

    def test_an_exact_canonical_url_is_a_409_with_the_existing_subject(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            ready(backend, BOB, "loud-owl")
            first = submit(backend)["body"]
            for url in (LINK, "HTTPS://EXAMPLE.COM:443/post/1", "https://example.com/post/1#other"):
                answer = submit(backend, BOB, url=url, title="Same thing")
                self.assertEqual((answer["statusCode"], answer["body"]["error"]), (409, "duplicate_submission"), url)
                self.assertEqual(answer["body"]["existing"], {"subject": first["subject"], "url": CANONICAL, "title": "A small tool", "state": "pending"})
            self.assertEqual(len(backend.submissions()), 1)

    def test_a_query_string_makes_a_different_link(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            submit(backend)
            self.assertEqual(submit(backend, url="https://example.com/post/1?page=2")["statusCode"], 201)

    def test_a_duplicate_of_a_promoted_submission_points_at_the_item(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            first = submit(backend)["body"]
            backend.table("submission").update_item(
                Key={"id": first["subject"]}, UpdateExpression="SET #s = :s, itemId = :i", ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":s": "promoted", ":i": "item-xyz"}
            )
            answer = submit(backend, ALICE)
            self.assertEqual(answer["body"]["existing"], {"subject": "item-xyz", "url": CANONICAL, "title": "A small tool", "state": "promoted"})

    def test_a_duplicate_of_a_hidden_submission_reveals_nothing(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            first = submit(backend)["body"]
            backend.table("submission").update_item(Key={"id": first["subject"]}, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":s": "hidden"})
            answer = submit(backend)
            self.assertEqual((answer["statusCode"], answer["body"]["error"]), (409, "duplicate_submission"))
            self.assertNotIn("existing", answer["body"])

    def test_same_domain_items_in_the_last_48_hours_are_returned_as_similar(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            ready(backend, BOB, "loud-owl")
            old = submit(backend, url="https://example.com/old", title="Old one")["body"]
            backend.now += 47 * 3600
            recent = submit(backend, BOB, url="https://example.com/recent", title="Recent one")["body"]
            other = submit(backend, BOB, url="https://other.example/x", title="Elsewhere")["body"]
            backend.now += 3700
            answer = submit(backend, ALICE, url="https://example.com/new", title="New one")
            self.assertEqual(answer["statusCode"], 201)
            self.assertEqual({row["subject"] for row in answer["body"]["similar"]}, {recent["subject"]}, "the first is now just over 48 hours old")
            self.assertEqual(answer["body"]["similar"][0]["title"], "Recent one")
            self.assertNotIn(other["subject"], json.dumps(answer))
            self.assertEqual(old["state"], "pending")
            (stored,) = [row for row in backend.submissions() if row["title"] == "New one"]
            self.assertEqual(stored["similar"], [recent["subject"]])

    def test_hidden_submissions_are_not_similar(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            first = submit(backend, url="https://example.com/one", title="One")["body"]
            backend.table("submission").update_item(Key={"id": first["subject"]}, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":s": "hidden"})
            self.assertEqual(submit(backend, url="https://example.com/two", title="Two")["body"]["similar"], [])

    def test_at_most_five_similar_links_newest_first(self) -> None:
        with ReaderBackend(submissions_per_day=100) as backend:
            ready(backend, ALICE, "quiet-fox")
            backend.age_everyone()
            for number in range(7):
                backend.now += 60
                submit(backend, url=f"https://example.com/p{number}", title=f"Post {number}")
            backend.now += 60
            titles = [row["title"] for row in submit(backend, url="https://example.com/last", title="Last")["body"]["similar"]]
            self.assertEqual(titles, ["Post 6", "Post 5", "Post 4", "Post 3", "Post 2"])

    def test_validation(self) -> None:
        with ReaderBackend(submission_kinds=("article", "tool")) as backend:
            ready(backend, ALICE, "quiet-fox")
            cases = [
                ({"url": "ftp://example.com/x"}, "invalid_url"), ({"url": "javascript:alert(1)"}, "invalid_url"), ({"url": "https://u:p@example.com/"}, "invalid_url"),
                ({"url": "https://example.com/a b"}, "invalid_url"), ({"url": "https://example.com/" + "a" * 2100}, "invalid_url"), ({"url": 7}, "invalid_url"), ({"url": ""}, "invalid_url"),
                ({"title": ""}, "invalid_title"), ({"title": "   "}, "invalid_title"), ({"title": "x" * 201}, "invalid_title"), ({"title": "bell\x07"}, "invalid_title"), ({"title": 5}, "invalid_title"),
                ({"note": "x" * 501}, "invalid_note"), ({"note": "write to me@example.test"}, "invalid_note"), ({"title": "Mail me@example.test"}, "invalid_title"),
                ({"url": "https://example.com/unsubscribe?to=me@example.test"}, "invalid_url"), ({"note": "null\x00byte"}, "invalid_note"), ({"note": 5}, "invalid_note"),
                ({"kind": "video"}, "invalid_kind"), ({"kind": 3}, "invalid_kind"), ({"extra": "field"}, "invalid_submission"),
            ]
            for changes, error in cases:
                payload = {"url": "https://example.com/ok", "title": "Fine", **changes}
                answer = backend.call(ALICE, "submit", payload)
                self.assertEqual((answer["statusCode"], answer["body"]["error"]), (422, error), changes)
            self.assertEqual(backend.submissions(), [])
            good = backend.call(ALICE, "submit", {"url": "https://example.com/ok", "title": "  A   spaced\ttitle ", "kind": "tool"})
            self.assertEqual((good["statusCode"], good["body"]["title"], good["body"]["kind"]), (201, "A spaced title", "tool"))
            self.assertEqual(backend.call(ALICE, "submit", {"url": "https://example.com/ok2", "title": "Default kind"})["body"]["kind"], "article")

    def test_the_title_and_note_are_stored_as_plain_text_and_never_interpreted(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            submit(backend, title="<script>alert(1)</script> & more", note="<b>bold</b>")
            (stored,) = backend.submissions()
            self.assertEqual((stored["title"], stored["note"]), ("<script>alert(1)</script> & more", "<b>bold</b>"))

    def test_a_submission_schedules_a_snapshot_run(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            submit(backend)
            self.assertEqual(len(backend.schedules()), 1)


class SubmissionLimitTests(unittest.TestCase):
    def attempt(self, backend: ReaderBackend, subject: str, number: int) -> dict:
        return submit(backend, subject, url=f"https://site{number}.example/post", title=f"Post {number}")

    def test_ten_a_day_and_a_third_of_that_for_new_accounts(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            statuses = [self.attempt(backend, ALICE, number)["statusCode"] for number in range(5)]
            self.assertEqual(statuses, [201, 201, 201, 429, 429], "a new account gets 10 // 3 = 3")
            refused = self.attempt(backend, ALICE, 9)
            self.assertEqual(refused["body"]["error"], "rate_limited")
            window_end = (int(backend.now // 86400) + 1) * 86400
            self.assertEqual(refused["body"]["retryAfter"], int(window_end - backend.now))
            self.assertEqual(len(backend.submissions()), 3)

    def test_an_established_account_gets_ten_and_the_count_restarts_the_next_day(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            backend.age_everyone()
            statuses = [self.attempt(backend, ALICE, number)["statusCode"] for number in range(12)]
            self.assertEqual(statuses, [201] * 10 + [429] * 2)
            self.assertEqual(self.attempt(backend, BOB, 1)["body"]["error"], "handle_required")
            backend.now = (int(backend.now // 86400) + 1) * 86400 + 5
            self.assertEqual(self.attempt(backend, ALICE, 20)["statusCode"], 201)

    def test_the_limit_is_per_reader_and_does_not_use_the_voting_allowance(self) -> None:
        with ReaderBackend(actions_per_hour=3, submissions_per_day=3) as backend:
            ready(backend, ALICE, "quiet-fox")
            ready(backend, BOB, "loud-owl")
            for _ in range(3):
                backend.call(ALICE, "vote", {"subject": "item-one", "dimension": "up", "on": True})
            self.assertEqual(self.attempt(backend, ALICE, 1)["statusCode"], 201, "votes are a different bucket")
            self.assertEqual(self.attempt(backend, BOB, 2)["statusCode"], 201)

    def test_duplicates_and_invalid_urls_are_counted_or_free_as_documented(self) -> None:
        with ReaderBackend(submissions_per_day=3, actions_per_hour=120) as backend:
            ready(backend, ALICE, "quiet-fox")
            backend.age_everyone()
            self.assertEqual(self.attempt(backend, ALICE, 1)["statusCode"], 201)
            self.assertEqual(self.attempt(backend, ALICE, 1)["statusCode"], 409, "a duplicate counts against the day")
            self.assertEqual(submit(backend, url="nope")["statusCode"], 422, "a malformed request is refused before it is counted")
            self.assertEqual(self.attempt(backend, ALICE, 2)["statusCode"], 201)
            self.assertEqual(self.attempt(backend, ALICE, 3)["statusCode"], 429)


class VotesOnSubmissionsTests(unittest.TestCase):
    def test_a_pending_or_promoted_submission_can_be_voted_on_but_a_hidden_one_cannot(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            subject = submit(backend)["body"]["subject"]
            vote = {"subject": subject, "dimension": "up", "on": True}
            self.assertEqual(backend.call(BOB, "vote", vote)["statusCode"], 200)
            self.assertEqual(backend.call(BOB, "me", {"subjects": [subject]})["body"]["votes"], {subject: {"up": 1}})
            for state, expected in (("promoted", 200), ("hidden", 404)):
                backend.table("submission").update_item(Key={"id": subject}, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":s": state})
                self.assertEqual(backend.call(CAROL, "vote", vote)["statusCode"], expected, state)
            self.assertEqual(backend.call(CAROL, "vote", {"subject": "sub-" + "0" * 24, "dimension": "up", "on": True})["statusCode"], 404)


def row(number: int, **changes) -> dict:
    created = START_SECONDS - number * 60
    base = {
        "id": f"sub-{number:024x}", "canonicalUrl": f"https://example.com/{number}", "domain": "example.com", "title": f"Post {number}", "kind": "link",
        "readerId": str(uuid.UUID(int=1)), "state": "pending", "similar": [], "createdAt": __import__("reader_fixtures").iso_at(created),
    }
    return {**base, **changes}


class SubmissionSnapshotTests(unittest.TestCase):
    READER = str(uuid.UUID(int=1))
    PROFILES = [{"readerId": READER, "handle": "quiet-fox"}]

    def build(self, submissions, votes=(), published=None):
        return build_snapshot(
            list(votes), self.PROFILES, published_at=published or {}, now_seconds=START_SECONDS + 3600, settings=SnapshotSettings(dimensions=("real",)), submissions=submissions
        )

    def test_the_file_lists_visible_submissions_newest_first_and_leaves_hidden_ones_out(self) -> None:
        submissions = [row(1), row(2, state="hidden"), row(3, state="promoted", itemId="item-xyz", note="Nice"), row(4, similar=["sub-" + "a" * 24])]
        listed = self.build(submissions).submissions
        self.assertEqual(listed["generatedAt"], "2027-01-15T09:00:00Z")
        self.assertEqual([entry["title"] for entry in listed["submissions"]], ["Post 1", "Post 3", "Post 4"])
        by_title = {entry["title"]: entry for entry in listed["submissions"]}
        self.assertEqual(
            by_title["Post 3"],
            {
                "id": row(3)["id"], "url": "https://example.com/3", "domain": "example.com", "title": "Post 3", "kind": "link", "readerId": self.READER, "handle": "quiet-fox",
                "createdAt": row(3)["createdAt"], "state": "promoted", "similar": [], "note": "Nice", "itemId": "item-xyz",
            },
        )
        self.assertEqual(by_title["Post 4"]["similar"], ["sub-" + "a" * 24])
        self.assertNotIn("note", by_title["Post 1"])
        self.assertNotIn("sub-" + "0" * 23 + "2", json.dumps(listed))

    def test_the_newest_two_hundred_are_listed(self) -> None:
        listed = self.build([row(number) for number in range(SUBMISSIONS_LISTED + 5)]).submissions["submissions"]
        self.assertEqual(len(listed), SUBMISSIONS_LISTED)
        self.assertEqual(listed[0]["title"], "Post 0")
        self.assertEqual(listed[-1]["title"], f"Post {SUBMISSIONS_LISTED - 1}")

    def test_a_submission_whose_reader_has_no_profile_has_no_handle(self) -> None:
        listed = self.build([row(1, readerId=str(uuid.UUID(int=2)))]).submissions["submissions"]
        self.assertIsNone(listed[0]["handle"])

    def test_votes_on_visible_submissions_count_and_votes_on_hidden_ones_do_not(self) -> None:
        votes = [
            {"subjectKey": row(1)["id"], "readerId": "r2", "dimension": "up", "value": 1, "voterRole": "reader", "createdAt": "2027-01-15T07:30:00Z"},
            {"subjectKey": row(2)["id"], "readerId": "r2", "dimension": "up", "value": 1, "voterRole": "reader", "createdAt": "2027-01-15T07:30:00Z"},
        ]
        snapshot = self.build([row(1), row(2, state="hidden")], votes)
        self.assertEqual(list(snapshot.items["items"]), [row(1)["id"]])
        self.assertEqual(snapshot.items["items"][row(1)["id"]]["up"], 1)
        self.assertEqual([entry["subject"] for entry in snapshot.board["rising"]], [row(1)["id"]])

    def test_the_submitters_earn_karma_from_upvotes_and_used_it_reports_by_others(self) -> None:
        alice, bob, carol = (str(uuid.UUID(int=number)) for number in (11, 12, 13))
        profiles = [{"readerId": reader, "handle": handle} for reader, handle in ((alice, "alice-a"), (bob, "bob-b"), (carol, "carol-c"))]

        def vote(subject, reader, dimension):
            return {"subjectKey": subject, "readerId": reader, "dimension": dimension, "value": 1, "voterRole": "reader", "createdAt": "2027-01-15T07:00:00Z"}

        submissions = [row(1, readerId=alice, state="promoted", itemId="item-one"), row(2, readerId=bob), row(3, readerId=carol, state="hidden")]
        votes = [
            vote(row(1)["id"], bob, "up"), vote(row(1)["id"], alice, "up"), vote("item-one", bob, "up"), vote("item-one", carol, "used-it"),
            vote(row(2)["id"], alice, "up"), vote(row(3)["id"], alice, "up"), vote(row(3)["id"], bob, "used-it"),
        ]
        snapshot = build_snapshot(
            votes, profiles, published_at={"item-one": "2027-01-15T00:00:00Z"}, now_seconds=START_SECONDS + 3600,
            settings=SnapshotSettings(dimensions=("real",)), submissions=submissions,
        )
        self.assertEqual(snapshot.karma, {alice: 1 + 1 + 2, bob: 1, carol: 0}, "alice: bob's upvote on the submission and on the item, carol's used-it x2; her own vote does not count; hidden earns nothing")
        self.assertEqual([(entry["handle"], entry["karma"]) for entry in snapshot.readers["readers"]], [("alice-a", 4), ("bob-b", 1)])


class SubmissionTaskTests(unittest.TestCase):
    def test_the_task_writes_the_submissions_file_under_the_policy_and_it_carries_votes_and_karma(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            alice_reader = ready(backend, ALICE, "quiet-fox")
            subject = submit(backend, note="Good")["body"]["subject"]
            hidden = submit(backend, url="https://example.com/hidden", title="Hidden one")["body"]["subject"]
            backend.table("submission").update_item(Key={"id": hidden}, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":s": "hidden"})
            backend.call(BOB, "vote", {"subject": subject, "dimension": "up", "on": True})
            store = LocalDirectoryWriter(Path(directory))
            report = run_snapshot(backend, store, base_path="posts", review_signals=lambda *args: [])
            self.assertIn("posts/_data/reader/submissions.json", report.written)
            listed = json.loads(store.get("posts/_data/reader/submissions.json"))["submissions"]
            self.assertEqual([entry["id"] for entry in listed], [subject])
            self.assertEqual((listed[0]["handle"], listed[0]["readerId"], listed[0]["note"]), ("quiet-fox", alice_reader, "Good"))
            self.assertEqual(json.loads(store.get("posts/_data/reader/items.json"))["items"][subject]["up"], 1)
            readers = json.loads(store.get("posts/_data/reader/readers.json"))["readers"]
            self.assertEqual(readers, [{"readerId": alice_reader, "handle": "quiet-fox", "karma": 1}])
            profile = backend.table("profile").get_item(Key={"id": ALICE})["Item"]
            self.assertEqual(int(profile["karma"]), 1, "karma is materialised for /api/reader/me")

    def test_the_public_files_hold_no_site_subject_person_id_or_email(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            reader_id = ready(backend, ALICE, "quiet-fox")
            submit(backend, note="Worth a look", title="Fine title")
            backend.table("profile").update_item(Key={"id": ALICE}, UpdateExpression="SET email = :e, personId = :p", ExpressionAttributeValues={":e": "alice@example.test", ":p": str(uuid.UUID(int=99))})
            store = LocalDirectoryWriter(Path(directory))
            report = run_snapshot(backend, store, review_signals=lambda *args: [])
            files = {key: store.get(key) for key in report.written}
            self.assertEqual(scan_files(files, allowed_reader_ids=[reader_id]), {})
            self.assertNotIn(ALICE, "".join(body.decode() for body in files.values()))


class ReviewTests(unittest.TestCase):
    def test_signals_are_added_once_as_a_json_string_by_the_worker_not_the_request(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            ready(backend, ALICE, "quiet-fox")
            subject = submit(backend)["body"]["subject"]
            self.assertNotIn("reviewedAt", backend.submissions()[0], "the request path runs no checks")
            calls: list[tuple] = []

            def signals(title, note, url):
                calls.append((title, note, url))
                return [{"source": "humanus", "policy": "promotion", "detector": "buy-now", "severity": "warn", "excerpt": "buy now"}]

            store = LocalDirectoryWriter(Path(directory))
            report = run_snapshot(backend, store, review_signals=signals)
            run_snapshot(backend, store, review_signals=signals)
            self.assertEqual(report.to_dict()["review"], {"submissions": 1, "error": None})
            self.assertEqual(calls, [("A small tool", None, CANONICAL)], "reviewed once")
            (stored,) = backend.submissions()
            self.assertIsInstance(stored["signals"], str)
            self.assertEqual(parsed_signals(stored["signals"])[0]["detector"], "buy-now")
            self.assertEqual((stored["id"], stored["extractionState"]), (subject, "pending"), "extraction is a later step and is left alone")
            self.assertTrue(stored["reviewedAt"])

    def test_a_failing_check_is_reported_and_never_stops_the_numbers(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            ready(backend, ALICE, "quiet-fox")
            submit(backend)

            def broken(*args):
                raise RuntimeError("humanus is down")

            store = LocalDirectoryWriter(Path(directory))
            report = run_snapshot(backend, store, review_signals=broken)
            self.assertEqual(report.review.error, "RuntimeError")
            self.assertEqual(len(json.loads(store.get("_data/reader/submissions.json"))["submissions"]), 1)

    def test_humanus_rules_flag_spam_and_chatbot_text_and_shortened_links(self) -> None:
        found = submission_signals("BUY NOW!!! GREAT DEAL TODAY HERE", "Certainly! Click here to earn $500 a day.", "https://bit.ly/abc")
        detectors = {signal["detector"] for signal in found}
        self.assertTrue({"url-shortener", "buy-now", "click-here", "earn-money", "exclamations", "capitals", "exclamation-openers"} <= detectors, detectors)
        self.assertEqual({signal["source"] for signal in found}, {"humanus", "papyrus"})
        self.assertTrue(all(len(signal["excerpt"]) <= 80 for signal in found))
        self.assertEqual(submission_signals("A small tool for reading logs", "I used it on a project last week.", "https://example.com/tool"), [])

    def test_the_default_checks_run_for_real_in_the_task(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            ready(backend, ALICE, "quiet-fox")
            submit(backend, title="Buy now and earn $100 a day", url="https://bit.ly/zzz")
            run_snapshot(backend, LocalDirectoryWriter(Path(directory)))
            (stored,) = backend.submissions()
            detectors = {signal["detector"] for signal in parsed_signals(stored["signals"])}
            self.assertTrue({"buy-now", "earn-money", "url-shortener"} <= detectors, detectors)


class RetirementOfSubmissionsTests(unittest.TestCase):
    def names(self):
        from reader_fixtures import TABLE_NAMES
        from papyrus_content.reader_steering.retirement import ReaderTableNames

        return ReaderTableNames(profile=TABLE_NAMES["profile"], handle=TABLE_NAMES["handle"], vote=TABLE_NAMES["vote"], state=TABLE_NAMES["rate"], submission=TABLE_NAMES["submission"])

    def apply(self, backend, *records):
        from papyrus_content.reader_steering.retirement import RetirementReport, apply_retirements

        apply_retirements(backend.resource, self.names(), records, RetirementReport())

    def test_a_deleted_reader_takes_their_submissions_with_them(self) -> None:
        from papyrus_content.reader_steering.retirement import RetiredSubject

        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            ready(backend, BOB, "loud-owl")
            submit(backend, ALICE, url="https://example.com/a", title="Alice's")
            submit(backend, BOB, url="https://example.com/b", title="Bob's")
            self.apply(backend, RetiredSubject(ALICE, "deleted", None, ""))
            self.assertEqual([entry["title"] for entry in backend.submissions()], ["Bob's"])

    def test_a_merged_reader_s_submissions_move_to_the_survivor(self) -> None:
        from papyrus_content.reader_steering.retirement import RetiredSubject

        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            bob_reader = ready(backend, BOB, "loud-owl")
            submit(backend, ALICE, url="https://example.com/a", title="Alice's")
            self.apply(backend, RetiredSubject(ALICE, "merged", BOB, ""))
            self.assertEqual([(entry["title"], entry["readerId"]) for entry in backend.submissions()], [("Alice's", bob_reader)])


if __name__ == "__main__":
    unittest.main()
