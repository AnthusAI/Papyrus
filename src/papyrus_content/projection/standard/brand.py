"""A site's brand pack, applied by the standard projection.

``projection.json`` ``brandPack`` names a JSON file in the static directory. The pack is validated against the platform policy
(``papyrus_content.brand_pack``); a pack that fails stops the build and names every problem. A valid pack becomes one small stylesheet of
custom properties, ``css/papyrus-brand-<hash>.css`` (the hash is of the stylesheet's own text, so it is cached for a year and a changed
brand is a new file), and the self-hosted font files it needs. The shared stylesheets, ``papyrus-tokens.css`` and
``papyrus-publication.css``, are the same for every site.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from papyrus_content.brand_pack import validate_brand_pack

ASSET_DIRECTORY = Path(__file__).parent / "assets"
FONT_DIRECTORY = ASSET_DIRECTORY / "fonts"
TOKENS_CSS_PATH = "css/papyrus-tokens.css"
PUBLICATION_CSS_PATH = "css/papyrus-publication.css"

#: Font families the platform self-hosts, with the files that make each. A family on the allow-list whose files are not here yet is refused at
#: build time with a message saying so; the allow-list never promises a file this module cannot serve.
SELF_HOSTED_FONTS = {
    "Source Serif 4": {
        "generic": "serif",
        "faces": (
            ("normal", "source-serif-4-latin-wght-normal.woff2", "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD"),
            ("italic", "source-serif-4-latin-wght-italic.woff2", "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD"),
        ),
    },
}

CORNERS = {
    "square": ("0", "0", "0"),
    "soft": ("4px", "8px", "12px"),
    "round": ("8px", "14px", "22px"),
}
ROLE_PROPERTIES = (
    ("bg", "--papyrus-bg"),
    ("ink", "--papyrus-ink"),
    ("bandBg", "--papyrus-band-bg"),
    ("bandCardBg", "--papyrus-band-card-bg"),
    ("bandMutedBg", "--papyrus-band-muted-bg"),
    ("buttonBg", "--papyrus-button-bg"),
    ("buttonInk", "--papyrus-button-ink"),
    ("rule", "--papyrus-rule"),
    ("focus", "--papyrus-focus"),
)
DARK_SELECTORS = ":root:not([data-theme=light]):not(.light):not(.light-theme)"
DARK_FORCED = ":root[data-theme=dark], :root.dark, :root.dark-theme"
FONT_FILE_PREFIX = "fonts/"


@dataclass(frozen=True)
class Brand:
    """The files a brand pack adds to a site, keyed by output path, and the stylesheet's path."""

    name: str
    stylesheet_path: str
    files: dict[str, bytes]
    preload: tuple[str, ...]


def read_pack(static_directory: Path | None, relative: str) -> dict:
    if static_directory is None:
        raise ValueError(f'brandPack "{relative}" needs a static directory to read it from.')
    path = (Path(static_directory) / relative).resolve()
    if not path.is_relative_to(Path(static_directory).resolve()):
        raise ValueError(f'brandPack "{relative}" must stay inside the static directory.')
    if not path.is_file():
        raise ValueError(f'brandPack "{relative}" does not exist in the static directory.')
    return json.loads(path.read_text(encoding="utf-8"))


def _theme_block(roles: dict) -> str:
    return "".join(f"{prop}:{roles[role]};" for role, prop in ROLE_PROPERTIES)


def _font_family(name: str, kind: str) -> str:
    return f'"{name}", {SELF_HOSTED_FONTS[name]["generic"]}'


def _font_faces(families: list[str]) -> tuple[str, dict[str, bytes], tuple[str, ...]]:
    css, files, preload = [], {}, []
    for family in dict.fromkeys(families):
        for style, filename, unicode_range in SELF_HOSTED_FONTS[family]["faces"]:
            key = f"{FONT_FILE_PREFIX}{filename}"
            files[key] = (FONT_DIRECTORY / filename).read_bytes()
            css.append(
                f'@font-face{{font-family:"{family}";font-style:{style};font-weight:200 900;font-display:swap;'
                f'src:url(/{key}) format("woff2");unicode-range:{unicode_range}}}'
            )
            if style == "normal":
                preload.append(f"/{key}")
    return "\n".join(css), files, tuple(preload)


def build_brand(pack: dict) -> Brand:
    problems = validate_brand_pack(pack)
    if problems:
        raise ValueError("The brand pack is not valid:\n- " + "\n- ".join(problems))
    families = [pack["fonts"]["heading"], pack["fonts"]["body"]]
    unhosted = [family for family in families if family not in SELF_HOSTED_FONTS]
    if unhosted:
        raise ValueError(
            f"The brand pack asks for {', '.join(sorted(set(unhosted)))}, which is on the font allow-list but whose files the platform does not host yet; "
            f"hosted today: {', '.join(sorted(SELF_HOSTED_FONTS))}."
        )
    faces, files, preload = _font_faces(families)
    small, medium, large = CORNERS[pack.get("shape", {}).get("corners", "soft")]
    light, dark = pack["colors"]["light"], pack["colors"]["dark"]
    ornaments = pack.get("ornaments", "quiet")
    text = (
        f"{faces}\n"
        f":root{{{_theme_block(light)}color-scheme:light dark;"
        f"--papyrus-font-heading:{_font_family(pack['fonts']['heading'], 'heading')};--papyrus-font-body:{_font_family(pack['fonts']['body'], 'body')};"
        f"--papyrus-corner-sm:{small};--papyrus-corner-md:{medium};--papyrus-corner-lg:{large};}}\n"
        f"@media (prefers-color-scheme: dark){{{DARK_SELECTORS}{{{_theme_block(dark)}}}}}\n"
        f"{DARK_FORCED}{{{_theme_block(dark)}}}\n"
        f"body.markus-body{{--papyrus-ornaments:{ornaments};}}\n"
    )
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    path = f"css/papyrus-brand-{digest}.css"
    files[path] = text.encode("utf-8")
    return Brand(name=pack["name"], stylesheet_path=path, files=files, preload=preload)
