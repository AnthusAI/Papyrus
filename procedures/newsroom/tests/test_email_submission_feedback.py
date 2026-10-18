from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from papyrus_newsroom import email_submission_feedback
from papyrus_newsroom.email_submissions import (
    REJECTION_KIND_UNREGISTERED_SENDER,
    UNREGISTERED_SENDER_RESPONSE_ERROR,
)


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


class EmailSubmissionFeedbackTests(unittest.TestCase):
    def test_build_reference_feedback_entries_includes_plugin_and_pdf(self):
        references = [
            {
                "id": "ref-1",
                "lineageId": "lineage-1",
                "title": "Attention Is All You Need",
                "sourceUri": "https://arxiv.org/abs/1706.03762",
            }
        ]
        attachments = [
            {
                "id": "att-source",
                "referenceLineageId": "lineage-1",
                "role": "source",
                "filename": "paper.pdf",
                "mediaType": "application/pdf",
                "storagePath": "corpora/AI-ML-research/refs/paper.pdf",
                "metadata": '{"sourcePlugin":"arxiv"}',
            },
            {
                "id": "att-text",
                "referenceLineageId": "lineage-1",
                "role": "extracted_text",
                "filename": "paper.txt",
                "mediaType": "text/plain",
                "storagePath": "corpora/AI-ML-research/refs/paper.txt",
            },
        ]
        entries = email_submission_feedback.build_reference_feedback_entries(
            references=references,
            attachments=attachments,
            find_result={"items": [{"reference": {"id": "ref-1"}, "status": "planned"}]},
            process_result={
                "items": [
                    {
                        "reference": {"id": "ref-1"},
                        "status": "generated",
                        "title": "Attention Is All You Need",
                        "subtitle": "Transformer architecture",
                        "summary": "Introduces the Transformer.",
                    }
                ]
            },
        )
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["sourcePlugin"], "arxiv")
        self.assertEqual(entry["referenceLineageId"], "lineage-1")
        self.assertEqual(
            entry["newsroomUrl"],
            "https://p.apyr.us/newsroom/references/lineage-1",
        )
        self.assertTrue(entry["pdfLocated"])
        self.assertEqual(entry["subtitle"], "Transformer architecture")
        self.assertEqual(entry["summarizeStatus"], "generated")
        self.assertEqual(len(entry["attachments"]), 2)

    def test_format_unregistered_sender_rejection_email(self):
        report = {
            "messageId": "message-email-submission-unauth",
            "subject": "Fwd: Newsletter",
            "responseStatus": "REJECTED",
            "responseError": UNREGISTERED_SENDER_RESPONSE_ERROR,
            "authorized": False,
            "rejectionKind": REJECTION_KIND_UNREGISTERED_SENDER,
            "recipientEmail": "submissions@p.apyr.us",
        }
        subject, body, html_body = email_submission_feedback.format_submission_feedback_email(report)
        self.assertIn("submission not accepted", subject)
        self.assertIn("only registered Papyrus users", body)
        self.assertIn("submissions@p.apyr.us", body)
        self.assertIn("https://p.apyr.us", body)
        self.assertNotIn("Pipeline:", body)
        self.assertIn("Submission not accepted", html_body)
        self.assertIn("Sign in to Papyrus", html_body)

    def test_maybe_send_unregistered_sender_rejection(self):
        client = mock.Mock()
        client.get_record.return_value = {
            "id": "message-email-submission-unauth",
            "summary": "Paper",
            "responseStatus": "REJECTED",
            "responseError": UNREGISTERED_SENDER_RESPONSE_ERROR,
            "metadata": (
                '{"senderEmail":"stranger@example.com","authorized":false,'
                f'"rejectionKind":"{REJECTION_KIND_UNREGISTERED_SENDER}",'
                '"recipientEmail":"submissions@p.apyr.us"}'
            ),
        }
        ses = mock.Mock()
        ses.send_raw_email.return_value = {"MessageId": "ses-unauth"}
        with mock.patch.dict(
            "os.environ",
            {
                "PAPYRUS_INBOUND_FEEDBACK_EMAIL_ENABLED": "true",
                "PAPYRUS_INBOUND_FEEDBACK_FROM_EMAIL": "submissions@p.apyr.us",
            },
            clear=False,
        ):
            result = email_submission_feedback.maybe_send_submission_feedback_email(
                client,
                message_id="message-email-submission-unauth",
                processing_error=UNREGISTERED_SENDER_RESPONSE_ERROR,
                ses_client=ses,
            )
        self.assertTrue(result["sent"])
        self.assertEqual(result["to"], "stranger@example.com")
        raw_message = ses.send_raw_email.call_args.kwargs["RawMessage"]["Data"]
        self.assertIn(b"stranger@example.com", raw_message)
        self.assertIn(b"submission_not_accepted", raw_message.lower())

    def test_format_submission_feedback_email_completed(self):
        report = {
            "messageId": "message-email-submission-abc",
            "subject": "New paper",
            "responseStatus": "COMPLETED",
            "registeredReferenceCount": 1,
            "pipeline": {
                "find": {"eligible": 1, "planned": 1, "changes": 1, "failures": 0},
                "process": {"attempted": 1, "generated": 1},
            },
            "references": [
                {
                    "title": "Example",
                    "subtitle": "Sub",
                    "summary": "Sum",
                    "sourceUri": "https://example.com",
                    "newsroomUrl": "https://p.apyr.us/newsroom/references/lineage-example",
                    "sourcePlugin": "default",
                    "findStatus": "planned",
                    "summarizeStatus": "generated",
                    "pdfConfirmationRequired": False,
                    "attachments": [{"role": "source", "filename": "x.pdf"}],
                }
            ],
        }
        subject, body, html_body = email_submission_feedback.format_submission_feedback_email(report)
        self.assertIn("processed", subject)
        self.assertIn("Example", body)
        self.assertIn("https://p.apyr.us/newsroom/references/lineage-example", body)
        self.assertNotIn("Subtitle:", body)
        self.assertNotIn("Summary:", body)
        self.assertIn("Source plugin: default", body)
        self.assertIn("Open in Papyrus", html_body)
        self.assertNotIn(">Subtitle<", html_body)
        self.assertNotIn(">Summary<", html_body)
        self.assertIn("#f7f7f4", html_body)
        self.assertIn("https://p.apyr.us/newsroom/references/lineage-example", html_body)

    def test_maybe_send_skips_when_already_sent(self):
        client = mock.Mock()
        client.get_record.return_value = {
            "id": "message-1",
            "metadata": '{"feedbackEmailSentAt":"2026-01-01T00:00:00.000Z"}',
        }
        result = email_submission_feedback.maybe_send_submission_feedback_email(
            client,
            message_id="message-1",
        )
        self.assertFalse(result["sent"])
        self.assertEqual(result["reason"], "already-sent")
        client.graphql.assert_not_called()

    def test_maybe_send_records_metadata_on_success(self):
        client = mock.Mock()
        client.get_record.return_value = {
            "id": "message-1",
            "summary": "Paper link",
            "responseStatus": "COMPLETED",
            "metadata": '{"senderEmail":"editor@example.com","authorized":true}',
        }
        ses = mock.Mock()
        ses.send_raw_email.return_value = {"MessageId": "ses-123"}
        with mock.patch.dict(
            "os.environ",
            {
                "PAPYRUS_INBOUND_FEEDBACK_EMAIL_ENABLED": "true",
                "PAPYRUS_INBOUND_FEEDBACK_FROM_EMAIL": "submissions@p.apyr.us",
            },
            clear=False,
        ):
            result = email_submission_feedback.maybe_send_submission_feedback_email(
                client,
                message_id="message-1",
                processing_result={"registeredReferenceCount": 0},
                ses_client=ses,
            )
        self.assertTrue(result["sent"])
        ses.send_raw_email.assert_called_once()
        raw_message = ses.send_raw_email.call_args.kwargs["RawMessage"]["Data"]
        self.assertIn(b"Message-ID:", raw_message)
        email_body = b""
        self.assertIn(b"multipart/alternative", raw_message)
        client.graphql.assert_called_once()

    def test_reference_entry_is_receipt_ready_requires_metadata(self):
        ready = {
            "title": "Real Title",
            "subtitle": "Real Subtitle",
            "summary": "Real summary text.",
            "sourceUri": "https://arxiv.org/abs/2603.06674",
        }
        self.assertTrue(email_submission_feedback.reference_entry_is_receipt_ready(ready))
        placeholder = {
            "title": "2603.06674",
            "subtitle": "Sub",
            "summary": "Sum",
            "sourceUri": "https://arxiv.org/abs/2603.06674",
        }
        self.assertFalse(email_submission_feedback.reference_entry_is_receipt_ready(placeholder))

    def test_maybe_send_defers_until_references_enriched(self):
        client = mock.Mock()
        client.get_record.return_value = {
            "id": "message-1",
            "summary": "Paper",
            "responseStatus": "COMPLETED",
            "metadata": json.dumps(
                {
                    "senderEmail": "editor@example.com",
                    "authorized": True,
                    "processingResult": {"registeredReferenceIds": ["ref-1"]},
                }
            ),
        }
        with mock.patch.dict("os.environ", {"PAPYRUS_INBOUND_FEEDBACK_EMAIL_ENABLED": "true"}, clear=False):
            with mock.patch.object(
                email_submission_feedback,
                "prepare_reference_entries_for_feedback",
                return_value=[
                    {
                        "title": "2603.06674",
                        "subtitle": "Sub",
                        "summary": "Sum",
                        "sourceUri": "https://arxiv.org/abs/2603.06674",
                    }
                ],
            ):
                result = email_submission_feedback.maybe_send_submission_feedback_email(
                    client,
                    message_id="message-1",
                    processing_result={"registeredReferenceIds": ["ref-1"]},
                )
        self.assertFalse(result["sent"])
        self.assertEqual(result["reason"], "deferred-awaiting-enrichment")
        client.graphql.assert_called_once()


if __name__ == "__main__":
    unittest.main()
