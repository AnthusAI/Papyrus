from __future__ import annotations

import os
import unittest
from unittest import mock

from papyrus_newsroom import email_submission_replies


def setUpModule():
    environment_patch = mock.patch.dict(
        os.environ,
        {
            "PAPYRUS_INBOUND_EMAIL_DOMAIN": "p.apyr.us",
            "PAPYRUS_PUBLIC_SITE_BASE_URL": "https://p.apyr.us",
        },
    )
    environment_patch.start()
    unittest.addModuleCleanup(environment_patch.stop)


class EmailSubmissionReplyTests(unittest.TestCase):
    def test_parse_submission_message_id_from_rfc_message_id(self):
        resolved = email_submission_replies.parse_submission_message_id_from_rfc_message_id(
            "<message-email-submission-40ca4b073ca02d75f724@p.apyr.us>"
        )
        self.assertEqual(resolved, "message-email-submission-40ca4b073ca02d75f724")

    def test_extract_user_composed_reply_text_strips_quote(self):
        body = "Here is the PDF.\n\nOn Mon, May 31, 2026 Alice wrote:\n> quoted"
        self.assertEqual(email_submission_replies.extract_user_composed_reply_text(body), "Here is the PDF.")

    def test_classify_attachment_only_reply(self):
        classification = email_submission_replies.classify_inbound_reply(
            body_text="On Mon wrote:\n> old",
            parent_message_id="message-email-submission-abc",
            attachments=[
                email_submission_replies.InboundMimeAttachment(
                    filename="paper.pdf",
                    media_type="application/pdf",
                    payload=b"%PDF-1.4",
                )
            ],
        )
        self.assertEqual(classification, "attachment_only_reply")

    def test_classify_conversational_reply(self):
        classification = email_submission_replies.classify_inbound_reply(
            body_text="Can you use this PDF instead?",
            parent_message_id="message-email-submission-abc",
            attachments=[],
        )
        self.assertEqual(classification, "conversational_reply")

    def test_classify_newsletter_forward_as_agent_intake(self):
        citations = [
            {"url": "https://arxiv.org/abs/1"},
            {"url": "https://arxiv.org/abs/2"},
        ]
        body = "Intro paragraph about both papers.\n\n" + "\n".join(row["url"] for row in citations)
        self.assertEqual(
            email_submission_replies.classify_new_submission_intake(body, citations),
            "agent_intake",
        )

    def test_classify_message_plus_single_url_as_agent_intake(self):
        citations = [{"url": "https://arxiv.org/abs/1706.03762"}]
        body = (
            "Please file this transformer paper. The authors argue attention is all you need, "
            "and I think we should track follow-up work on sparse attention variants too."
        )
        self.assertEqual(
            email_submission_replies.classify_new_submission_intake(body, citations),
            "agent_intake",
        )

    def test_classify_single_url_only_as_direct_intake(self):
        citations = [{"url": "https://arxiv.org/abs/1706.03762"}]
        self.assertEqual(
            email_submission_replies.classify_new_submission_intake(
                "https://arxiv.org/abs/1706.03762",
                citations,
            ),
            "direct_citation_intake",
        )

    def test_classify_single_pdf_only_as_pdf_only_intake(self):
        pdf = email_submission_replies.InboundMimeAttachment(
            filename="paper.pdf",
            media_type="application/pdf",
            payload=b"%PDF-1.4",
        )
        self.assertEqual(
            email_submission_replies.classify_new_submission_intake("", [], [pdf]),
            "pdf_only_intake",
        )

    def test_classify_pdf_plus_url_as_agent_intake(self):
        pdf = email_submission_replies.InboundMimeAttachment(
            filename="paper.pdf",
            media_type="application/pdf",
            payload=b"%PDF-1.4",
        )
        citations = [{"url": "https://arxiv.org/abs/1706.03762"}]
        self.assertEqual(
            email_submission_replies.classify_new_submission_intake(
                "https://arxiv.org/abs/1706.03762",
                citations,
                [pdf],
            ),
            "agent_intake",
        )

    def test_feedback_rfc_message_id(self):
        with unittest.mock.patch.dict(
            "os.environ",
            {"PAPYRUS_INBOUND_EMAIL_DOMAIN": "p.apyr.us"},
            clear=False,
        ):
            value = email_submission_replies.feedback_rfc_message_id("message-email-submission-abc")
        self.assertEqual(value, "<message-email-submission-abc@p.apyr.us>")


if __name__ == "__main__":
    unittest.main()
