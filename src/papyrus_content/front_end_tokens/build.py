"""Write ``papyrus-tokens.css`` from ``tokens.json``. Run ``python -m papyrus_content.front_end_tokens`` to rewrite the file or ``--check`` to fail when it is stale."""

from __future__ import annotations

import json
from pathlib import Path

TOKENS_PATH = Path(__file__).with_name("tokens.json")
TOKENS = json.loads(TOKENS_PATH.read_text(encoding="utf-8"))
STYLESHEET_PATH = Path(__file__).resolve().parents[1] / "projection" / "standard" / "assets" / "papyrus-tokens.css"
ROOT_PIXELS = 16  # the browser's default text size; tokens are written in rem so a reader's own text size and zoom still apply
HEADER = "/* Generated from src/papyrus_content/front_end_tokens/tokens.json by `python -m papyrus_content.front_end_tokens`. Do not edit by hand. */\n"


def rem(pixels: float) -> str:
    text = f"{pixels / ROOT_PIXELS:.4f}".rstrip("0").rstrip(".")
    return f"{text}rem" if text not in ("", "0") else "0"


def declarations(tokens: dict) -> dict[str, dict[str, str]]:
    """Every custom property, per layout: ``{layout: {name: value}}``."""
    found: dict[str, dict[str, str]] = {"compact": {}, "wide": {}}
    for layout in found:
        found[layout]["--papyrus-rhythm"] = rem(tokens["layouts"][layout]["rhythm"])
        for floor, rule in tokens["floors"].items():
            found[layout][f"--papyrus-floor-{floor}"] = rem(rule["px"])
        for role, style in tokens["text"].items():
            found[layout][f"--papyrus-text-{role}-size"] = rem(style[layout]["size"])
            found[layout][f"--papyrus-text-{role}-line"] = rem(style[layout]["line"])
        for group in ("space", "radius", "size"):
            for name, value in tokens[group].items():
                found[layout][f"--papyrus-{group if group != 'size' else 'size'}-{name}"] = rem(value[layout])
    return found


def build_tokens_css(tokens: dict | None = None) -> str:
    tokens = tokens or TOKENS
    found = declarations(tokens)
    lines = [HEADER, ":root {\n"]
    lines += [f"  {name}: {value};\n" for name, value in found["compact"].items()]
    lines += ["  --papyrus-ratio-media: calc(16 / 9);\n}\n", f"@media (min-width: {tokens['layouts']['wide']['minWidth']}px) {{\n  :root {{\n"]
    lines += [f"    {name}: {value};\n" for name, value in found["wide"].items() if found["compact"][name] != value]
    lines += ["  }\n}\n"]
    return "".join(lines)


def main(arguments: list[str]) -> int:
    text = build_tokens_css()
    if "--check" in arguments:
        if not STYLESHEET_PATH.exists() or STYLESHEET_PATH.read_text(encoding="utf-8") != text:
            print(f"{STYLESHEET_PATH} is stale; run `python -m papyrus_content.front_end_tokens`.")
            return 1
        return 0
    STYLESHEET_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {STYLESHEET_PATH}")
    return 0

