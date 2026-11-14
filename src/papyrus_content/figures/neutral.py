"""The neutral default design system: unbranded grays, the browser's own sans-serif, no logos and no worked examples.

It exists so an agent can draw for a site that has no design system of its own, and say plainly that it did (``--neutral-default``). It is not
a house style and invents no brand. Because it names a generic font family, nothing is embedded: the picture uses the sans-serif of the
machine that rendered it, and the renderer says so. A site with a real design system never uses this.
"""
from __future__ import annotations

from .design_system import DesignSystem, DesignSystemError, design_system_problems

_COLORS = {
    "paper": ("#f7f7f7", "#0d0f12"),
    "panel": ("#e9ecef", "#1d2127"),
    "card": ("#ffffff", "#15181d"),
    "ink": ("#111111", "#f1f1f1"),
    "ink-muted": ("#4a4f57", "#aab0b8"),
    "machine": ("#d5dae0", "#2b313a"),
    "on-machine": ("#111111", "#f1f1f1"),
    "machine-text": ("#2f3640", "#c8d0da"),
    "human": ("#e2e2e2", "#333333"),
    "on-human": ("#111111", "#f1f1f1"),
    "on-human-accent": ("#333333", "#d6d6d6"),
    "figure-hatch": ("#c4c9d0", "#2a2f36"),
    "brand": ("#3a4048", "#cfd3d9"),
    "on-brand": ("#ffffff", "#0d0f12"),
}
_TYPE_STYLES = (
    ("figure-numeral", "56px", 800), ("figure-head", "36px", 700), ("figure-statement", "30px", 800),
    ("figure-label", "26px", 600), ("figure-stamp", "26px", 800),
)

MAPPING = {
    "publication": "Neutral default (unbranded)",
    "canvas": {"diagram_width": 680, "illustration_width": 960, "illustration_height": 540, "phone_width": 343, "max_height": 1100, "margin": 24, "phone_text_min": 13, "phone_line_min": 2, "export_scale": 2},
    "fonts": {"display": {"family": "sans-serif", "weight": "700"}, "text": {"family": "sans-serif", "weight": "400 800"}},
    "figure_roles": {
        "ground": "panel", "inset": "card", "ink": "ink", "ink-muted": "ink-muted", "focal": "ink", "on-focal": "paper",
        "machine-fill": "machine", "on-machine": "on-machine", "machine-mark": "machine-text",
        "human-fill": "human", "on-human": "on-human", "human-mark": "on-human-accent",
        "hatch": "figure-hatch", "brand": "brand", "on-brand": "on-brand",
    },
    "type_roles": {"numeral": "figure-numeral", "head": "figure-head", "statement": "figure-statement", "label": "figure-label", "stamp": "figure-stamp"},
    "uppercase_type_roles": ["head", "stamp"],
}


def neutral_design_system() -> DesignSystem:
    tokens = {
        "color": {"tokens": [{"name": name, "value": {"light": light, "dark": dark}} for name, (light, dark) in _COLORS.items()]},
        "type": {"groups": [{"family": "text", "styles": [
            {"name": name, "fontSize": size, "fontWeight": weight, **({"letterSpacing": "0.06em"} if name == "figure-stamp" else {})}
            for name, size, weight in _TYPE_STYLES
        ]}]},
    }
    design_system = DesignSystem(name=MAPPING["publication"], mapping=MAPPING, tokens=tokens, fonts={"display": None, "text": None})
    problems = design_system_problems(design_system)
    if problems:  # a programming error, not user input
        raise DesignSystemError("the neutral default is broken: " + "; ".join(problems))
    return design_system
