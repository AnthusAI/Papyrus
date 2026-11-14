"""The prompt skeleton: the one place the image toolchain writes a prompt, and the only code that touches its wording.

Every style rule, wording, negative and constraint comes from the profile (a saved, versioned choice of the publication's editors). The code here only
orders the slots and supplies the joining words. ``prompt_lint.py`` fails the build when this module holds any other piece of wording.
Design: project/wiki/image-toolchain.md sections 5.9 and 6.2.
"""
from __future__ import annotations

PLAN_VERSION = "image-prompt/v2"
SLOT_ORDER = ("style", "treatment", "image type", "constraints", "subject", "composition", "colours", "section", "story", "avoid")


def _by(ratio: str) -> str:
    left, _, right = ratio.partition(":")
    return f"{left} by {right}"


def _guidance(resolved: dict, prefixes: tuple[str, ...]) -> list[tuple[str, str]]:
    effective, sources = resolved["effective"], resolved["fieldSources"]
    return [(text, sources[f"guidance[{index}]"]) for index, text in enumerate(effective.get("guidance") or [])
            if sources[f"guidance[{index}]"].startswith(prefixes)]


def _composition(effective: dict) -> str:
    sizes = effective.get("sizes") or {}
    zones = " ".join(zone["instruction"] for zone in effective.get("safeZones") or [])
    parts = []
    if sizes:
        parts.append(f"{_by(sizes['aspectRatio'])} ({sizes['width']}x{sizes['height']}).")
    if zones:
        parts.append(zones)
    return " ".join(parts)


def _colours(effective: dict) -> str:
    return ", ".join(f"{colour['name']} ({colour['hex']})" for colour in effective.get("palette") or [])


def compose_plan(resolved: dict, brief: str, *, native_negative: bool = False) -> dict:
    """The prompt plan for one picture: labelled segments, each with the layer that produced it, plus the avoid list and the joined text.

    With no profile (``resolved["profile"]`` is None) the plan holds the brief and nothing else: no style is invented here.
    """
    effective = resolved["effective"]
    constraints = resolved.get("constraints") or []
    avoid = [*(effective.get("avoid") or []), *(item for constraint in constraints for item in constraint.get("promptAvoid") or [])]
    avoid = list(dict.fromkeys(avoid))
    composition = _composition(effective)
    colours = _colours(effective)
    slots = {
        "style": [(effective.get("masterPrompt"), "publication")],
        "treatment": _guidance(resolved, ("treatment:",)),
        "image type": _guidance(resolved, ("use:", "image-type:")),
        "constraints": [(constraint["promptDirective"], f"constraint:{constraint['id']}") for constraint in constraints if constraint.get("promptDirective")],
        "subject": [(f"Subject: {brief.strip()}", "request")],
        "composition": [(f"Composition: {composition}" if composition else "", "image-type")],
        "colours": [(f"Colours: {colours}" if colours else "", "publication")],
        "section": _guidance(resolved, ("section:",)),
        "story": _guidance(resolved, ("story:",)),
    }
    segments = [{"slot": slot, "source": where, "text": text.strip()} for slot in SLOT_ORDER if slot in slots for text, where in slots[slot] if text and text.strip()]
    lines = [segment["text"] for segment in segments]
    if avoid and not native_negative:
        lines.append(f"Avoid: {', '.join(avoid)}")
    sizes = effective.get("sizes") or {}
    return {"planVersion": PLAN_VERSION, "imageType": resolved["imageType"], "segments": segments, "avoid": avoid,
            "settings": {key: sizes[key] for key in ("aspectRatio", "width", "height") if key in sizes},
            "profile": resolved.get("profile"), "resolutionHash": resolved["resolutionHash"], "text": "\n".join(lines)}
