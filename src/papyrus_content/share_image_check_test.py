"""The share-picture check (features_backend/lens-check.feature has the narrative). The network is always a fake."""

import pytest

from papyrus_content import lens_evidence as evidence
from papyrus_content.lens_evidence_test import live_site, row
from papyrus_content.share_image_check import Fetched, ShareImageUnavailable, assess_share_image, dimensions, sniff_format
from papyrus_content.share_image_samples import sample_image

URL = "https://example.test/assets/share.jpg"


def serving(image_format="jpeg", width=1200, height=630, content_type=None, status=200):
    mime = content_type if content_type is not None else f"image/{image_format}"
    return lambda url: Fetched(status, mime, sample_image(image_format, width, height) if status == 200 else b"")


def test_the_samples_are_read_back_by_format_and_size():
    for image_format in ("jpeg", "png", "webp"):
        body = sample_image(image_format, 1200, 630)
        assert sniff_format(body) == image_format and dimensions(body, image_format) == (1200, 630)


def test_a_missing_picture_is_a_warning():
    verdict = assess_share_image(None, serving())
    assert verdict.result == "warning" and "no picture" in verdict.message


@pytest.mark.parametrize("url", ["/assets/share.jpg", "http://example.test/share.jpg", "https:///share.jpg", "not a url"])
def test_an_address_that_is_not_absolute_https_is_a_warning(url):
    assert assess_share_image(url, serving()).result == "warning"


def test_no_fetcher_is_not_verified_never_a_pass():
    verdict = assess_share_image(URL, None)
    assert verdict.result == "not_verified" and "not verified" in verdict.message


def test_an_unavailable_network_is_not_verified():
    def down(url):
        raise ShareImageUnavailable("name not resolved")

    verdict = assess_share_image(URL, down)
    assert verdict.result == "not_verified" and "name not resolved" in verdict.message


def test_a_missing_file_is_a_warning():
    verdict = assess_share_image(URL, serving(status=404))
    assert verdict.result == "warning" and verdict.evidence["status"] == 404


def test_a_page_served_as_html_is_a_bad_type():
    verdict = assess_share_image(URL, lambda url: Fetched(200, "text/html; charset=utf-8", b"<html></html>"))
    assert verdict.result == "warning" and "not an image" in verdict.message


def test_a_type_that_does_not_match_the_file_is_a_warning():
    verdict = assess_share_image(URL, serving("png", content_type="image/jpeg"))
    assert verdict.result == "warning" and "does not match" in verdict.evidence["note"]


def test_a_small_picture_is_a_warning():
    verdict = assess_share_image(URL, serving("jpeg", 300, 157))
    assert verdict.result == "warning" and "smaller" in verdict.message


def test_a_picture_with_an_odd_shape_is_a_warning():
    assert assess_share_image(URL, serving("png", 1000, 1000)).result == "warning"


@pytest.mark.parametrize("image_format", ["jpeg", "png"])
def test_a_large_jpeg_or_png_is_ok_and_records_what_was_seen(image_format):
    verdict = assess_share_image(URL, serving(image_format, 1200, 630))
    assert verdict.result == "ok"
    assert verdict.evidence["format"] == image_format and (verdict.evidence["width"], verdict.evidence["height"]) == (1200, 630)
    assert URL in verdict.tested and "1200x630" in verdict.tested and "result ok" in verdict.tested


def test_a_webp_is_a_compatibility_warning_not_a_failure_claim():
    verdict = assess_share_image(URL, serving("webp", 912, 572))
    assert verdict.result == "warning" and "JPEG or PNG" in verdict.message and "not proof of failure" in verdict.message
    assert verdict.evidence["width"] == 912


# --- through the lens check ----------------------------------------------------------------------------------------------------------

FRONT = "title: Board refuses\nsummary: The board refused it.\ndate: 2026-03-03\nauthor: Dana Reyes\nimage: /assets/share.webp\nimageAlt: A harbour\n"


def c4(front=FRONT, fetch=None):
    story = evidence.story_from_row(row("The board refused it.\n", front))
    return next(found for found in evidence.run_checks(story, live_site(), lens="social", fetch_image=fetch) if found["check"] == "C4")


def test_c4_is_not_assessable_without_a_fetcher_even_though_c1_can_build_the_address():
    story = evidence.story_from_row(row("The board refused it.\n", FRONT))
    found = {each["check"]: each for each in evidence.run_checks(story, live_site(), lens="social")}
    assert found["C1"]["state"] == "pass" and found["C4"]["state"] == "not_assessable"


def test_c4_flags_webp_and_the_fetched_address_is_the_absolute_og_image():
    seen = []

    def fetch(url):
        seen.append(url)
        return serving("webp", 912, 572)(url)

    found = c4(fetch=fetch)
    assert seen == ["https://example.test/assets/share.webp"] and found["state"] == "concern" and "Record this" in found["message"]


def test_c4_passes_a_jpeg_and_has_the_note_evidence():
    found = c4(FRONT.replace("webp", "jpg"), serving("jpeg"))
    assert found["state"] == "pass" and found["evidence"]["note"].startswith("Share picture https://example.test/assets/share.jpg")


def test_c4_flags_a_story_with_no_picture():
    found = c4("title: Board refuses\nsummary: The board refused it.\ndate: 2026-03-03\nauthor: Dana Reyes\n", serving())
    assert found["state"] == "concern" and found["evidence"]["url"] is None
