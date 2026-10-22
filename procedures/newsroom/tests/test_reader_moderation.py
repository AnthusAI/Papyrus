"""Reader moderation: reports, the transitions staff apply, undo, bans, promotion and what leaves the public files."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content.projection.writers import LocalDirectoryWriter  # noqa: E402
from reader_fixtures import ReaderBackend, reader_handler, run_snapshot, subject_for  # noqa: E402

ALICE, BOB, CAROL = subject_for("alice"), subject_for("bob"), subject_for("carol")
ITEM = "item-one"
SUBMISSION, COMMENT, READER = "submission", "comment", "reader"


def ready(backend: ReaderBackend, subject: str, handle: str) -> str:
    backend.call(subject, "handle", {"handle": handle})
    return backend.call(subject, "me")["body"]["readerId"]


def submit(backend: ReaderBackend, who: str = ALICE, url: str = "https://example.com/a", title: str = "A small tool") -> str:
    return backend.call(who, "submit", {"url": url, "title": title})["body"]["subject"]


def comment(backend: ReaderBackend, who: str = ALICE, body: str = "Worth reading.", subject: str = ITEM, **extra) -> str:
    return backend.call(who, "comment", {"subject": subject, "body": body, **extra})["body"]["id"]


def row(backend: ReaderBackend, table: str, key: str) -> dict:
    return backend.table(table).get_item(Key={"id": key})["Item"]


def set_state(backend: ReaderBackend, table: str, key: str, state: str) -> None:
    backend.table(table).update_item(Key={"id": key}, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":s": state})


class ReportTests(unittest.TestCase):
    def test_a_report_puts_the_item_back_in_the_queue_once_per_reader(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            bob_reader = ready(backend, BOB, "loud-owl")
            ready(backend, CAROL, "plain-cat")
            subject = submit(backend)
            backend.staff_call("approve", SUBMISSION, subject)
            self.assertEqual(row(backend, "submission", subject)["moderation"], "approved")
            answer = backend.call(BOB, "report", {"target": subject, "reason": "Looks like an advert."})
            self.assertEqual((answer["statusCode"], answer["body"]), (200, {"reported": True}))
            stored = row(backend, "submission", subject)
            self.assertEqual((stored["moderation"], int(stored["reportCount"])), ("new", 1))
            (report,) = backend.reports()
            self.assertEqual((report["reporterReaderId"], report["target"], report["targetType"], report["state"], report["reason"]), (bob_reader, subject, SUBMISSION, "open", "Looks like an advert."))
            self.assertRegex(report["id"], r"^rep-[0-9a-f]{24}$")
            backend.call(BOB, "report", {"target": subject, "reason": "Again."})
            self.assertEqual(int(row(backend, "submission", subject)["reportCount"]), 1, "the same reader reports once")
            backend.call(CAROL, "report", {"target": subject, "reason": "Spam."})
            self.assertEqual((int(row(backend, "submission", subject)["reportCount"]), len(backend.reports())), (2, 2))

    def test_comments_can_be_reported_and_the_report_is_closed_when_a_moderator_decides(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            ready(backend, BOB, "loud-owl")
            comment_id = comment(backend)
            backend.call(BOB, "report", {"target": comment_id, "reason": "Rude."})
            self.assertEqual(backend.reports()[0]["targetType"], COMMENT)
            self.assertEqual(backend.staff_call("hide", COMMENT, comment_id, reason="Rude")["status"], "ok")
            self.assertEqual([report["state"] for report in backend.reports()], ["closed"])
            self.assertTrue(backend.reports()[0]["closedAt"])

    def test_what_can_be_reported_and_how(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            ready(backend, BOB, "loud-owl")
            subject = submit(backend)
            hidden = comment(backend)
            set_state(backend, "comment", hidden, "hidden")
            deleted = comment(backend, body="Another")
            set_state(backend, "comment", deleted, "deleted")
            cases = [
                ({"target": "item-one", "reason": "x"}, 422, "invalid_target"), ({"target": ALICE, "reason": "x"}, 422, "invalid_target"), ({"target": 7, "reason": "x"}, 422, "invalid_target"),
                ({"target": backend.call(ALICE, "me")["body"]["readerId"], "reason": "x"}, 422, "invalid_target"),
                ({"target": subject, "reason": ""}, 422, "invalid_reason"), ({"target": subject, "reason": "  "}, 422, "invalid_reason"), ({"target": subject, "reason": "x" * 501}, 422, "invalid_reason"),
                ({"target": subject, "reason": "bell\x07"}, 422, "invalid_reason"), ({"target": subject}, 422, "invalid_reason"), ({"target": subject, "reason": "x", "extra": 1}, 422, "invalid_report"),
                ({"target": "sub-" + "0" * 24, "reason": "x"}, 404, "unknown_target"), ({"target": "cmt-" + "0" * 32, "reason": "x"}, 404, "unknown_target"),
                ({"target": hidden, "reason": "x"}, 404, "unknown_target"), ({"target": deleted, "reason": "x"}, 404, "unknown_target"),
            ]
            for payload, status, error in cases:
                answer = backend.call(BOB, "report", payload)
                self.assertEqual((answer["statusCode"], answer["body"]["error"]), (status, error), payload)
            self.assertEqual(backend.reports(), [])

    def test_twenty_reports_a_day_and_a_third_for_a_new_account(self) -> None:
        with ReaderBackend(submissions_per_day=100, comments_per_hour=500) as backend:
            ready(backend, ALICE, "quiet-fox")
            backend.age_everyone()
            ids = [comment(backend, body=f"Comment {number}") for number in range(25)]
            ready(backend, BOB, "loud-owl")
            statuses = [backend.call(BOB, "report", {"target": target, "reason": "Spam"})["statusCode"] for target in ids]
            self.assertEqual(statuses, [200] * 6 + [429] * 19, "BOB is a new account: 20 // 3 = 6 a day")
            refused = backend.call(BOB, "report", {"target": ids[-1], "reason": "Spam"})
            self.assertEqual((refused["body"]["error"], 0 < refused["body"]["retryAfter"] <= 86400), ("rate_limited", True))
            backend.age_everyone()
            statuses = [backend.call(BOB, "report", {"target": target, "reason": "Spam"})["statusCode"] for target in ids]
            self.assertEqual(statuses, [200] * 20 + [429] * 5, "the next day the count starts over; repeating a report counts too")

    def test_a_banned_reader_cannot_report(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            reader_id = ready(backend, BOB, "loud-owl")
            subject = submit(backend)
            backend.staff_call("ban", READER, reader_id)
            self.assertEqual(backend.call(BOB, "report", {"target": subject, "reason": "x"})["body"]["error"], "reader_banned")


class TransitionTests(unittest.TestCase):
    def test_only_editors_and_admins_may_moderate(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            subject = submit(backend)
            for groups in ((), ("reader",), ("author",), ("Editors",)):
                receipt = backend.staff_call("hide", SUBMISSION, subject, groups=groups)
                self.assertEqual((receipt["status"], receipt["error"]), ("refused", "not_staff"), groups)
            self.assertEqual(backend.staff_call("hide", SUBMISSION, subject, groups=("admin",))["status"], "ok")
            self.assertEqual(backend.staff_call("hide", SUBMISSION, subject, sub="")["error"], "not_staff")
            self.assertEqual(len(backend.actions()), 1)

    def test_groups_arrive_as_a_list_or_a_string(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            subject = submit(backend)
            event = {"arguments": {"action": "hide", "targetType": SUBMISSION, "target": subject}, "identity": {"sub": "s", "claims": {"cognito:groups": "[editor]"}}, "info": {}}
            self.assertEqual(reader_handler.handle_staff_event(event, store=backend.store, settings=backend.settings, now_seconds=backend.now)["status"], "ok")

    def test_approve_hide_and_unhide_a_submission_with_a_log_row_for_each(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            subject = submit(backend)
            self.assertEqual((row(backend, "submission", subject)["state"], row(backend, "submission", subject)["moderation"]), ("pending", "new"))
            approve = backend.staff_call("approve", SUBMISSION, subject, reason="Fine")
            self.assertEqual(approve["status"], "ok")
            self.assertEqual((row(backend, "submission", subject)["state"], row(backend, "submission", subject)["moderation"]), ("pending", "approved"))
            self.assertEqual(backend.staff_call("approve", SUBMISSION, subject)["error"], "already_reviewed")
            backend.now += 10
            hide = backend.staff_call("hide", SUBMISSION, subject, reason="Changed my mind")
            self.assertEqual(row(backend, "submission", subject)["state"], "hidden")
            self.assertEqual(backend.staff_call("hide", SUBMISSION, subject)["error"], "already_hidden")
            backend.now += 10
            self.assertEqual(backend.staff_call("unhide", SUBMISSION, subject)["status"], "ok")
            self.assertEqual(row(backend, "submission", subject)["state"], "pending")
            self.assertEqual(backend.staff_call("unhide", SUBMISSION, subject)["error"], "not_hidden")
            log = backend.actions()
            self.assertEqual([entry["action"] for entry in log], ["approve", "hide", "unhide"])
            first = log[0]
            self.assertEqual((first["id"], first["by"], first["actorSub"], first["targetType"], first["target"], first["reason"]), (approve["id"], "human", "staff-sub-1", SUBMISSION, subject, "Fine"))
            self.assertEqual((first["fromState"], first["toState"], first["fromModeration"], first["toModeration"], first["__typename"]), ("pending", "pending", "new", "approved", "ModerationAction"))
            self.assertEqual(log[1]["id"], hide["id"])
            self.assertTrue(all(entry["at"] and "undoOf" not in entry for entry in log))

    def test_comments_follow_the_same_rules_and_a_deleted_comment_is_beyond_moderation(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            comment_id = comment(backend)
            self.assertEqual(backend.staff_call("hide", COMMENT, comment_id)["status"], "ok")
            self.assertEqual(row(backend, "comment", comment_id)["state"], "hidden")
            self.assertEqual(backend.staff_call("unhide", COMMENT, comment_id)["status"], "ok")
            self.assertEqual(row(backend, "comment", comment_id)["state"], "visible")
            set_state(backend, "comment", comment_id, "deleted")
            for action in ("hide", "approve", "unhide"):
                self.assertEqual(backend.staff_call(action, COMMENT, comment_id)["error"], "target_deleted", action)

    def test_a_promoted_submission_that_is_hidden_comes_back_promoted(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            subject = submit(backend)
            self.assertEqual(backend.staff_call("promote", SUBMISSION, subject)["status"], "ok")
            backend.staff_call("hide", SUBMISSION, subject)
            backend.staff_call("unhide", SUBMISSION, subject)
            self.assertEqual(row(backend, "submission", subject)["state"], "promoted")

    def test_ban_limit_and_unban_a_reader_by_reader_id(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            reader_id = ready(backend, BOB, "loud-owl")
            subject = submit(backend)
            self.assertEqual(backend.staff_call("limit", READER, reader_id, reason="Flooding")["status"], "ok")
            backend.now += 1
            self.assertEqual(row(backend, "profile", BOB)["state"], "limited")
            self.assertEqual(backend.call(BOB, "me")["body"]["state"], "limited")
            self.assertEqual(backend.call(BOB, "vote", {"subject": ITEM, "dimension": "up", "on": True})["body"]["error"], "reader_limited")
            self.assertEqual(backend.call(BOB, "comment", {"subject": ITEM, "body": "x"})["body"]["error"], "reader_limited")
            self.assertEqual(backend.staff_call("limit", READER, reader_id)["error"], "not_active")
            self.assertEqual(backend.staff_call("ban", READER, reader_id)["status"], "ok")
            backend.now += 1
            self.assertEqual(backend.staff_call("ban", READER, reader_id)["error"], "already_banned")
            writes = [
                ("vote", {"subject": ITEM, "dimension": "up", "on": True}), ("rating", {"subject": ITEM, "dimension": "real", "value": 3}), ("handle", {"handle": "new-name"}),
                ("submit", {"url": "https://example.com/new", "title": "T"}), ("comment", {"subject": ITEM, "body": "x"}), ("comment-edit", {"id": "cmt-" + "0" * 32, "body": "x"}),
                ("comment-delete", {"id": "cmt-" + "0" * 32}), ("report", {"target": subject, "reason": "x"}),
            ]
            for action, payload in writes:
                answer = backend.call(BOB, action, payload)
                self.assertEqual((answer["statusCode"], answer["body"]["error"]), (403, "reader_banned"), action)
            self.assertEqual(backend.call(BOB, "me")["body"]["state"], "banned", "a banned reader can still see their own state")
            backend.now += 1
            self.assertEqual(backend.staff_call("unban", READER, reader_id)["status"], "ok")
            self.assertEqual(backend.call(BOB, "vote", {"subject": ITEM, "dimension": "up", "on": True})["statusCode"], 200)
            self.assertEqual(backend.staff_call("unban", READER, reader_id)["error"], "not_restricted")
            self.assertEqual([entry["action"] for entry in backend.actions()], ["limit", "ban", "unban"])
            self.assertEqual({entry["target"] for entry in backend.actions()}, {reader_id})
            self.assertNotIn(BOB, json.dumps(backend.actions(), default=str), "the log holds the public reader id, never the siteSubject")

    def test_invalid_requests(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            subject = submit(backend)
            comment_id = comment(backend)
            reader_id = backend.call(ALICE, "me")["body"]["readerId"]
            cases = [
                (("dance", SUBMISSION, subject), "invalid_action"), (("hide", "post", subject), "invalid_target"), (("hide", COMMENT, subject), "invalid_target"),
                (("hide", SUBMISSION, "sub-" + "0" * 24), "unknown_target"), (("hide", SUBMISSION, 7), "invalid_target"), (("hide", READER, reader_id), "invalid_action"),
                (("ban", SUBMISSION, subject), "invalid_action"), (("promote", COMMENT, comment_id), "invalid_action"), (("approve", READER, reader_id), "invalid_action"),
                (("hide", READER, "f" * 8 + "-0000-0000-0000-" + "0" * 12), "unknown_target"), (("undo", SUBMISSION, subject), "invalid_undo"),
            ]
            for (action, target_type, target), error in cases:
                self.assertEqual(backend.staff_call(action, target_type, target)["error"], error, (action, target_type))
            for reason in ("x" * 501, "bell\x07"):
                self.assertEqual(backend.staff_call("hide", SUBMISSION, subject, reason=reason)["error"], "invalid_reason")
            self.assertEqual(backend.actions(), [])

    def test_a_stale_view_cannot_overwrite_a_newer_decision(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            subject = submit(backend)
            stale = reader_handler.moderation_rules.content_plan("hide", SUBMISSION, row(backend, "submission", subject))
            backend.staff_call("hide", SUBMISSION, subject)
            record = {"id": "mod-" + "1" * 32, "by": "human", "actorSub": "s", "action": "hide", "targetType": SUBMISSION, "target": subject, "reason": "", "fromState": "pending", "toState": "hidden", "at": "2027-01-01T00:00:00.000Z"}
            self.assertEqual(backend.store.transact_moderation(record, SUBMISSION, subject, stale), "target_changed")
            self.assertEqual(len(backend.actions()), 1, "the refused action wrote no log row")


class UndoTests(unittest.TestCase):
    def test_undo_restores_the_state_the_action_replaced(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            subject = submit(backend)
            hide = backend.staff_call("hide", SUBMISSION, subject)
            backend.now += 5
            undo = backend.staff_call("undo", SUBMISSION, subject, undo_of=hide["id"], reason="Mistake")
            self.assertEqual(undo["status"], "ok")
            restored = row(backend, "submission", subject)
            self.assertEqual((restored["state"], restored["moderation"]), ("pending", "new"), "the item is back in the queue as it was")
            undone, entry = row(backend, "action", hide["id"]), row(backend, "action", undo["id"])
            self.assertEqual(undone["undoneBy"], undo["id"])
            self.assertEqual((entry["action"], entry["undoOf"], entry["reason"], entry["fromState"], entry["toState"]), ("undo", hide["id"], "Mistake", "hidden", "pending"))
            self.assertEqual(backend.staff_call("undo", SUBMISSION, subject, undo_of=hide["id"])["error"], "already_undone")
            self.assertEqual(len(backend.actions()), 2)

    def test_undo_covers_approve_ban_and_limit_and_can_itself_be_undone(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            reader_id = ready(backend, BOB, "loud-owl")
            subject = submit(backend)
            approve = backend.staff_call("approve", SUBMISSION, subject)
            backend.staff_call("undo", SUBMISSION, subject, undo_of=approve["id"])
            self.assertEqual(row(backend, "submission", subject)["moderation"], "new")
            ban = backend.staff_call("ban", READER, reader_id)
            undo_ban = backend.staff_call("undo", READER, reader_id, undo_of=ban["id"])
            self.assertEqual(row(backend, "profile", BOB)["state"], "active")
            redo = backend.staff_call("undo", READER, reader_id, undo_of=undo_ban["id"])
            self.assertEqual((redo["status"], row(backend, "profile", BOB)["state"]), ("ok", "banned"))
            limit_reader = ready(backend, CAROL, "plain-cat")
            limit = backend.staff_call("limit", READER, limit_reader)
            backend.staff_call("undo", READER, limit_reader, undo_of=limit["id"])
            self.assertEqual(row(backend, "profile", CAROL)["state"], "active")

    def test_undo_is_refused_when_the_target_has_moved_on(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            subject = submit(backend)
            hide = backend.staff_call("hide", SUBMISSION, subject)
            backend.staff_call("unhide", SUBMISSION, subject)
            self.assertEqual(backend.staff_call("undo", SUBMISSION, subject, undo_of=hide["id"])["error"], "target_changed")
            self.assertEqual(row(backend, "submission", subject)["state"], "pending")

    def test_a_promotion_cannot_be_undone_and_an_undo_must_name_this_targets_action(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            first = submit(backend)
            second = submit(backend, url="https://example.com/b", title="B")
            promote = backend.staff_call("promote", SUBMISSION, first)
            self.assertEqual(backend.staff_call("undo", SUBMISSION, first, undo_of=promote["id"])["error"], "not_undoable")
            self.assertEqual(backend.staff_call("undo", SUBMISSION, second, undo_of=promote["id"])["error"], "invalid_undo")
            for bad in (None, "", "nope", "mod-" + "0" * 32):
                self.assertEqual(backend.staff_call("undo", SUBMISSION, second, undo_of=bad)["error"], "invalid_undo", bad)

    def test_two_undos_of_the_same_action_cannot_both_win(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            subject = submit(backend)
            hide = backend.staff_call("hide", SUBMISSION, subject)
            original = backend.store.get_action(hide["id"])
            plan = reader_handler.moderation_rules.undo_plan(backend.store, original, SUBMISSION, row(backend, "submission", subject))
            backend.staff_call("undo", SUBMISSION, subject, undo_of=hide["id"])
            backend.staff_call("hide", SUBMISSION, subject)
            record = {"id": "mod-" + "2" * 32, "by": "human", "actorSub": "s", "action": "undo", "targetType": SUBMISSION, "target": subject, "reason": "", "fromState": "hidden", "toState": "pending", "undoOf": hide["id"], "at": "2027-01-01T00:00:00.000Z"}
            self.assertEqual(backend.store.transact_moderation(record, SUBMISSION, subject, plan, undoes=hide["id"]), "already_undone")


class PromoteTests(unittest.TestCase):
    def test_promote_creates_a_draft_item_and_marks_the_submission(self) -> None:
        with ReaderBackend() as backend:
            reader_id = ready(backend, ALICE, "quiet-fox")
            subject = backend.call(ALICE, "submit", {"url": "https://example.com/tool", "title": "A small tool", "note": "Worked well", "kind": "link"})["body"]["subject"]
            receipt = backend.staff_call("promote", SUBMISSION, subject, reason="Good find")
            self.assertEqual(receipt["status"], "ok")
            stored = row(backend, "submission", subject)
            self.assertEqual((stored["state"], stored["moderation"]), ("promoted", "approved"))
            (item,) = backend.items()
            self.assertEqual(stored["itemId"], item["lineageId"])
            self.assertRegex(item["lineageId"], r"^item-[0-9a-f]{12}$")
            self.assertEqual(item["id"], item["lineageId"] + "-v1")
            expected = {
                "versionNumber": 1, "versionState": "draft", "versionCreatedBy": "user:staff-sub-1", "changeReason": "reader-submission-promote", "type": "brief", "stage": "idea",
                "status": "draft", "typeStatus": "brief#draft", "section": "unsectioned", "sectionStatus": "unsectioned#draft", "title": "A small tool", "headline": "A small tool",
                "deck": "Worked well", "__typename": "Item",
            }
            self.assertEqual({key: (int(item[key]) if key == "versionNumber" else item[key]) for key in expected}, expected)
            self.assertRegex(item["slug"], r"^draft-unsectioned-[0-9a-f]{8}$")
            self.assertEqual(json.loads(item["metadata"]), {"createdFrom": "reader_submission", "submissionId": subject, "sourceUrl": "https://example.com/tool", "kind": "link", "submittedBy": reader_id})
            self.assertNotIn(ALICE, json.dumps(item, default=str))

    def test_promotion_uses_the_publications_type_and_section(self) -> None:
        with ReaderBackend(promote_item_type="link", promote_section="tools") as backend:
            ready(backend, ALICE, "quiet-fox")
            backend.staff_call("promote", SUBMISSION, submit(backend))
            (item,) = backend.items()
            self.assertEqual((item["type"], item["typeStatus"], item["section"], item["sectionStatus"]), ("link", "link#draft", "tools", "tools#draft"))

    def test_only_a_pending_submission_can_be_promoted_once(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            subject = submit(backend)
            self.assertEqual(backend.staff_call("promote", SUBMISSION, subject)["status"], "ok")
            self.assertEqual(backend.staff_call("promote", SUBMISSION, subject)["error"], "not_pending")
            hidden = submit(backend, url="https://example.com/h", title="H")
            backend.staff_call("hide", SUBMISSION, hidden)
            self.assertEqual(backend.staff_call("promote", SUBMISSION, hidden)["error"], "not_pending")
            self.assertEqual(len(backend.items()), 1)

    def test_a_duplicate_of_a_promoted_submission_points_at_the_item(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            ready(backend, BOB, "loud-owl")
            subject = submit(backend)
            backend.staff_call("promote", SUBMISSION, subject)
            answer = backend.call(BOB, "submit", {"url": "https://example.com/a", "title": "Again"})
            self.assertEqual(answer["body"]["existing"]["subject"], backend.items()[0]["lineageId"])
            self.assertEqual(answer["body"]["existing"]["state"], "promoted")

    def test_upvotes_on_the_promoted_item_earn_the_submitter_karma(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            ready(backend, ALICE, "quiet-fox")
            subject = submit(backend)
            backend.staff_call("promote", SUBMISSION, subject)
            lineage = backend.items()[0]["lineageId"]
            backend.publish(lineage)
            backend.call(BOB, "vote", {"subject": lineage, "dimension": "up", "on": True})
            backend.call(CAROL, "vote", {"subject": lineage, "dimension": "used-it", "on": True})
            report = run_snapshot(backend, LocalDirectoryWriter(Path(directory)), published=("item-one", "item-two", lineage), review_signals=lambda *args: [])
            self.assertEqual(report.karma_updated, 1)
            self.assertEqual(int(backend.table("profile").get_item(Key={"id": ALICE})["Item"]["karma"]), 1 + 2)


class ModeTests(unittest.TestCase):
    def test_new_content_waits_in_the_queue_in_human_mode_and_not_when_moderation_is_off(self) -> None:
        for mode, expected in (("human", "new"), ("off", "approved")):
            with ReaderBackend(moderation_mode=mode) as backend:
                ready(backend, ALICE, "quiet-fox")
                subject, comment_id = submit(backend), comment(backend)
                self.assertEqual((row(backend, "submission", subject)["moderation"], row(backend, "comment", comment_id)["moderation"]), (expected, expected), mode)
                self.assertEqual((row(backend, "submission", subject)["state"], row(backend, "comment", comment_id)["state"]), ("pending", "visible"))

    def test_pre_moderation_holds_new_content_until_a_moderator_approves_it(self) -> None:
        with ReaderBackend(pre_moderation=True) as backend, tempfile.TemporaryDirectory() as directory:
            ready(backend, ALICE, "quiet-fox")
            answer = backend.call(ALICE, "submit", {"url": "https://example.com/a", "title": "A"})
            self.assertEqual((answer["statusCode"], answer["body"]["state"]), (201, "held"))
            subject = answer["body"]["subject"]
            held_comment = backend.call(ALICE, "comment", {"subject": ITEM, "body": "Waiting."})
            self.assertEqual((held_comment["statusCode"], held_comment["body"]["state"]), (201, "held"))
            self.assertEqual((row(backend, "submission", subject)["state"], row(backend, "comment", held_comment["body"]["id"])["state"]), ("hidden", "hidden"))
            writer = LocalDirectoryWriter(Path(directory))
            run_snapshot(backend, writer, review_signals=lambda *args: [])
            self.assertEqual(json.loads(writer.get("_data/reader/submissions.json"))["submissions"], [])
            self.assertIsNone(writer.get("_data/reader/comments/item-one.json"))
            self.assertEqual(backend.call(BOB, "vote", {"subject": subject, "dimension": "up", "on": True})["statusCode"], 404, "a held submission is not there yet")
            self.assertEqual(backend.staff_call("approve", SUBMISSION, subject)["status"], "ok")
            self.assertEqual(backend.staff_call("approve", COMMENT, held_comment["body"]["id"])["status"], "ok")
            self.assertEqual((row(backend, "submission", subject)["state"], row(backend, "comment", held_comment["body"]["id"])["state"]), ("pending", "visible"))
            backend.now += 120
            run_snapshot(backend, writer, review_signals=lambda *args: [])
            self.assertEqual([entry["id"] for entry in json.loads(writer.get("_data/reader/submissions.json"))["submissions"]], [subject])
            self.assertEqual(len(json.loads(writer.get("_data/reader/comments/item-one.json"))["comments"]), 1)

    def test_undoing_the_approval_of_a_held_item_hides_it_again(self) -> None:
        with ReaderBackend(pre_moderation=True) as backend:
            ready(backend, ALICE, "quiet-fox")
            subject = backend.call(ALICE, "submit", {"url": "https://example.com/a", "title": "A"})["body"]["subject"]
            approve = backend.staff_call("approve", SUBMISSION, subject)
            backend.staff_call("undo", SUBMISSION, subject, undo_of=approve["id"])
            self.assertEqual((row(backend, "submission", subject)["state"], row(backend, "submission", subject)["moderation"]), ("hidden", "new"))

    def test_pre_moderation_does_nothing_when_moderation_is_off(self) -> None:
        with ReaderBackend(moderation_mode="off", pre_moderation=True) as backend:
            ready(backend, ALICE, "quiet-fox")
            self.assertEqual(backend.call(ALICE, "submit", {"url": "https://example.com/a", "title": "A"})["body"]["state"], "pending")


class HiddenContentTests(unittest.TestCase):
    def test_hidden_content_leaves_the_next_snapshot_and_comes_back_when_unhidden(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            ready(backend, ALICE, "quiet-fox")
            subject = submit(backend)
            comment_id = comment(backend, subject=subject)
            other = comment(backend, body="Stays.")
            backend.call(BOB, "vote", {"subject": subject, "dimension": "up", "on": True})
            writer = LocalDirectoryWriter(Path(directory))
            run_snapshot(backend, writer, review_signals=lambda *args: [])
            self.assertEqual(len(json.loads(writer.get("_data/reader/submissions.json"))["submissions"]), 1)
            self.assertEqual(len(json.loads(writer.get(f"_data/reader/comments/{subject}.json"))["comments"]), 1)
            backend.staff_call("hide", SUBMISSION, subject)
            backend.staff_call("hide", COMMENT, other)
            backend.now += 120
            report = run_snapshot(backend, writer, review_signals=lambda *args: [])
            self.assertEqual(json.loads(writer.get("_data/reader/submissions.json"))["submissions"], [])
            items = json.loads(writer.get("_data/reader/items.json"))["items"]
            self.assertNotIn(subject, items, "a hidden submission and its votes are not counted")
            self.assertEqual(json.loads(writer.get(f"_data/reader/comments/{subject}.json"))["comments"], [], "the comment file of a hidden submission is emptied")
            self.assertEqual(json.loads(writer.get("_data/reader/comments/item-one.json"))["comments"], [])
            text = "".join(writer.get(key).decode() for key in report.written)
            self.assertNotIn("Stays.", text)
            self.assertNotIn("A small tool", text)
            self.assertNotIn(comment_id, text)
            backend.staff_call("unhide", SUBMISSION, subject)
            backend.now += 120
            run_snapshot(backend, writer, review_signals=lambda *args: [])
            self.assertEqual(len(json.loads(writer.get("_data/reader/submissions.json"))["submissions"]), 1)
            self.assertEqual(json.loads(writer.get("_data/reader/items.json"))["items"][subject]["up"], 1)

    def test_a_hidden_comment_cannot_be_replied_to_and_a_visible_reply_keeps_a_stub(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            ready(backend, ALICE, "quiet-fox")
            ready(backend, BOB, "loud-owl")
            top = comment(backend)
            backend.now += 5
            comment(backend, BOB, "A reply.", parent=top)
            backend.staff_call("hide", COMMENT, top)
            self.assertEqual(backend.call(BOB, "comment", {"subject": ITEM, "body": "More", "parent": top})["body"]["error"], "invalid_parent")
            writer = LocalDirectoryWriter(Path(directory))
            run_snapshot(backend, writer, review_signals=lambda *args: [])
            entries = json.loads(writer.get("_data/reader/comments/item-one.json"))["comments"]
            self.assertEqual([("stub" in entry, entry["parent"]) for entry in entries], [(True, None), (False, top)])


if __name__ == "__main__":
    unittest.main()
