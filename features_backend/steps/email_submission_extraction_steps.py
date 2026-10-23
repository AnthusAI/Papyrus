from pathlib import Path

from behave import given, then, when


def _message(body, headers=""):
    return ("From: editor@example.org\nTo: submissions@example.net\n"
            "Subject: Reading\n" + headers + "\n" + body).encode()


@given("a submitted multipart newsletter with editorial links and account actions")
def multipart_newsletter(context):
    fixture = Path(__file__).parents[1] / "fixtures/email-submission/newsletter.eml"
    context.email_submission_raw = fixture.read_bytes()


@given("a submitted plain text newsletter with duplicate tracking variants")
def duplicate_newsletter(context):
    context.email_submission_raw = _message(
        "https://example.org/article?utm_source=mail#top\n"
        "https://example.org/article?fbclid=tracking\nhttps://example.org/article")


@given("a submitted automatic response containing an editorial link")
def auto_newsletter(context):
    context.email_submission_raw = _message("https://example.org/article", "Auto-Submitted: auto-replied\n")


@given("a submitted newsletter containing more than the permitted editorial links")
def excessive_newsletter(context):
    context.email_submission_raw = _message("\n".join(f"https://example.org/article/{i}" for i in range(26)))


@when("Papyrus extracts the email submission")
def extract_email(context):
    from papyrus_content.email_submission import SubmissionRejected, extract_submission
    context.email_submission_error = None
    try:
        context.email_submission = extract_submission(context.email_submission_raw)
    except SubmissionRejected as error:
        context.email_submission_error = error.code


@then("the submission has two distinct editorial links and sender provenance")
def extracted_newsletter(context):
    assert context.email_submission_error is None
    submission = context.email_submission
    assert [link["url"] for link in submission["links"]] == [
        "https://example.org/articles/one", "https://example.org/articles/two?id=23"]
    assert submission["sender"] == "editor@example.org"
    assert submission["messageId"] == "<newsletter-001@example.org>"
    assert submission["date"] == "Fri, 23 Oct 2026 08:00:00 +0000"


@then("email instructions and attachment links are not reference candidates")
def instructions_are_data(context):
    submission = context.email_submission
    assert "body" not in submission
    assert all("attachment" not in link["url"] for link in submission["links"])
    assert "ignored_attachments" in submission["warnings"]


@then("the submission has one canonical editorial link")
def canonical_candidate(context):
    assert context.email_submission_error is None
    assert [link["url"] for link in context.email_submission["links"]] == ["https://example.org/article"]


@then('the email submission is refused with code "{code}"')
def submission_refused(context, code):
    assert context.email_submission_error == code
