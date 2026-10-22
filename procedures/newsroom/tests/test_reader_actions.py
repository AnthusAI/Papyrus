"""reader-actions: handles, votes, ratings, abuse limits and the snapshot debounce, against moto tables."""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reader_fixtures import (  # noqa: E402
    SCHEDULER_ROLE_ARN,
    SNAPSHOT_FUNCTION_ARN,
    START_SECONDS,
    ReaderBackend,
    reader_handler,
    subject_for,
)

ALICE = subject_for("alice")
BOB = subject_for("bob")


class IdentityTests(unittest.TestCase):
    def test_only_site_subjects_are_accepted_in_production_settings(self) -> None:
        with ReaderBackend() as backend:
            for bad in ["", "ss1_short", "ssdev_" + "A" * 43, "person-123", "a@example.test", None, 7, "ss1_" + "A" * 44]:
                answer = backend.call(bad, "me")
                self.assertEqual(answer["statusCode"], 403, bad)
                self.assertEqual(answer["body"]["error"], "reader_identity_invalid")
            self.assertEqual(backend.table("profile").scan()["Count"], 0)

    def test_interim_subjects_only_when_the_site_was_synthesized_for_development(self) -> None:
        interim = subject_for("alice", "ssdev_")
        with ReaderBackend(allow_interim=True) as backend:
            self.assertEqual(backend.call(interim, "me")["statusCode"], 200)

    def test_me_creates_a_profile_once_with_a_random_public_reader_id(self) -> None:
        with ReaderBackend() as backend:
            first = backend.call(ALICE, "me")["body"]
            second = backend.call(ALICE, "me")["body"]
            self.assertEqual(first["readerId"], second["readerId"])
            self.assertNotEqual(first["readerId"], backend.call(BOB, "me")["body"]["readerId"])
            self.assertEqual({key: first[key] for key in ("handle", "karma", "state", "votes")}, {"handle": None, "karma": 0, "state": "active", "votes": {}})
            self.assertNotIn(ALICE, json.dumps(first))
            self.assertNotIn(ALICE[4:], first["readerId"])

    def test_the_profile_is_keyed_on_the_site_subject(self) -> None:
        with ReaderBackend() as backend:
            backend.call(ALICE, "me")
            stored = backend.table("profile").get_item(Key={"id": ALICE})["Item"]
            self.assertEqual(stored["siteSubject"], ALICE)
            self.assertEqual(stored["__typename"], "ReaderProfile")

    def test_malformed_events_are_refused(self) -> None:
        with ReaderBackend() as backend:
            event = {"siteSubject": ALICE, "isStaff": "yes", "action": "me", "payload": {}}
            answer = reader_handler.handle_event(event, store=backend.store, settings=backend.settings, now_seconds=backend.now, schedule_snapshot=lambda: None)
            self.assertEqual(answer["statusCode"], 400)
            self.assertEqual(backend.call(ALICE, "dance")["statusCode"], 400)


class HandleTests(unittest.TestCase):
    def test_setting_a_handle_shows_in_me_and_lowercases(self) -> None:
        with ReaderBackend() as backend:
            answer = backend.call(ALICE, "handle", {"handle": "Quiet-Fox"})
            self.assertEqual(answer["statusCode"], 200)
            self.assertEqual(answer["body"]["handle"], "quiet-fox")
            self.assertEqual(backend.call(ALICE, "me")["body"]["handle"], "quiet-fox")

    def test_a_handle_is_set_once(self) -> None:
        with ReaderBackend() as backend:
            backend.call(ALICE, "handle", {"handle": "quiet-fox"})
            answer = backend.call(ALICE, "handle", {"handle": "other-name"})
            self.assertEqual((answer["statusCode"], answer["body"]["error"]), (409, "handle_already_set"))

    def test_a_taken_handle_is_refused_case_insensitively(self) -> None:
        with ReaderBackend() as backend:
            backend.call(ALICE, "handle", {"handle": "quiet-fox"})
            answer = backend.call(BOB, "handle", {"handle": "QUIET-FOX"})
            self.assertEqual((answer["statusCode"], answer["body"]["error"]), (409, "handle_taken"))
            self.assertIsNone(backend.call(BOB, "me")["body"]["handle"])
            self.assertEqual(backend.call(BOB, "handle", {"handle": "other-name"})["statusCode"], 200)

    def test_invalid_and_reserved_handles(self) -> None:
        with ReaderBackend() as backend:
            for bad in ["ab", "x" * 25, "has space", "dots.dots", "ünï", "", 5, None, "a@example.test"]:
                self.assertEqual(backend.call(ALICE, "handle", {"handle": bad})["body"]["error"], "invalid_handle", bad)
            for reserved in ["admin", "ADMIN", "Moderator", "papyrus"]:
                self.assertEqual(backend.call(ALICE, "handle", {"handle": reserved})["body"]["error"], "reserved_handle", reserved)
            self.assertIsNone(backend.call(ALICE, "me")["body"]["handle"])

    def test_the_publication_adds_reserved_handles(self) -> None:
        with ReaderBackend() as backend:
            backend.settings = reader_handler.ReaderSettings(dimensions=("real",), reserved_handles=frozenset({"shipped-team"}))
            self.assertEqual(backend.call(ALICE, "handle", {"handle": "shipped-team"})["body"]["error"], "reserved_handle")

    def test_a_banned_reader_cannot_take_a_handle(self) -> None:
        with ReaderBackend() as backend:
            backend.call(ALICE, "me")
            backend.table("profile").update_item(Key={"id": ALICE}, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":s": "banned"})
            self.assertEqual(backend.call(ALICE, "handle", {"handle": "quiet-fox"})["body"]["error"], "reader_banned")
            self.assertEqual(backend.call(ALICE, "me")["body"]["state"], "banned")


class VoteTests(unittest.TestCase):
    def test_an_upvote_is_idempotent_and_stored_under_a_deterministic_id(self) -> None:
        with ReaderBackend() as backend:
            reader_id = backend.call(ALICE, "me")["body"]["readerId"]
            for _ in range(3):
                answer = backend.call(ALICE, "vote", {"subject": "item-one", "dimension": "up", "on": True})
                self.assertEqual(answer["statusCode"], 200)
            votes = backend.votes()
            self.assertEqual([vote["id"] for vote in votes], [f"item-one#{reader_id}#up"])
            self.assertEqual((votes[0]["value"], votes[0]["voterRole"], votes[0]["__typename"]), (1, "reader", "ReaderVote"))

    def test_unvote_deletes_and_is_idempotent(self) -> None:
        with ReaderBackend() as backend:
            backend.call(ALICE, "vote", {"subject": "item-one", "dimension": "up", "on": True})
            for _ in range(2):
                self.assertEqual(backend.call(ALICE, "vote", {"subject": "item-one", "dimension": "up", "on": False})["statusCode"], 200)
            self.assertEqual(backend.votes(), [])

    def test_a_revote_overwrites_and_keeps_the_first_created_at(self) -> None:
        with ReaderBackend() as backend:
            backend.call(ALICE, "rating", {"subject": "item-one", "dimension": "real", "value": 2})
            created = backend.votes()[0]["createdAt"]
            backend.now += 60
            backend.call(ALICE, "rating", {"subject": "item-one", "dimension": "real", "value": 5})
            (vote,) = backend.votes()
            self.assertEqual((vote["value"], vote["createdAt"]), (5, created))
            self.assertGreater(vote["updatedAt"], created)

    def test_rating_null_deletes_and_values_are_validated(self) -> None:
        with ReaderBackend() as backend:
            backend.call(ALICE, "rating", {"subject": "item-one", "dimension": "useful", "value": 3})
            backend.call(ALICE, "rating", {"subject": "item-one", "dimension": "useful", "value": None})
            self.assertEqual(backend.votes(), [])
            for bad in [0, 6, 2.5, "3", True, [], {}]:
                answer = backend.call(ALICE, "rating", {"subject": "item-one", "dimension": "useful", "value": bad})
                self.assertEqual((answer["statusCode"], answer["body"]["error"]), (422, "invalid_rating"), bad)

    def test_dimensions_come_from_the_publication(self) -> None:
        with ReaderBackend(dimensions=("real",)) as backend:
            self.assertEqual(backend.call(ALICE, "rating", {"subject": "item-one", "dimension": "useful", "value": 3})["body"]["error"], "invalid_dimension")
            self.assertEqual(backend.call(ALICE, "rating", {"subject": "item-one", "dimension": "up", "value": 3})["body"]["error"], "invalid_dimension")
            self.assertEqual(backend.call(ALICE, "vote", {"subject": "item-one", "dimension": "real", "on": True})["body"]["error"], "invalid_dimension")
            self.assertEqual(backend.call(ALICE, "vote", {"subject": "item-one", "dimension": "used-it", "on": True})["statusCode"], 200)

    def test_the_subject_must_be_a_published_item(self) -> None:
        with ReaderBackend() as backend:
            backend.publish("draft-item", status="draft")
            for subject in ["missing", "draft-item"]:
                answer = backend.call(ALICE, "vote", {"subject": subject, "dimension": "up", "on": True})
                self.assertEqual((answer["statusCode"], answer["body"]["error"]), (404, "unknown_subject"), subject)
            for bad in ["", "has#hash", "a b", "x" * 201, None, 3]:
                self.assertEqual(backend.call(ALICE, "vote", {"subject": bad, "dimension": "up", "on": True})["body"]["error"], "invalid_subject", bad)
            self.assertEqual(backend.votes(), [])

    def test_vote_on_must_be_a_boolean(self) -> None:
        with ReaderBackend() as backend:
            for bad in [1, "true", None]:
                self.assertEqual(backend.call(ALICE, "vote", {"subject": "item-one", "dimension": "up", "on": bad})["body"]["error"], "invalid_vote")

    def test_a_staff_reader_votes_as_an_editor(self) -> None:
        with ReaderBackend() as backend:
            backend.call(ALICE, "rating", {"subject": "item-one", "dimension": "real", "value": 4}, staff=True)
            backend.call(BOB, "rating", {"subject": "item-one", "dimension": "real", "value": 4})
            self.assertEqual(sorted(vote["voterRole"] for vote in backend.votes()), ["editor", "reader"])

    def test_me_returns_only_my_votes_for_the_asked_subjects(self) -> None:
        with ReaderBackend() as backend:
            backend.call(ALICE, "vote", {"subject": "item-one", "dimension": "up", "on": True})
            backend.call(ALICE, "rating", {"subject": "item-one", "dimension": "real", "value": 4})
            backend.call(ALICE, "vote", {"subject": "item-two", "dimension": "used-it", "on": True})
            backend.call(BOB, "vote", {"subject": "item-one", "dimension": "up", "on": True})
            body = backend.call(ALICE, "me", {"subjects": ["item-one", "item-two", "item-three"]})["body"]
            self.assertEqual(body["votes"], {"item-one": {"up": 1, "real": 4}, "item-two": {"used-it": 1}})
            self.assertEqual(backend.call(ALICE, "me", {"subjects": ["x"] * 51})["statusCode"], 422)
            self.assertEqual(backend.call(ALICE, "me", {"subjects": ["a#b"]})["statusCode"], 422)

    def test_limited_readers_cannot_vote_but_can_read(self) -> None:
        with ReaderBackend() as backend:
            backend.call(ALICE, "me")
            backend.table("profile").update_item(Key={"id": ALICE}, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":s": "limited"})
            self.assertEqual(backend.call(ALICE, "vote", {"subject": "item-one", "dimension": "up", "on": True})["body"]["error"], "reader_limited")
            self.assertEqual(backend.call(ALICE, "me")["statusCode"], 200)


class RateLimitTests(unittest.TestCase):
    def vote(self, backend: ReaderBackend, subject_name: str = "item-one") -> dict:
        return backend.call(ALICE, "vote", {"subject": subject_name, "dimension": "up", "on": True})

    def test_a_new_account_gets_a_third_of_the_hourly_limit(self) -> None:
        with ReaderBackend(actions_per_hour=30) as backend:
            answers = [self.vote(backend) for _ in range(12)]
            self.assertEqual([answer["statusCode"] for answer in answers], [200] * 10 + [429] * 2)
            self.assertEqual(answers[-1]["body"]["error"], "rate_limited")
            self.assertGreater(answers[-1]["body"]["retryAfter"], 0)
            self.assertLessEqual(answers[-1]["body"]["retryAfter"], 3600)

    def test_an_established_account_gets_the_full_limit_and_votes_and_ratings_share_it(self) -> None:
        with ReaderBackend(actions_per_hour=30) as backend:
            backend.call(ALICE, "me")
            backend.age_everyone()
            statuses = []
            for number in range(32):
                if number % 2:
                    statuses.append(backend.call(ALICE, "rating", {"subject": "item-one", "dimension": "real", "value": 3})["statusCode"])
                else:
                    statuses.append(self.vote(backend)["statusCode"])
            self.assertEqual(statuses, [200] * 30 + [429] * 2)

    def test_the_limit_starts_over_in_the_next_hour_and_is_per_reader(self) -> None:
        with ReaderBackend(actions_per_hour=3) as backend:
            self.assertEqual([self.vote(backend)["statusCode"] for _ in range(2)], [200, 429])
            self.assertEqual(backend.call(BOB, "vote", {"subject": "item-one", "dimension": "up", "on": True})["statusCode"], 200)
            backend.now += 3600
            self.assertEqual(self.vote(backend)["statusCode"], 200)

    def test_the_retry_after_counts_down_to_the_next_hour(self) -> None:
        with ReaderBackend(actions_per_hour=3) as backend:
            self.vote(backend)
            backend.now += 1000
            refused = self.vote(backend)
            window_end = (int(backend.now // 3600) + 1) * 3600
            self.assertEqual(refused["body"]["retryAfter"], int(window_end - backend.now))

    def test_refused_votes_write_nothing(self) -> None:
        with ReaderBackend(actions_per_hour=3) as backend:
            self.vote(backend)
            self.assertEqual(self.vote(backend, "item-two")["statusCode"], 429)
            self.assertEqual([vote["subjectKey"] for vote in backend.votes()], ["item-one"])


class SnapshotDebounceTests(unittest.TestCase):
    """Trailing edge: the first write in a window schedules one run for the end of the window."""

    def vote(self, backend: ReaderBackend, who: str = "alice", on: bool = True) -> None:
        backend.call(subject_for(who), "vote", {"subject": "item-one", "dimension": "up", "on": on})

    def test_the_first_write_schedules_one_run_at_the_end_of_the_window(self) -> None:
        with ReaderBackend() as backend:
            for number in range(5):
                self.vote(backend, f"reader-{number}")
                backend.now += 10
            schedules = backend.schedules()
            self.assertEqual(len(schedules), 1, "five writes inside the window still schedule one run")
            schedule = schedules[0]
            opened = int(START_SECONDS)
            self.assertEqual(schedule["Name"], f"papyrus-reader-snapshot-{opened + 60}")
            self.assertEqual(schedule["ScheduleExpression"], "at(" + time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(opened + 60)) + ")")
            self.assertEqual(schedule["ScheduleExpressionTimezone"], "UTC")
            self.assertEqual(schedule["FlexibleTimeWindow"], {"Mode": "OFF"})
            self.assertEqual(schedule["ActionAfterCompletion"], "DELETE")
            self.assertEqual((schedule["Target"]["Arn"], schedule["Target"]["RoleArn"]), (SNAPSHOT_FUNCTION_ARN, SCHEDULER_ROLE_ARN))
            self.assertEqual(json.loads(schedule["Target"]["Input"]), {"projectionTask": {"task": "reader-snapshot"}})

    def test_a_vote_inside_the_window_is_covered_by_the_run_at_its_end(self) -> None:
        with ReaderBackend() as backend:
            self.vote(backend, "alice")
            backend.now += 59
            self.vote(backend, "bob")
            (schedule,) = backend.schedules()
            run_at = int(START_SECONDS) + 60
            self.assertGreater(run_at, backend.now, "the run is still ahead of the late vote")
            self.assertIn(str(run_at), schedule["Name"])
            self.assertEqual(len(backend.votes()), 2, "both votes are stored before the run reads them")

    def test_a_write_after_the_window_opens_the_next_window(self) -> None:
        with ReaderBackend() as backend:
            self.vote(backend)
            backend.now += 61
            self.vote(backend, on=False)
            self.assertEqual(len(backend.schedules()), 2)

    def test_reads_handles_and_refused_requests_schedule_nothing(self) -> None:
        with ReaderBackend() as backend:
            backend.call(ALICE, "me")
            backend.call(ALICE, "handle", {"handle": "quiet-fox"})
            backend.call(ALICE, "vote", {"subject": "missing", "dimension": "up", "on": True})
            backend.call(ALICE, "rating", {"subject": "item-one", "dimension": "real", "value": 9})
            self.assertEqual(backend.schedules(), [])

    def test_without_a_snapshot_target_nothing_is_scheduled_and_the_vote_still_works(self) -> None:
        with ReaderBackend(snapshot_enabled=False) as backend:
            self.assertEqual(backend.call(ALICE, "vote", {"subject": "item-one", "dimension": "up", "on": True})["statusCode"], 200)
            self.assertEqual(backend.schedules(), [])

    def test_a_failing_schedule_never_fails_the_vote_and_the_next_write_tries_again(self) -> None:
        with ReaderBackend() as backend:
            real = backend.scheduler_client.create_schedule
            backend.scheduler_client.create_schedule = lambda **_: (_ for _ in ()).throw(RuntimeError("down"))
            self.assertEqual(backend.call(ALICE, "vote", {"subject": "item-one", "dimension": "up", "on": True})["statusCode"], 200)
            self.assertEqual(backend.schedules(), [])
            backend.scheduler_client.create_schedule = real
            backend.now += 1
            self.vote(backend, "bob")
            self.assertEqual(len(backend.schedules()), 1, "the window was released, so the next write scheduled the run")


class SettingsTests(unittest.TestCase):
    def test_settings_come_from_one_json_environment_variable(self) -> None:
        settings = reader_handler.settings_from_environment(
            {"PAPYRUS_READER_SETTINGS": json.dumps({"dimensions": ["real"], "limits": {"actionsPerHour": 7, "newAccountHours": 2, "newAccountDivisor": 2}, "reservedHandles": ["x-team"], "allowInterimSubjects": True})}
        )
        self.assertEqual((settings.dimensions, settings.actions_per_hour, settings.new_account_hours, settings.new_account_divisor), (("real",), 7, 2, 2))
        self.assertEqual((settings.reserved_handles, settings.allow_interim_subjects), (frozenset({"x-team"}), True))
        defaults = reader_handler.settings_from_environment({})
        self.assertEqual((defaults.actions_per_hour, defaults.allow_interim_subjects), (120, False))

    def test_the_published_id_prefix_matches_the_content_package(self) -> None:
        from papyrus_content.publishing import PUBLISHED_ID_PREFIX

        self.assertEqual(reader_handler.PUBLISHED_ID_PREFIX, PUBLISHED_ID_PREFIX)


if __name__ == "__main__":
    unittest.main()
