from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_VOICEOVER_PROVIDERS = ("openai",)
THEMES = ("dark", "light")
DEFAULT_VIDEO_CONFIG_PATH = "video/video.yml"
VIDEO_CONFIG_ENV = "PAPYRUS_VIDEO_CONFIG"
DEFAULT_WORK_DIR = "video/work"
DEFAULT_QUOTE_ACCENT_COLOR = "var(--color-accent)"

TOP_LEVEL_KEYS = {
    "schemaVersion",
    "outputDir",
    "workDir",
    "browserBundle",
    "leadSlugs",
    "scene",
    "components",
    "slideProps",
    "quoteAccentColor",
    "postRoll",
    "tts",
}
SCENE_THEME_KEYS = {"background", "color", "vars"}
COMPONENT_KEYS = {"titleSlide", "quoteCard"}
POST_ROLL_KEYS = {"eyebrow", "title", "tagline", "voice", "props"}


@dataclass(frozen=True)
class SceneTheme:
    background: str
    color: str
    vars: dict[str, str] = field(default_factory=dict)

    def styles(self) -> dict[str, Any]:
        return {"background": self.background, "color": self.color, "vars": dict(self.vars)}

    def background_props(self) -> dict[str, Any]:
        return {"variant": "solid", "color": self.background}


@dataclass(frozen=True)
class PostRoll:
    eyebrow: str
    title: str
    tagline: str
    voice: str
    props: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VideoConfig:
    root: Path
    output_dir: Path
    work_dir: Path
    browser_bundle: Path
    lead_slugs: tuple[str, ...]
    dark: SceneTheme
    light: SceneTheme
    title_slide_component: str
    quote_card_component: str
    slide_props: dict[str, Any]
    quote_accent_color: str
    post_roll: PostRoll | None
    tts_provider: str

    def scene_theme(self, theme: str) -> SceneTheme:
        if theme not in THEMES:
            raise ValueError(f"Unknown video theme '{theme}'. Expected one of: {', '.join(THEMES)}.")
        return self.light if theme == "light" else self.dark


def _require_mapping(value: Any, key: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Video config '{key}' must be a mapping.")
    return value


def _require_string(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Video config '{key}' must be a non-empty string.")
    return value.strip()


def _reject_unknown_keys(mapping: dict[str, Any], allowed: set[str], prefix: str) -> None:
    for key in mapping:
        if key not in allowed:
            qualified = f"{prefix}.{key}" if prefix else str(key)
            raise ValueError(f"Video config has unknown key '{qualified}'.")


def _parse_scene_theme(value: Any, key: str) -> SceneTheme:
    mapping = _require_mapping(value, key)
    _reject_unknown_keys(mapping, SCENE_THEME_KEYS, key)
    raw_vars = mapping.get("vars") or {}
    scene_vars = _require_mapping(raw_vars, f"{key}.vars")
    for var_name, var_value in scene_vars.items():
        if not isinstance(var_value, str):
            raise ValueError(f"Video config '{key}.vars.{var_name}' must be a string.")
    return SceneTheme(
        background=_require_string(mapping.get("background"), f"{key}.background"),
        color=_require_string(mapping.get("color"), f"{key}.color"),
        vars={str(name): str(var_value) for name, var_value in scene_vars.items()},
    )


def _parse_post_roll(value: Any) -> PostRoll | None:
    if value is None:
        return None
    mapping = _require_mapping(value, "postRoll")
    _reject_unknown_keys(mapping, POST_ROLL_KEYS, "postRoll")
    props = _require_mapping(mapping.get("props") or {}, "postRoll.props")
    voice = _require_string(mapping.get("voice"), "postRoll.voice")
    return PostRoll(
        eyebrow=_require_string(mapping.get("eyebrow"), "postRoll.eyebrow"),
        title=_require_string(mapping.get("title"), "postRoll.title"),
        tagline=_require_string(mapping.get("tagline"), "postRoll.tagline"),
        voice=voice,
        props=dict(props),
    )


def resolve_video_config_path(explicit: str | None = None) -> Path:
    configured = (explicit or os.environ.get(VIDEO_CONFIG_ENV) or DEFAULT_VIDEO_CONFIG_PATH).strip()
    return Path(configured)


def load_video_config(path: str | Path, *, root: Path | None = None) -> VideoConfig:
    config_path = Path(path)
    if not config_path.is_file():
        raise ValueError(
            f"Video config not found at {config_path}. Create it (see docs/video-pipeline.md) "
            f"or point {VIDEO_CONFIG_ENV} at it."
        )
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError(f"Video config {config_path} is not valid YAML: {error}") from error
    document = _require_mapping(raw, "<document>")
    _reject_unknown_keys(document, TOP_LEVEL_KEYS, "")
    if document.get("schemaVersion") != 1:
        raise ValueError("Video config 'schemaVersion' must be 1.")

    publication_root = root if root is not None else Path.cwd()
    scene = _require_mapping(document.get("scene"), "scene")
    _reject_unknown_keys(scene, set(THEMES), "scene")
    components = _require_mapping(document.get("components"), "components")
    _reject_unknown_keys(components, COMPONENT_KEYS, "components")
    tts = _require_mapping(document.get("tts"), "tts")
    _reject_unknown_keys(tts, {"provider"}, "tts")
    provider = _require_string(tts.get("provider"), "tts.provider").lower()
    if provider not in SUPPORTED_VOICEOVER_PROVIDERS:
        raise ValueError(
            f"Video config 'tts.provider' must be one of: {', '.join(SUPPORTED_VOICEOVER_PROVIDERS)}."
        )
    lead_slugs = document.get("leadSlugs") or []
    if not isinstance(lead_slugs, list) or not all(isinstance(entry, str) and entry.strip() for entry in lead_slugs):
        raise ValueError("Video config 'leadSlugs' must be a list of non-empty strings.")
    slide_props = _require_mapping(document.get("slideProps") or {}, "slideProps")

    return VideoConfig(
        root=publication_root,
        output_dir=publication_root / _require_string(document.get("outputDir"), "outputDir"),
        work_dir=publication_root / str(document.get("workDir") or DEFAULT_WORK_DIR),
        browser_bundle=publication_root / _require_string(document.get("browserBundle"), "browserBundle"),
        lead_slugs=tuple(entry.strip() for entry in lead_slugs),
        dark=_parse_scene_theme(scene.get("dark"), "scene.dark"),
        light=_parse_scene_theme(scene.get("light"), "scene.light"),
        title_slide_component=_require_string(components.get("titleSlide"), "components.titleSlide"),
        quote_card_component=_require_string(components.get("quoteCard"), "components.quoteCard"),
        slide_props=dict(slide_props),
        quote_accent_color=str(document.get("quoteAccentColor") or DEFAULT_QUOTE_ACCENT_COLOR),
        post_roll=_parse_post_roll(document.get("postRoll")),
        tts_provider=provider,
    )
