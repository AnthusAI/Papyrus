from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from procedures.newsroom.tests.fake_client import FakeAuthoringClient
from papyrus_content.videoml import commands, dsl, pipeline
from papyrus_content.videoml.config import load_video_config

FIXTURE_CONFIG = Path(__file__).parent / "fixtures" / "videoml" / "video.yml"
ITEM = {
    "id": "item-articles-sample-article",
    "slug": "sample-article",
    "type": "article",
    "section": "Mission",
    "headline": "Sample Headline",
    "deck": "Sample deck",
    "publishedAt": "2026-07-04T12:00:00.000Z",
    "pullQuotes": ["Quote one.", "Quote two."],
    "editorial": json.dumps({"excerpt": "Sample excerpt."}),
}


class DirStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.puts: list[tuple[str, str]] = []

    def put(self, storage_path: str, local_path: Path, *, content_type: str, sha256: str) -> str:
        target = self.root / storage_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(local_path).read_bytes())
        self.puts.append((storage_path, content_type))
        return "uploaded"


def write_config(root: Path, text: str) -> Path:
    path = root / "video.yml"
    path.write_text(text, encoding="utf-8")
    return path


class VideoConfigTests(unittest.TestCase):
    def test_loads_fixture_relative_to_root(self) -> None:
        root = Path("/publication")
        config = load_video_config(FIXTURE_CONFIG, root=root)
        self.assertEqual(config.output_dir, root / "video/out")
        self.assertEqual(config.lead_slugs, ("sample-article",))
        self.assertEqual(config.dark.vars["--color-accent"], "#e54d2e")
        self.assertEqual(config.title_slide_component, "sample-title-slide")
        self.assertEqual(config.post_roll.title, "SAMPLE NEWS")

    def test_missing_file_explains_what_is_missing(self) -> None:
        with self.assertRaisesRegex(ValueError, "Video config not found"):
            load_video_config(Path("/nonexistent/video.yml"))

    def test_bad_keys_are_named(self) -> None:
        base = FIXTURE_CONFIG.read_text(encoding="utf-8")
        cases = {
            "schemaVersion: 2": ("schemaVersion: 1", "schemaVersion"),
            "outputDir:": ("outputDir: video/out", "outputDir"),
            "scene.dark.background": ('    background: "#191918"\n', "scene.dark.background"),
            "components.quoteCard": ("  quoteCard: sample-quote-card\n", "components.quoteCard"),
            "tts.provider": ("  provider: openai", "tts.provider"),
        }
        replacements = {
            "schemaVersion: 2": "schemaVersion: 2",
            "outputDir:": "",
            "scene.dark.background": "",
            "components.quoteCard": "",
            "tts.provider": "  provider: polly",
        }
        for label, (needle, key) in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as directory:
                path = write_config(Path(directory), base.replace(needle, replacements[label]))
                with self.assertRaisesRegex(ValueError, key.replace(".", r"\.")):
                    load_video_config(path)

    def test_unknown_key_is_rejected_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_config(Path(directory), FIXTURE_CONFIG.read_text(encoding="utf-8") + "mystery: 1\n")
            with self.assertRaisesRegex(ValueError, "unknown key 'mystery'"):
                load_video_config(path)


class DslTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_video_config(FIXTURE_CONFIG, root=Path("/publication"))
        self.article = dsl.article_from_item(ITEM)

    def build(self, article: dict, theme: str = "dark") -> str:
        return dsl.build_article_dsl(article, config=self.config, voice="alloy", model="gpt-4o-mini-tts", theme=theme)

    def test_article_from_item_reads_cms_fields(self) -> None:
        self.assertEqual(self.article["excerpt"], "Sample excerpt.")
        self.assertEqual(self.article["publishDate"], "2026-07-04")
        self.assertEqual(self.article["pullQuotes"], ["Quote one.", "Quote two."])

    def test_fallback_dsl_uses_configured_components_and_post_roll(self) -> None:
        xml = self.build(self.article)
        self.assertIn('provider="openai"', xml)
        self.assertIn("<sample-title-slide", xml)
        self.assertIn("<sample-quote-card", xml)
        self.assertIn("<video-background", xml)
        self.assertIn('"eyebrowRule":true', xml)
        self.assertIn('"--color-accent":"#e54d2e"', xml)
        self.assertIn("To learn more, check out the July 4, 2026 edition of Sample News.", xml)
        self.assertLess(xml.index('id="hook"'), xml.index('id="title"'))
        self.assertLess(xml.index('id="title"'), xml.index('id="post-roll"'))
        self.assertIn('"pictogramSlug":"sample-article"', xml)

    def test_authored_scenes_replace_fallback_and_get_post_roll(self) -> None:
        article = {
            **self.article,
            "video": {
                "scenes": [
                    {"kind": "quote", "quote": "Opening quote, isn't it.", "voice": "Opening voice."},
                    {"kind": "slide", "pictogram": "sample-article", "voice": "Picture voice."},
                ],
                "postRollVoice": "Custom closing.",
            },
        }
        xml = self.build(article)
        self.assertIn("Opening quote, isn&#39;t it.", xml)
        self.assertIn('"pictogramSize":600', xml)
        self.assertIn('"horizontalAlign":"center"', xml)
        self.assertIn("Custom closing.", xml)
        self.assertNotIn('id="hook"', xml)
        self.assertLess(xml.index('id="scene-1"'), xml.index('id="scene-2"'))
        self.assertLess(xml.index('id="scene-2"'), xml.index('id="post-roll"'))

    def test_authored_scene_without_voice_is_rejected(self) -> None:
        article = {**self.article, "video": {"scenes": [{"kind": "slide", "title": "T"}]}}
        with self.assertRaisesRegex(ValueError, "missing voice"):
            self.build(article)

    def test_light_theme_uses_light_palette(self) -> None:
        xml = self.build(self.article, theme="light")
        self.assertIn('"background":"#ffffff"', xml)
        self.assertIn('"color":"#ffffff"', xml)
        self.assertNotIn("#191918", xml)

    def test_retheme_swaps_dark_dsl_and_rejects_foreign_palette(self) -> None:
        dark_xml = self.build(self.article)
        light_xml = dsl.retheme_vml_xml(dark_xml, "light", self.config)
        self.assertEqual(light_xml, self.build(self.article, theme="light"))
        with self.assertRaisesRegex(ValueError, "different scene palette"):
            dsl.retheme_vml_xml("<vml></vml>", "light", self.config)

    def test_rewrite_voiceover_provider_replaces_first_element(self) -> None:
        xml = '<vml><voiceover provider="a" voice="b" model="c" /></vml>'
        replacement = dsl.voiceover_element("openai", voice="alloy", model="m")
        self.assertIn('voice="alloy"', dsl.rewrite_voiceover_provider(xml, replacement))

    def test_resolve_prefers_stored_script_unless_from_article(self) -> None:
        stored = self.build(self.article).replace("Sample Headline", "Stored Headline")
        client = FakeAuthoringClient(
            {
                "Item": [
                    ITEM,
                    {
                        "id": "item-videoml-sample-article",
                        "slug": "sample-article--videoml",
                        "editorial": json.dumps({"videoScript": {"dsl": stored}}),
                    },
                ]
            }
        )
        defaults = lambda _provider: {"voice": "alloy", "model": "m"}
        common = dict(client=client, config=self.config, target_slug="sample-article", theme="light", voiceover_defaults=defaults, provider="openai")
        from_store = dsl.resolve_dsl_for_render(from_article=False, **common)
        from_copy = dsl.resolve_dsl_for_render(from_article=True, **common)
        self.assertIn("Stored Headline", from_store)
        self.assertIn('"background":"#ffffff"', from_store)
        self.assertIn("Sample Headline", from_copy)
        self.assertNotIn("Stored Headline", from_copy)

    def test_resolve_unknown_slug_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "No item with slug"):
            dsl.resolve_dsl_for_render(
                client=FakeAuthoringClient(),
                config=self.config,
                target_slug="missing",
                theme="dark",
                from_article=False,
                voiceover_defaults=lambda _p: {"voice": "v", "model": "m"},
                provider="openai",
            )


class CommandResolutionTests(unittest.TestCase):
    def test_env_beats_node_modules_and_missing_cli_explains(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = load_video_config(FIXTURE_CONFIG, root=root)
            args = (config, root / "a.xml", root / "work", root / "out.mp4")
            with self.assertRaisesRegex(ValueError, "VIDEOML_CLI"):
                pipeline.resolve_vml_command(*args, environ={})
            local = root / "node_modules" / ".bin"
            local.mkdir(parents=True)
            (local / "vml").write_text("#!/bin/sh\n", encoding="utf-8")
            command, cwd = pipeline.resolve_vml_command(*args, environ={})
            self.assertEqual(command[:3], ["npx", "--no-install", "vml"])
            self.assertEqual(command[3], "pipeline")
            self.assertEqual(cwd, root)
            explicit = root / "custom-vml"
            explicit.write_text("#!/bin/sh\n", encoding="utf-8")
            command, _cwd = pipeline.resolve_vml_command(*args, environ={"VIDEOML_CLI": str(explicit)})
            self.assertEqual(command[0], str(explicit))
            self.assertIn("--out", command)
            with self.assertRaisesRegex(ValueError, "not a file"):
                pipeline.resolve_vml_command(*args, environ={"VIDEOML_CLI": str(root / "nope")})


class RenderTests(unittest.TestCase):
    def test_render_invokes_stubbed_cli_and_writes_dsl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = load_video_config(FIXTURE_CONFIG, root=root)
            (root / "public" / "videoml").mkdir(parents=True)
            config.browser_bundle.write_text("bundle", encoding="utf-8")
            (root / "node_modules" / ".bin").mkdir(parents=True)
            (root / "node_modules" / ".bin" / "vml").write_text("", encoding="utf-8")
            client = FakeAuthoringClient({"Item": [ITEM]})

            def fake_run(command, **kwargs):
                Path(command[command.index("--out") + 1]).write_bytes(b"mp4")
                self.assertEqual(kwargs["env"]["OPENAI_API_KEY"], "sk-test")
                self.assertEqual(kwargs["env"]["BABULUS_BROWSER_BUNDLE"], str(config.browser_bundle))
                return mock.Mock(returncode=0, stdout="", stderr="")

            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}), mock.patch.object(pipeline.subprocess, "run", side_effect=fake_run) as run:
                output = pipeline.render_video(config, client, "sample-article", theme="light", provider="openai")
            self.assertEqual(output, root / "video/out/sample-article-light.mp4")
            self.assertEqual(run.call_count, 1)
            self.assertTrue((root / "video/work/sample-article/sample-article-light.babulus.xml").is_file())
            self.assertTrue((root / "video/work/sample-article/.videoml/config.yml").is_file())

    def test_render_without_bundle_names_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = load_video_config(FIXTURE_CONFIG, root=Path(directory))
            with self.assertRaisesRegex(ValueError, "browser bundle is missing"):
                pipeline.render_video(config, FakeAuthoringClient({"Item": [ITEM]}), "sample-article", provider="openai")


class CommandOptionTests(unittest.TestCase):
    def test_theme_and_jobs_options(self) -> None:
        self.assertEqual(commands.resolve_themes(commands.parse_theme_option(None)), ["dark", "light"])
        self.assertEqual(commands.resolve_themes("light"), ["light"])
        with self.assertRaises(ValueError):
            commands.parse_theme_option("sepia")
        self.assertEqual(commands.parse_jobs_option(None), 3)
        self.assertEqual(commands.parse_jobs_option("5"), 5)

    def test_seed_dry_run_renders_nothing(self) -> None:
        config = load_video_config(FIXTURE_CONFIG, root=Path("/publication"))
        client = FakeAuthoringClient({"Item": [ITEM]})
        with mock.patch.object(commands, "render_video") as render, mock.patch("builtins.print") as printed:
            commands.videos_seed(["--dry-run", "--theme", "light"], client=client, config=config)
        render.assert_not_called()
        plan = json.loads(printed.call_args[0][0])["plan"]
        self.assertEqual(plan[0]["output"], "/publication/video/out/sample-article-light.mp4")

    def test_render_requires_article(self) -> None:
        config = load_video_config(FIXTURE_CONFIG, root=Path("/publication"))
        with self.assertRaisesRegex(ValueError, "--article"):
            commands.videos_render([], config=config)


class AttachTests(unittest.TestCase):
    def test_attach_writes_lead_media_asset_and_uploads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = load_video_config(FIXTURE_CONFIG, root=root)
            config.output_dir.mkdir(parents=True)
            (config.output_dir / "sample-article.mp4").write_bytes(b"dark")
            (config.output_dir / "sample-article-light.mp4").write_bytes(b"light")
            client = FakeAuthoringClient({"Item": [ITEM]})
            store = DirStore(root / "store")
            result = commands.attach_rendered_video(client, store, config, "sample-article")
            row = client.get_record("MediaAsset", result["mediaAssetId"])
            self.assertEqual(row["itemId"], ITEM["id"])
            self.assertEqual(row["type"], "video")
            self.assertEqual(row["role"], "lead")
            self.assertEqual(row["storagePath"], "media/videos/sample-article.mp4")
            self.assertEqual(
                json.loads(row["metadata"])["themeVariants"]["light"]["storagePath"],
                "media/videos/sample-article-light.mp4",
            )
            self.assertEqual((root / "store/media/videos/sample-article.mp4").read_bytes(), b"dark")
            self.assertEqual({path for path, _type in store.puts}, {"media/videos/sample-article.mp4", "media/videos/sample-article-light.mp4"})
            commands.attach_rendered_video(client, store, config, "sample-article")
            self.assertEqual(len(client.list_records("MediaAsset")), 1)

    def test_attach_without_render_explains(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = load_video_config(FIXTURE_CONFIG, root=Path(directory))
            with self.assertRaisesRegex(ValueError, "Rendered video not found"):
                commands.attach_rendered_video(FakeAuthoringClient({"Item": [ITEM]}), DirStore(Path(directory)), config, "sample-article")


if __name__ == "__main__":
    unittest.main()
