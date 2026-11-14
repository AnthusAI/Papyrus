"""Inbound email reports a filing it could not do (features_backend/no-fallbacks-email-intake.feature). The backend and the filing are stand-ins."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_newsroom import email_submission_replies as replies  # noqa: E402
from papyrus_newsroom import email_submissions  # noqa: E402


class _Client:
    def __init__(self, message):
        self.message = message
        self.updates = []

    def get_record(self, model, record_id):
        return self.message

    def graphql(self, query, variables=None):
        self.updates.append(variables)
        return {}


def held(context) -> SimpleNamespace:
    if not hasattr(context, "intake"):
        context.intake = SimpleNamespace(client=None, classification=None, result=None, feedback=[], chat_started=False)
    return context.intake


def _given(context, classification):
    state = held(context)
    state.classification = classification
    metadata = {"authorized": True, "intakeClassification": classification, "parentSubmissionMessageId": "parent-1"}
    import json

    state.client = _Client({"id": "message-1", "metadata": json.dumps(metadata)})


@given("an authorized PDF-only submission whose filing fails")
def _pdf(context):
    _given(context, "pdf_only_intake")


@given("an authorized attachment-only reply whose filing fails")
def _attachment(context):
    _given(context, "attachment_only_reply")


@when("the submission is processed")
def _process(context):
    state = held(context)
    envelope = SimpleNamespace(body_text="", html_parts=[], attachments=[], in_reply_to=None, references_header=None, subject="s")

    def chat(*args, **kwargs):
        state.chat_started = True
        return {}

    def feedback(client, **kwargs):
        state.feedback.append(kwargs)
        return {"sent": True}

    with mock.patch.object(replies, "load_inbound_mime_envelope_from_metadata", return_value=envelope), \
            mock.patch.object(replies, "enqueue_console_chat_for_email_reply", chat), \
            mock.patch.object(replies, "enqueue_console_chat_for_email_intake", chat), \
            mock.patch.object(replies, "try_file_attachment_only_reply", return_value={"ok": False, "reason": "no-registered-reference"}), \
            mock.patch("papyrus_newsroom.email_pdf_intake.process_pdf_only_intake", return_value={"ok": False, "reason": "unreadable-pdf"}), \
            mock.patch.object(email_submissions, "_try_send_submission_feedback", feedback), \
            mock.patch.object(email_submissions, "_mark_message_processing", lambda *a, **k: None):
        state.result = replies.process_inbound_email_submission(state.client, message_id="message-1", corpus_key="example", apply=False)


@then("the message is marked failed with the filing's reason")
def _failed(context):
    state = held(context)
    reason = "no-registered-reference" if state.classification == "attachment_only_reply" else "unreadable-pdf"
    assert state.result["status"] == "failed" and reason in state.result["error"], state.result
    marked = [update["input"] for update in state.client.updates if update and update.get("input", {}).get("status") == "failed"]
    assert marked and reason in marked[0]["responseError"], state.client.updates


@then("the sender is sent that reason")
def _sent(context):
    state = held(context)
    assert len(state.feedback) == 1 and state.feedback[0]["processing_error"] == state.result["error"]


@then("no chat agent is started for it")
def _no_chat(context):
    assert not held(context).chat_started


@given("the inbound MIME reader test for the Lambda")
def _node_test(context):
    held(context)


@when("it reads a phone's single-part message, a nested multipart message with an attachment, an HTML-only message and a message with no text")
def _run_node(context):
    import subprocess

    held(context).node = subprocess.run(
        ["node", "amplify/functions/shared/email-mime-intake.test.mjs"], cwd=REPO_ROOT, capture_output=True, text=True)


@then("the text and links come from the message's own text parts only, and a message with no text part yields no body and no links")
def _node_ok(context):
    node = held(context).node
    assert node.returncode == 0 and "multipart ok" in node.stdout, node.stdout + node.stderr
