from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

_HTTPS_URL = re.compile(r"https://[^\s\"'<>\\`]{1,500}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_OPTIONAL_CSS = (
    "header_band", "header_text", "button_fill", "button_text", "button_border", "footer_band", "footer_text", "label_font",
)
_UNSAFE_CSS = re.compile(r"[<>{};\"\\`]|url\(|expression\(|@import", re.I)


def _check_css(name: str, value: str) -> str:
    if _UNSAFE_CSS.search(value):
        raise ValueError(f"Unsafe characters in email theme value {name!r}")
    return value


@dataclass(frozen=True)
class EmailTheme:
    accent: str
    text: str
    background: str
    surface: str = "#ffffff"
    muted: str = "#555555"
    font_family: str = "Georgia, 'Times New Roman', serif"
    logo_url: str | None = None
    site_name: str = ""
    # Optional branding. All unset means the plain layout; none of these changes what the fields above mean.
    header_band: str | None = None
    header_text: str | None = None
    button_fill: str | None = None
    button_text: str | None = None
    button_border: str | None = None
    footer_band: str | None = None
    footer_text: str | None = None
    wordmark_image_url: str | None = None
    wordmark_alt: str | None = None
    wordmark_width: int | None = None
    wordmark_height: int | None = None
    footer_wordmark_width: int | None = None
    label_font: str | None = None

    def __post_init__(self) -> None:
        for name in ("accent", "text", "background", "surface", "muted", "font_family"):
            _check_css(name, getattr(self, name))
        for name in _OPTIONAL_CSS:
            value = getattr(self, name)
            if value is not None:
                _check_css(name, value)
        if self.wordmark_image_url is not None:
            if not _HTTPS_URL.fullmatch(self.wordmark_image_url):
                raise ValueError("Email theme value 'wordmark_image_url' must be an absolute https URL")
            for name in ("wordmark_width", "wordmark_height"):
                value = getattr(self, name)
                if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 2000:
                    raise ValueError(f"Email theme value {name!r} is required with a wordmark image (1 to 2000 pixels)")
        if self.footer_wordmark_width is not None:
            value = self.footer_wordmark_width
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 400:
                raise ValueError("Email theme value 'footer_wordmark_width' must be a whole number of pixels from 1 to 400")
        if self.wordmark_alt is not None and (len(self.wordmark_alt) > 200 or _CONTROL.search(self.wordmark_alt)):
            raise ValueError("Email theme value 'wordmark_alt' is too long or has control characters")

    @property
    def has_bands(self) -> bool:
        return bool(self.header_band or self.footer_band)

    @property
    def is_branded(self) -> bool:
        """Any new branding field is set: the bands, button colours or wordmark."""
        return bool(
            self.header_band or self.footer_band or self.button_fill or self.button_border or self.wordmark_image_url
        )

    @property
    def wordmark_text(self) -> str:
        return self.wordmark_alt or self.site_name

    @property
    def header_ink(self) -> str:
        return self.header_text or (readable_on(self.header_band) if self.header_band else self.text)

    @property
    def footer_ink(self) -> str:
        return self.footer_text or (readable_on(self.footer_band) if self.footer_band else self.muted)

    @property
    def mono(self) -> str:
        return self.label_font or "Menlo, Consolas, 'Courier New', monospace"


_OPTIONAL_KEYS = (
    ("headerBand", "header_band"),
    ("headerText", "header_text"),
    ("buttonFill", "button_fill"),
    ("buttonText", "button_text"),
    ("buttonBorder", "button_border"),
    ("footerBand", "footer_band"),
    ("footerText", "footer_text"),
    ("wordmarkImageUrl", "wordmark_image_url"),
    ("wordmarkAlt", "wordmark_alt"),
    ("labelFont", "label_font"),
)


def theme_from_config(cfg: Mapping[str, Any], site_name: str) -> EmailTheme:
    """Build a theme from the site's ``email`` theme config block."""
    defaults = EmailTheme(accent="#000000", text="#000000", background="#ffffff")
    kwargs: dict[str, Any] = {"site_name": site_name}
    for key in ("accent", "text", "background"):
        value = cfg.get(key)
        if not value:
            raise ValueError(f"Email theme config is missing {key!r}")
        kwargs[key] = str(value)
    for key, attr in (("surface", "surface"), ("muted", "muted"), ("fontFamily", "font_family")):
        if cfg.get(key):
            kwargs[attr] = str(cfg[key])
        else:
            kwargs[attr] = getattr(defaults, attr)
    kwargs["logo_url"] = str(cfg["logoUrl"]) if cfg.get("logoUrl") else None
    for key, attr in _OPTIONAL_KEYS:
        if cfg.get(key):
            kwargs[attr] = str(cfg[key])
    for key, attr in (("wordmarkWidth", "wordmark_width"), ("wordmarkHeight", "wordmark_height"), ("footerWordmarkWidth", "footer_wordmark_width")):
        if cfg.get(key) is not None:
            kwargs[attr] = cfg[key]
    return EmailTheme(**kwargs)


def readable_on(color: str) -> str:
    """Black or white text for a solid ``color`` background (hex only; white otherwise)."""
    m = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", color.strip())
    if not m:
        return "#ffffff"
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    return "#000000" if lum > 0.179 else "#ffffff"
