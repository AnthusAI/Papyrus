import json
import os
from email import policy
from email.parser import BytesParser
from unittest.mock import patch

from behave import given, then, when

from papyrus_newsroom.email_submission_feedback import maybe_send_submission_feedback_email
from papyrus_newsroom.email_submission_replies import parse_submission_message_id_from_rfc_message_id
from papyrus_newsroom.email_submissions import (
    REJECTION_KIND_UNREGISTERED_SENDER,
    UNREGISTERED_SENDER_RESPONSE_ERROR,
)

SUBMISSION_MESSAGE_ID = "message-email-submission-0123456789abcdef0123"
NEWSROOM_ENVIRONMENT = {
    "PAPYRUS_INBOUND_EMAIL_DOMAIN": "newsroom.example.org",
    "PAPYRUS_PUBLIC_SITE_BASE_URL": "https://newsroom.example.org",
    "PAPYRUS_INBOUND_FEEDBACK_EMAIL_ENABLED": "true",
}


class OneStoredSubmission:
    def __init__(self, message: dict):
        self.message = message

    def get_record(self, model_name: str, record_id: str) -> dict:
        assert (model_name, record_id) == ("Message", self.message["id"])
        return dict(self.message)

    def graphql(self, query: str, variables: dict) -> dict:
        assert "updateMessage" in query
        self.message["metadata"] = variables["input"]["metadata"]
        return {"updateMessage": {"id": self.message["id"]}}

    def stored_metadata(self) -> dict:
        return json.loads(self.message["metadata"])


class MailThatWasSent:
    def __init__(self):
        self.raw_messages: list[bytes] = []

    def send_raw_email(self, *, Source: str, Destinations: list[str], RawMessage: dict) -> dict:
        self.raw_messages.append(RawMessage["Data"])
        return {"MessageId": f"sent-{len(self.raw_messages)}"}


def store_submission(context, *, subject: str, sender: str, response_status: str, metadata: dict, response_error: str = ""):
    context.submission_store = OneStoredSubmission(
        {
            "id": SUBMISSION_MESSAGE_ID,
            "summary": subject,
            "responseStatus": response_status,
            "responseError": response_error,
            "metadata": json.dumps({"senderEmail": sender, "recipientEmail": "submissions@newsroom.example.org", **metadata}),
        }
    )
    context.mail_that_was_sent = MailThatWasSent()
    context.receipt_environment = dict(NEWSROOM_ENVIRONMENT)


def the_one_receipt(context):
    assert len(context.mail_that_was_sent.raw_messages) == 1, len(context.mail_that_was_sent.raw_messages)
    return BytesParser(policy=policy.default).parsebytes(context.mail_that_was_sent.raw_messages[0])


def plain_text_of(receipt) -> str:
    return receipt.get_body(preferencelist=("plain",)).get_content()


@given('an accepted email submission "{subject}" from "{sender}" that was processed')
def accepted_submission_that_was_processed(context, subject, sender):
    store_submission(context, subject=subject, sender=sender, response_status="COMPLETED", metadata={"authorized": True})


@given('an accepted email submission "{subject}" from "{sender}" that failed with "{reason}"')
def accepted_submission_that_failed(context, subject, sender, reason):
    store_submission(
        context, subject=subject, sender=sender, response_status="FAILED", response_error=reason, metadata={"authorized": True}
    )


@given('an email submission "{subject}" from "{sender}", who is not registered')
def submission_from_a_stranger(context, subject, sender):
    store_submission(
        context,
        subject=subject,
        sender=sender,
        response_status="REJECTED",
        response_error=UNREGISTERED_SENDER_RESPONSE_ERROR,
        metadata={"authorized": False, "rejectionKind": REJECTION_KIND_UNREGISTERED_SENDER},
    )


@given('an accepted email submission "{subject}" from "{sender}" that the email agent has not filed anything from')
def accepted_submission_the_agent_is_still_reading(context, subject, sender):
    store_submission(
        context,
        subject=subject,
        sender=sender,
        response_status="IN_PROGRESS",
        metadata={"authorized": True, "intakeClassification": "agent_intake"},
    )


@given("the operator has turned receipts off")
def operator_turned_receipts_off(context):
    context.receipt_environment["PAPYRUS_INBOUND_FEEDBACK_EMAIL_ENABLED"] = "false"


@when("Papyrus reports back to the sender")
@when("Papyrus reports back to the sender again")
def papyrus_reports_back_to_the_sender(context):
    with patch.dict(os.environ, context.receipt_environment):
        context.receipt_outcome = maybe_send_submission_feedback_email(
            context.submission_store,
            message_id=SUBMISSION_MESSAGE_ID,
            ses_client=context.mail_that_was_sent,
        )


@then('one receipt is mailed to "{recipient}" with a subject ending "{subject_ending}"')
def one_receipt_is_mailed(context, recipient, subject_ending):
    receipt = the_one_receipt(context)
    assert receipt["To"] == recipient, receipt["To"]
    assert str(receipt["Subject"]).endswith(subject_ending), receipt["Subject"]


@then('an answer to the receipt goes to "{reply_address}"')
def answer_goes_to(context, reply_address):
    assert the_one_receipt(context)["Reply-To"] == reply_address, the_one_receipt(context)["Reply-To"]


@then("the receipt carries the submission's own id, so an answer continues that submission")
def receipt_carries_the_submission_id(context):
    assert parse_submission_message_id_from_rfc_message_id(the_one_receipt(context)["Message-ID"]) == SUBMISSION_MESSAGE_ID


@then("no second receipt is mailed")
def no_second_receipt(context):
    assert len(context.mail_that_was_sent.raw_messages) == 1, len(context.mail_that_was_sent.raw_messages)
    assert context.receipt_outcome["reason"] == "already-sent", context.receipt_outcome


@then('the receipt says "{expected_text}"')
def receipt_says(context, expected_text):
    assert expected_text in plain_text_of(the_one_receipt(context)), plain_text_of(the_one_receipt(context))


@then("the receipt reports no References")
def receipt_reports_no_references(context):
    assert "References registered" not in plain_text_of(the_one_receipt(context))


@then("no receipt is mailed")
def no_receipt_is_mailed(context):
    assert context.mail_that_was_sent.raw_messages == [], len(context.mail_that_was_sent.raw_messages)
    assert context.receipt_outcome["sent"] is False, context.receipt_outcome


@then("the submission records that its receipt is waiting for the agent to file References")
def submission_records_the_wait(context):
    stored_metadata = context.submission_store.stored_metadata()
    assert stored_metadata["feedbackEmailDeferred"] is True, stored_metadata
    assert stored_metadata["feedbackEmailDeferReason"] == "agent-intake-awaiting-filed-references", stored_metadata
