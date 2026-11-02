"""`stories save-version --images`: planning, validation, rewriting and the two upload lanes. No AWS, no backend."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content import story_images
from papyrus_content.markus_import import media_id_for
from papyrus_content.story_images import MAX_IMAGE_BYTES, plan_story_images, src_path_for


def png(path: Path, width: int = 40, height: int = 20) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), (1, 2, 3)).save(path)
    return path


def test_src_path_matches_the_editors_srcPathFor():
    assert src_path_for("Hello World", "My Chart (final).PNG") == "assets/hello-world/my-chart-final.png"
    assert src_path_for("hello", "chart.dark.png") == "assets/hello/chart.dark.png"
    assert src_path_for("", "!!!.png") == "assets/article/image.png"
    assert src_path_for("hello", "chart.png", {"assets/hello/chart.png"}) == "assets/hello/chart-2.png"
    assert src_path_for("hello", "chart.png", {"assets/hello/chart.png", "assets/hello/chart-2.png"}) == "assets/hello/chart-3.png"


def test_directive_and_markdown_are_rewritten_and_web_and_absent_files_left_alone(tmp_path):
    png(tmp_path / "images" / "a.png")
    png(tmp_path / "b.png")
    body = (
        '::image{src="images/a.png" alt="A" layout="inline"}\n\n![B](b.png "Title")\n\n'
        '::image{src="https://example.com/x.png" alt="web"}\n\n::image{src="gone.png" alt="gone"}\n\n'
        "```\n::image{src=\"b.png\"}\n```\n"
    )
    plan = plan_story_images(body, tmp_path, slug="hello")
    assert 'src="assets/hello/a.png" alt="A" layout="inline"' in plan.body
    assert '![B](assets/hello/b.png "Title")' in plan.body
    assert 'src="https://example.com/x.png"' in plan.body and 'src="gone.png"' in plan.body
    assert '```\n::image{src="b.png"}\n```' in plan.body  # code fences are untouched
    assert plan.unresolved == ["gone.png"]
    assert [i.src_path for i in plan.images] == ["assets/hello/a.png", "assets/hello/b.png"]


def test_dark_sibling_gets_an_explicit_srcDark_and_a_media_row_with_editor_fields(tmp_path):
    png(tmp_path / "c.png", 80, 40)
    png(tmp_path / "c.dark.png", 80, 40)
    plan = plan_story_images('::image{src="c.png" alt="C"}', tmp_path, slug="hello")
    assert plan.body == '::image{src="assets/hello/c.png" srcDark="assets/hello/c.dark.png" alt="C"}'
    light, dark = plan.images
    assert (light.role, dark.role, dark.paired_with) == ("light", "dark", "c.png")
    row = light.media_row("item-v2")
    assert row["id"] == media_id_for("item-v2", "assets/hello/c.png")
    assert (row["type"], row["role"], row["alt"], row["storagePath"]) == ("image", "body", "c.png", "media/assets/hello/c.png")
    assert row["sortKey"] == "001#assets/hello/c.png" and plan.images[1].media_row("item-v2")["sortKey"] == "002#assets/hello/c.dark.png"
    assert (row["width"], row["height"]) == (80, 40)
    assert json.loads(row["metadata"]).keys() == {"srcPath", "sha256", "bytes", "contentType"}


def test_explicit_srcDark_is_rewritten_and_none_disables_pairing(tmp_path):
    png(tmp_path / "c.png")
    png(tmp_path / "c.dark.png")
    png(tmp_path / "night.png")
    plan = plan_story_images('::image{src="c.png" srcDark="night.png"}', tmp_path, slug="s")
    assert plan.body == '::image{src="assets/s/c.png" srcDark="assets/s/night.png"}'
    off = plan_story_images('::image{src="c.png" srcDark="none"}', tmp_path, slug="s")
    assert off.body == '::image{src="assets/s/c.png" srcDark="none"}' and len(off.images) == 1


def test_markdown_picture_with_a_dark_sibling_uploads_both_and_says_it_cannot_pair(tmp_path):
    png(tmp_path / "p.png")
    png(tmp_path / "p.dark.png")
    plan = plan_story_images("![P](p.png)", tmp_path, slug="s")
    assert plan.body == "![P](assets/s/p.png)" and len(plan.images) == 2 and "no srcDark" in plan.notes[0]


def test_same_file_twice_is_one_upload_and_same_stem_in_two_folders_is_numbered(tmp_path):
    png(tmp_path / "one" / "x.png")
    png(tmp_path / "two" / "x.png", 10, 10)
    body = '::image{src="one/x.png"}\n::image{src="one/x.png"}\n::image{src="two/x.png"}\n'
    plan = plan_story_images(body, tmp_path, slug="s")
    assert [i.src_path for i in plan.images] == ["assets/s/x.png", "assets/s/x-2.png"]
    assert plan.body.count("assets/s/x.png") == 2 and "assets/s/x-2.png" in plan.body


def test_planning_is_deterministic(tmp_path):
    png(tmp_path / "c.png")
    first = plan_story_images('::image{src="c.png"}', tmp_path, slug="s")
    second = plan_story_images('::image{src="c.png"}', tmp_path, slug="s")
    assert first.body == second.body
    assert first.media_rows("v")[0] == second.media_rows("v")[0]


def test_rejections_name_every_bad_file_at_once(tmp_path):
    (tmp_path / "huge.png").write_bytes(b"\0" * (MAX_IMAGE_BYTES + 1))
    (tmp_path / "notes.txt").write_text("text")
    (tmp_path / "empty.png").write_bytes(b"")
    png(tmp_path / "w.png", 100, 50)
    png(tmp_path / "w.dark.png", 100, 80)
    body = "\n".join(f'::image{{src="{n}"}}' for n in ("huge.png", "notes.txt", "empty.png", "w.png"))
    with pytest.raises(ValueError) as raised:
        plan_story_images(body, tmp_path, slug="s")
    message = str(raised.value)
    assert "huge.png" in message and "10 MB" in message
    assert "notes.txt" in message and "PNG, JPEG, GIF, WebP, AVIF or SVG" in message
    assert "empty.png" in message and "empty" in message
    assert "w.dark.png" in message and "aspect ratio" in message


def test_exactly_ten_megabytes_is_accepted(tmp_path):
    big = tmp_path / "big.png"
    png(big)
    with big.open("ab") as handle:
        handle.write(b"\0" * (MAX_IMAGE_BYTES - big.stat().st_size))
    assert big.stat().st_size == MAX_IMAGE_BYTES
    assert plan_story_images('::image{src="big.png"}', tmp_path, slug="s").images[0].size == MAX_IMAGE_BYTES


def test_aspect_tolerance_is_half_a_percent(tmp_path):
    png(tmp_path / "a.png", 1000, 500)
    png(tmp_path / "a.dark.png", 1000, 501)  # 0.2% off
    plan_story_images('::image{src="a.png"}', tmp_path, slug="s")
    png(tmp_path / "b.png", 1000, 500)
    png(tmp_path / "b.dark.png", 1000, 504)  # 0.8% off
    with pytest.raises(ValueError, match="b.dark.png.*aspect ratio"):
        plan_story_images('::image{src="b.png"}', tmp_path, slug="s")


def test_svg_pairs_by_its_viewbox(tmp_path):
    (tmp_path / "v.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"></svg>')
    (tmp_path / "v.dark.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200"></svg>')
    plan = plan_story_images('::image{src="v.svg"}', tmp_path, slug="s")
    assert [i.content_type for i in plan.images] == ["image/svg+xml"] * 2
    assert "width" not in plan.images[0].media_row("x")


def test_a_missing_explicit_dark_file_is_an_error(tmp_path):
    png(tmp_path / "c.png")
    with pytest.raises(ValueError, match="nope.png.*not found"):
        plan_story_images('::image{src="c.png" srcDark="nope.png"}', tmp_path, slug="s")


def test_paths_outside_the_folder_are_not_followed(tmp_path):
    png(tmp_path / "outside.png")
    inner = tmp_path / "inner"
    inner.mkdir()
    plan = plan_story_images('::image{src="../outside.png"}', inner, slug="s")
    assert plan.images == [] and plan.unresolved == ["../outside.png"]


def test_images_must_be_a_directory(tmp_path):
    with pytest.raises(ValueError, match="not a directory"):
        plan_story_images("x", tmp_path / "missing", slug="s")


def test_tenant_stored_media_path(tmp_path):
    png(tmp_path / "c.png")
    plan = plan_story_images('::image{src="c.png"}', tmp_path, slug="s", tenant_id="tenant-a")
    assert plan.images[0].storage_path.endswith("assets/s/c.png") and plan.images[0].storage_path != "media/assets/s/c.png"


# -- lanes ---------------------------------------------------------------------------------------------------------

class RecordingIdentity:
    def __init__(self):
        self.calls = []

    def get_id(self, **kwargs):
        self.calls.append(("get_id", kwargs))
        return {"IdentityId": "id-1"}

    def get_credentials_for_identity(self, **kwargs):
        self.calls.append(("credentials", kwargs))
        return {"Credentials": {"AccessKeyId": "AK", "SecretKey": "SK", "SessionToken": "ST"}}


def test_user_lane_trades_the_id_token_for_temporary_s3_credentials(monkeypatch):
    identity = RecordingIdentity()
    seen = {}
    monkeypatch.setattr(story_images, "user_identity", lambda: ("the-id-token", "https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_Pool"))
    monkeypatch.setattr(story_images, "_cognito_identity_client", lambda region: seen.setdefault("region", region) and identity)
    monkeypatch.setattr(story_images, "_s3_client", lambda credentials, region: ("s3", credentials, region))
    result = story_images.user_lane_s3_client("eu-west-1:abc")
    assert result == ("s3", {"AccessKeyId": "AK", "SecretKey": "SK", "SessionToken": "ST"}, "eu-west-1")
    logins = {"cognito-idp.eu-west-1.amazonaws.com/eu-west-1_Pool": "the-id-token"}
    assert identity.calls == [("get_id", {"IdentityPoolId": "eu-west-1:abc", "Logins": logins}),
                              ("credentials", {"IdentityId": "id-1", "Logins": logins})]
    assert seen["region"] == "eu-west-1"


def test_user_lane_without_an_identity_pool_says_what_to_set(monkeypatch, tmp_path):
    monkeypatch.delenv("PAPYRUS_IDENTITY_POOL_ID", raising=False)
    monkeypatch.setattr("papyrus_content.env.amplify_outputs_path", lambda: tmp_path / "none.json")
    monkeypatch.setattr(story_images, "user_identity", lambda: ("t", "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_P"))
    with pytest.raises(ValueError, match="identity pool.*PAPYRUS_IDENTITY_POOL_ID"):
        story_images.user_lane_s3_client()


def test_identity_pool_comes_from_the_environment_then_amplify_outputs(monkeypatch, tmp_path):
    from papyrus_content.env import identity_pool_id_from_amplify_outputs

    outputs = tmp_path / "amplify_outputs.json"
    outputs.write_text(json.dumps({"auth": {"identity_pool_id": "us-east-1:from-file"}}))
    monkeypatch.delenv("PAPYRUS_IDENTITY_POOL_ID", raising=False)
    assert identity_pool_id_from_amplify_outputs(outputs) == "us-east-1:from-file"
    monkeypatch.setenv("PAPYRUS_IDENTITY_POOL_ID", "us-east-1:from-env")
    assert identity_pool_id_from_amplify_outputs(outputs) == "us-east-1:from-env"


def test_user_identity_uses_the_signed_in_sessions_id_token(monkeypatch):
    from papyrus_content import cli_user_auth

    monkeypatch.setattr("papyrus_content.env.graphql_endpoint", lambda: "https://api.example/graphql")
    monkeypatch.setattr(cli_user_auth, "selected_headers", lambda endpoint: {"Authorization": "tok"})
    monkeypatch.setattr(cli_user_auth, "config_for_endpoint", lambda endpoint: mock.Mock(issuer="https://cognito-idp.us-east-1.amazonaws.com/p"))
    assert story_images.user_identity() == ("tok", "https://cognito-idp.us-east-1.amazonaws.com/p")
    monkeypatch.setattr(cli_user_auth, "selected_headers", lambda endpoint: None)
    with pytest.raises(ValueError, match="papyrus login"):
        story_images.user_identity()


def test_open_media_store_picks_the_lane(monkeypatch):
    built = []
    fake_store = lambda bucket=None, client=None, **_: built.append((bucket, client)) or "store"
    monkeypatch.setattr("papyrus_content.media_store.S3MediaStore", fake_store)
    monkeypatch.setattr(story_images, "user_lane_s3_client", lambda pool: ("user-client", pool))
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
    assert story_images.open_media_store("b") == "store" and built[-1] == ("b", None)
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "user")
    story_images.open_media_store("b", "pool")
    assert built[-1] == ("b", ("user-client", "pool"))


def test_a_file_already_stored_keeps_its_path_even_after_the_slug_changes(tmp_path):
    png(tmp_path / "c.png")
    first = plan_story_images('::image{src="c.png"}', tmp_path, slug="draft-unsectioned-1a2b3c4d")
    stored = story_images.existing_assets(
        [row for row in first.media_rows("item-v2")]
    )
    again = plan_story_images('::image{src="c.png"}', tmp_path, slug="a-real-title", existing=stored)
    assert [i.src_path for i in again.images] == ["assets/draft-unsectioned-1a2b3c4d/c.png"]
    assert again.images[0].storage_path == first.images[0].storage_path


def test_a_name_holding_different_content_is_numbered_not_overwritten(tmp_path):
    png(tmp_path / "c.png", 40, 20)
    existing = {"assets/hello/c.png": "0" * 64}
    plan = plan_story_images('::image{src="c.png"}', tmp_path, slug="hello", existing=existing)
    assert plan.images[0].src_path == "assets/hello/c-2.png"
    assert 'src="assets/hello/c-2.png"' in plan.body


def test_existing_assets_reads_src_path_and_sha_from_metadata_rows():
    rows = [
        {"metadata": json.dumps({"srcPath": "assets/a/x.png", "sha256": "ab"})},
        {"metadata": {"srcPath": "assets/a/y.png", "sha256": "cd"}},
        {"metadata": "not json"},
        {"metadata": json.dumps({"srcPath": "assets/a/z.png"})},
    ]
    assert story_images.existing_assets(rows) == {"assets/a/x.png": "ab", "assets/a/y.png": "cd"}
