from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

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

    def __post_init__(self) -> None:
        for name in ("accent", "text", "background", "surface", "muted", "font_family"):
            _check_css(name, getattr(self, name))


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
