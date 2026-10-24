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


@given("a submitted newsletter containing 41 unique editorial links")
def excessive_newsletter(context):
    context.email_submission_raw = _message("\n".join(f"https://example.org/article/{i}" for i in range(41)))


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


@then("all 41 eligible links are retained for resumable intake")
def all_candidates_retained(context):
    assert context.email_submission_error is None
    assert len(context.email_submission["links"]) == 41


@given("a synthetic Beehiiv article link and an unsubscribe action link")
def synthetic_tracker_newsletter(context):
    context.email_submission_raw = _message(
        '<a href="https://link.mail.beehiiv.com/ss/c/opaque?id=article">Read story</a>'
        '<a href="https://link.mail.beehiiv.com/ss/c/opaque?id=unsubscribe">Unsubscribe</a>',
        "Content-Type: text/html\n")


@when("Papyrus extracts with an offline synthetic redirect adapter")
def extract_with_synthetic_adapter(context):
    from papyrus_content.email_submission import extract_submission, resolve_beehiiv_tracking_url

    requests = []

    def request(url, **options):
        requests.append((url, options))
        if len(requests) == 1:
            return {"status": 302, "headers": {"Location": "https://news.example.org/story?utm_source=mail"}}
        return {"status": 200, "headers": {}}

    def resolver(url):
        return resolve_beehiiv_tracking_url(
            url, resolve_host=lambda *_args, **_kwargs: ["93.184.216.34"], request=request, clock=lambda: 0)

    context.email_submission = extract_submission(context.email_submission_raw, tracking_resolver=resolver)
    context.email_submission_requests = requests


@then("only the normalized final article URL is retained")
def only_normalized_article_retained(context):
    assert context.email_submission["links"] == [
        {"url": "https://news.example.org/story", "title": "Read story"}]
    assert "link.mail.beehiiv.com" not in repr(context.email_submission)


@then("the adapter pins public addresses without following redirects or reading bodies")
def redirect_adapter_is_bounded(context):
    requests = context.email_submission_requests
    assert len(requests) == 2
    assert all(options["connect_addresses"] == ("93.184.216.34",) for _, options in requests)
    assert all(options["allow_redirects"] is False for _, options in requests)
    assert all(options["method"] == "HEAD" and options["read_body"] is False for _, options in requests)
