from __future__ import annotations

import unittest


class ThreatIntelligenceVideoPipelineTests(unittest.TestCase):
    def test_build_babulus_xml_includes_voiceover(self) -> None:
        from publications.threat_intelligence.videoml.video_pipeline import build_babulus_xml

        xml = build_babulus_xml(
            {
                "slug": "the-balance-of-power-is-shifting",
                "headline": "Sample Headline",
                "deck": "Sample deck",
                "excerpt": "Sample excerpt.",
                "section": "Mission",
                "byline": "Anthus AI Solutions",
                "pullQuotes": ["Quote one."],
                "image": {
                    "alt": "Sample pictogram",
                    "credit": "Anthus Threat Intelligence diagram",
                },
            },
            voice="alloy",
            model="gpt-4o-mini-tts",
        )
        self.assertIn('provider="openai"', xml)
        self.assertIn("Sample Headline", xml)
        self.assertIn("Sample excerpt.", xml)
        self.assertIn("<layer id=\"background\"", xml)
        self.assertIn("<ti-title-slide", xml)
        self.assertIn("pictogramSlug", xml)
        self.assertIn("the-balance-of-power-is-shifting", xml)
        self.assertIn("<quote-card", xml)
        self.assertIn("<video-background", xml)
        self.assertNotIn("data:image/svg+xml;base64,", xml)
        self.assertIn("eyebrowRule", xml)
        self.assertIn("--ti-alarm-red", xml)
        self.assertIn('"--ti-section-rule":"#e54d2e"', xml)
        self.assertNotIn("#ec6142", xml)
        closing_index = xml.index('id="closing"')
        closing_eyebrow_rule = xml.index("eyebrowRule", closing_index)
        self.assertGreater(closing_eyebrow_rule, closing_index)
        self.assertIn("<ti-title-slide", xml[closing_index:])
        self.assertIn("THREAT INTELLIGENCE", xml)
        self.assertIn("Learn more", xml)
        self.assertIn("July 4, 2026", xml)
        self.assertNotIn("This briefing is from", xml)
        self.assertIn('"variant":"solid"', xml)
        self.assertNotIn('"gradient"', xml)
        hook_index = xml.index('id="hook"')
        title_index = xml.index('id="title"')
        self.assertLess(hook_index, title_index)

    def test_build_edition_overview_xml_includes_spotlights(self) -> None:
        from publications.threat_intelligence.videoml.video_pipeline import build_edition_overview_xml, load_ti_seed_payload

        xml = build_edition_overview_xml(
            load_ti_seed_payload(),
            voice="alloy",
            model="gpt-4o-mini-tts",
        )
        self.assertIn("edition-teaser", xml)
        self.assertNotIn('id="intro"', xml)
        hook_index = xml.index('id="hook"')
        title_index = xml.index('id="title"')
        teaser_index = xml.index("edition-teaser")
        self.assertLess(hook_index, title_index)
        self.assertLess(title_index, teaser_index)
        self.assertLess(teaser_index, xml.index("spotlight-1"))
        self.assertIn("spotlight-1", xml)
        self.assertIn("spotlight-6", xml)
        self.assertIn("Practical advice for staying secure", xml)
        self.assertNotIn("#ec6142", xml)
        self.assertIn('"--ti-section-rule":"#e54d2e"', xml)
        self.assertIn("eyebrowRule", xml)
        teaser_index = xml.index("edition-teaser")
        teaser_eyebrow_rule = xml.index("eyebrowRule", teaser_index)
        self.assertGreater(teaser_eyebrow_rule, teaser_index)
        self.assertIn("THREAT INTELLIGENCE", xml)
        self.assertIn("Learn more", xml)
        self.assertIn("July 4, 2026", xml)
        self.assertIn("To learn more, check out the July 4, 2026 edition", xml)
        self.assertIn('"variant":"solid"', xml)
        self.assertNotIn('"gradient"', xml)
        self.assertIn("pictogramSlug", xml)
        self.assertIn("the-balance-of-power-is-shifting", xml)

    def test_ti_scene_styles_light_has_light_palette(self) -> None:
        from publications.threat_intelligence.videoml.video_pipeline import (
            TI_SCENE_STYLES_DARK,
            TI_SCENE_STYLES_LIGHT,
            TI_BACKGROUND_PROPS_DARK,
            TI_BACKGROUND_PROPS_LIGHT,
            scene_styles_for_theme,
            background_props_for_theme,
        )

        self.assertEqual(TI_SCENE_STYLES_DARK["background"], "#191918")
        self.assertEqual(TI_SCENE_STYLES_LIGHT["background"], "#f9f9f8")
        self.assertEqual(TI_BACKGROUND_PROPS_DARK["color"], "#191918")
        self.assertEqual(TI_BACKGROUND_PROPS_LIGHT["color"], "#f9f9f8")
        self.assertEqual(scene_styles_for_theme("dark")["background"], "#191918")
        self.assertEqual(scene_styles_for_theme("light")["background"], "#f9f9f8")
        self.assertEqual(background_props_for_theme("dark")["color"], "#191918")
        self.assertEqual(background_props_for_theme("light")["color"], "#f9f9f8")

        dark_vars = TI_SCENE_STYLES_DARK["vars"]
        light_vars = TI_SCENE_STYLES_LIGHT["vars"]
        self.assertEqual(dark_vars["--ti-alarm-red"], "#e54d2e")
        self.assertEqual(light_vars["--ti-alarm-red"], "#c54028")
        self.assertEqual(dark_vars["--ti-pictogram-edge"], "#363a3f")
        self.assertEqual(light_vars["--ti-pictogram-edge"], "#889096")

    def test_article_output_mp4_light_suffix(self) -> None:
        from publications.threat_intelligence.videoml.video_pipeline import article_output_mp4, edition_overview_output_mp4

        dark_article = article_output_mp4({"slug": "test-slug"}, theme="dark")
        light_article = article_output_mp4({"slug": "test-slug"}, theme="light")
        default_article = article_output_mp4({"slug": "test-slug"})
        self.assertEqual(dark_article.name, "test-slug.mp4")
        self.assertEqual(light_article.name, "test-slug-light.mp4")
        self.assertEqual(default_article.name, "test-slug.mp4")

        dark_overview = edition_overview_output_mp4(theme="dark")
        light_overview = edition_overview_output_mp4(theme="light")
        default_overview = edition_overview_output_mp4()
        self.assertEqual(dark_overview.name, "edition-overview.mp4")
        self.assertEqual(light_overview.name, "edition-overview-light.mp4")
        self.assertEqual(default_overview.name, "edition-overview.mp4")

    def test_build_babulus_xml_light_theme_uses_light_palette(self) -> None:
        from publications.threat_intelligence.videoml.video_pipeline import build_babulus_xml

        xml = build_babulus_xml(
            {
                "slug": "the-balance-of-power-is-shifting",
                "headline": "Sample Headline",
                "deck": "Sample deck",
                "excerpt": "Sample excerpt.",
                "section": "Mission",
                "byline": "Anthus AI Solutions",
                "pullQuotes": ["Quote one."],
                "image": {
                    "alt": "Sample pictogram",
                    "credit": "Anthus Threat Intelligence diagram",
                },
            },
            voice="alloy",
            model="gpt-4o-mini-tts",
            theme="light",
        )
        self.assertIn('"--ti-section-rule":"#c54028"', xml)
        self.assertIn('"--ti-alarm-red":"#c54028"', xml)
        self.assertIn('"--ti-headline-color":"#44403c"', xml)
        self.assertIn('"background":"#f9f9f8"', xml)
        self.assertNotIn("#191918", xml)
        self.assertNotIn("#e54d2e", xml)

    def test_parse_theme_option_validates_values(self) -> None:
        from publications.threat_intelligence.videoml.videos_commands import parse_theme_option, resolve_themes

        self.assertEqual(parse_theme_option(None), "both")
        self.assertEqual(parse_theme_option("both"), "both")
        self.assertEqual(parse_theme_option("dark"), "dark")
        self.assertEqual(parse_theme_option("light"), "light")
        self.assertEqual(resolve_themes("both"), ["dark", "light"])
        self.assertEqual(resolve_themes("dark"), ["dark"])
        self.assertEqual(resolve_themes("light"), ["light"])

        with self.assertRaises(ValueError):
            parse_theme_option("invalid")

    def test_parse_jobs_option_defaults_and_validates(self) -> None:
        from publications.threat_intelligence.videoml.videos_commands import parse_jobs_option

        self.assertEqual(parse_jobs_option(None), 3)
        self.assertEqual(parse_jobs_option("1"), 1)
        self.assertEqual(parse_jobs_option("4"), 4)

        with self.assertRaises(ValueError):
            parse_jobs_option("0")
        with self.assertRaises(ValueError):
            parse_jobs_option("-1")


if __name__ == "__main__":
    unittest.main()
