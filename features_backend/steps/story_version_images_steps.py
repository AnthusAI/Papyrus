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

from papyrus_content import story_commands, story_images  # noqa: E402
from papyrus_content.markus_import import media_id_for  # noqa: E402
from papyrus_content.publishing import ItemFields, publish_item, save_item  # noqa: E402
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

    objects: dict = {}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"Metadata": {"sha256": self.objects[Key]["sha256"]}}

    def put_object(self, Bucket, Key, Body, ContentType, Metadata):
        self.puts.append(Key)
        self.objects[Key] = {"bytes": Body.read(), "type": ContentType, "sha256": Metadata["sha256"]}


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
        context.s3_clients.append(client)
        return client

    return factory


def run_save(context, dry_run: bool = False) -> None:
    body_path = Path(context.tmp) / "body.md"
    body_path.write_text(context.body_text, encoding="utf-8")
    flags = ["--story", LINEAGE, "--body-file", str(body_path), "--reason", "pictures", "--author-label", "t",
             "--images", str(context.folder), "--no-check"]
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
    return sorted(context.client.tables["Item"].values(), key=lambda row: int(row["versionNumber"]))


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
    assert sorted(context.s3_objects) == sorted([first, second])


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
