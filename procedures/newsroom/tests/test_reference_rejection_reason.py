"""A rejection needs a reason, and the editor's own words are one.

The CLI no longer demands --reason-code when --note says why: the curation
Lambda reads those words for the code they name, so the scope-training
negatives keep arriving from the surfaces that ask for words instead of a
chip. Only a rejection with neither words nor a code is refused.
"""

import pathlib
import sys
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.references_commands import references_review_curation  # noqa: E402


class ReferenceRejectionReasonTest(unittest.TestCase):
    def _review(self, flags):
        """Run the command against a stubbed authoring client and return what it asked for."""
        with mock.patch("papyrus_content.references_commands.create_authoring_client",
                        return_value=(mock.Mock(graphql=mock.Mock()), None)), \
             mock.patch("papyrus_newsroom.reference_actions.review_reference_curation") as review, \
             mock.patch("builtins.print"):
            review.return_value = {"referenceId": "reference-a", "action": "reject", "status": "rejected",
                                   "reasonCode": "out_of_scope", "messageId": "message-a"}
            references_review_curation(flags)
        return review.call_args.kwargs

    def test_written_reason_alone_sends_the_words_and_no_reason_code(self):
        sent = self._review(["--reference", "reference-a", "--action", "reject",
                             "--note", "Out of scope for this publication."])
        self.assertEqual(sent["note"], "Out of scope for this publication.")
        self.assertEqual(sent["reason_code"], "", "no code is invented for the editor's words")

    def test_a_chosen_reason_code_is_still_sent_as_chosen(self):
        sent = self._review(["--reference", "reference-a", "--action", "reject",
                             "--reason-code", "duplicate", "--note", "Already have it."])
        self.assertEqual(sent["reason_code"], "duplicate")

    def test_an_accepted_reference_needs_no_reason_at_all(self):
        sent = self._review(["--reference", "reference-a", "--action", "accept"])
        self.assertEqual(sent["reason_code"], "")

    def test_a_rejection_with_neither_words_nor_a_code_is_refused(self):
        with self.assertRaises(ValueError) as refusal:
            self._review(["--reference", "reference-a", "--action", "reject"])
        self.assertIn("--reason-code or --note", str(refusal.exception))

    def test_blank_words_are_no_reason(self):
        with self.assertRaises(ValueError):
            self._review(["--reference", "reference-a", "--action", "reject", "--note", "   "])


if __name__ == "__main__":
    unittest.main()
