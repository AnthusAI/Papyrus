import os
from email.message import EmailMessage
from unittest.mock import patch

from behave import given, then, when

from papyrus_newsroom.email_mime_intake import extract_direct_citations_from_intake_text
from papyrus_newsroom.email_submission_replies import (
    classify_inbound_email_intake,
    extract_user_composed_reply_text,
    feedback_rfc_message_id,
    parse_inbound_mime_envelope,
    resolve_parent_submission_message_id,
)

HANDLING_IN_WORDS_BY_ROUTE = {
    "direct_citation_intake": "filed directly as a Reference",
    "pdf_only_intake": "filed directly as an attached paper",
    "agent_intake": "handed to the email agent",
    "new_submission": "treated as a submission with no sources",
    "conversational_reply": "continued as a conversation with the agent",
    "attachment_only_reply": "filed as the paper for the earlier submission",
    "empty_reply": "ignored as an empty answer",
}
PROSE_BY_DESCRIPTION = {
    "no prose": "",
    "a short note": "Worth a look.",
    "a long commentary": (
        "This study changes how I read the earlier results on reader trust. "
        "The sample is three times larger than anything published before it, "
        "and the authors release their survey instrument for others to reuse."
    ),
}
SUBMISSION_AN_ANSWER_CONTINUES = "message-email-submission-0123456789abcdef0123"
QUOTED_RECEIPT = "On Tue, 3 Nov 2026 at 09:14, Papyrus wrote:\n> We filed 2 References from your message."
SMALLEST_PDF_BYTES = b"%PDF-1.4\n%%EOF\n"


def new_email(body_text: str, attached_paper_count: int, headers: dict[str, str] | None = None) -> bytes:
    message = EmailMessage()
    message["From"] = "Reader <reader@mail.example>"
    message["To"] = "newsroom@newsroom.example.org"
    message["Subject"] = "For the newsroom"
    for header_name, header_value in (headers or {}).items():
        message[header_name] = header_value
    message.set_content(body_text or "\n")
    for paper_number in range(attached_paper_count):
        message.add_attachment(
            SMALLEST_PDF_BYTES,
            maintype="application",
            subtype="pdf",
            filename=f"paper-{paper_number + 1}.pdf",
        )
    return message.as_bytes()


@given("a first email to the newsroom with {link_count:d} links, {paper_count:d} attached papers and {prose_description}")
def first_email_to_the_newsroom(context, link_count, paper_count, prose_description):
    links = "\n".join(f"https://journal.example/articles/{number + 1}" for number in range(link_count))
    body_text = "\n\n".join(part for part in (PROSE_BY_DESCRIPTION[prose_description], links) if part)
    context.raw_email = new_email(body_text, paper_count)


@given('the receipt for submission "{submission_message_id}" was mailed from "{inbound_domain}"')
def receipt_was_mailed(context, submission_message_id, inbound_domain):
    with patch.dict(os.environ, {"PAPYRUS_INBOUND_EMAIL_DOMAIN": inbound_domain}):
        context.receipt_rfc_message_id = feedback_rfc_message_id(submission_message_id)
    assert context.receipt_rfc_message_id == f"<{submission_message_id}@{inbound_domain}>"


@given('an answer whose "{header_name}" header is "{header_value}"')
def answer_with_header(context, header_name, header_value):
    context.raw_email = new_email("Thanks, one more question.", 0, {header_name: header_value})


@given('an answer to a receipt in which the sender typed "{typed_text}" above the quoted receipt')
def answer_with_typed_text(context, typed_text):
    context.answer_body_text = f"{typed_text}\n\n{QUOTED_RECEIPT}"


@given('an answer to a receipt in which the sender typed "" above the quoted receipt')
def answer_with_nothing_typed(context):
    context.answer_body_text = QUOTED_RECEIPT


@given("the answer carries {paper_count:d} attached papers")
def answer_carries_papers(context, paper_count):
    context.raw_email = new_email(
        context.answer_body_text,
        paper_count,
        {"In-Reply-To": f"<{SUBMISSION_AN_ANSWER_CONTINUES}@newsroom.example.org>"},
    )


@given('an answer to a receipt in which the sender typed "{typed_text}" above a quotation that begins "{quotation_opening}"')
def answer_above_a_quotation(context, typed_text, quotation_opening):
    context.answer_body_text = f"{typed_text}\n\n{quotation_opening}\n> Earlier words that are not the sender's."


@when("Papyrus decides how to handle the email")
def papyrus_decides_how_to_handle_the_email(context):
    envelope = parse_inbound_mime_envelope(context.raw_email)
    context.submission_the_email_continues = resolve_parent_submission_message_id(
        in_reply_to=envelope.in_reply_to,
        references_header=envelope.references_header,
    )
    context.route = classify_inbound_email_intake(
        body_text=envelope.body_text,
        citations=extract_direct_citations_from_intake_text(
            body_text=envelope.body_text,
            html_parts=list(envelope.html_parts),
        ),
        parent_message_id=context.submission_the_email_continues,
        attachments=envelope.attachments,
    )


@when("Papyrus reads what the sender wrote")
def papyrus_reads_what_the_sender_wrote(context):
    context.words_of_the_sender = extract_user_composed_reply_text(context.answer_body_text)


@then("Papyrus decides the email is to be {handling_in_words}")
def email_is_handled(context, handling_in_words):
    assert HANDLING_IN_WORDS_BY_ROUTE[context.route] == handling_in_words, (context.route, handling_in_words)


@then('the email continues submission "{submission_message_id}"')
def email_continues_submission(context, submission_message_id):
    expected = None if submission_message_id == "nothing" else submission_message_id
    assert context.submission_the_email_continues == expected, context.submission_the_email_continues


@then('the sender\'s words are exactly "{expected_words}"')
def words_of_the_sender_are(context, expected_words):
    assert context.words_of_the_sender == expected_words, context.words_of_the_sender
