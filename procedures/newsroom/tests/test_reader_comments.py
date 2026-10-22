"""Reader comments: posting, validation, one level of replies, the edit window, delete stubs, limits, the snapshot and steering context."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content.projection.writers import LocalDirectoryWriter  # noqa: E402
from papyrus_content.reader_steering.retirement import ReaderTableNames, RetiredSubject, RetirementReport, apply_retirements  # noqa: E402
from papyrus_content.reader_steering.review import parsed_signals  # noqa: E402
from papyrus_content.reader_steering.snapshot import SnapshotSettings, build_snapshot, comments_key  # noqa: E402
from reader_fixtures import TABLE_NAMES, ReaderBackend, run_snapshot, subject_for  # noqa: E402
from reader_privacy import scan_files  # noqa: E402

ALICE, BOB, CAROL = subject_for("alice"), subject_for("bob"), subject_for("carol")
ITEM = "item-one"


def ready(backend: ReaderBackend, subject: str, handle: str) -> str:
    backend.call(subject, "handle", {"handle": handle})
    return backend.call(subject, "me")["body"]["readerId"]


def comment(backend: ReaderBackend, who: str = ALICE, body: str = "Worth reading.", subject: str = ITEM, **extra) -> dict:
    return backend.call(who, "comment", {"subject": subject, "body": body, **extra})


class PostTests(unittest.TestCase):
    def test_a_comment_is_stored_visible_with_the_readers_public_id_only(self) -> None:
        with ReaderBackend() as backend:
            reader_id = ready(backend, ALICE, "quiet-fox")
            answer = comment(backend, body="  Worth reading.\r\nTwice.  ")
            self.assertEqual(answer["statusCode"], 201)
            self.assertEqual({key: answer["body"][key] for key in ("subject", "parent", "body", "ratingContext")}, {"subject": ITEM, "parent": None, "body": "Worth reading.\nTwice.", "ratingContext": None})
            self.assertRegex(answer["body"]["id"], r"^cmt-[0-9a-f]{32}$")
            (stored,) = backend.comments()
            self.assertEqual((stored["subjectKey"], stored["readerId"], stored["state"], stored["__typename"]), (ITEM, reader_id, "visible", "ReaderComment"))
            self.assertNotIn("parentId", stored)
            self.assertNotIn(ALICE, json.dumps(answer) + json.dumps(stored, default=str))

    def test_a_handle_is_needed_and_banned_or_limited_readers_cannot_comment(self) -> None:
        with ReaderBackend() as backend:
            answer = comment(backend)
            self.assertEqual((answer["statusCode"], answer["body"]["error"]), (422, "handle_required"))
            ready(backend, ALICE, "quiet-fox")
            for state, error in (("banned", "reader_banned"), ("limited", "reader_limited")):
                backend.table("profile").update_item(Key={"id": ALICE}, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":s": state})
                self.assertEqual((comment(backend)["statusCode"], comment(backend)["body"]["error"]), (403, error))
            self.assertEqual(backend.comments(), [])

    def test_the_subject_must_be_a_published_item_or_a_visible_submission(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            backend.publish("draft", status="draft")
            for subject in ("missing", "draft", "sub-" + "0" * 24):
                self.assertEqual(comment(backend, subject=subject)["body"]["error"], "unknown_subject", subject)
            for bad in ("", "has#hash", "x" * 201, None, 3):
                self.assertEqual(comment(backend, subject=bad)["body"]["error"], "invalid_subject", bad)
            link = backend.call(ALICE, "submit", {"url": "https://example.com/a", "title": "A"})["body"]["subject"]
            self.assertEqual(comment(backend, subject=link)["statusCode"], 201)
            backend.table("submission").update_item(Key={"id": link}, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":s": "hidden"})
            self.assertEqual(comment(backend, subject=link)["statusCode"], 404)

    def test_a_comment_schedules_a_snapshot_run(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            comment(backend)
            self.assertEqual(len(backend.schedules()), 1)


class ValidationTests(unittest.TestCase):
    def test_text_rules(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            backend.age_everyone()
            refused = {
                "": "invalid_body", "   \n ": "invalid_body", 7: "invalid_body", None: "invalid_body", "bell\x07": "invalid_body", "x" * 2001: "body_too_long",
                "a https://a.example b http://b.example c www.c.example d HTTPS://D.example": "too_many_links", "write to me@example.test": "invalid_body",
            }
            for body, error in refused.items():
                answer = comment(backend, body=body)
                self.assertEqual((answer["statusCode"], answer["body"]["error"]), (422, error), repr(body)[:40])
            self.assertEqual(backend.comments(), [])
            self.assertEqual(comment(backend, body="x" * 2000)["statusCode"], 201, "2000 characters is allowed")
            self.assertEqual(comment(backend, body="ü" * 2000)["statusCode"], 201, "the cap counts characters, not bytes")
            self.assertEqual(comment(backend, body="https://a.example http://b.example www.c.example")["statusCode"], 201, "three links are allowed")
            self.assertEqual(comment(backend, body="Tabs\tand\nnewlines are fine")["statusCode"], 201)

    def test_markup_is_stored_as_the_text_it_is(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            comment(backend, body='<img src=x onerror="alert(1)"> & <b>bold</b>')
            self.assertEqual(backend.comments()[0]["body"], '<img src=x onerror="alert(1)"> & <b>bold</b>')

    def test_the_limits_come_from_the_publication(self) -> None:
        with ReaderBackend(comments_per_hour=300, comment_maximum_length=10, comment_maximum_links=0) as backend:
            ready(backend, ALICE, "quiet-fox")
            self.assertEqual(comment(backend, body="x" * 11)["body"]["error"], "body_too_long")
            self.assertEqual(comment(backend, body="www.a.test")["body"]["error"], "too_many_links")

    def test_unknown_fields_are_refused(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            self.assertEqual(comment(backend, readerId="someone")["body"]["error"], "invalid_comment")


class ThreadingTests(unittest.TestCase):
    def test_one_level_of_replies(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            ready(backend, BOB, "loud-owl")
            top = comment(backend)["body"]["id"]
            reply = comment(backend, BOB, "Agreed.", parent=top)
            self.assertEqual((reply["statusCode"], reply["body"]["parent"]), (201, top))
            self.assertEqual(backend.table("comment").get_item(Key={"id": reply["body"]["id"]})["Item"]["parentId"], top)
            nested = comment(backend, ALICE, "Thanks.", parent=reply["body"]["id"])
            self.assertEqual((nested["statusCode"], nested["body"]["error"]), (422, "invalid_parent"), "replies do not nest")

    def test_the_parent_must_exist_on_the_same_subject_and_be_visible(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            top = comment(backend)["body"]["id"]
            for parent in ("cmt-" + "0" * 32, "nope", 5, "cmt-" + "g" * 32):
                self.assertEqual(comment(backend, parent=parent)["body"]["error"], "invalid_parent", parent)
            self.assertEqual(comment(backend, subject="item-two", parent=top)["body"]["error"], "invalid_parent", "another item")
            for state in ("hidden", "deleted"):
                backend.table("comment").update_item(Key={"id": top}, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":s": state})
                self.assertEqual(comment(backend, parent=top)["body"]["error"], "invalid_parent", state)


class RatingContextTests(unittest.TestCase):
    def test_a_comment_can_explain_the_readers_own_current_rating(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            backend.call(ALICE, "rating", {"subject": ITEM, "dimension": "real", "value": 4})
            answer = comment(backend, body="The benchmarks held up.", ratingContext={"dimension": "real", "value": 4})
            self.assertEqual((answer["statusCode"], answer["body"]["ratingContext"]), (201, {"dimension": "real", "value": 4}))
            (stored,) = backend.comments()
            self.assertEqual(json.loads(stored["ratingContext"]), {"dimension": "real", "value": 4})
            backend.call(ALICE, "vote", {"subject": ITEM, "dimension": "up", "on": True})
            self.assertEqual(comment(backend, ratingContext={"dimension": "up", "value": 1})["statusCode"], 201)

    def test_a_comment_cannot_claim_a_rating_the_reader_did_not_give(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            backend.call(ALICE, "rating", {"subject": ITEM, "dimension": "real", "value": 4})
            for context, error in (
                ({"dimension": "real", "value": 5}, "rating_context_mismatch"), ({"dimension": "useful", "value": 4}, "rating_context_mismatch"),
                ({"dimension": "up", "value": 1}, "rating_context_mismatch"), ({"dimension": "nope", "value": 4}, "invalid_rating_context"),
                ({"dimension": "real"}, "invalid_rating_context"), ({"dimension": "real", "value": True}, "invalid_rating_context"),
                ({"dimension": "real", "value": "4"}, "invalid_rating_context"), ("real", "invalid_rating_context"), ({"dimension": "real", "value": 4, "extra": 1}, "invalid_rating_context"),
            ):
                answer = comment(backend, ratingContext=context)
                self.assertEqual((answer["statusCode"], answer["body"]["error"]), (422, error), context)
            self.assertEqual(backend.comments(), [])

    def test_a_reply_does_not_explain_a_rating(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            backend.call(ALICE, "rating", {"subject": ITEM, "dimension": "real", "value": 4})
            top = comment(backend)["body"]["id"]
            self.assertEqual(comment(backend, parent=top, ratingContext={"dimension": "real", "value": 4})["body"]["error"], "invalid_rating_context")


class EditAndDeleteTests(unittest.TestCase):
    def edit(self, backend, who, comment_id, body="Edited."):
        return backend.call(who, "comment-edit", {"id": comment_id, "body": body})

    def delete(self, backend, who, comment_id):
        return backend.call(who, "comment-delete", {"id": comment_id})

    def test_the_author_edits_for_ten_minutes_and_the_comment_is_marked_edited(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            comment_id = comment(backend)["body"]["id"]
            backend.now += 599
            answer = self.edit(backend, ALICE, comment_id, "Better words.")
            self.assertEqual((answer["statusCode"], answer["body"]["body"]), (200, "Better words."))
            (stored,) = backend.comments()
            self.assertEqual((stored["body"], bool(stored["editedAt"]), stored["state"]), ("Better words.", True, "visible"))
            backend.now += 2
            late = self.edit(backend, ALICE, comment_id)
            self.assertEqual((late["statusCode"], late["body"]["error"]), (403, "edit_window_closed"))
            self.assertEqual(backend.comments()[0]["body"], "Better words.")

    def test_the_edit_window_is_the_publications(self) -> None:
        with ReaderBackend(comment_edit_minutes=1) as backend:
            ready(backend, ALICE, "quiet-fox")
            comment_id = comment(backend)["body"]["id"]
            backend.now += 61
            self.assertEqual(self.edit(backend, ALICE, comment_id)["body"]["error"], "edit_window_closed")

    def test_an_edit_follows_the_same_text_rules_and_only_the_author_may_edit(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            ready(backend, BOB, "loud-owl")
            comment_id = comment(backend)["body"]["id"]
            for body, error in (("", "invalid_body"), ("x" * 2001, "body_too_long"), ("me@example.test", "invalid_body")):
                self.assertEqual(self.edit(backend, ALICE, comment_id, body)["body"]["error"], error)
            self.assertEqual(self.edit(backend, BOB, comment_id)["statusCode"], 404, "someone else's comment looks missing")
            self.assertEqual(self.edit(backend, ALICE, "cmt-" + "0" * 32)["statusCode"], 404)
            self.assertEqual(backend.call(ALICE, "comment-edit", {"id": comment_id, "body": "x", "parent": "y"})["body"]["error"], "invalid_comment")
            self.assertEqual(backend.comments()[0]["body"], "Worth reading.")

    def test_an_edit_asks_for_a_new_review(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            ready(backend, ALICE, "quiet-fox")
            comment_id = comment(backend)["body"]["id"]
            run_snapshot(backend, LocalDirectoryWriter(Path(directory)))
            self.assertTrue(backend.comments()[0]["reviewedAt"])
            self.edit(backend, ALICE, comment_id, "Buy now at a great price")
            self.assertNotIn("reviewedAt", backend.comments()[0])
            run_snapshot(backend, LocalDirectoryWriter(Path(directory)))
            self.assertIn("buy-now", {signal["detector"] for signal in parsed_signals(backend.comments()[0]["signals"])})

    def test_delete_clears_the_text_and_is_idempotent(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            ready(backend, BOB, "loud-owl")
            comment_id = comment(backend)["body"]["id"]
            self.assertEqual(self.delete(backend, BOB, comment_id)["statusCode"], 404)
            for _ in range(2):
                self.assertEqual(self.delete(backend, ALICE, comment_id)["body"], {"id": comment_id, "state": "deleted"})
            (stored,) = backend.comments()
            self.assertEqual((stored["state"], stored["body"], bool(stored["deletedAt"])), ("deleted", "", True))
            self.assertEqual(self.edit(backend, ALICE, comment_id)["body"]["error"], "comment_deleted")

    def test_a_hidden_comment_cannot_be_edited_or_deleted_by_its_author(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            comment_id = comment(backend)["body"]["id"]
            backend.table("comment").update_item(Key={"id": comment_id}, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":s": "hidden"})
            self.assertEqual(self.edit(backend, ALICE, comment_id)["statusCode"], 404)
            self.assertEqual(self.delete(backend, ALICE, comment_id)["statusCode"], 404)
            self.assertEqual(backend.comments()[0]["state"], "hidden")

    def test_a_banned_reader_cannot_delete_either(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            comment_id = comment(backend)["body"]["id"]
            backend.table("profile").update_item(Key={"id": ALICE}, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":s": "banned"})
            self.assertEqual(self.delete(backend, ALICE, comment_id)["body"]["error"], "reader_banned")


class RateLimitTests(unittest.TestCase):
    def test_thirty_an_hour_and_a_third_of_that_for_a_new_account(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            statuses = [comment(backend, body=f"Comment {number}")["statusCode"] for number in range(12)]
            self.assertEqual(statuses, [201] * 10 + [429] * 2, "a new account gets 30 // 3 = 10")
            backend.age_everyone()
            statuses = [comment(backend, body=f"Later {number}")["statusCode"] for number in range(32)]
            self.assertEqual(statuses, [201] * 30 + [429] * 2)
            refused = comment(backend)
            self.assertEqual((refused["body"]["error"], 0 < refused["body"]["retryAfter"] <= 3600), ("rate_limited", True))
            backend.now += 3600
            self.assertEqual(comment(backend)["statusCode"], 201)

    def test_edits_count_and_votes_do_not_share_the_bucket(self) -> None:
        with ReaderBackend(comments_per_hour=3, actions_per_hour=120) as backend:
            ready(backend, ALICE, "quiet-fox")
            backend.age_everyone()
            first = comment(backend)["body"]["id"]
            backend.call(ALICE, "vote", {"subject": ITEM, "dimension": "up", "on": True})
            self.assertEqual(backend.call(ALICE, "comment-edit", {"id": first, "body": "One."})["statusCode"], 200)
            self.assertEqual(backend.call(ALICE, "comment-edit", {"id": first, "body": "Two."})["statusCode"], 200)
            self.assertEqual(backend.call(ALICE, "comment-edit", {"id": first, "body": "Three."})["statusCode"], 429)

    def test_a_refused_comment_writes_nothing(self) -> None:
        with ReaderBackend(comments_per_hour=3) as backend:
            ready(backend, ALICE, "quiet-fox")
            comment(backend)
            self.assertEqual(comment(backend)["statusCode"], 429)
            self.assertEqual(len(backend.comments()), 1)


def row(number: int, subject: str = ITEM, **changes) -> dict:
    base = {
        "id": f"cmt-{number:032x}", "subjectKey": subject, "readerId": str(uuid.UUID(int=1)), "body": f"Comment {number}", "state": "visible",
        "createdAt": f"2027-01-15T0{number % 10}:00:00.000Z",
    }
    return {**base, **changes}


class SnapshotShapeTests(unittest.TestCase):
    PROFILES = [{"readerId": str(uuid.UUID(int=1)), "handle": "quiet-fox"}]

    def build(self, comments, votes=(), published=None):
        published = published if published is not None else {ITEM: "2027-01-14T00:00:00Z"}
        return build_snapshot(list(votes), self.PROFILES, published_at=published, now_seconds=1_800_000_000.0, settings=SnapshotSettings(dimensions=("real",)), comments=comments)

    def test_visible_comments_oldest_first_with_the_documented_fields(self) -> None:
        snapshot = self.build([row(2, parentId=row(1)["id"], editedAt="2027-01-15T05:00:00.000Z"), row(1), row(3, state="hidden"), row(4, state="deleted", body="")])
        payload = snapshot.comments[ITEM]
        self.assertEqual(set(payload), {"generatedAt", "subject", "comments"})
        self.assertEqual(payload["subject"], ITEM)
        self.assertEqual(
            payload["comments"],
            [
                {"id": row(1)["id"], "readerId": str(uuid.UUID(int=1)), "handle": "quiet-fox", "body": "Comment 1", "createdAt": row(1)["createdAt"], "parent": None, "edited": False},
                {"id": row(2)["id"], "readerId": str(uuid.UUID(int=1)), "handle": "quiet-fox", "body": "Comment 2", "createdAt": row(2)["createdAt"], "parent": row(1)["id"], "edited": True},
            ],
        )
        text = json.dumps(snapshot.comments)
        self.assertNotIn("Comment 3", text)
        self.assertNotIn(row(3)["id"], text, "a hidden comment without replies leaves no trace")
        self.assertNotIn(row(4)["id"], text, "a deleted comment without replies leaves no trace")

    def test_counts_are_in_items_even_for_a_subject_nobody_voted_on(self) -> None:
        snapshot = self.build([row(1), row(2), row(3, state="hidden")])
        self.assertEqual(snapshot.items["items"][ITEM]["comments"], 2)
        self.assertEqual((snapshot.items["items"][ITEM]["up"], snapshot.items["items"][ITEM]["usedIt"]), (0, 0))
        voted = self.build([], votes=[{"subjectKey": ITEM, "readerId": "r", "dimension": "up", "value": 1, "voterRole": "reader", "createdAt": "2027-01-15T00:00:00Z"}])
        self.assertEqual(voted.items["items"][ITEM]["comments"], 0)

    def test_a_deleted_or_hidden_top_level_comment_with_visible_replies_becomes_a_stub(self) -> None:
        for state in ("deleted", "hidden"):
            snapshot = self.build([row(1, state=state, body=""), row(2, parentId=row(1)["id"])])
            entries = snapshot.comments[ITEM]["comments"]
            self.assertEqual(entries[0], {"id": row(1)["id"], "stub": True, "parent": None, "createdAt": row(1)["createdAt"]}, state)
            self.assertEqual(entries[1]["parent"], row(1)["id"])
            self.assertEqual(snapshot.items["items"][ITEM]["comments"], 1, "a stub is not counted")
            self.assertNotIn("readerId", json.dumps(entries[0]))

    def test_comments_on_unpublished_subjects_and_unsafe_file_names_are_left_out(self) -> None:
        snapshot = self.build([row(1), row(2, subject="gone"), row(3, subject="../escape")], published={ITEM: None, "gone2": None, "../escape": None})
        self.assertEqual(list(snapshot.comments), [ITEM])
        self.assertEqual((comments_key("../escape"), comments_key(".hidden"), comments_key("a/b"), comments_key("item:one.v2")), (None, None, None, "_data/reader/comments/item:one.v2.json"))

    def test_the_number_of_comments_is_not_capped_in_the_file(self) -> None:
        entries = self.build([row(number, createdAt=f"2027-01-{15 + number // 20:02d}T{number % 20:02d}:00:00.000Z") for number in range(1, 150)]).comments[ITEM]["comments"]
        self.assertEqual(len(entries), 149)


class SnapshotTaskTests(unittest.TestCase):
    def test_a_file_per_subject_under_the_base_path_that_is_rewritten_only_when_it_changes(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            reader_id = ready(backend, ALICE, "quiet-fox")
            first = comment(backend)["body"]["id"]
            comment(backend, ALICE, "Second.", subject="item-two")
            writer = LocalDirectoryWriter(Path(directory))
            purged: list[list[str]] = []
            report = run_snapshot(backend, writer, base_path="posts", invalidate=lambda keys: purged.append(list(keys)) or keys)
            self.assertEqual(report.comment_files, 2)
            self.assertIn("posts/_data/reader/comments/item-one.json", report.written)
            body = json.loads(writer.get("posts/_data/reader/comments/item-one.json"))
            self.assertEqual([(entry["id"], entry["handle"], entry["readerId"]) for entry in body["comments"]], [(first, "quiet-fox", reader_id)])
            items = json.loads(writer.get("posts/_data/reader/items.json"))["items"]
            self.assertEqual((items[ITEM]["comments"], items["item-two"]["comments"]), (1, 1))
            backend.now += 120
            again = run_snapshot(backend, writer, base_path="posts", invalidate=lambda keys: purged.append(list(keys)) or keys)
            self.assertEqual(again.comment_files, 0, "nothing changed, so no comment file is written or purged")
            self.assertFalse([key for key in again.written if "comments/" in key])
            comment(backend, ALICE, "Third.")
            third = run_snapshot(backend, writer, base_path="posts")
            self.assertEqual([key for key in third.written if "comments/" in key], ["posts/_data/reader/comments/item-one.json"])

    def test_hidden_and_deleted_comments_leave_the_next_snapshot_and_the_file_is_emptied(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            ready(backend, ALICE, "quiet-fox")
            comment_id = comment(backend)["body"]["id"]
            writer = LocalDirectoryWriter(Path(directory))
            run_snapshot(backend, writer)
            self.assertEqual(len(json.loads(writer.get("_data/reader/comments/item-one.json"))["comments"]), 1)
            backend.call(ALICE, "comment-delete", {"id": comment_id})
            backend.now += 120
            report = run_snapshot(backend, writer)
            emptied = json.loads(writer.get("_data/reader/comments/item-one.json"))
            self.assertEqual((emptied["comments"], emptied["subject"]), ([], ITEM))
            self.assertIn("_data/reader/comments/item-one.json", report.written)
            self.assertNotIn("Worth reading", writer.get("_data/reader/comments/item-one.json").decode())
            self.assertEqual(json.loads(writer.get("_data/reader/items.json"))["items"].get(ITEM, {"comments": 0})["comments"], 0)
            backend.now += 120
            self.assertEqual(run_snapshot(backend, writer).comment_files, 0, "an emptied file is not rewritten again")

    def test_a_thread_keeps_a_stub_for_a_deleted_parent(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            ready(backend, ALICE, "quiet-fox")
            ready(backend, BOB, "loud-owl")
            top = comment(backend)["body"]["id"]
            backend.now += 5
            comment(backend, BOB, "A reply.", parent=top)
            backend.call(ALICE, "comment-delete", {"id": top})
            writer = LocalDirectoryWriter(Path(directory))
            run_snapshot(backend, writer)
            entries = json.loads(writer.get("_data/reader/comments/item-one.json"))["comments"]
            self.assertEqual([("stub" in entry, entry["parent"]) for entry in entries], [(True, None), (False, top)])

    def test_the_comment_files_hold_no_site_subject_person_id_or_email(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            reader_id = ready(backend, ALICE, "quiet-fox")
            backend.table("profile").update_item(Key={"id": ALICE}, UpdateExpression="SET email = :e, personId = :p", ExpressionAttributeValues={":e": "alice@example.test", ":p": str(uuid.UUID(int=99))})
            backend.call(ALICE, "rating", {"subject": ITEM, "dimension": "real", "value": 4})
            comment(backend, body="Fine.", ratingContext={"dimension": "real", "value": 4})
            writer = LocalDirectoryWriter(Path(directory))
            report = run_snapshot(backend, writer)
            files = {key: writer.get(key) for key in report.written}
            self.assertEqual(scan_files(files, allowed_reader_ids=[reader_id]), {})
            text = writer.get("_data/reader/comments/item-one.json").decode()
            self.assertNotIn("ratingContext", text, "the rating a comment explains is not public next to the reader")
            self.assertNotIn("signals", text)

    def test_signals_are_added_to_new_comments_by_the_worker(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            ready(backend, ALICE, "quiet-fox")
            comment(backend, body="Click here to earn $50 a day")
            self.assertNotIn("reviewedAt", backend.comments()[0])
            report = run_snapshot(backend, LocalDirectoryWriter(Path(directory)))
            self.assertEqual(report.review.comments, 1)
            self.assertTrue({"click-here", "earn-money"} <= {signal["detector"] for signal in parsed_signals(backend.comments()[0]["signals"])})

    def test_a_broken_check_never_stops_the_files(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            ready(backend, ALICE, "quiet-fox")
            comment(backend)

            def broken(_text):
                raise RuntimeError("down")

            writer = LocalDirectoryWriter(Path(directory))
            report = run_snapshot(backend, writer, comment_signals=broken)
            self.assertEqual(report.review.error, "RuntimeError")
            self.assertEqual(len(json.loads(writer.get("_data/reader/comments/item-one.json"))["comments"]), 1)


class RetirementTests(unittest.TestCase):
    def names(self) -> ReaderTableNames:
        return ReaderTableNames(profile=TABLE_NAMES["profile"], handle=TABLE_NAMES["handle"], vote=TABLE_NAMES["vote"], state=TABLE_NAMES["rate"], submission=TABLE_NAMES["submission"], comment=TABLE_NAMES["comment"])

    def test_a_deleted_readers_comments_are_deleted_and_a_merged_readers_move_to_the_survivor(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            bob_reader = ready(backend, BOB, "loud-owl")
            ready(backend, CAROL, "plain-cat")
            comment(backend, ALICE, "Alice's.")
            comment(backend, CAROL, "Carol's.")
            apply_retirements(backend.resource, self.names(), [RetiredSubject(ALICE, "merged", BOB, "")], RetirementReport())
            self.assertEqual(sorted((entry["body"], entry["readerId"]) for entry in backend.comments())[0], ("Alice's.", bob_reader))
            apply_retirements(backend.resource, self.names(), [RetiredSubject(CAROL, "deleted", None, "")], RetirementReport())
            self.assertEqual([entry["body"] for entry in backend.comments()], ["Alice's."])


if __name__ == "__main__":
    unittest.main()
