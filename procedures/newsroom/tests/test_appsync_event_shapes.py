"""Staff mutations reach the function in two AppSync shapes; both must route to the staff path.

The Amplify Gen 2 Lambda data source sends ``typeName`` and ``fieldName`` at the top level and no ``info`` key (the bug that made
``fileProposal`` and ``moderateReader`` answer a null ``status`` on deployed sites). A direct resolver nests it under ``info``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reader_fixtures import ReaderBackend, proposal_handler, reader_handler  # noqa: E402
from test_reader_moderation import ALICE, ready, submit  # noqa: E402

rules = proposal_handler.proposal_rules
SUBMISSION = "submission"
ARGUMENTS = {"kind": "story_draft", "title": "Agents are eating the board", "body": "Why this matters.\n"}


class FieldNameTests(unittest.TestCase):
    def test_field_name_comes_from_info_or_the_top_level(self) -> None:
        self.assertEqual(rules.event_field_name({"info": {"fieldName": "fileProposal"}}), "fileProposal")
        self.assertEqual(rules.event_field_name({"fieldName": "moderateReader", "typeName": "Mutation"}), "moderateReader")
        self.assertEqual(rules.event_field_name({"info": {}, "fieldName": "fileProposal"}), "fileProposal")
        self.assertIsNone(rules.event_field_name({"info": None}))
        self.assertIsNone(rules.event_field_name({"siteSubject": "s", "action": "vote", "payload": {}}))

    def test_only_appsync_events_are_staff_events(self) -> None:
        self.assertTrue(reader_handler.is_appsync_event({"arguments": {}, "fieldName": "fileProposal"}))
        self.assertTrue(reader_handler.is_appsync_event({"arguments": {}, "info": {"fieldName": "fileProposal"}}))
        self.assertTrue(reader_handler.is_appsync_event({"arguments": {}, "info": {}}))
        self.assertFalse(reader_handler.is_appsync_event({"siteSubject": "ss1_x", "action": "vote", "payload": {}, "isStaff": False}))
        self.assertFalse(reader_handler.is_appsync_event({"fieldName": "fileProposal"}))


class DeployedEventShapeTests(unittest.TestCase):
    def test_file_proposal_in_the_gen2_shape_creates_a_proposal(self) -> None:
        with ReaderBackend() as backend:
            answer = backend.proposal_call("fileProposal", ARGUMENTS)
            self.assertEqual(answer["status"], "ok", answer)
            self.assertEqual(len(backend.proposals()), 1)

    def test_transition_proposal_in_the_gen2_shape_moves_it(self) -> None:
        with ReaderBackend() as backend:
            identifier = backend.proposal_call("fileProposal", ARGUMENTS)["id"]
            self.assertEqual(backend.proposal_call("transitionProposal", {"proposalId": identifier, "state": "in_steering"})["status"], "ok")
            self.assertEqual(backend.proposals()[0]["state"], "in_steering")

    def test_moderate_reader_in_the_gen2_shape_hides_a_submission(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            subject = submit(backend)
            answer = backend.staff_call("hide", SUBMISSION, subject)
            self.assertEqual(answer["status"], "ok", answer)
            self.assertEqual(backend.table("submission").get_item(Key={"id": subject})["Item"]["state"], "hidden")

    def test_a_reader_is_refused_in_the_gen2_shape(self) -> None:
        with ReaderBackend() as backend:
            self.assertEqual(backend.proposal_call("fileProposal", ARGUMENTS, groups=("reader",))["error"], "not_staff")
            self.assertEqual(backend.staff_call("hide", SUBMISSION, "sub-1", groups=("reader",))["error"], "not_staff")
            self.assertEqual(backend.proposals(), [])

    def test_an_operator_role_files_a_proposal_in_the_gen2_shape(self) -> None:
        with ReaderBackend() as backend:
            self.assertEqual(backend.operator_proposal_call("fileProposal", ARGUMENTS)["status"], "ok")

    def test_the_info_shape_still_works(self) -> None:
        with ReaderBackend() as backend:
            ready(backend, ALICE, "quiet-fox")
            subject = submit(backend)
            self.assertEqual(backend.proposal_call("fileProposal", ARGUMENTS, shape="info")["status"], "ok")
            self.assertEqual(backend.staff_call("hide", SUBMISSION, subject, shape="info")["status"], "ok")
            self.assertEqual(backend.operator_proposal_call("fileProposal", ARGUMENTS, shape="info")["status"], "ok")
            self.assertEqual(len(backend.proposals()), 2)


if __name__ == "__main__":
    unittest.main()
