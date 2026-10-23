from email.message import EmailMessage
from pathlib import Path

import pytest

from papyrus_content.email_submission import (
    SubmissionRejected,
    extract_submission,
    safe_editorial_url,
)

FIXTURE = Path(__file__).resolve().parents[3] / "features_backend/fixtures/email-submission/newsletter.eml"


def message(body, **headers):
    email = EmailMessage()
    email["From"] = "editor@example.org"
    email["To"] = "submissions@example.net"
    email["Subject"] = "Reading"
    for name, value in headers.items():
        email[name.replace("_", "-")] = value
    email.set_content(body)
    return email.as_bytes()


def urls(raw):
    return [link["url"] for link in extract_submission(raw)["links"]]


def test_multipart_editorial_links_only():
    result = extract_submission(FIXTURE.read_bytes())
    assert [link["url"] for link in result["links"]] == [
        "https://example.org/articles/one", "https://example.org/articles/two?id=23"]
    assert result["sender"] == "editor@example.org"
    assert result["recipients"] == ["submissions@example.net"]
    assert result["links"][0]["title"] == "One"
    assert "body" not in result
    assert "authentication" not in result


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/x", "http://[::1]/x", "http://169.254.169.254/latest/meta-data",
    "http://2130706433/x", "http://0x7f000001/x", "http://0177.0.0.1/x",
    "https://localhost/x", "https://host.local/x", "https://host.internal/x",
    "https://user:pass@example.org/x", "https://example.org:8443/x", "file:///etc/passwd",
    "https://example.org/%75nsubscribe", "https://example.org/%2575nsubscribe",
    "https://example.org/login", "https://example.org/reset-password", "https://example.org/oauth/callback",
    "https://example.org/x?token=secret", "https://example.org/x?X-Amz-Signature=secret",
    "https://example.org/x?email=editor%40example.org", "https://example.org/x?key=secret",
    "https://example.org/x?redirect=https%3A%2F%2Fexample.net%2Farticle",
    "https://example.org/x?%2574oken=secret",
    "https://example.org/?action=unsubscribe&id=123",
    "https://example.org/?action=confirm&user=123",
    "https://example.org/?mode=reset-password",
    "https://example.org/?operation=login",
    "https://example.org/?command=activate",
    "https://example.org/AbCdEfGhIjKlMnOpQrStUvWxYz1234567890",
    "https://example.org/x?id=AbCdEfGhIjKlMnOpQrStUvWxYz1234567890",
    "https://tracking.example.org/x", "https://example.org/click/abc", "https://example.org/open.gif",
])
def test_action_secret_and_non_public_urls_excluded(url):
    assert safe_editorial_url(url) is None
    assert urls(message(url)) == []


def test_canonicalization_and_plain_punctuation():
    assert urls(message("See (https://EXAMPLE.org:443/article?z=2&utm_source=mail&a=1#top).\n"
                        "https://example.org/article?a=1&z=2")) == ["https://example.org/article?a=1&z=2"]


def test_balanced_parentheses_in_an_editorial_url_are_preserved():
    assert urls(message("(https://example.org/article_(journal)).")) == ["https://example.org/article_(journal)"]


def test_fallback_link_title_is_bounded():
    result = extract_submission(message("https://example.org/" + "read/" * 100))
    assert len(result["links"][0]["title"]) == 256


def test_base64_and_quoted_printable_text_are_decoded():
    email = EmailMessage()
    email["From"] = "editor@example.org"
    email.set_content("https://example.org/one", cte="base64")
    email.add_alternative('<a href="https://example.org/two">Caf\u00e9</a>', subtype="html", cte="quoted-printable")
    assert urls(email.as_bytes()) == ["https://example.org/one", "https://example.org/two"]


@pytest.mark.parametrize("headers", [
    {"Auto_Submitted": "auto-generated"}, {"Auto_Submitted": "auto-replied"},
    {"X_Papyrus_Submission": "processed"}, {"Return_Path": "<>"},
])
def test_loop_prevention(headers):
    with pytest.raises(SubmissionRejected, match="automated_message"):
        extract_submission(message("https://example.org/article", **headers))


def test_newsletters_and_explicit_manual_submission_allowed():
    assert urls(message("https://example.org/article", Auto_Submitted="no", Precedence="bulk",
                        List_ID="Weekly <weekly.example.org>")) == ["https://example.org/article"]


def test_forwarded_message_attachment_contributes_links_without_authorizing_from():
    outer = EmailMessage()
    outer["From"] = "editor@example.org"
    outer.set_content("https://example.org/one")
    attached = EmailMessage()
    attached.set_content("https://example.org/attached")
    outer.add_attachment(attached)
    assert urls(outer.as_bytes()) == ["https://example.org/one", "https://example.org/attached"]


@pytest.mark.parametrize("raw,code", [
    (b"x" * 1048577, "message_too_large"),
    (b"From: a@example.org\nFrom: b@example.org\n\nhttps://example.org/x", "invalid_sender"),
    (b"From: a@example.org, b@example.org\n\nhttps://example.org/x", "invalid_sender"),
    (b"From: a@example.org\nContent-Type: multipart/mixed; boundary=missing\n\nbody", "malformed_mime"),
    (b"From: a@example.org\nContent-Type: text/plain; charset=utf-8\n\n\xff", "invalid_encoding"),
    (b"From: a@example.org\nContent-Type: text/plain; charset=unrecognized\n\ntext", "invalid_encoding"),
    (b"From: a@example.org\nContent-Type: multipart/report; report-type=delivery-status\n\nbody", "automated_message"),
])
def test_malformed_or_oversize_message_is_rejected(raw, code):
    with pytest.raises(SubmissionRejected) as error:
        extract_submission(raw)
    assert error.value.code == code


def test_link_ceiling_refuses_without_partial_results():
    with pytest.raises(SubmissionRejected, match="too_many_links"):
        extract_submission(message("\n".join(f"https://example.org/article/{n}" for n in range(26))))


def test_mime_part_ceiling():
    email = EmailMessage()
    email["From"] = "editor@example.org"
    email.make_mixed()
    for i in range(64):
        part = EmailMessage()
        part.set_content(str(i))
        email.attach(part)
    with pytest.raises(SubmissionRejected, match="too_many_mime_parts"):
        extract_submission(email.as_bytes())


def test_mime_depth_ceiling():
    root = EmailMessage()
    root["From"] = "editor@example.org"
    current = root
    for _ in range(13):
        current.make_mixed()
        child = EmailMessage()
        current.attach(child)
        current = child
    current.set_content("https://example.org/article")
    with pytest.raises(SubmissionRejected, match="mime_too_deep"):
        extract_submission(root.as_bytes())


def test_link_labels_do_not_smuggle_account_actions():
    email = EmailMessage()
    email["From"] = "editor@example.org"
    email.set_content('<a href="https://example.org/opaque">Unsubscribe</a>'
                      '<a href="https://example.org/other">Manage your preferences</a>', subtype="html")
    assert urls(email.as_bytes()) == []


def test_classifier_link_titles_do_not_retain_urls_addresses_or_secret_values():
    email = EmailMessage()
    email["From"] = "editor@example.org"
    email.set_content('<a href="https://example.org/article">Research notes '
                      'https://private.example.org/download?token=hidden '
                      'editor@example.org token=secret AbCdEfGhIjKlMnOpQrStUvWxYz1234567890</a>', subtype="html")
    result = extract_submission(email.as_bytes())
    assert result["links"] == [{"url": "https://example.org/article", "title": "Research notes"}]
