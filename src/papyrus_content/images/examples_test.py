"""Example pictures: the command line's upload steps, the file checks, the draft profile and the provider rule (features_backend/image-profile-examples.feature)."""
from __future__ import annotations

import hashlib
import io
import json

import pytest

from papyrus_content.images import cli as images_cli
from papyrus_content.images.examples import MAX_EXAMPLE_BYTES, ROLE_BY_KIND, provider_examples, provider_grants
from papyrus_content.images.handlers import Caller, execute
from papyrus_content.images.profile_fakes import FakeBackend, profile_copy
from papyrus_content.images.profile_handlers import with_client
from papyrus_content.images.profile_init import draft_document
from papyrus_content.images.upload import PictureError, describe_picture, media_type_of, upload_picture
from papyrus_content.images.visual_style import validate_profile

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 32


def test_the_type_comes_from_the_first_bytes_not_the_name(tmp_path):
    assert (media_type_of(PNG), media_type_of(JPEG), media_type_of(WEBP), media_type_of(b"<svg/>"), media_type_of(b"")) == ("image/png", "image/jpeg", "image/webp", None, None)
    fake = tmp_path / "cover.png"
    fake.write_bytes(b"<svg xmlns='http://www.w3.org/2000/svg'/>")
    with pytest.raises(PictureError, match="not a PNG, JPEG or WebP"):
        describe_picture(str(fake), "exemplar")


def test_a_picture_over_ten_megabytes_is_refused_before_anything_is_asked_of_the_backend(tmp_path):
    big = tmp_path / "big.png"
    big.write_bytes(PNG + b"\x00" * MAX_EXAMPLE_BYTES)
    with pytest.raises(PictureError, match="10 MB"):
        describe_picture(str(big), "exemplar")


def test_the_file_is_named_by_its_hash_in_a_private_item_slot(tmp_path):
    path = tmp_path / "Holiday Photo (1).PNG"
    path.write_bytes(PNG)
    attachment, data = describe_picture(str(path), "negative")
    digest = hashlib.sha256(PNG).hexdigest()
    assert data == PNG and attachment == {"ownerKind": "item", "ownerId": "item-editorial-doctrine-visual-style", "role": "visual_negative", "sortKey": digest,
                                          "filename": f"{digest}.png", "mediaType": "image/png", "byteSize": len(PNG), "sha256": digest}
    assert ROLE_BY_KIND == {"exemplar": "visual_example", "negative": "visual_negative"}


class UploadClient:
    def __init__(self):
        self.calls = []

    def create_model_attachment_upload(self, attachment):
        self.calls.append(("create", attachment["filename"]))
        return {"uploadId": "upload-1", "attachmentId": "model-attachment-9", "uploadUrl": "https://upload.example/signed", "requiredHeaders": {"content-type": "image/png"}}

    def complete_model_attachment_upload(self, upload_id, attachment):
        self.calls.append(("complete", upload_id))
        return {"id": "model-attachment-9"}


def test_the_three_upload_steps_run_in_order_and_return_the_attachment_id(tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(PNG)
    client, puts = UploadClient(), []
    attachment_id = upload_picture(client, str(path), "exemplar", put=lambda url, data, headers: puts.append((url, len(data), headers)))
    assert attachment_id == "model-attachment-9" and puts == [("https://upload.example/signed", len(PNG), {"content-type": "image/png"})]
    assert [call[0] for call in client.calls] == ["create", "complete"]


EXAMPLE_ARGS = ["profile", "example", "add", "--image-type", "cover-illustration", "--kind", "exemplar", "--note", "Calm.", "--reason", "Added."]


def run(argv, tmp_path, **options):
    out = io.StringIO()
    status = images_cli.command(argv, environ={}, stdout=out, **options)
    return status, json.loads(out.getvalue())


def test_file_uploads_the_picture_then_adds_it(tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(PNG)
    seen, uploads = [], []
    from papyrus_content.images.handlers import Outcome

    def handler(arguments, caller):
        seen.append(arguments)
        return Outcome({"attachmentId": arguments["attachmentId"], "sha256": "sha256:aa", "versionNumber": 2}, "p")

    status, envelope = run([*EXAMPLE_ARGS, "--expected-current-version-id", "v1", "--file", str(path)], tmp_path, handlers={"image_profile_example_add": handler},
                           uploader=lambda picture, kind: uploads.append((picture, kind)) or "model-attachment-9")
    assert status == 0 and uploads == [(str(path), "exemplar")]
    assert seen[0]["attachmentId"] == "model-attachment-9" and "_picture" not in seen[0]


def test_a_wrong_file_is_refused_before_the_uploader_runs_and_dry_run_uploads_nothing(tmp_path):
    text = tmp_path / "notes.png"
    text.write_text("not a picture")
    uploads = []
    status, envelope = run([*EXAMPLE_ARGS, "--expected-current-version-id", "v1", "--file", str(text)], tmp_path, uploader=lambda *a: uploads.append(a) or "x")
    assert status == 2 and envelope["error"]["code"] == "invalid_input" and "PNG, JPEG or WebP" in envelope["error"]["message"] and uploads == []
    good = tmp_path / "a.png"
    good.write_bytes(PNG)
    status, envelope = run([*EXAMPLE_ARGS, "--expected-current-version-id", "v1", "--file", str(good), "--dry-run"], tmp_path, uploader=lambda *a: uploads.append(a) or "x")
    assert status == 0 and envelope["result"]["dryRun"] is True and uploads == []


def test_the_usage_line_shows_the_picture_flag():
    assert "[--file PICTURE]" in images_cli.usage_for(["profile", "example", "add"])


def test_the_draft_is_valid_without_a_brand_and_holds_no_style_wording():
    document, notes = draft_document(None)
    assert validate_profile(document) == [] and "identity" not in document
    assert notes[0].startswith("No brand colours")
    flat = json.dumps(document).lower()
    for word in ("flat", "calm", "photograph", "illustration", "avoid"):
        assert word not in flat


def test_a_draft_never_saves():
    store = FakeBackend("ours")
    envelope = execute("image_profile_init", {"brand": {"palette": [{"name": "Ink", "hex": "#1f2a44"}]}}, Caller(), with_client(store))
    assert envelope["ok"] and store.writes == [] and envelope["result"]["expectedCurrentVersionId"] == "none"


def test_provider_rules():
    document = profile_copy()
    document["imageTypes"]["cover-illustration"]["examples"] = [
        {"attachmentId": "a", "kind": "exemplar", "note": "", "sendToProvider": True}, {"attachmentId": "b", "kind": "exemplar", "note": "", "sendToProvider": False},
        {"attachmentId": "c", "kind": "negative", "note": "", "sendToProvider": True}]
    document["imageTypes"]["inline-illustration"]["examples"] = [{"attachmentId": "d", "kind": "exemplar", "note": "", "sendToProvider": True}]
    assert [e["attachmentId"] for e in provider_examples(document, "cover-illustration")] == ["a"]   # no negatives, nothing unallowed, nothing from a parent
    assert provider_examples(document, "social-card") == []
    assert provider_grants(document) == {("cover-illustration", "a"), ("cover-illustration", "c"), ("inline-illustration", "d")}
