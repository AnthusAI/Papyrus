"""Validate a BrandPack against ``schema.json`` (v1, Draft 2020-12) and the platform policy in ``policy.json``.

The schema says what may be set; the policy says what a value must satisfy. Both are plain JSON so the TypeScript twin reads the same
files and the same vectors (``scripts/fixtures/brand-pack-vectors.json``). Every refusal names the setting, and a contrast refusal
names the pair, the theme and the measured ratio.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

from jsonschema import Draft202012Validator

from papyrus_content.site_config.validate import schema_messages

_HERE = Path(__file__).parent
SCHEMA = json.loads((_HERE / "schema.json").read_text(encoding="utf-8"))
POLICY = json.loads((_HERE / "policy.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
_VALIDATOR = Draft202012Validator(SCHEMA)
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def relative_luminance(color: str) -> float:
    """WCAG 2.x relative luminance of ``#rrggbb``."""
    channels = []
    for start in (1, 3, 5):
        value = int(color[start : start + 2], 16) / 255
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: str, second: str) -> float:
    """WCAG 2.x contrast ratio, from 1 to 21."""
    high, low = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _shown(ratio: float) -> str:
    """Two decimals, truncated so a ratio just under a minimum is never shown as meeting it."""
    return f"{int(ratio * 100) / 100:.2f}"


def _contrast_errors(colors: Mapping) -> list[str]:
    errors = []
    for theme in ("light", "dark"):
        roles = colors.get(theme)
        if not isinstance(roles, Mapping):
            continue
        for pairs, kind in ((POLICY["textPairs"], "text"), (POLICY["lightnessPairs"], "lightness")):
            minimum, rule = POLICY["contrast"][kind]["minimum"], POLICY["contrast"][kind]["rule"]
            for pair in pairs:
                first, second = roles.get(pair["foreground"]), roles.get(pair["background"])
                if not all(isinstance(value, str) and _HEX.match(value) for value in (first, second)):
                    continue
                ratio = contrast_ratio(first, second)
                if ratio < minimum:
                    what = "text" if kind == "text" else "must differ in lightness, not only hue"
                    errors.append(
                        f"colors.{theme}: {pair['foreground']} on {pair['background']} ({first} on {second}) has contrast {_shown(ratio)}:1, "
                        f"needs {minimum:g}:1 ({what}; {rule})"
                    )
    return errors


def _font_errors(fonts: Mapping) -> list[str]:
    allowed = [font["family"] for font in POLICY["fonts"]]
    return [
        f"fonts.{role}: {family!r} is not an allowed font; allowed: {', '.join(allowed)}"
        for role, family in fonts.items()
        if isinstance(family, str) and family not in allowed
    ]


def validate_brand_pack(pack: object) -> list[str]:
    """Every problem with ``pack``, each naming the setting; an empty list means it is valid for the shared tier."""
    if not isinstance(pack, Mapping):
        return ["BrandPack: must be an object"]
    errors = [
        message
        for error in sorted(_VALIDATOR.iter_errors(pack), key=lambda e: list(map(str, e.absolute_path)))
        for message in schema_messages(error, "BrandPack")
    ]
    if isinstance(pack.get("colors"), Mapping):
        errors += _contrast_errors(pack["colors"])
    if isinstance(pack.get("fonts"), Mapping):
        errors += _font_errors(pack["fonts"])
    return errors
