"""A translated Story may show a localized picture (features_backend/story-localize-images.feature). The saves run on the shared in-memory fake backend."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import yaml
from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "features_backend" / "steps"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from story_localize_steps import LINEAGE, _latest, _upload, _versions  # noqa: E402


def _figures(row) -> list[dict]:
    from papyrus_content.markus_renderer.content_markup import _IMAGE_DIRECTIVE_RE, parse_attrs

    return [parse_attrs(match.group("attrs")) for match in _IMAGE_DIRECTIVE_RE.finditer(row["bodyMarkus"])]


def _front_matter(row) -> dict:
    return yaml.safe_load(json.loads(row["metadata"])["frontMatterYaml"]) or {}


@given('the English Story has the stored picture "{path}" that its figure record says holds {count:d} labels')
def step_figure_with_words(context, path, count):
    context.client.tables.setdefault("MediaAsset", {})["media-waymo"] = {
        "id": "media-waymo", "itemId": context.primary["id"], "type": "image", "sortKey": "0001",
        "metadata": json.dumps({"srcPath": path, "figure": {"embeddedText": True, "textLabels": count}})}
    context.primary["bodyMarkus"] = context.primary["bodyMarkus"].replace('src="assets/waymo.png"', f'src="{path}"')


@then('the translation\'s figure shows "{path}" with the alt text "{alt}"')
def step_figure_alt(context, path, alt):
    figure = _figures(_latest(context))[0]
    assert figure["src"] == path and figure["alt"] == alt, figure


@then('the translation\'s figure shows "{path}" with the dark picture "{dark}"')
def step_figure_dark(context, path, dark):
    figure = _figures(_latest(context))[0]
    assert figure["src"] == path and figure.get("srcDark") == dark, figure


@then("the translation records no picture variant")
def step_no_variant(context):
    assert "imageVariants" not in _front_matter(_latest(context)), _front_matter(_latest(context))


@then("the run reports {count:d} picture(s) that hold words")
@then("the run reports {count:d} pictures that hold words")
@then("the run reports {count:d} picture that holds words")
def step_reports(context, count):
    assert context.output["imagesWithText"] == count, context.output


@then('the translation\'s record names "{path}" as holding words and not localized')
def step_record_words(context, path):
    localization = json.loads(_latest(context)["metadata"])["localization"]
    assert [(entry["src"], entry["localized"]) for entry in localization["imagesWithText"]] == [(path, False)], localization


@then('the translation records "{path}" as the "{language}" variant of "{original}"')
def step_records_variant(context, path, language, original):
    entries = _front_matter(_latest(context))["imageVariants"]
    assert [(e["from"], e["src"], e["language"]) for e in entries] == [(original, path, language)], entries


@when('an editor saves the pictures "{light}" and "{dark}" as the "{language}" variant of "{original}"')
@given('an editor saves the pictures "{light}" and "{dark}" as the "{language}" variant of "{original}"')
def step_save_variant(context, light, dark, language, original):
    from papyrus_content.localize import image_save
    from papyrus_content.localize.record import carry_provenance

    saved = {}

    def fake_plan(body, root, slug, existing, front_matter):
        from papyrus_content import story_images

        plan = story_images.StoryImagePlan(body=body)
        for name in sorted(path.name for path in Path(root).iterdir()):   # the files the save staged: SLUG.png and SLUG.dark.png
            role, stored = ("dark", dark) if ".dark." in name else ("light", light)
            local = Path(root) / name
            plan.images.append(story_images.PlannedStoryImage(ref=name, local_path=local, role=role, src_path=stored, storage_path="media/" + stored,
                                                              content_type="image/png", size=4, sha256="0" * 64, width=10, height=10, position=len(plan.images) + 1))
        return plan

    with mock.patch("papyrus_content.story_images.plan_story_images", fake_plan), \
            mock.patch("papyrus_content.story_images.open_media_store", lambda *a, **k: mock.Mock()), \
            mock.patch("papyrus_content.story_images.upload_planned_images", lambda plan, store: [(image, "stored") for image in plan.images]), \
            mock.patch("papyrus_content.localize.record.download_attachment_buffer", create=True), \
            mock.patch("papyrus_content.model_attachments.upload_attachment_body", _upload(context)), \
            mock.patch("papyrus_content.model_attachments.download_attachment_buffer", lambda client, row: context.files.get(row["storagePath"])):
        import tempfile

        with tempfile.TemporaryDirectory() as scratch:
            files = Path(scratch)
            (files / "light.png").write_bytes(b"png1")
            (files / "dark.png").write_bytes(b"png2")
            context.variant_lines = image_save.save_variant(
                context.client, story="story-waymo", language=language, original=original, light=files / "light.png", dark=files / "dark.png",
                reason="localized figure", author="Test Editor", texts={"alt": "Un auto sin conductor"})
    context.versions_after_variant = len(_versions(context))
