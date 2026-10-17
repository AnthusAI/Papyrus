from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.preview_upload import PreviewUploadError, upload_preview  # noqa: E402
from procedures.newsroom.tests.fake_s3 import FakeS3Client  # noqa: E402


def prepare_site_directory(context) -> Path:
    context.site_dir = Path(tempfile.mkdtemp(prefix="preview-site-"))
    context.add_cleanup(__import__("shutil").rmtree, context.site_dir, True)
    context.s3_client = FakeS3Client()
    context.upload_error = None
    return context.site_dir


@given('a built site with "{first}" and "{second}"')
def built_site(context, first: str, second: str) -> None:
    site = prepare_site_directory(context)
    for relative in (first, second):
        target = site / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"<p>{relative}</p>", encoding="utf-8")


@given("an empty build directory")
def empty_build(context) -> None:
    prepare_site_directory(context)


@given('the bucket already holds "{first}" and "{second}"')
def bucket_holds(context, first: str, second: str) -> None:
    for key in (first, second):
        context.s3_client.objects[key] = {"Body": b"x", "Metadata": {}}


@when("I upload the built site to the preview prefix")
def upload(context) -> None:
    try:
        upload_preview(context.s3_client, "bucket", context.site_dir)
    except PreviewUploadError as error:
        context.upload_error = str(error)


@then('the bucket holds "{first}" and "{second}"')
def bucket_has_both(context, first: str, second: str) -> None:
    assert first in context.s3_client.objects and second in context.s3_client.objects, sorted(context.s3_client.objects)


@then('the bucket no longer holds "{key}"')
def bucket_lacks(context, key: str) -> None:
    assert key not in context.s3_client.objects, sorted(context.s3_client.objects)


@then('the bucket still holds "{key}"')
def bucket_still_has(context, key: str) -> None:
    assert key in context.s3_client.objects, sorted(context.s3_client.objects)


@then('the upload is refused with "{text}"')
def refused(context, text: str) -> None:
    assert context.upload_error and text in context.upload_error, context.upload_error
