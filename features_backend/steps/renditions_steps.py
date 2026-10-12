from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from PIL import Image  # noqa: E402

from papyrus_content.projection.engine import ProjectionContext, project, project_all  # noqa: E402
from papyrus_content.projection.source import PublishedContentSource  # noqa: E402
from papyrus_content.projection.writers import LocalDirectoryWriter  # noqa: E402
from papyrus_content.renditions import DirectoryRenditionStore, make_renditions, meta_key, settings_from_mapping  # noqa: E402
from papyrus_content.renditions_commands import run_renditions  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402
from procedures.newsroom.tests.projection_fixtures import (  # noqa: E402
    RecordingWriter,
    WorkDirectory,
    copy_fixture_content,
    publish_content_tree,
    static_directory_for,
    tree_digests,
)
from procedures.newsroom.tests.renditions_fixtures import (  # noqa: E402
    GATSBY_IMAGE_SETTINGS,
    LEGACY_IMAGE_SETTINGS,
    NOTE_MEDIA_KEY,
    SMALL_IMAGE_PATH,
    WIDE_IMAGE_PATH,
    FakeFunctionClient,
    FakeMediaBucket,
    fixture_media,
    full_build_with_images,
    load_renditions_handler,
    projector_with_images,
    rendition_files,
    write_pictured_content,
    write_projection_settings,
)

PICTURED_SOURCES = ("images/wide.jpg", "images/small.png", "images/diagram.svg")


def media_rows_for(item_id: str, media: dict[str, bytes]) -> list[dict]:
    return [
        {
            "id": f"media-{index}",
            "itemId": item_id,
            "type": "image",
            "sortKey": f"{index:03d}",
            "storagePath": f"media/{source}",
            "metadata": json.dumps({"srcPath": source}),
        }
        for index, source in enumerate(sorted(media))
    ]


def prepare_pictured_site(context, image_settings: dict) -> None:
    context.work = WorkDirectory()
    context.add_cleanup(context.work.cleanup)
    context.image_settings = image_settings
    context.media = fixture_media()
    context.content_root = copy_fixture_content(context.work.root)
    write_pictured_content(context.content_root, context.media)
    context.client = FakeAuthoringClient({"MediaAsset": media_rows_for("item-articles-pictured", context.media)})
    context.static_directory = static_directory_for(context.content_root, context.work.root)
    context.site_store_root = context.work.root / "site-store"
    context.store = DirectoryRenditionStore(context.site_store_root)
    context.projector = projector_with_images(context.static_directory, image_settings, context.store)
    context.projected_root = context.work.root / "projected"
    context.writer = RecordingWriter(context.projected_root)
    context.projection = ProjectionContext(
        source=PublishedContentSource(context.client), projector=context.projector, writer=context.writer
    )
    context.error = None
    publish_content_tree(context.client, context.content_root)


def make_all_renditions(context) -> None:
    settings = settings_from_mapping(context.image_settings)
    context.written_by_source = {
        source: make_renditions(settings, context.store, source, data) for source, data in context.media.items()
    }


@given("a pictured article and its images are published")
def pictured_site_published(context) -> None:
    prepare_pictured_site(context, GATSBY_IMAGE_SETTINGS)


@given("a pictured article and its images are published with the legacy image pipeline")
def pictured_site_published_legacy(context) -> None:
    prepare_pictured_site(context, LEGACY_IMAGE_SETTINGS)


@given("the images are uploaded and renditions are made")
@when("the images are uploaded and renditions are made")
def images_uploaded(context) -> None:
    make_all_renditions(context)


@when("I project the pictured site to a local directory")
def project_everything(context) -> None:
    opened = []
    real_open = Image.open

    def counting_open(*arguments, **keywords):
        opened.append(arguments)
        return real_open(*arguments, **keywords)

    with mock.patch.object(Image, "open", counting_open):
        context.report = project_all(context.projection)
    context.opened_images = opened


@when("I project the pictured article before any renditions exist")
def project_without_renditions(context) -> None:
    try:
        project(context.projection, "item-articles-pictured")
    except Exception as error:  # noqa: BLE001 - the mutation path turns this into live:false plus the message
        context.error = f"{type(error).__name__}: {error}"


def full_build_directory(context) -> Path:
    out_directory = context.work.root / "full-build"
    if not out_directory.exists():
        full_build_with_images(context.content_root, out_directory, context.image_settings)
    return out_directory


@then("every rendition file equals the file the full build writes")
def renditions_equal_full_build(context) -> None:
    expected = rendition_files(full_build_directory(context))
    actual = rendition_files(context.site_store_root)
    assert sorted(actual) == sorted(expected), (sorted(actual), sorted(expected))
    assert expected, "the full build wrote no renditions"
    different = [key for key in expected if actual[key] != expected[key]]
    assert not different, different


@then("the description of each image is written after its rendition files")
def description_written_last(context) -> None:
    for source, result in context.written_by_source.items():
        assert result["keys"][-1] == meta_key(settings_from_mapping(context.image_settings).pipeline, source), result["keys"]
        meta = json.loads((context.site_store_root / result["keys"][-1]).read_text(encoding="utf-8"))
        assert meta["source"] == source and meta["version"] == 1


@then('the listing copy of "{source}" is {width:d} pixels wide')
def listing_copy_width(context, source: str, width: int) -> None:
    with Image.open(context.site_store_root / "assets" / "content" / source) as copy:
        assert copy.width == width, copy.width


@then('the listing copy of "{source}" is byte-identical to the original')
def listing_copy_identical(context, source: str) -> None:
    assert (context.site_store_root / "assets" / "content" / source).read_bytes() == context.media[source]


@then("the projected pages are identical to the pages of the full build")
def pages_equal_full_build(context) -> None:
    assert context.report.ok, context.report.errors
    expected = {
        key: digest
        for key, digest in tree_digests(full_build_directory(context)).items()
        if not key.startswith("assets/responsive/")
    }
    assert tree_digests(context.projected_root) == expected


@then("no image was opened while projecting")
def no_image_opened(context) -> None:
    assert context.opened_images == [], context.opened_images


@then('the projection reports an error naming "{source}" and the renditions command')
def projection_reports_missing_renditions(context, source: str) -> None:
    message = context.error or ""
    assert source in message and "papyrus ops content renditions --source" in message, message


def prepare_function(context) -> None:
    context.work = WorkDirectory()
    context.add_cleanup(context.work.cleanup)
    context.static_directory = context.work.root / "static"
    context.static_directory.mkdir()
    write_projection_settings(context.static_directory, GATSBY_IMAGE_SETTINGS)
    context.site_store_root = context.work.root / "site-store"
    context.site_store_root.mkdir()
    handler = load_renditions_handler()
    handler._loaded["settings"] = settings_from_mapping(GATSBY_IMAGE_SETTINGS)
    handler._loaded["store"] = DirectoryRenditionStore(context.site_store_root)
    context.handler = handler
    context.function_client = FakeFunctionClient(handler)
    context.media_bucket = FakeMediaBucket({})
    handler._loaded["s3"] = context.media_bucket
    context.reports = []


@given("the renditions function is configured for the fixture site")
def function_configured(context) -> None:
    prepare_function(context)


@given("the media store holds the fixture images")
def media_store_holds_images(context) -> None:
    for source, data in fixture_media().items():
        context.media_bucket.objects[f"media/{source}"] = data
    context.media_bucket.objects[NOTE_MEDIA_KEY] = b"not an image"


@when('the object "{key}" is created')
def object_created(context, key: str) -> None:
    context.media_bucket.objects.setdefault(key, b"not an image")
    event = {"source": "aws.s3", "detail-type": "Object Created", "detail": {"bucket": {"name": "media"}, "object": {"key": key}}}
    context.function_result = context.handler.handler(event, None)


def run_backfill(context, *, dry_run: bool, keys: list[str] | None = None, skip_existing: bool = True) -> dict:
    return run_renditions(
        context.function_client,
        context.media_bucket,
        function_name="renditions",
        media_bucket="media",
        keys=keys,
        skip_existing=skip_existing,
        dry_run=dry_run,
        workers=2,
    )


@when("I back-fill renditions with a dry run")
def backfill_dry_run(context) -> None:
    context.reports.append(run_backfill(context, dry_run=True))


@when("I back-fill renditions")
@given("I back-fill renditions")
def backfill(context) -> None:
    context.reports.append(run_backfill(context, dry_run=False))


@when("I back-fill renditions again")
def backfill_again(context) -> None:
    context.reports.append(run_backfill(context, dry_run=False))


@when('I request renditions for "{source}"')
def request_renditions(context, source: str) -> None:
    context.reports.append(run_backfill(context, dry_run=False, keys=[f"media/{source}"], skip_existing=False))


@then("nothing is written to the site store")
def nothing_written(context) -> None:
    assert tree_digests(context.site_store_root) == {}


@then('the report covers {images:d} images and counts action "{action}" {count:d}')
def report_covers(context, images: int, action: str, count: int) -> None:
    report = context.reports[-1]
    assert report["images"] == images and report["counts"].get(action) == count, report


@then('the report counts action "{action}" {count:d}')
def report_counts(context, action: str, count: int) -> None:
    assert context.reports[-1]["counts"].get(action) == count, context.reports[-1]


@then('the first report counts action "{action}" {count:d}')
def first_report_counts(context, action: str, count: int) -> None:
    assert context.reports[0]["counts"].get(action) == count, context.reports[0]


@then('the second report counts action "{action}" {count:d}')
def second_report_counts(context, action: str, count: int) -> None:
    assert context.reports[1]["counts"].get(action) == count, context.reports[1]


@then('the site store holds the description of "{source}"')
def site_store_holds_description(context, source: str) -> None:
    key = meta_key(settings_from_mapping(GATSBY_IMAGE_SETTINGS).pipeline, source)
    assert (context.site_store_root / key).is_file(), key
