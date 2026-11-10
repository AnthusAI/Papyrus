"""`papyrus stories save-version --images` (features_backend/story-version-images.feature).

The authoring backend is the in-memory fake; S3 and Cognito are fakes behind `boto3.client`, so the real store and
lane code runs. Nothing here reaches AWS.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from botocore.exceptions import ClientError  # noqa: E402
from PIL import Image  # noqa: E402

from papyrus_content import renditions_commands, story_commands, story_images  # noqa: E402
from papyrus_content.projection import runtime  # noqa: E402
from papyrus_content.renditions import DirectoryRenditionStore, meta_key, settings_from_mapping  # noqa: E402
from procedures.newsroom.tests.renditions_fixtures import LEGACY_IMAGE_SETTINGS, FakeMediaBucket, load_renditions_handler, projector_with_images  # noqa: E402
from papyrus_content.markus_import import media_id_for  # noqa: E402
from papyrus_content.publishing import ItemFields, PublishError, publish_item, save_item  # noqa: E402
from fake_client import FakeAuthoringClient  # noqa: E402

LINEAGE = "story-hello"
NOW = "2026-10-05T12:00:00Z"
FRONT = "title: Hello\n"
POOL = "us-east-1:example-identity-pool"
ID_TOKEN = "header.claims.id-token-of-the-signed-in-editor"
ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_example"
TEMP_CREDENTIALS = {"AccessKeyId": "ASIATEMP", "SecretKey": "temp-secret", "SessionToken": "temp-token"}


class FakeS3:
    def __init__(self, credentials: dict | None):
        self.credentials = credentials
        self.puts: list[str] = []
        self.copies: list[tuple[str, str]] = []

    objects: dict = {}
    events: list = []   # the keys the bucket announced (every put and copy), which is what wakes the renditions function

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"Metadata": {"sha256": self.objects[Key]["sha256"]}, "ContentType": self.objects[Key]["type"]}

    def put_object(self, Bucket, Key, Body, ContentType, Metadata):
        self.puts.append(Key)
        self.events.append(Key)
        self.objects[Key] = {"bytes": Body.read(), "type": ContentType, "sha256": Metadata["sha256"]}

    def copy_object(self, Bucket, Key, CopySource, MetadataDirective, **fields):
        self.copies.append((CopySource["Key"], Key))
        self.events.append(Key)
        self.objects[Key] = dict(self.objects[CopySource["Key"]])

    def get_paginator(self, name):
        objects = self.objects

        class Paginator:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": key} for key in sorted(objects) if key.startswith(Prefix)]}

        return Paginator()


class FakeIdentity:
    def __init__(self, record: dict):
        self.record = record

    def get_id(self, IdentityPoolId, Logins):
        self.record["get_id"] = {"pool": IdentityPoolId, "logins": Logins}
        return {"IdentityId": "us-east-1:identity"}

    def get_credentials_for_identity(self, IdentityId, Logins):
        self.record["credentials_for"] = {"identity": IdentityId, "logins": Logins}
        return {"Credentials": dict(TEMP_CREDENTIALS)}


def write_png(path: Path, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), (10, 20, 30)).save(path)


def body_with(directive: str, n: int = 2) -> str:
    return f"Version {n}.\n\n{directive}\n"


@given('a story "{slug}" with a first draft')
def step_story(context, slug):
    context.slug = slug
    context.client = FakeAuthoringClient()
    context.client.endpoint = "https://example.test/graphql"
    context.tmp = tempfile.mkdtemp(prefix="story-images-")
    context.tmp_dirs.append(context.tmp)
    save_item(
        context.client,
        ItemFields(type="article", slug=slug, section="articles", front_matter_yaml=FRONT, body_markus="First.\n",
                   aliases=[], id=f"{LINEAGE}-v1"),
        actor="t", now=NOW,
    )
    context.client.update_record("Item", {"id": f"{LINEAGE}-v1", "lineageId": LINEAGE, "versionNumber": 1, "versionState": "current"})
    context.s3_objects = {}
    context.s3_events = []
    context.s3_clients = []
    context.identity_record = {}
    context.lane = "iam"
    context.no_pool = False
    context.results = []


@given("a folder of pictures")
def step_folder(context):
    context.folder = Path(context.tmp) / "pictures"
    context.folder.mkdir()


@given('the folder holds "{first}" at {w1:d} by {h1:d} pixels and "{second}" at {w2:d} by {h2:d} pixels')
def step_two_pictures(context, first, w1, h1, second, w2, h2):
    write_png(context.folder / first, w1, h1)
    write_png(context.folder / second, w2, h2)


@given('the folder holds "{name}" at {width:d} by {height:d} pixels')
def step_one_picture(context, name, width, height):
    write_png(context.folder / name, width, height)


@given('the folder holds "{name}" larger than 10 MB')
def step_huge(context, name):
    (context.folder / name).write_bytes(b"\0" * (10 * 1024 * 1024 + 1))


@given('the folder holds a file "{name}" with some text')
def step_text_file(context, name):
    (context.folder / name).write_text("not a picture")


@given('the new text is an image line for "{name}"')
def step_image_line(context, name):
    context.body_text = body_with(f'::image{{src="{name}" alt="A chart"}}')


@given('the new text is an image line with src "{name}" and srcDark "{dark}"')
def step_image_line_dark(context, name, dark):
    context.body_text = body_with(f'::image{{src="{name}" srcDark="{dark}" alt="A chart"}}')


@given('the new text has a Markdown picture "{first}" and a Markdown picture "{second}"')
def step_markdown(context, first, second):
    context.body_text = body_with(f"![First]({first})\n\n![Second]({second})")


@given("the CLI uses the IAM lane")
def step_iam(context):
    context.lane = "iam"


@given("the CLI uses the signed-in user lane")
def step_user(context):
    context.lane = "user"


@given("no identity pool is configured")
def step_no_pool(context):
    context.no_pool = True


def fake_boto_client(context):
    def factory(service, **kwargs):
        if service == "cognito-identity":
            return FakeIdentity(context.identity_record)
        assert service == "s3", service
        credentials = kwargs.get("aws_access_key_id")
        client = FakeS3(None if credentials is None else {"key": credentials, "token": kwargs.get("aws_session_token")})
        client.objects = context.s3_objects
        client.events = context.s3_events
        context.s3_clients.append(client)
        return client

    return factory


def run_save(context, dry_run: bool = False) -> None:
    body_path = Path(context.tmp) / "body.md"
    body_path.write_text(context.body_text, encoding="utf-8")
    flags = ["--story", LINEAGE, "--body-file", str(body_path), "--reason", "pictures", "--images", str(context.folder), "--no-check"]
    if context.lane == "iam":
        flags += ["--author-label", "t"]   # signed in, the session names the author
    if dry_run:
        flags.append("--dry-run")
    environment = {"PAPYRUS_GRAPHQL_AUTH": context.lane, "PAPYRUS_MEDIA_BUCKET": "media-bucket"}
    if context.lane == "user" and not context.no_pool:
        environment["PAPYRUS_IDENTITY_POOL_ID"] = POOL
    patches = [
        mock.patch.dict(os.environ, environment),
        mock.patch.object(story_commands, "create_authoring_client", lambda: (context.client, {})),
        mock.patch("boto3.client", fake_boto_client(context)),
        mock.patch.object(story_images, "user_identity", lambda: (ID_TOKEN, ISSUER)),
        mock.patch("papyrus_content.cli_user_auth.signed_in_label", lambda endpoint: "Ada Example"),
        mock.patch("papyrus_content.env.amplify_outputs_path", lambda: Path(context.tmp) / "no-amplify-outputs.json"),
    ]
    output = io.StringIO()
    error = None
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        if context.no_pool:
            os.environ.pop("PAPYRUS_IDENTITY_POOL_ID", None)
        with contextlib.redirect_stdout(output):
            try:
                story_commands.stories_save_version(flags)
            except ValueError as raised:
                error = str(raised)
    context.results.append({"output": output.getvalue(), "error": error})
    context.result = context.results[-1]


@when("the story is saved with the folder of pictures")
def step_save(context):
    run_save(context)


@when("the story is saved with the folder of pictures as a dry run")
def step_dry_run(context):
    run_save(context, dry_run=True)


@when("the story is saved again with the same text and the same folder")
def step_save_again(context):
    run_save(context)


def versions(context):
    return sorted((row for row in context.client.tables["Item"].values() if row.get("type") != "sub-task"), key=lambda row: int(row["versionNumber"]))   # the Story's versions, not its checklist steps


def new_version(context):
    return versions(context)[-1]


def media_rows(context, item_id):
    return context.client.list_by_index("mediaAssetsByItemAndSortKey", item_id)


def src_paths(rows):
    return sorted(json.loads(row["metadata"])["srcPath"] for row in rows)


@then("the save succeeds")
def step_succeeds(context):
    assert context.result["error"] is None, context.result["error"]
    assert "saved" in context.result["output"]


@then("the second save succeeds")
def step_second_succeeds(context):
    assert len(context.results) == 2
    assert context.results[1]["error"] is None, context.results[1]["error"]


@then('the saved text points at "{src}" with srcDark "{dark}"')
def step_text_dark(context, src, dark):
    text = new_version(context)["bodyMarkus"]
    assert f'src="{src}"' in text and f'srcDark="{dark}"' in text, text


@then('the saved text points at "{src}" with no srcDark')
def step_text_no_dark(context, src):
    text = new_version(context)["bodyMarkus"]
    assert f'src="{src}"' in text and "srcDark" not in text, text


@given("the story's address becomes \"{slug}\"")
@when("the story's address becomes \"{slug}\"")
def step_address(context, slug):
    for row in [row for row in context.client.tables["Item"].values() if row.get("type") != "sub-task"]:
        context.client.update_record("Item", {"id": row["id"], "slug": slug})


@when('the picture "{name}" is replaced by a different one at {width:d} by {height:d} pixels')
def step_replace_picture(context, name, width, height):
    write_png(context.folder / name, width, height)


@then('the saved text has the Markdown picture "{first}" and the Markdown picture "{second}"')
def step_text_markdown(context, first, second):
    text = new_version(context)["bodyMarkus"]
    assert f"![First]({first})" in text and f"![Second]({second})" in text, text


@then('the new version has media rows for "{first}" and "{second}"')
def step_rows_two(context, first, second):
    assert src_paths(media_rows(context, new_version(context)["id"])) == sorted([first, second])


@then('the new version has media rows for "{first}"')
def step_rows_one(context, first):
    assert src_paths(media_rows(context, new_version(context)["id"])) == [first]


@then('the media row for "{src}" is a body image stored at "{storage}" named "{name}"')
def step_row_fields(context, src, storage, name):
    item_id = new_version(context)["id"]
    row = next(r for r in media_rows(context, item_id) if json.loads(r["metadata"])["srcPath"] == src)
    assert (row["type"], row["role"], row["storagePath"], row["alt"]) == ("image", "body", storage, name), row
    assert row["id"] == media_id_for(item_id, src)
    assert (row["width"], row["height"]) == (800, 400)
    metadata = json.loads(row["metadata"])
    assert metadata["contentType"] == "image/png" and metadata["bytes"] > 0 and len(metadata["sha256"]) == 64


@then('the stored files are "{first}" and "{second}"')
def step_stored_two(context, first, second):
    assert sorted(context.s3_objects) == sorted({first, second})


@then('the stored files are still just "{first}" and "{second}"')
def step_stored_still(context, first, second):
    assert sorted(context.s3_objects) == sorted([first, second])


@then("the new version can be published")
def step_publishable(context):
    assert publish_item(context.client, new_version(context)["id"], actor="t", now=NOW).changed


@then('the plan lists "{name}" with its media id, "{storage}" and its size in bytes')
def step_plan_light(context, name, storage):
    line = next(l for l in context.result["output"].splitlines() if "\timage\tlight\t" in l and f"\t{name}\t" in l)
    item_id = f"{LINEAGE}-v2"
    size = (context.folder / name).stat().st_size
    assert media_id_for(item_id, "assets/hello/" + name) in line and storage in line and f"{size} bytes" in line, line


@then('the plan lists "{dark}" as the dark version of "{light}"')
def step_plan_dark(context, dark, light):
    line = next(l for l in context.result["output"].splitlines() if "\timage\tdark\t" in l and f"\t{dark}\t" in l)
    assert f"dark of {light}" in line, line


@then("nothing was written to the backend or to storage")
def step_nothing(context):
    assert versions(context)[-1]["versionNumber"] == 1, "a version was saved"
    assert not context.client.tables.get("MediaAsset"), "media rows were written"
    assert context.s3_objects == {}, "files were stored"
    assert not any(client.puts for client in context.s3_clients)


@then('the save is rejected naming "{first}" and "{second}"')
def step_rejected(context, first, second):
    error = context.result["error"]
    assert error is not None, "the save should have been rejected"
    assert first in error and second in error, error


@then('the save is rejected naming "{what}"')
def step_rejected_one(context, what):
    error = context.result["error"]
    assert error is not None and what in error, error


@then("the story still has only its first version")
def step_first_only(context):
    assert len(versions(context)) == 1


@then("the second save found the stored files already in place")
def step_second_unchanged(context):
    output = context.results[1]["output"]
    assert "image-unchanged" in output and "image-uploaded" not in output, output


@then('each version has exactly one media row for each of "{first}" and "{second}"')
def step_one_row_each(context, first, second):
    rows = context.client.tables["MediaAsset"].values()
    for item in versions(context)[1:]:
        assert src_paths([r for r in rows if r["itemId"] == item["id"]]) == sorted([first, second])
    assert len({r["id"] for r in rows}) == len(list(rows))


@then("the media ids are the same ones the editor and the Markus import derive from the version and the stored path")
def step_ids(context):
    for item in versions(context)[1:]:
        for row in (r for r in context.client.tables["MediaAsset"].values() if r["itemId"] == item["id"]):
            src = json.loads(row["metadata"])["srcPath"]
            digest = hashlib.sha256(src.encode()).hexdigest()[:10]
            assert row["id"] == f"media-{item['id']}-{digest}"


@then("the upload used the operator's AWS credentials")
def step_operator_credentials(context):
    assert context.s3_clients and all(client.credentials is None for client in context.s3_clients)
    assert any(client.puts for client in context.s3_clients)


@then("no identity-pool credentials were requested")
def step_no_pool_request(context):
    assert context.identity_record == {}


@then("the identity pool was given the signed-in user's ID token")
def step_pool_token(context):
    logins = context.identity_record["get_id"]["logins"]
    assert context.identity_record["get_id"]["pool"] == POOL
    assert logins == {"cognito-idp.us-east-1.amazonaws.com/us-east-1_example": ID_TOKEN}


@then("the stored files were uploaded with the temporary credentials the pool returned")
def step_temp_credentials(context):
    assert context.s3_clients
    for client in context.s3_clients:
        assert client.credentials == {"key": "ASIATEMP", "token": "temp-token"}, client.credentials
    assert sorted(context.s3_objects) == ["media/assets/hello/chart.dark.png", "media/assets/hello/chart.png"]


@then("the media rows were written through the signed-in session's GraphQL client")
def step_session_rows(context):
    assert context.lane == "user"
    assert len(media_rows(context, new_version(context)["id"])) == 2


@then("no AWS credentials of the operator were used")
def step_no_operator(context):
    assert all(client.credentials is not None for client in context.s3_clients)


# -- tenant sites (features_backend/tenant-story-images.feature) ---------------------------------------------------

TENANT_KEY = "media/machines-on-machines/assets/hello/chart.png"
ONE_KEY = "media/assets/hello/chart.png"
SOURCE = "assets/hello/chart.png"
PROJECTION = {"PAPYRUS_PUBLICATION_KIND": "s3-projection"}


@given('the story belongs to the tenant "{tenant}"')
def step_tenant(context, tenant):
    context.tenant = tenant
    context.client.tenant_id = tenant
    stamp_like_the_graphql_client(context.client, tenant)


def stamp_like_the_graphql_client(client, tenant):
    """The real client runs every write through tenant_stamped_payload; the fake does the same for media rows, so a rewritten key shows up here."""
    from papyrus_content.tenancy import tenant_stamped_payload

    for method in ("upsert", "create_record", "update_record"):
        original = getattr(client, method)

        def stamped(model_name, payload, _original=original):
            if model_name in ("MediaAsset", "PublishedMediaAsset") and "storagePath" in payload:
                payload = {**payload, "storagePath": tenant_stamped_payload(model_name, tenant, payload)["storagePath"]}
            return _original(model_name, payload)

        setattr(client, method, stamped)


@given("an identity pool is configured")
def step_pool(context):
    context.no_pool = False


def site_directory(context) -> Path:
    if not hasattr(context, "site_root"):
        context.site_root = Path(tempfile.mkdtemp(prefix="tenant-site-"))
        context.tmp_dirs.append(str(context.site_root))
        (context.site_root / "static").mkdir()
        (context.site_root / "store").mkdir()
    return context.site_root


@given("the story's picture was saved under the old tenant key")
def step_old_key(context):
    run_save(context)
    objects = context.s3_objects
    objects[TENANT_KEY] = objects.pop(ONE_KEY)
    context.s3_events.clear()
    for row in media_rows(context, new_version(context)["id"]):
        context.client.update_record("MediaAsset", {"id": row["id"], "storagePath": TENANT_KEY})


@given("the story's picture was saved at the one key but its media rows name the old tenant key")
def step_rows_wrong(context):
    run_save(context)
    context.s3_events.clear()
    for row in media_rows(context, new_version(context)["id"]):
        context.client.tables["MediaAsset"][row["id"]]["storagePath"] = TENANT_KEY


@then('the plan copies nothing and re-points the rows to "{new}"')
def step_plan_repoint(context, new):
    out = context.command_output
    assert "\tobject-already-there\t" in out and "\tobject\t" not in out and f"\t{TENANT_KEY}\t->\t{new}" in out, out
    assert "0 object(s) to copy" in out, out


@then("only the rows' storage paths were written")
def step_only_paths(context):
    writes = [(m, set(p)) for m, p in context.client.updates if m in ("MediaAsset", "PublishedMediaAsset")][-len(context.client.tables["MediaAsset"]):]
    assert writes and all(fields == {"id", "storagePath"} for _m, fields in writes), writes
    assert all(key.startswith("media/assets/") for key in context.s3_objects), sorted(context.s3_objects)


@given("the old file is gone from the bucket")
def step_old_gone(context):
    context.s3_objects.pop(TENANT_KEY)


@then('the only stored file is "{key}"')
def step_only_file(context, key):
    assert sorted(context.s3_objects) == [key], sorted(context.s3_objects)


@then('the published media row for "{src}" is stored at "{key}" where the file exists')
def step_published_row_key(context, src, key):
    rows = [r for r in context.client.list_records("PublishedMediaAsset") if json.loads(r["metadata"])["srcPath"] == src]
    assert [r["storagePath"] for r in rows] == [key], rows
    assert key in context.s3_objects, sorted(context.s3_objects)


@then('the media row for "{src}" is stored at "{key}" where the file exists')
def step_row_key_exists(context, src, key):
    step_row_key(context, src, key)
    assert key in context.s3_objects, sorted(context.s3_objects)


@then('the media row for "{src}" is stored at "{key}"')
def step_row_key(context, src, key):
    rows = [r for r in media_rows(context, new_version(context)["id"]) if json.loads(r["metadata"])["srcPath"] == src]
    assert [r["storagePath"] for r in rows] == [key], rows


@when("the bucket announces the stored pictures to the site's image function")
def step_announce(context):
    root = site_directory(context)
    handler = load_renditions_handler()
    settings = settings_from_mapping(LEGACY_IMAGE_SETTINGS)
    handler._loaded["settings"] = settings
    handler._loaded["store"] = DirectoryRenditionStore(root / "store")
    handler._loaded["prefixed"] = handler._loaded["store"]
    bucket = FakeMediaBucket({key: obj["bytes"] for key, obj in context.s3_objects.items()})
    handler._loaded["s3"] = bucket
    context.rendition_results = [
        handler.render_media_object(settings, "media-bucket", key) for key in sorted(set(context.s3_events))
    ]
    context.s3_events.clear()


@then('the renditions exist for "{source}"')
def step_renditions_exist(context, source):
    store = DirectoryRenditionStore(site_directory(context) / "store")
    assert store.get(meta_key(settings_from_mapping(LEGACY_IMAGE_SETTINGS).pipeline, source)) is not None, context.rendition_results


def preflight(context):
    root = site_directory(context)
    projector = projector_with_images(root / "static", LEGACY_IMAGE_SETTINGS, DirectoryRenditionStore(root / "store"))
    row = new_version(context)
    with mock.patch.object(runtime, "load_projector", lambda environ=None, **kw: projector):
        runtime.render_preflight(context.client, row["id"], PROJECTION)


@then("the publish check of the new version passes")
def step_preflight_passes(context):
    preflight(context)


@then("the publish check of the new version is refused before anything is written")
def step_preflight_refused(context):
    context.refusal = None
    try:
        preflight(context)
    except PublishError as error:
        context.refusal = error
    assert context.refusal is not None and context.refusal.code == "page-not-renderable"


@then('the refusal names "{source}", "{key}" and "{command}"')
def step_refusal_names(context, source, key, command):
    message = context.refusal.message
    assert source in message and key in message and command in message, message


def run_command(context, command, flags, extra_environment=None):
    environment = {
        "PAPYRUS_GRAPHQL_AUTH": "user",
        "PAPYRUS_MEDIA_BUCKET": "media-bucket",
        "PAPYRUS_IDENTITY_POOL_ID": POOL,
        "PAPYRUS_TENANT_ID": context.tenant,
    }
    environment.update(extra_environment or {})
    output = io.StringIO()
    context.exit_code = 0
    context.puts_before = put_count(context)
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.dict(os.environ, environment))
        stack.enter_context(mock.patch.object(story_commands, "create_authoring_client", lambda: (context.client, {})))
        stack.enter_context(mock.patch("boto3.client", fake_boto_client(context)))
        stack.enter_context(mock.patch.object(story_images, "user_identity", lambda: (ID_TOKEN, ISSUER)))
        stack.enter_context(mock.patch("papyrus_content.env.amplify_outputs_path", lambda: Path(context.tmp) / "none.json"))
        stack.enter_context(contextlib.redirect_stdout(output))
        try:
            command(flags)
        except SystemExit as exit_request:
            context.exit_code = exit_request.code
    context.command_output = output.getvalue()


def put_count(context):
    return sum(len(client.puts) for client in context.s3_clients)


@when("the repair is planned")
def step_repair_plan(context):
    context.before = (dict(context.s3_objects), json.dumps(context.client.tables["MediaAsset"], sort_keys=True))
    run_command(context, story_commands.stories_repair_image_paths, ["--story", "story-hello"])


@when("the repair is written")
def step_repair_write(context):
    run_command(context, story_commands.stories_repair_image_paths, ["--story", "story-hello", "--write"])


@then('the plan copies "{old}" to "{new}"')
def step_plan_copies(context, old, new):
    assert f"\tobject\t{old}\t->\t{new}" in context.command_output, context.command_output


@then("nothing was changed by the repair")
def step_nothing_changed(context):
    objects, rows = context.before
    assert objects == context.s3_objects and rows == json.dumps(context.client.tables["MediaAsset"], sort_keys=True)
    assert "dry run" in context.command_output


@then('the story\'s media rows point at "{key}"')
@then('the story\'s media rows still point at "{key}"')
def step_rows_point(context, key):
    rows = context.client.tables["MediaAsset"].values()
    assert rows and {row["storagePath"] for row in rows} == {key}, [row["storagePath"] for row in rows]


@then("both the old and the new file are stored")
def step_both(context):
    assert {TENANT_KEY, ONE_KEY} <= set(context.s3_objects)


@then("no file was uploaded again")
def step_no_upload(context):
    assert put_count(context) == context.puts_before, context.command_output


@then('the repair fails naming "{key}"')
def step_repair_fails(context, key):
    assert context.exit_code == 1 and key in context.command_output, (context.exit_code, context.command_output)


@then("the repair says there is nothing to repair")
def step_nothing_to_repair(context):
    assert "nothing to repair" in context.command_output, context.command_output


@when('renditions are requested for "{source}" by the signed-in editor')
def step_request(context, source):
    context.s3_events.clear()
    run_command(context, renditions_commands.content_renditions, ["--source", source], {"PAPYRUS_MEDIA_BUCKET": "media-bucket"})


@then("the request succeeds and the file was announced again")
def step_request_ok(context):
    assert context.exit_code == 0, context.command_output
    assert context.s3_events == [ONE_KEY], context.s3_events


@then('the request fails naming "{key}" and "{command}"')
def step_request_fails(context, key, command):
    assert context.exit_code == 1 and key in context.command_output and command in context.command_output, context.command_output
