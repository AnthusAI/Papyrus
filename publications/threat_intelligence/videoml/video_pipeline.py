from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from papyrus_content.env import PAPYRUS_ROOT, load_dotenv
from papyrus_content.papyrus_config import resolve_openai_api_key, resolve_openai_tts_defaults

DEFAULT_VIDEOML_CLI = Path.home() / "Projects" / "VideoML" / "cli"
DEFAULT_BABULUS_ROOT = Path.home() / "Projects" / "Babulus"
TI_BROWSER_BUNDLE = PAPYRUS_ROOT / "public" / "videoml" / "ti-browser-bundle.js"
TI_SEED_PROFILE = "threat-intelligence"
TI_VIDEO_OUTPUT_DIR = PAPYRUS_ROOT / "publications" / "threat_intelligence" / "seed-art" / "videos"
TI_SEED_CONTENT_PATH = (
    PAPYRUS_ROOT / "publications" / "threat_intelligence" / "seed" / "seed-edition-content.json"
)
EDITION_OVERVIEW_SLUG = "edition-overview"
LEAD_VIDEO_SLUGS = (
    "the-balance-of-power-is-shifting",
    "how-our-newsroom-learns",
    "audit-aws-exposure-before-attackers-do",
    "audit-azure-blast-radius-before-attackers-do",
    "treat-openai-accounts-like-production-infrastructure",
    "how-to-play-games-securely",
)

# Matches Threat Intelligence blog dark mode (`app/globals.css` sand-dark + tomato accent).
TI_SCENE_STYLES_DARK: dict[str, Any] = {
    "background": "#191918",
    "color": "#eeeeec",
    "vars": {
        "--color-bg": "#191918",
        "--color-bg-subtle": "#111110",
        "--color-surface": "#21201c",
        "--color-surface-strong": "#2a2926",
        "--color-text": "#eeeeec",
        "--color-text-muted": "#b5b3ad",
        "--color-primary": "#eeeeec",
        "--color-accent": "#e54d2e",
        "--color-secondary": "#7f7e77",
        "--ti-section-rule": "#e54d2e",
        "--ti-alarm-red": "#e54d2e",
        "--ti-headline-color": "#eeeeec",
        "--ti-body-color": "#b5b3ad",
        "--ti-cta-red": "#e54d2e",
        "--background": "#191918",
        "--foreground": "#b5b3ad",
        "--foreground-strong": "#eeeeec",
        "--ti-pictogram-edge": "#363a3f",
        "--ti-pictogram-node": "#2e3135",
        "--ti-pictogram-muted": "#43484e",
        "--ti-pictogram-throb": "#ac4d39",
        "--ti-pictogram-compromised": "#e54d2e",
        "--ti-pictogram-accent-glow": "rgba(251, 146, 60, 0.2)",
        "--grass-8": "#30a46c",
        "--amber-8": "#f59e0b",
        "--sand-8": "#9090a0",
        "--font-headline": "Helvetica Neue, Segoe UI, Helvetica, Arial, sans-serif",
        "--font-subhead": "Helvetica Neue, Segoe UI, Helvetica, Arial, sans-serif",
        "--font-eyebrow": "Helvetica Neue, Segoe UI, Helvetica, Arial, sans-serif",
    },
}

TI_BACKGROUND_PROPS_DARK: dict[str, Any] = {
    "variant": "solid",
    "color": "#191918",
}

# Matches Threat Intelligence blog light mode (`app/globals.css` sand-light + tomato-11 accent).
# Uses tomato-11 (#c54028) for WCAG-compliant contrast on sand-2 (#f9f9f8) paper.
TI_SCENE_STYLES_LIGHT: dict[str, Any] = {
    "background": "#f9f9f8",
    "color": "#44403c",
    "vars": {
        "--color-bg": "#f9f9f8",
        "--color-bg-subtle": "#fcfcfc",
        "--color-surface": "#fcfcfc",
        "--color-surface-strong": "#f2f2f0",
        "--color-text": "#44403c",
        "--color-text-muted": "#696964",
        "--color-primary": "#44403c",
        "--color-accent": "#c54028",
        "--color-secondary": "#8a8a83",
        "--ti-section-rule": "#c54028",
        "--ti-alarm-red": "#c54028",
        "--ti-headline-color": "#44403c",
        "--ti-body-color": "#696964",
        "--ti-cta-red": "#c54028",
        "--background": "#f9f9f8",
        "--foreground": "#696964",
        "--foreground-strong": "#44403c",
        "--ti-pictogram-edge": "#889096",
        "--ti-pictogram-node": "#889096",
        "--ti-pictogram-muted": "#a8adb4",
        "--ti-pictogram-throb": "#d9542e",
        "--ti-pictogram-compromised": "#c54028",
        "--ti-pictogram-accent-glow": "rgba(234, 88, 12, 0.18)",
        "--grass-8": "#30a46c",
        "--amber-8": "#f59e0b",
        "--sand-8": "#9090a0",
        "--font-headline": "Helvetica Neue, Segoe UI, Helvetica, Arial, sans-serif",
        "--font-subhead": "Helvetica Neue, Segoe UI, Helvetica, Arial, sans-serif",
        "--font-eyebrow": "Helvetica Neue, Segoe UI, Helvetica, Arial, sans-serif",
    },
}

TI_BACKGROUND_PROPS_LIGHT: dict[str, Any] = {
    "variant": "solid",
    "color": "#f9f9f8",
}

# Backward-compatible aliases (dark is the default theme).
TI_SCENE_STYLES = TI_SCENE_STYLES_DARK
TI_BACKGROUND_PROPS = TI_BACKGROUND_PROPS_DARK

THEMES = ("dark", "light")


def scene_styles_for_theme(theme: str) -> dict[str, Any]:
    return TI_SCENE_STYLES_LIGHT if theme == "light" else TI_SCENE_STYLES_DARK


def background_props_for_theme(theme: str) -> dict[str, Any]:
    return TI_BACKGROUND_PROPS_LIGHT if theme == "light" else TI_BACKGROUND_PROPS_DARK

TI_TAGLINE = "Practical advice for staying secure as the threat landscape shifts."


def load_ti_seed_payload() -> dict[str, Any]:
    payload = json.loads(TI_SEED_CONTENT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Seed content at {TI_SEED_CONTENT_PATH} must be a JSON object.")
    return payload


def load_ti_seed_articles() -> list[dict[str, Any]]:
    payload = load_ti_seed_payload()
    articles = payload.get("articles")
    if not isinstance(articles, list):
        raise ValueError(f"Seed content at {TI_SEED_CONTENT_PATH} must define articles as an array.")
    return [article for article in articles if isinstance(article, dict)]


def lead_video_articles(articles: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    source = articles if articles is not None else load_ti_seed_articles()
    selected = [article for article in source if str(article.get("slug", "")).strip() in LEAD_VIDEO_SLUGS]
    if not selected:
        raise ValueError("No lead-video articles found in the Threat Intelligence seed edition.")
    order = {slug: index for index, slug in enumerate(LEAD_VIDEO_SLUGS)}
    selected.sort(key=lambda article: order.get(str(article.get("slug", "")).strip(), 999))
    return selected


def article_output_mp4(article: dict[str, Any], *, output_dir: Path | None = None, theme: str = "dark") -> Path:
    slug = str(article.get("slug", "")).strip()
    if not slug:
        raise ValueError("Seed article is missing slug.")
    target_dir = output_dir or TI_VIDEO_OUTPUT_DIR
    suffix = "-light" if theme == "light" else ""
    return target_dir / f"{slug}{suffix}.mp4"


def edition_overview_output_mp4(*, output_dir: Path | None = None, theme: str = "dark") -> Path:
    target_dir = output_dir or TI_VIDEO_OUTPUT_DIR
    suffix = "-light" if theme == "light" else ""
    return target_dir / f"{EDITION_OVERVIEW_SLUG}{suffix}.mp4"


def props_attr(value: dict[str, Any]) -> str:
    raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return raw.replace("&", "&amp;")


def truncate_display(text: str, max_len: int = 240) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_len:
        return cleaned
    trimmed = cleaned[: max_len - 1].rsplit(" ", 1)[0]
    return f"{trimmed}…"


def first_sentence(text: str) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""
    match = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)
    return match[0]


def ensure_videoml_browser_bundle() -> Path:
    if not TI_BROWSER_BUNDLE.exists():
        build_script = PAPYRUS_ROOT / "scripts" / "videoml" / "build-browser-bundle.mjs"
        if not build_script.exists():
            raise ValueError(f"VideoML browser bundle is missing and build script was not found: {build_script}")
        result = subprocess.run(
            ["npm", "run", "videoml:bundle"],
            cwd=str(PAPYRUS_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Failed to build the Threat Intelligence VideoML browser bundle.\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
    if not TI_BROWSER_BUNDLE.exists():
        raise ValueError(f"VideoML browser bundle is missing at {TI_BROWSER_BUNDLE}. Run npm run videoml:bundle.")
    return TI_BROWSER_BUNDLE


def title_slide_layer(
    *,
    pictogram_slug: str | None = None,
    eyebrow: str | None = None,
    title: str | None = None,
    subtitle: str | None = None,
    horizontal_align: str = "left",
    logo_size: int = 400,
    title_size: int = 56,
    subtitle_size: int = 26,
    title_color: str | None = None,
    title_weight: int | None = None,
    eyebrow_weight: int | None = None,
    eyebrow_letter_spacing: float | None = None,
    eyebrow_size: int = 14,
    eyebrow_rule: bool = False,
) -> str:
    props: dict[str, Any] = {
        "verticalAlign": "center",
        "horizontalAlign": horizontal_align,
        "entranceStartFrame": -999,
        "background": "transparent",
        "titleSize": title_size,
        "subtitleSize": subtitle_size,
    }
    if eyebrow:
        props["eyebrow"] = eyebrow
    if title:
        props["title"] = title
    if subtitle:
        props["subtitle"] = subtitle
    if title_color:
        props["titleColor"] = title_color
    if title_weight is not None:
        props["titleWeight"] = title_weight
    if eyebrow_weight is not None:
        props["eyebrowWeight"] = eyebrow_weight
    if eyebrow_letter_spacing is not None:
        props["eyebrowLetterSpacing"] = eyebrow_letter_spacing
    if eyebrow_size != 14:
        props["eyebrowSize"] = eyebrow_size
    if eyebrow_rule:
        props["eyebrowRule"] = True
    if pictogram_slug:
        props["pictogramSlug"] = pictogram_slug
        props["pictogramSize"] = logo_size
    tag = "ti-title-slide" if (pictogram_slug or eyebrow_rule) else "title-slide"
    return f"""    <layer id="content" z="10">
      <{tag} props='{props_attr(props)}' />
    </layer>"""


def quote_card_layer(*, quote: str, attribution: str, accent_color: str = "var(--ti-alarm-red)") -> str:
    return f"""    <layer id="content" z="10">
      <quote-card props='{props_attr({"quote": quote, "attribution": attribution, "accentColor": accent_color})}' />
    </layer>"""


def closing_cta_layer(*, slide_date: str) -> str:
    return title_slide_layer(
        eyebrow=f"Learn more — {slide_date} edition",
        title="THREAT INTELLIGENCE",
        subtitle=TI_TAGLINE,
        horizontal_align="center",
        title_size=96,
        subtitle_size=28,
        title_color="var(--ti-alarm-red)",
        title_weight=900,
        eyebrow_weight=900,
        eyebrow_letter_spacing=0.09,
        eyebrow_rule=True,
    )


def closing_cta_voice(slide_date: str) -> str:
    return f"To learn more, check out the {slide_date} edition of Anthus Threat Intelligence. {TI_TAGLINE}"


def render_scene(
    scene_id: str,
    scene_title: str,
    content_layer: str,
    cue_xml: str,
    *,
    styles: dict[str, Any] | None = None,
    background_props: dict[str, Any] | None = None,
) -> str:
    resolved_styles = styles if styles is not None else TI_SCENE_STYLES_DARK
    resolved_background = background_props if background_props is not None else TI_BACKGROUND_PROPS_DARK
    return f"""  <scene id="{escape(scene_id)}" title="{escape(scene_title)}" styles='{props_attr(resolved_styles)}'>
    <layer id="background" z="0">
      <video-background props='{props_attr(resolved_background)}' />
    </layer>
{content_layer}
    {cue_xml}
  </scene>"""


def format_voice_edition_date(publish_date: str) -> str:
    try:
        parsed = date.fromisoformat(publish_date)
    except ValueError:
        return publish_date
    month = parsed.strftime("%B")
    day = parsed.day
    suffix = "th"
    if day % 10 == 1 and day != 11:
        suffix = "st"
    elif day % 10 == 2 and day != 12:
        suffix = "nd"
    elif day % 10 == 3 and day != 13:
        suffix = "rd"
    return f"{month} {day}{suffix}, {parsed.year}"


def format_slide_edition_date(publish_date: str) -> str:
    try:
        parsed = date.fromisoformat(publish_date)
    except ValueError:
        return publish_date
    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


def resolve_publish_date(publish_date: str | None = None) -> str:
    if publish_date and publish_date.strip():
        return publish_date.strip()
    return str(load_ti_seed_payload().get("publishDate") or "2026-07-04").strip()


def branded_title_slide_layer(
    *,
    pictogram_slug: str | None,
    eyebrow: str | None,
    title: str | None,
    subtitle: str | None,
    horizontal_align: str = "left",
    logo_size: int = 400,
    title_size: int = 56,
    subtitle_size: int = 26,
) -> str:
    return title_slide_layer(
        pictogram_slug=pictogram_slug,
        eyebrow=eyebrow,
        title=title,
        subtitle=subtitle,
        horizontal_align=horizontal_align,
        logo_size=logo_size,
        title_size=title_size,
        subtitle_size=subtitle_size,
        title_weight=900,
        eyebrow_weight=900,
        eyebrow_letter_spacing=0.09,
        eyebrow_rule=True,
    )


def build_babulus_xml(
    article: dict[str, Any],
    *,
    voice: str,
    model: str,
    publish_date: str | None = None,
    theme: str = "dark",
) -> str:
    slug = slugify(str(article.get("slug") or "article"))
    headline = str(article.get("headline") or slug)
    deck = str(article.get("deck") or "").strip()
    excerpt = str(article.get("excerpt") or "").strip()
    section = str(article.get("section") or "Anthus Threat Intelligence").strip()
    pull_quotes = [str(entry).strip() for entry in (article.get("pullQuotes") or []) if str(entry).strip()][:2]
    pictogram_slug = slug if slug in LEAD_VIDEO_SLUGS else None
    slide_date = format_slide_edition_date(resolve_publish_date(publish_date))
    closing_voice = closing_cta_voice(slide_date)
    styles = scene_styles_for_theme(theme)
    bg_props = background_props_for_theme(theme)

    def _scene(scene_id: str, scene_title: str, content_layer: str, cue_xml: str) -> str:
        return render_scene(scene_id, scene_title, content_layer, cue_xml, styles=styles, background_props=bg_props)

    title_cue_parts = [f"<voice>{escape(headline)}</voice>"]
    if deck:
        title_cue_parts.append('<pause seconds="0.5s" />')
        title_cue_parts.append(f"<voice>{escape(deck)}</voice>")
    title_cue = f"""<cue id="title-cue">
      {"\n      ".join(title_cue_parts)}
    </cue>"""

    scenes: list[str] = []

    if pull_quotes:
        hook_quote = pull_quotes[0]
        scenes.append(
            _scene(
                "hook",
                "Hook",
                quote_card_layer(quote=hook_quote, attribution=section),
                f"""<cue id="hook-cue">
      <voice>{escape(hook_quote)}</voice>
    </cue>""",
            )
        )

    scenes.append(
        _scene(
            "title",
            "Title",
            branded_title_slide_layer(
                pictogram_slug=pictogram_slug,
                eyebrow=section,
                title=headline,
                subtitle=deck or None,
                horizontal_align="left",
                logo_size=420,
                title_size=56,
                subtitle_size=26,
            ),
            title_cue,
        )
    )

    if excerpt:
        scenes.append(
            _scene(
                "body-excerpt",
                "Briefing",
                branded_title_slide_layer(
                    pictogram_slug=pictogram_slug,
                    eyebrow="Briefing",
                    title=headline,
                    subtitle=truncate_display(excerpt),
                    horizontal_align="left",
                    logo_size=360,
                    title_size=42,
                    subtitle_size=24,
                ),
                f"""<cue id="body-excerpt-cue">
      <voice>{escape(excerpt)}</voice>
    </cue>""",
            )
        )

    if len(pull_quotes) > 1:
        quote = pull_quotes[1]
        voice_line = f'As the article puts it: "{quote}"'
        scenes.append(
            _scene(
                "body-quote-2",
                "Quote 2",
                quote_card_layer(quote=quote, attribution=section),
                f"""<cue id="body-quote-2-cue">
      <voice>{escape(voice_line)}</voice>
    </cue>""",
            )
        )

    scenes.append(
        _scene(
            "closing",
            "Closing",
            closing_cta_layer(slide_date=slide_date),
            f"""<cue id="closing-cue">
      <voice>{escape(closing_voice)}</voice>
    </cue>""",
        )
    )

    body = "\n\n".join(scenes)
    return f"""<vml id="{escape(slug)}" title="{escape(headline)}" fps="30" width="1280" height="720">
  <voiceover provider="openai" voice="{escape(voice)}" model="{escape(model)}" />

{body}
</vml>
"""


def build_edition_overview_xml(
    payload: dict[str, Any] | None = None,
    *,
    voice: str,
    model: str,
    theme: str = "dark",
) -> str:
    edition = payload if payload is not None else load_ti_seed_payload()
    title = str(edition.get("title") or "Anthus Threat Intelligence").strip()
    description = str(edition.get("description") or TI_TAGLINE).strip()
    publish_date = resolve_publish_date(str(edition.get("publishDate") or "").strip() or None)
    slide_date = format_slide_edition_date(publish_date)
    articles = lead_video_articles()
    styles = scene_styles_for_theme(theme)
    bg_props = background_props_for_theme(theme)

    def _scene(scene_id: str, scene_title: str, content_layer: str, cue_xml: str) -> str:
        return render_scene(scene_id, scene_title, content_layer, cue_xml, styles=styles, background_props=bg_props)

    teaser_voice = (
        f"{description} "
        f"This edition features {len(articles)} video briefings with practical checks you can run now."
    )
    closing_voice = closing_cta_voice(slide_date)
    title_voice = f"Anthus Threat Intelligence. {slide_date}. {TI_TAGLINE}"

    first_article = articles[0]
    first_slug = str(first_article.get("slug") or "").strip()
    first_section = str(first_article.get("section") or "Briefing").strip()
    first_pull_quotes = [
        str(entry).strip() for entry in (first_article.get("pullQuotes") or []) if str(entry).strip()
    ]
    first_pictogram_slug = first_slug if first_slug in LEAD_VIDEO_SLUGS else None

    scenes: list[str] = []

    if first_pull_quotes:
        hook_quote = first_pull_quotes[0]
        scenes.append(
            _scene(
                "hook",
                "Hook",
                quote_card_layer(quote=hook_quote, attribution=first_section),
                f"""<cue id="hook-cue">
      <voice>{escape(hook_quote)}</voice>
    </cue>""",
            )
        )

    scenes.append(
        _scene(
            "title",
            "Title",
            branded_title_slide_layer(
                pictogram_slug=first_pictogram_slug,
                eyebrow="Anthus Threat Intelligence",
                title=title,
                subtitle=TI_TAGLINE,
                horizontal_align="left",
                logo_size=440,
                title_size=56,
                subtitle_size=26,
            ),
            f"""<cue id="title-cue">
      <voice>{escape(title_voice)}</voice>
    </cue>""",
        )
    )

    scenes.append(
        _scene(
            "edition-teaser",
            "Edition teaser",
            title_slide_layer(
                eyebrow=slide_date,
                title="In this edition",
                subtitle=truncate_display(
                    ". ".join(str(article.get("headline") or "").strip() for article in articles if article.get("headline")),
                    220,
                ),
                horizontal_align="left",
                title_size=48,
                subtitle_size=24,
                title_weight=900,
                eyebrow_weight=900,
                eyebrow_letter_spacing=0.09,
                eyebrow_rule=True,
            ),
            f"""<cue id="edition-teaser-cue">
      <voice>{escape(teaser_voice)}</voice>
    </cue>""",
        )
    )

    for index, article in enumerate(articles, start=1):
        slug = str(article.get("slug") or f"spotlight-{index}").strip()
        headline = str(article.get("headline") or slug)
        section = str(article.get("section") or "Briefing").strip()
        excerpt = str(article.get("excerpt") or "").strip()
        hook = first_sentence(excerpt) or str(article.get("deck") or "").strip()
        voice_line = f"{headline}. {hook}".strip()
        pictogram_slug = slug if slug in LEAD_VIDEO_SLUGS else None
        scenes.append(
            _scene(
                f"spotlight-{index}",
                headline,
                branded_title_slide_layer(
                    pictogram_slug=pictogram_slug,
                    eyebrow=section,
                    title=headline,
                    subtitle=truncate_display(hook, 180) if hook else None,
                    horizontal_align="left",
                    logo_size=400,
                    title_size=42,
                    subtitle_size=24,
                ),
                f"""<cue id="spotlight-{index}-cue">
      <voice>{escape(voice_line)}</voice>
    </cue>""",
            )
        )

    scenes.append(
        _scene(
            "closing",
            "Closing",
            closing_cta_layer(slide_date=slide_date),
            f"""<cue id="closing-cue">
      <voice>{escape(closing_voice)}</voice>
    </cue>""",
        )
    )

    body = "\n\n".join(scenes)
    return f"""<vml id="{escape(EDITION_OVERVIEW_SLUG)}" title="{escape(title)}" fps="30" width="1280" height="720">
  <voiceover provider="openai" voice="{escape(voice)}" model="{escape(model)}" />

{body}
</vml>
"""


def resolve_vml_command(dsl_path: Path, project_dir: Path, target_mp4: Path) -> tuple[list[str], Path | None]:
    babulus_root = Path(str(os.environ.get("BABULUS_ROOT") or DEFAULT_BABULUS_ROOT))
    babulus_cli = babulus_root / "packages" / "videoml-cli" / "src" / "cli.ts"
    if babulus_cli.exists():
        return (
            [
                "npx",
                "tsx",
                str(babulus_cli),
                "pipeline",
                str(dsl_path),
                "--project-dir",
                str(project_dir),
                "--out",
                str(target_mp4),
            ],
            babulus_root,
        )

    configured = str(os.environ.get("VIDEOML_CLI_DIR") or "").strip()
    cli_root = Path(configured) if configured else DEFAULT_VIDEOML_CLI
    candidates = [
        cli_root / "node_modules" / ".bin" / "vml",
        cli_root / "bin" / "vml.js",
        cli_root / "bin" / "vml",
    ]
    for candidate in candidates:
        if candidate.exists():
            if candidate.suffix == ".js":
                command = ["node", str(candidate), "pipeline", str(dsl_path), "--project-dir", str(project_dir), "--out", str(target_mp4)]
            else:
                command = [str(candidate), "pipeline", str(dsl_path), "--project-dir", str(project_dir), "--out", str(target_mp4)]
            return command, cli_root

    found = shutil.which("vml")
    if found:
        return ([found, "pipeline", str(dsl_path), "--project-dir", str(project_dir), "--out", str(target_mp4)], None)

    raise ValueError(
        "Could not find a VideoML CLI. Install Babulus at ~/Projects/Babulus "
        "(preferred) or run `npm install` in ~/Projects/VideoML/cli."
    )


def build_vml_env() -> dict[str, str]:
    load_dotenv()
    api_key = resolve_openai_api_key()
    if not api_key:
        raise ValueError(
            "OpenAI API key is required. Set OPENAI_API_KEY or openai.api_key in .papyrus/config.yaml "
            "(use PAPYRUS_CONFIG when running from a worktree)."
        )
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = api_key
    env["BABULUS_BROWSER_BUNDLE"] = str(TI_BROWSER_BUNDLE)
    defaults = resolve_openai_tts_defaults()
    if defaults.get("baseUrl"):
        env["OPENAI_BASE_URL"] = str(defaults["baseUrl"])
    return env


def probe_openai_key() -> dict[str, Any]:
    load_dotenv()
    api_key = resolve_openai_api_key()
    if not api_key:
        raise ValueError(
            "OpenAI API key is missing. Set OPENAI_API_KEY or openai.api_key in .papyrus/config.yaml."
        )
    defaults = resolve_openai_tts_defaults()
    request_body = json.dumps(
        {
            "model": defaults["model"],
            "input": "ok",
            "voice": defaults["voice"],
        }
    ).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    base_url = str(defaults.get("baseUrl") or "https://api.openai.com/v1").rstrip("/")
    request = urllib.request.Request(
        f"{base_url}/audio/speech",
        data=request_body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content_type = response.headers.get("Content-Type", "")
            body = response.read(64)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ValueError(f"OpenAI TTS probe failed ({error.code}): {detail}") from error
    except urllib.error.URLError as error:
        raise ValueError(f"OpenAI TTS probe failed: {error}") from error

    return {
        "ok": True,
        "model": defaults["model"],
        "voice": defaults["voice"],
        "contentType": content_type,
        "bytesRead": len(body),
    }


def render_dsl_to_mp4(
    *,
    dsl_path: Path,
    dsl_xml: str,
    project_dir: Path,
    target_mp4: Path,
) -> Path:
    target_mp4.parent.mkdir(parents=True, exist_ok=True)
    project_dir.mkdir(parents=True, exist_ok=True)
    ensure_videoml_browser_bundle()
    dsl_path.write_text(dsl_xml, encoding="utf-8")

    command, command_cwd = resolve_vml_command(dsl_path, project_dir, target_mp4)
    result = subprocess.run(
        command,
        cwd=str(command_cwd or PAPYRUS_ROOT),
        env=build_vml_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "VideoML render failed.\n"
            f"command: {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    if not target_mp4.exists():
        raise RuntimeError(f"VideoML reported success but output file is missing: {target_mp4}")
    return target_mp4


def render_video(
    article: dict[str, Any],
    *,
    output_mp4: Path | None = None,
    work_dir: Path | None = None,
    theme: str = "dark",
) -> Path:
    defaults = resolve_openai_tts_defaults()
    slug = str(article.get("slug") or "").strip()
    if not slug:
        raise ValueError("Article slug is required for video rendering.")

    target_mp4 = output_mp4 or article_output_mp4(article, theme=theme)
    project_dir = work_dir or (PAPYRUS_ROOT / "videoml-work" / slug)
    dsl_path = project_dir / f"{slug}-{theme}.babulus.xml"
    dsl_xml = build_babulus_xml(
        article,
        voice=str(defaults["voice"]),
        model=str(defaults["model"]),
        publish_date=str(load_ti_seed_payload().get("publishDate") or "").strip() or None,
        theme=theme,
    )
    return render_dsl_to_mp4(
        dsl_path=dsl_path,
        dsl_xml=dsl_xml,
        project_dir=project_dir,
        target_mp4=target_mp4,
    )


def render_edition_overview(
    *,
    payload: dict[str, Any] | None = None,
    output_mp4: Path | None = None,
    work_dir: Path | None = None,
    theme: str = "dark",
) -> Path:
    defaults = resolve_openai_tts_defaults()
    edition = payload if payload is not None else load_ti_seed_payload()
    target_mp4 = output_mp4 or edition_overview_output_mp4(theme=theme)
    project_dir = work_dir or (PAPYRUS_ROOT / "videoml-work" / EDITION_OVERVIEW_SLUG)
    dsl_path = project_dir / f"{EDITION_OVERVIEW_SLUG}-{theme}.babulus.xml"
    dsl_xml = build_edition_overview_xml(
        edition,
        voice=str(defaults["voice"]),
        model=str(defaults["model"]),
        theme=theme,
    )
    return render_dsl_to_mp4(
        dsl_path=dsl_path,
        dsl_xml=dsl_xml,
        project_dir=project_dir,
        target_mp4=target_mp4,
    )


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "article"
