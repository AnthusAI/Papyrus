"""The publication's image style as plain text for agents: the editorial context entry and the context pack layer. Everything but the headings comes from the profile."""
from __future__ import annotations

from .visual_style import USES, available_types, type_line

CHOOSE_A_TYPE = ("Choose an image type before asking for a picture. For covers, try the types in the order listed. "
                 "For pictures inside the article you must name a type.")
USE_HEADINGS = {"cover": "Cover and cards", "inline": "Inside the article", "social": "Social cards"}


def types_text(profile: dict) -> str:
    """The image types, grouped by use, one plain line each, in the order the profile lists them (covers in the order of typePreference)."""
    preference = profile.get("typePreference") or {}
    lines: list[str] = []
    for use in USES:
        rows = available_types(profile, use)
        order = [key for key in preference.get(use) or [] if any(row["key"] == key for row in rows)]
        rows = sorted(rows, key=lambda row: order.index(row["key"]) if row["key"] in order else len(order))
        if rows:
            lines.append(USE_HEADINGS[use] + ":")
            lines.extend("- " + type_line(profile, row) for row in rows)
    return "\n".join([*lines, "", CHOOSE_A_TYPE]) if lines else ""


def style_text(profile: dict, *, section: dict | None = None, types_only: bool = False) -> str:
    """The style for an agent. ``types_only`` is for agents that only need to know what kinds of picture exist."""
    blocks: list[str] = []
    if not types_only:
        identity, techniques, subjects = profile.get("identity") or {}, profile.get("techniques") or {}, profile.get("subjects") or {}
        if identity.get("summary"):
            blocks.append(str(identity["summary"]))
        avoid = [*(techniques.get("avoided") or []), *(subjects.get("never") or [])]
        if avoid:
            blocks.append("Never in a picture: " + ", ".join(avoid) + ".")
        rules = [constraint["text"] for constraint in profile.get("constraints") or [] if constraint.get("text")]
        if rules:
            blocks.append("Rules that cannot be loosened:\n" + "\n".join(f"- {text}" for text in rules))
        guidance = str((section or {}).get("visualGuidance") or "").strip()
        if guidance:
            blocks.append("For this section: " + guidance)
    types = types_text(profile)
    if types:
        blocks.append(types)
    return "\n\n".join(blocks)
