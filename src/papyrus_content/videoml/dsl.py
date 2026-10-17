from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Callable
from xml.sax.saxutils import escape

from .config import THEMES, VideoConfig

VIDEO_RHYTHM_UNIT = 6
VIDEO_COPY_ROW_MULTIPLE = 4
VIDEO_ROW_HEIGHT = VIDEO_RHYTHM_UNIT * VIDEO_COPY_ROW_MULTIPLE
VIDEOML_ITEM_SUFFIX = "--videoml"
VIDEO_FPS = 30
VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720
TRANSITION_XML = (
    '  <transition id="trans-{index}" effect="push" duration="16f" ease="power3.inOut" '
    "props='{{\"direction\":\"left\"}}' />"
)


def video_rows(rows: int) -> int:
    return rows * VIDEO_ROW_HEIGHT


VIDEO_LAYOUT = {
    "padding": video_rows(4),
    "gap": video_rows(1),
    "column_gap": video_rows(2),
    "eyebrow_size": video_rows(1),
    "title_size": video_rows(3),
    "title_size_briefing": video_rows(2),
    "subtitle_size": video_rows(1),
    "subtitle_size_closing": video_rows(2),
    "closing_title_size": video_rows(4),
    "pictogram_size": video_rows(18),
    "pictogram_size_briefing": video_rows(15),
    "title_line_height": video_rows(3),
    "subtitle_line_height": video_rows(2),
}
PICTOGRAM_ONLY_SIZE = 600


def props_attr(value: dict[str, Any]) -> str:
    raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return raw.replace("&", "&amp;").replace("'", "&#39;").replace("<", "&lt;")


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "article"


def truncate_display(text: str, max_len: int = 240) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_len:
        return cleaned
    trimmed = cleaned[: max_len - 1].rsplit(" ", 1)[0]
    return f"{trimmed}…"


def format_publish_date(publish_date: str) -> str:
    try:
        parsed = date.fromisoformat(publish_date)
    except ValueError:
        return publish_date
    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


def videoml_item_slug(target_slug: str) -> str:
    normalized = target_slug.strip()
    if not normalized:
        raise ValueError("Video target slug is required.")
    return f"{normalized}{VIDEOML_ITEM_SUFFIX}"


def parse_json_field(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def parse_video_script_editorial(editorial: Any) -> dict[str, Any] | None:
    parsed = parse_json_field(editorial)
    if not isinstance(parsed, dict):
        return None
    video_script = parsed.get("videoScript")
    if not isinstance(video_script, dict):
        return None
    dsl = video_script.get("dsl")
    if not isinstance(dsl, str) or not dsl.strip():
        return None
    return video_script


def article_from_item(item: dict[str, Any]) -> dict[str, Any]:
    editorial = parse_json_field(item.get("editorial"))
    editorial = editorial if isinstance(editorial, dict) else {}
    newsroom = editorial.get("newsroom") if isinstance(editorial.get("newsroom"), dict) else {}
    pull_quotes = parse_json_field(item.get("pullQuotes"))
    pull_quotes = pull_quotes if isinstance(pull_quotes, list) else []
    published_at = str(item.get("publishedAt") or "").strip()
    return {
        "slug": str(item.get("slug") or "").strip(),
        "headline": str(item.get("headline") or item.get("title") or "").strip(),
        "deck": str(item.get("deck") or "").strip(),
        "section": str(item.get("section") or "").strip(),
        "excerpt": str(editorial.get("excerpt") or newsroom.get("excerpt") or "").strip(),
        "pullQuotes": [str(entry).strip() for entry in pull_quotes if str(entry).strip()],
        "video": editorial.get("video"),
        "publishDate": published_at[:10] if published_at else "",
    }


def voiceover_element(provider: str, *, voice: str, model: str) -> str:
    return f'<voiceover provider="{escape(provider)}" voice="{escape(voice)}" model="{escape(model)}" />'


def rewrite_voiceover_provider(dsl_xml: str, replacement: str) -> str:
    pattern = re.compile(r"<voiceover\b[^>]*/>")
    if not pattern.search(dsl_xml):
        return dsl_xml
    return pattern.sub(lambda _: replacement, dsl_xml, count=1)


def retheme_vml_xml(dsl_xml: str, theme: str, config: VideoConfig) -> str:
    if theme == "dark":
        return dsl_xml
    dark_styles = props_attr(config.dark.styles())
    dark_background = props_attr(config.dark.background_props())
    light_styles = props_attr(config.light.styles())
    light_background = props_attr(config.light.background_props())
    if dark_styles not in dsl_xml and light_styles not in dsl_xml:
        raise ValueError(
            "Stored VideoML script was authored against a different scene palette than the "
            "publication's video config (scene.dark). Regenerate the script."
        )
    updated = dsl_xml.replace(dark_styles, light_styles)
    return updated.replace(dark_background, light_background)


def title_slide_layer(config: VideoConfig, *, extra_props: dict[str, Any] | None = None, **fields: Any) -> str:
    props: dict[str, Any] = {
        "verticalAlign": "center",
        "horizontalAlign": fields.pop("horizontal_align", "left"),
        "entranceStartFrame": -999,
        "background": "transparent",
        "padding": VIDEO_LAYOUT["padding"],
        "gap": VIDEO_LAYOUT["gap"],
        "columnGap": VIDEO_LAYOUT["column_gap"],
        "titleSize": fields.pop("title_size", None) or VIDEO_LAYOUT["title_size"],
        "subtitleSize": fields.pop("subtitle_size", None) or VIDEO_LAYOUT["subtitle_size"],
        "titleLineHeight": VIDEO_LAYOUT["title_line_height"],
        "subtitleLineHeight": VIDEO_LAYOUT["subtitle_line_height"],
        **config.slide_props,
    }
    for source_name, prop_name in (
        ("eyebrow", "eyebrow"),
        ("masthead_eyebrow", "mastheadEyebrow"),
        ("title", "title"),
        ("subtitle", "subtitle"),
    ):
        value = fields.pop(source_name, None)
        if value:
            props[prop_name] = value
    if fields.pop("title_word_split", False):
        props["titleWordSplit"] = True
    pictogram_slug = fields.pop("pictogram_slug", None)
    logo_size = fields.pop("logo_size", None)
    secondary = fields.pop("secondary_pictogram_slug", None)
    delay = fields.pop("secondary_pictogram_delay_sec", None)
    if pictogram_slug:
        props["pictogramSlug"] = pictogram_slug
        props["pictogramSize"] = logo_size or VIDEO_LAYOUT["pictogram_size"]
        if secondary:
            props["secondaryPictogramSlug"] = secondary
        if delay is not None:
            props["secondaryPictogramDelaySec"] = delay
    if fields:
        raise ValueError(f"Unexpected title slide fields: {', '.join(sorted(fields))}")
    props.update(extra_props or {})
    tag = config.title_slide_component
    return f"""    <layer id="content" z="10">
      <{tag} props='{props_attr(props)}' />
    </layer>"""


def quote_card_layer(config: VideoConfig, *, quote: str, attribution: str = "", quote_size: int | None = None, quote_line_height: int | None = None) -> str:
    props: dict[str, Any] = {"quote": quote, "accentColor": config.quote_accent_color}
    if attribution:
        props["attribution"] = attribution
    if quote_size is not None:
        props["quoteSize"] = quote_size
    if quote_line_height is not None:
        props["quoteLineHeight"] = quote_line_height
    tag = config.quote_card_component
    return f"""    <layer id="content" z="10">
      <{tag} props='{props_attr(props)}' />
    </layer>"""


def render_scene(scene_id: str, scene_title: str, content_layer: str, cue_xml: str, *, config: VideoConfig, theme: str) -> str:
    scene_theme = config.scene_theme(theme)
    return f"""  <scene id="{escape(scene_id)}" title="{escape(scene_title)}" styles='{props_attr(scene_theme.styles())}'>
    <layer id="background" z="0">
      <video-background props='{props_attr(scene_theme.background_props())}' />
    </layer>
{content_layer}
    {cue_xml}
  </scene>"""


def cue_xml(cue_id: str, voice_text: str) -> str:
    return f"""<cue id="{escape(cue_id)}">
      <voice>{escape(voice_text)}</voice>
    </cue>"""


def authored_video_scenes(video_meta: Any) -> list[dict[str, Any]]:
    if not isinstance(video_meta, dict):
        return []
    scenes = video_meta.get("scenes")
    if not isinstance(scenes, list):
        return []
    return [scene for scene in scenes if isinstance(scene, dict)]


def post_roll_voice_override(video_meta: Any) -> str | None:
    if not isinstance(video_meta, dict):
        return None
    override = str(video_meta.get("postRollVoice") or "").strip()
    return override or None


def post_roll_voice(config: VideoConfig, publish_date: str) -> str:
    if config.post_roll is None:
        raise ValueError("Video config defines no postRoll.")
    return config.post_roll.voice.replace("{date}", format_publish_date(publish_date))


def post_roll_scene(config: VideoConfig, theme: str, publish_date: str, voice_override: str | None = None) -> str:
    post_roll = config.post_roll
    if post_roll is None:
        raise ValueError("Video config defines no postRoll.")
    voice_text = (voice_override or "").strip() or post_roll_voice(config, publish_date)
    layer = title_slide_layer(
        config,
        masthead_eyebrow=post_roll.eyebrow,
        title=post_roll.title,
        title_word_split=True,
        subtitle=post_roll.tagline,
        horizontal_align="center",
        title_size=VIDEO_LAYOUT["closing_title_size"],
        subtitle_size=VIDEO_LAYOUT["subtitle_size_closing"],
        extra_props=post_roll.props,
    )
    return render_scene("post-roll", "Post-roll", layer, cue_xml("post-roll-cue", voice_text), config=config, theme=theme)


def authored_scene_xml(scene: dict[str, Any], index: int, *, config: VideoConfig, theme: str) -> str:
    kind = str(scene.get("kind") or "slide").strip().lower()
    voice_text = str(scene.get("voice") or "").strip()
    if not voice_text:
        raise ValueError(f"Authored video scene {index} is missing voice narration.")
    scene_id = f"scene-{index}"
    cue = cue_xml(f"{scene_id}-cue", voice_text)
    if kind == "quote":
        quote = str(scene.get("quote") or "").strip()
        if not quote:
            raise ValueError(f"Authored quote scene {index} is missing its quote text.")
        quote_size = scene.get("quoteSize")
        quote_line_height = scene.get("quoteLineHeight")
        layer = quote_card_layer(
            config,
            quote=quote,
            attribution=str(scene.get("attribution") or "").strip(),
            quote_size=int(quote_size) if quote_size else None,
            quote_line_height=int(quote_line_height) if quote_line_height else None,
        )
        return render_scene(scene_id, str(scene.get("title") or "Quote"), layer, cue, config=config, theme=theme)
    if kind != "slide":
        raise ValueError(f"Authored video scene {index} has unknown kind: {kind!r}")
    eyebrow = str(scene.get("eyebrow") or "").strip() or None
    title = str(scene.get("title") or "").strip() or None
    subtitle = str(scene.get("subtitle") or "").strip() or None
    pictogram = str(scene.get("pictogram") or "").strip() or None
    has_text = bool(eyebrow or title or subtitle)
    if not has_text and not pictogram:
        raise ValueError(f"Authored slide scene {index} has neither text nor a pictogram.")
    delay = scene.get("secondaryPictogramDelaySec")
    layer = title_slide_layer(
        config,
        pictogram_slug=pictogram,
        secondary_pictogram_slug=str(scene.get("secondaryPictogram") or "").strip() or None,
        secondary_pictogram_delay_sec=float(delay) if delay is not None else None,
        eyebrow=eyebrow,
        title=title,
        subtitle=subtitle,
        horizontal_align="left" if has_text else "center",
        logo_size=None if has_text else PICTOGRAM_ONLY_SIZE,
    )
    return render_scene(scene_id, str(scene.get("title") or f"Scene {index}"), layer, cue, config=config, theme=theme)


def join_scenes_with_transitions(scene_blocks: list[str]) -> str:
    parts: list[str] = []
    for index, block in enumerate(scene_blocks):
        if index > 0:
            parts.append(TRANSITION_XML.format(index=index))
        parts.append(block)
    return "\n\n".join(parts)


def vml_document(slug: str, headline: str, voiceover_xml: str, body: str) -> str:
    return f"""<vml id="{escape(slug)}" title="{escape(headline)}" fps="{VIDEO_FPS}" width="{VIDEO_WIDTH}" height="{VIDEO_HEIGHT}">
  {voiceover_xml}

{body}
</vml>
"""


def fallback_scene_blocks(article: dict[str, Any], slug: str, headline: str, *, config: VideoConfig, theme: str) -> list[str]:
    deck = str(article.get("deck") or "").strip()
    excerpt = str(article.get("excerpt") or "").strip()
    section = str(article.get("section") or "").strip() or None
    pull_quotes = [str(entry).strip() for entry in (article.get("pullQuotes") or []) if str(entry).strip()][:2]
    pictogram_slug = slug if slug in config.lead_slugs else None

    def scene(scene_id: str, title: str, layer: str, cue: str) -> str:
        return render_scene(scene_id, title, layer, cue, config=config, theme=theme)

    blocks: list[str] = []
    if pull_quotes:
        blocks.append(scene("hook", "Hook", quote_card_layer(config, quote=pull_quotes[0]), cue_xml("hook-cue", pull_quotes[0])))

    title_voice_parts = [f"<voice>{escape(headline)}</voice>"]
    if deck:
        title_voice_parts.append('<pause seconds="0.5s" />')
        title_voice_parts.append(f"<voice>{escape(deck)}</voice>")
    title_cue = '<cue id="title-cue">\n      ' + "\n      ".join(title_voice_parts) + "\n    </cue>"
    blocks.append(
        scene(
            "title",
            "Title",
            title_slide_layer(
                config,
                pictogram_slug=pictogram_slug,
                eyebrow=section,
                title=headline,
                subtitle=deck or None,
                logo_size=VIDEO_LAYOUT["pictogram_size"],
            ),
            title_cue,
        )
    )
    if excerpt:
        blocks.append(
            scene(
                "body-excerpt",
                "Briefing",
                title_slide_layer(
                    config,
                    pictogram_slug=pictogram_slug,
                    eyebrow="Briefing",
                    title=headline,
                    subtitle=truncate_display(excerpt),
                    logo_size=VIDEO_LAYOUT["pictogram_size_briefing"],
                    title_size=VIDEO_LAYOUT["title_size_briefing"],
                ),
                cue_xml("body-excerpt-cue", excerpt),
            )
        )
    if len(pull_quotes) > 1:
        quote = pull_quotes[1]
        blocks.append(
            scene(
                "body-quote-2",
                "Quote 2",
                quote_card_layer(config, quote=quote),
                cue_xml("body-quote-2-cue", f'As the article puts it: "{quote}"'),
            )
        )
    return blocks


def build_article_dsl(
    article: dict[str, Any],
    *,
    config: VideoConfig,
    voice: str,
    model: str,
    theme: str = "dark",
    provider: str = "openai",
) -> str:
    slug = slugify(str(article.get("slug") or "article"))
    headline = str(article.get("headline") or slug)
    publish_date = str(article.get("publishDate") or "").strip()
    voiceover_xml = voiceover_element(provider, voice=voice, model=model)
    video_meta = article.get("video")
    authored = authored_video_scenes(video_meta)
    if authored:
        blocks = [
            authored_scene_xml(scene, index + 1, config=config, theme=theme)
            for index, scene in enumerate(authored)
        ]
    else:
        blocks = fallback_scene_blocks(article, slug, headline, config=config, theme=theme)
    if config.post_roll is not None:
        if not publish_date and "{date}" in config.post_roll.voice and not post_roll_voice_override(video_meta):
            raise ValueError(f"Article '{slug}' has no publishedAt date for the post-roll voice.")
        blocks.append(post_roll_scene(config, theme, publish_date, post_roll_voice_override(video_meta)))
    return vml_document(slug, headline, voiceover_xml, join_scenes_with_transitions(blocks))


def fetch_item_by_slug(client: Any, slug: str) -> dict[str, Any] | None:
    rows = client.list_by_index("itemBySlug", slug)
    return rows[0] if rows else None


def fetch_stored_dsl(client: Any, target_slug: str) -> str | None:
    item = fetch_item_by_slug(client, videoml_item_slug(target_slug))
    if not item:
        return None
    video_script = parse_video_script_editorial(item.get("editorial"))
    return str(video_script["dsl"]) if video_script else None


def resolve_dsl_for_render(
    *,
    client: Any,
    config: VideoConfig,
    target_slug: str,
    theme: str,
    from_article: bool,
    voiceover_defaults: Callable[[str], dict[str, str]],
    provider: str,
) -> str:
    if theme not in THEMES:
        raise ValueError(f"Unknown video theme '{theme}'.")
    defaults = voiceover_defaults(provider)
    replacement = voiceover_element(provider, voice=defaults["voice"], model=defaults["model"])
    if not from_article:
        stored = fetch_stored_dsl(client, target_slug)
        if stored:
            return rewrite_voiceover_provider(retheme_vml_xml(stored, theme, config), replacement)
    item = fetch_item_by_slug(client, target_slug)
    if item is None:
        raise ValueError(f"No item with slug '{target_slug}' and no stored VideoML script '{videoml_item_slug(target_slug)}'.")
    return build_article_dsl(
        article_from_item(item),
        config=config,
        voice=defaults["voice"],
        model=defaults["model"],
        theme=theme,
        provider=provider,
    )
