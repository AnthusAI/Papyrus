"""The platform's size policy, checked on tokens and on stylesheets.

Text has a floor in rendered pixels (reading 18, interface 14, label 13). Every text token must meet its floor in both layouts, every line
height must be a whole number of rhythm steps and leave the text its minimum line ratio, and a stylesheet's text sizes must come from tokens
so the floors cannot be bypassed by a literal.
"""

from __future__ import annotations

import re

from .build import TOKENS

FONT_SIZE = re.compile(r"font-size\s*:\s*([^;}]+)")
FONT_SHORTHAND = re.compile(r"(?<![-\w])font\s*:\s*[^;}]*?(\d*\.?\d+(?:px|rem|em|%|pt))\s*(?:/[^;}\s]+)?\s+[^;}]*")
COMMENT = re.compile(r"/\*.*?\*/", re.S)


def lint_tokens(tokens: dict | None = None) -> list[str]:
    tokens = tokens or TOKENS
    problems: list[str] = []
    floors = tokens["floors"]
    for role, style in tokens["text"].items():
        floor = floors[style["floor"]]
        for layout in ("compact", "wide"):
            rhythm = tokens["layouts"][layout]["rhythm"]
            size, line = style[layout]["size"], style[layout]["line"]
            if size < floor["px"]:
                problems.append(f"text.{role}.{layout}: {size}px is below the {style['floor']} floor of {floor['px']}px")
            if line % rhythm:
                problems.append(f"text.{role}.{layout}: line height {line}px is not a whole number of {rhythm}px rhythm steps")
            ratio = style.get("minimumLineRatio", floor["minimumLineRatio"])
            if line < size * ratio:
                problems.append(f"text.{role}.{layout}: line height {line}px is under {ratio} times the {size}px size")
    for group in ("space",):
        for name, value in tokens[group].items():
            for layout in ("compact", "wide"):
                if name != "gutter" and value[layout] % tokens["layouts"][layout]["rhythm"]:
                    problems.append(f"{group}.{name}.{layout}: {value[layout]}px is not a whole number of rhythm steps")
    return problems


def lint_stylesheet(css: str) -> list[str]:
    """A stylesheet's text sizes must be tokens (``var(--papyrus-text-<role>-size)`` or ``inherit``/``1em``-style relatives), never a literal length."""
    problems = []
    for found in FONT_SIZE.finditer(COMMENT.sub("", css)):
        value = found.group(1).strip()
        if value.startswith("var(--papyrus-text-") or value in {"inherit", "initial", "unset"} or re.fullmatch(r"[\d.]+(em|%)", value):
            continue
        problems.append(f"font-size: {value} is not a token; use var(--papyrus-text-<role>-size)")
    for found in FONT_SHORTHAND.finditer(COMMENT.sub("", css)):
        problems.append(f"font shorthand with a literal size {found.group(1)}; use the size and line tokens")
    return problems
