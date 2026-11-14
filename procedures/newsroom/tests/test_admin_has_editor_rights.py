"""An admin who is not in the editor group has every editor right, and a string-shaped groups claim does not hide it."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

from papyrus_content import staff_groups  # noqa: E402
from papyrus_content.reference_intake import IntakeError  # noqa: E402
from papyrus_content.review_requests import ReviewError, answer_review  # noqa: E402
from papyrus_content.newsletter.issues import allowed, EDITORS  # noqa: E402
from reader_fixtures import ReaderBackend, proposal_handler, reader_handler  # noqa: E402
from test_reference_intake import IDENTITY, IntakeClient, payload, submit  # noqa: E402

OWNER = ("admin", "Google_1234")  # the site owner: admin plus the federated Google group, never editor
SHAPES = [
    ["admin", "Google_1234"],
    "[admin Google_1234]",
    "[admin, Google_1234]",
    '["admin","Google_1234"]',
    "admin,Google_1234",
]


@pytest.mark.parametrize("shape", SHAPES)
def test_every_shape_of_the_groups_claim_yields_staff_for_an_admin(shape):
    assert staff_groups.claim_groups(shape) == ["admin", "Google_1234"]
    assert staff_groups.has_editor_rights(shape)


@pytest.mark.parametrize("groups", [["curator"], ["reader", "Google_1"], [], None, "", "[]", 7])
def test_without_either_group_nobody_is_staff(groups):
    assert not staff_groups.has_editor_rights(groups)


@pytest.mark.parametrize("shape", SHAPES)
def test_reference_review_intake_accepts_an_admin_without_the_editor_group(shape):
    identity = copy.deepcopy(IDENTITY)
    identity["claims"]["cognito:groups"] = shape
    result = submit(IntakeClient(), payload(), identity)
    assert result


def test_reference_review_intake_still_refuses_a_reader():
    identity = copy.deepcopy(IDENTITY)
    identity["claims"]["cognito:groups"] = "[reader Google_1]"
    with pytest.raises(IntakeError):
        submit(IntakeClient(), payload(), identity)


def test_answering_a_review_request_is_open_to_admins_and_closed_to_readers():
    with pytest.raises(ReviewError, match="only editors and admins"):
        answer_review(object(), "rr-1", decision="approve", by="x", roles=["reader"])
    # An admin passes the role check; the next failure is about the request, not about the role.
    with pytest.raises(Exception) as error:
        answer_review(object(), "rr-1", decision="approve", by="x", roles=["admin"])
    assert "only editors and admins" not in str(error.value)



def test_newsletter_guard_admits_an_admin_list_and_still_refuses_a_bare_string():
    assert allowed({"identity": {"groups": list(OWNER)}}, EDITORS)
    assert not allowed({"identity": {"groups": "admin"}}, EDITORS)
    assert not allowed({"identity": {"groups": ["reader"]}}, EDITORS)


class AdminOnlyProposalsTests(unittest.TestCase):
    """The Proposals panel and the editor tier (pin, hold, exclude) for an admin who is not an editor."""

    def test_an_admin_files_decides_and_uses_the_editor_tier(self) -> None:
        for groups in (OWNER, ("admin",)):
            with ReaderBackend() as backend:
                filed = backend.proposal_call("fileProposal", {"kind": "story_draft", "title": "Agents", "body": "# Agents\n\nBody.\n"}, groups=groups)
                self.assertEqual(filed["status"], "ok", filed)
                moved = backend.proposal_call("transitionProposal", {"proposalId": filed["id"], "state": "in_steering"}, groups=groups)
                self.assertEqual(moved["status"], "ok", moved)
                pinned = backend.proposal_call("editProposal", {"proposalId": filed["id"], "action": "pin"}, groups=groups)
                self.assertEqual(pinned["status"], "ok", pinned)

    def test_a_reader_is_still_refused(self) -> None:
        with ReaderBackend() as backend:
            refused = backend.proposal_call("fileProposal", {"kind": "story_draft", "title": "Agents", "body": "# A\n\nB.\n"}, groups=("reader",))
            self.assertEqual(refused["status"], "refused")
            self.assertEqual(refused["error"], "not_staff")

    def test_an_admin_moderates_with_a_string_groups_claim(self) -> None:
        for groups in (OWNER,):
            with ReaderBackend() as backend:
                answer = backend.staff_call("hide", "submission", "missing-target", groups=groups)
                self.assertNotEqual(answer.get("reason"), "not_staff", answer)

    def test_the_standalone_copies_agree_with_the_shared_helper(self) -> None:
        for shape in SHAPES + [["reader"], None, "[reader]", ""]:
            expected = staff_groups.claim_groups(shape)
            self.assertEqual(proposal_handler.proposal_rules.claim_groups(shape), expected)
            self.assertEqual(reader_handler.moderation_rules.claim_groups(shape), expected)
            self.assertEqual(proposal_handler.proposal_rules.has_editor_rights(shape), staff_groups.has_editor_rights(shape))
            self.assertEqual(reader_handler.moderation_rules.has_editor_rights(shape), staff_groups.has_editor_rights(shape))
