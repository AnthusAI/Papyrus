from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.videoml import commands, pipeline  # noqa: E402
from papyrus_content.videoml.config import load_video_config  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402

FIXTURE_CONFIG = REPO_ROOT / "procedures" / "newsroom" / "tests" / "fixtures" / "videoml" / "video.yml"


class RecordingStore:
    def __init__(self) -> None:
        self.puts: list[str] = []

    def put(self, storage_path: str, local_path: Path, *, content_type: str, sha256: str) -> str:
        self.puts.append(storage_path)
        return "uploaded"


def new_publication(context) -> Path:
    root = Path(tempfile.mkdtemp(prefix="videos-feature-"))
    context.add_cleanup(shutil.rmtree, root, True)
    context.publication = root
    return root


@given("a publication directory without a video config")
def publication_without_config(context) -> None:
    new_publication(context)
    context.config_path = context.publication / "video" / "video.yml"


@when('I run videos render for the article "{slug}"')
def run_render(context, slug: str) -> None:
    context.failure = None
    try:
        config = load_video_config(context.config_path, root=context.publication)
        commands.videos_render(["--article", slug], client=FakeAuthoringClient(), config=config)
    except ValueError as error:
        context.failure = str(error)


@then('the command fails mentioning "{text}"')
@then('the failure mentions "{text}"')
def failure_mentions(context, text: str) -> None:
    assert context.failure and text in context.failure, context.failure


@given('a publication with a video config and a rendered video for "{slug}"')
def publication_with_video(context, slug: str) -> None:
    root = new_publication(context)
    context.video_config = load_video_config(FIXTURE_CONFIG, root=root)
    context.video_config.output_dir.mkdir(parents=True)
    (context.video_config.output_dir / f"{slug}.mp4").write_bytes(b"mp4")


@given('a CMS item "{slug}"')
def cms_item(context, slug: str) -> None:
    context.item_id = f"item-articles-{slug}"
    context.client = FakeAuthoringClient({"Item": [{"id": context.item_id, "slug": slug, "headline": "Sample"}]})


@when('I attach the video for "{slug}"')
def attach(context, slug: str) -> None:
    context.store = RecordingStore()
    commands.attach_rendered_video(context.client, context.store, context.video_config, slug)


@then('the item has a lead video media asset stored at "{storage_path}"')
def lead_media(context, storage_path: str) -> None:
    rows = context.client.list_by_index("mediaAssetsByItemAndSortKey", context.item_id)
    assert len(rows) == 1, rows
    assert (rows[0]["type"], rows[0]["role"], rows[0]["storagePath"]) == ("video", "lead", storage_path), rows[0]
    json.loads(rows[0]["metadata"])


@then("the video file was uploaded to the media store")
def uploaded(context) -> None:
    assert context.store.puts == ["media/videos/sample-article.mp4"], context.store.puts


@given("the publication has @videoml/cli installed in node_modules")
def cli_installed(context) -> None:
    binary_dir = context.publication / "node_modules" / ".bin"
    binary_dir.mkdir(parents=True)
    (binary_dir / "vml").write_text("", encoding="utf-8")


@when("I resolve the VideoML command")
def resolve_command(context) -> None:
    root = context.publication
    context.command, context.command_cwd = pipeline.resolve_vml_command(
        context.video_config, root / "a.xml", root / "work", root / "out.mp4", environ={}
    )


@then('the command runs "{text}"')
def command_runs(context, text: str) -> None:
    assert " ".join(context.command[: len(text.split())]) == text, context.command


@then("the command runs in the publication directory")
def command_cwd(context) -> None:
    assert context.command_cwd == context.publication, context.command_cwd
