from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.site_store import SiteStore  # noqa: E402
from papyrus_content.site_store_test import FakeS3, FakeTable  # noqa: E402

BRAND_KEY = "tenants/alpha/site/brand/{}.json"


def _store(context):
    context.s3, context.catalogue = FakeS3(), FakeTable()
    context.events = []
    context.site_store = SiteStore(context.s3, "bucket", context.catalogue, now=lambda: "2026-11-13T00:00:00Z")
    original_put, original_create, original_update = context.s3.put_object, context.catalogue.create, context.catalogue.update_if
    context.s3.put_object = lambda **kw: (original_put(**kw), context.events.append(("object", kw["Key"])))[0]
    context.catalogue.create = lambda model, row: (original_create(model, row), context.events.append((model, row["id"])))[0]

    def update_if(model, row_id, changes, expected):
        saved = original_update(model, row_id, changes, expected)
        if saved:
            context.events.append((model, row_id, changes["currentVersion"]))
        return saved

    context.catalogue.update_if = update_if


def _seed(context, versions):
    _store(context)
    for number in range(1, versions + 1):
        context.site_store.save("alpha", "brand", {"colour": f"colour-{number}"}, "ada")
    context.events.clear()


@given('"alpha" has brand version {version:d}')
def brand_at_version(context, version):
    _seed(context, version)


@given('"alpha" has brand versions 1 to {last:d}')
def brand_versions(context, last):
    _seed(context, last)


@when("an admin saves new colours")
def save_colours(context):
    context.saved = context.site_store.save("alpha", "brand", {"colour": "new"}, "ada")


@when("an admin restores version {version:d}")
def restore_version(context, version):
    context.saved = context.site_store.restore("alpha", "brand", version, "ada")


@then("version {version:d} is written to S3 and SiteDocument points at it only after the object exists")
def object_before_pointer(context, version):
    assert context.saved == version
    assert context.events == [
        ("object", BRAND_KEY.format(version)),
        ("SiteDocumentVersion", f"alpha#brand#{version}"),
        ("SiteDocument", "alpha#brand", version),
    ], context.events
    assert context.site_store.read_current("alpha", "brand") == {"colour": "new"}


@then("version {version:d} is written with version {source:d}'s content")
def restored_content(context, version, source):
    assert context.saved == version
    assert context.site_store.current_version("alpha", "brand") == version
    assert context.site_store.read_current("alpha", "brand") == {"colour": f"colour-{source}"}
    assert context.site_store.read_version("alpha", "brand", 4) == {"colour": "colour-4"}


@when("a save of new colours fails after its object is written but before the pointer moves")
def failed_save(context):
    context.catalogue.fail_create = "SiteDocumentVersion"
    context.failure = None
    try:
        context.site_store.save("alpha", "brand", {"colour": "new"}, "ada")
    except OSError as error:
        context.failure = error
    context.catalogue.fail_create = None
    assert context.failure is not None


@then("the brand is still version 3 and the failed save is not live")
def old_version_live(context):
    assert ("bucket", BRAND_KEY.format(4)) in context.s3.objects
    assert context.site_store.current_version("alpha", "brand") == 3
    assert context.site_store.read_current("alpha", "brand") == {"colour": "colour-3"}


@then("the next save takes version 4 and replaces the leftover object")
def next_save_skips_leftover(context):
    # The leftover object has no version row, so no version 4 exists; the next save writes it again.
    assert context.site_store.save("alpha", "brand", {"colour": "retry"}, "ada") == 4
    assert context.site_store.read_current("alpha", "brand") == {"colour": "retry"}
