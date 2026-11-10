"""The figure checks that need no browser (the source, the numbers a browser measured, the two pictures). Ported from the Machines on Machines checker.

``source_problems`` reads ``figure.svg`` and ``figure.json``. ``rendered_problems`` reads what Chromium measured of the laid-out figure in one
theme. ``picture_problems`` compares the two written PNGs. A problem fails the figure; a warning ("note") is advice to read.
"""
from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from .design_system import DesignSystem

MAX_PICTURE_BYTES = 10 * 1024 * 1024
MAX_RATIO_DIFFERENCE = 0.005
LABEL_TARGET_CHARACTERS = 25
LABEL_LIMIT_CHARACTERS = 30
REQUIRED_METADATA = ("slug", "kind", "audience", "shows", "complements", "surrounding_text", "alt", "caption", "credit", "labelled_as", "approved_by", "layout")
KINDS = ("diagram", "chart", "illustration")
LABELS = {"none": None, "framed": None, "forecast": "FORECAST, NOT DATA", "invented": "INVENTED EXAMPLE", "invented-scene": "INVENTED SCENE"}
BANNED_ELEMENTS = ("filter", "linearGradient", "radialGradient", "image", "foreignObject", "script", "animate")
SVG_NAMESPACE = "{http://www.w3.org/2000/svg}"
PRIMITIVES_MARKER = "<!--primitives-->"


def canvas_width_for(kind: str | None, design_system: DesignSystem) -> int:
    canvas = design_system.canvas
    return canvas["illustration_width"] if kind == "illustration" else canvas["diagram_width"]


def source_problems(figure_source: str, metadata: dict, design_system: DesignSystem) -> list[str]:
    problems = []
    for key in REQUIRED_METADATA:
        if key not in metadata or (metadata[key] in ("", None) and key != "approved_by"):
            problems.append(f"figure.json is missing {key}")
    kind = metadata.get("kind")
    if kind not in KINDS:
        problems.append(f"kind must be one of {KINDS}")
    label_kind = metadata.get("labelled_as")
    if label_kind not in LABELS:
        problems.append(f"labelled_as must be one of {tuple(LABELS)}")
    elif LABELS[label_kind] and LABELS[label_kind] not in figure_source:
        problems.append(f'the picture must carry the stamp "{LABELS[label_kind]}"')
    if PRIMITIVES_MARKER not in figure_source:
        problems.append(f"figure.svg must include the {PRIMITIVES_MARKER} line after <desc>")
    if re.search(r"#[0-9a-fA-F]{3,8}\b(?!-)", re.sub(r'(?:href|url\()\s*=?\s*"?#[\w-]+', "", figure_source)):
        problems.append("figure.svg holds a raw color; use {role} names (both themes come from the roles)")
    unknown_roles = set(re.findall(r"\{([a-z-]+)\}", figure_source)) - set(design_system.mapping["figure_roles"])
    if unknown_roles:
        problems.append(f"unknown color roles: {sorted(unknown_roles)}")
    if "{brand}" in figure_source and kind != "illustration":
        problems.append("the brand color appears only in illustrations")
    if re.search(r"font-size|font-family|font-weight", figure_source):
        problems.append("set type only with t-<role> classes")
    if re.search(r'opacity="', figure_source):
        problems.append("no opacity; every color is a solid role")
    if kind != "illustration" and "rotate(" in figure_source:
        problems.append("nothing tilts in a diagram or chart")
    focal_count = len(re.findall(r'data-focal="true"', figure_source))
    if focal_count > 1:
        problems.append(f"{focal_count} focal marks; one is the limit")
    try:
        root = ElementTree.fromstring(re.sub(r"\{[a-z-]+\}", "x", figure_source).replace(PRIMITIVES_MARKER, ""))
    except ElementTree.ParseError as error:
        return problems + [f"figure.svg is not valid XML: {error}"]
    if root.get("role") != "img" or not root.get("aria-labelledby"):
        problems.append('the <svg> needs role="img" and aria-labelledby')
    children = list(root)
    if len(children) < 2 or children[0].tag != f"{SVG_NAMESPACE}title" or children[1].tag != f"{SVG_NAMESPACE}desc":
        problems.append("<title> and <desc> must be the first two children of the <svg>")
    view_box = [float(value) for value in root.get("viewBox", "0 0 0 0").split()]
    if len(view_box) != 4:
        return problems + ["the <svg> needs a viewBox of four numbers"]
    if view_box[2] != canvas_width_for(kind, design_system):
        problems.append(f"canvas width must be {canvas_width_for(kind, design_system)}")
    if kind != "illustration" and view_box[3] > design_system.canvas["max_height"]:
        problems.append(f"canvas is {view_box[3]:.0f} tall; over {design_system.canvas['max_height']} means split the figure")
    for element in root.iter():
        name = element.tag.replace(SVG_NAMESPACE, "")
        if name in BANNED_ELEMENTS:
            problems.append(f"<{name}> is not allowed")
    return problems


#: Run in the page: measures the laid-out figure. Returns text boxes, the colors under them, line widths and the font load states.
RENDERED_CHECK_SCRIPT = """
() => {
  const svg = document.querySelector('svg');
  const scale = svg.getBoundingClientRect().width / svg.viewBox.baseVal.width;
  const rgb = (value) => { const m = value.match(/rgba?\\((\\d+), (\\d+), (\\d+)/); return m ? [+m[1], +m[2], +m[3]] : null; };
  const under = (element, x, y) => {
    for (const candidate of document.elementsFromPoint(x, y)) {
      if (candidate === element || candidate.closest('text') || candidate.tagName === 'svg') continue;
      const color = rgb(getComputedStyle(candidate).fill);
      if (color) return color;
    }
    return null;
  };
  const texts = [...document.querySelectorAll('svg text')].map((element) => {
    const box = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return {
      text: element.textContent.trim(), left: box.left, right: box.right, top: box.top, bottom: box.bottom,
      fontFamily: style.fontFamily.split(',')[0].replaceAll('"', '').replaceAll("'", ''), fontSize: parseFloat(style.fontSize), fontWeight: style.fontWeight,
      textRole: element.getAttribute('class') || '', fill: rgb(style.fill), ground: under(element, (box.left + box.right) / 2, (box.top + box.bottom) / 2),
      groundLeft: under(element, box.left + 2, (box.top + box.bottom) / 2), groundRight: under(element, box.right - 2, (box.top + box.bottom) / 2),
    };
  });
  const lines = [...document.querySelectorAll('svg line, svg path[stroke], svg polyline, svg circle[stroke]')].filter((e) => !e.closest('defs, symbol, marker, pattern')).map((element) => ({
    tag: element.tagName, width: parseFloat(element.getAttribute('stroke-width') || '0'),
  }));
  return { texts, lines, scale, fontsLoaded: [...document.fonts].map((font) => font.family + ':' + font.status) };
}
"""


def relative_luminance(color: list[int]) -> float:
    def channel(value: int) -> float:
        fraction = value / 255
        return fraction / 12.92 if fraction <= 0.04045 else ((fraction + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(color[0]) + 0.7152 * channel(color[1]) + 0.0722 * channel(color[2])


def contrast_ratio(first: list[int], second: list[int]) -> float:
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def rendered_problems(measurements: dict, canvas_width: int, canvas_height: float, design_system: DesignSystem, theme_id: str) -> tuple[list[str], list[str]]:
    problems, warnings = [], []
    canvas = design_system.canvas
    phone_scale = canvas["phone_width"] / canvas_width
    margin = canvas["margin"]
    texts = measurements["texts"]
    families = design_system.font_families()
    for font_state in measurements.get("fontsLoaded", []):
        if font_state.endswith(":error"):
            problems.append(f"{theme_id}: font {font_state.rsplit(':', 1)[0]} failed to load, so the measurements are not the real ones")
    for text in texts:
        if text["fontFamily"] not in families:
            problems.append(f'{theme_id}: "{text["text"]}" is not in a design system font ({text["fontFamily"]})')
        phone_size = text["fontSize"] * phone_scale
        if phone_size < canvas["phone_text_min"] - 0.05:
            problems.append(f'{theme_id}: "{text["text"]}" is {phone_size:.1f}px on a phone; the floor is {canvas["phone_text_min"]}px')
        if not text["textRole"].startswith("t-"):
            problems.append(f'{theme_id}: "{text["text"]}" has no t-<role> class')
        characters = len(text["text"])
        if characters > LABEL_LIMIT_CHARACTERS:
            problems.append(f'"{text["text"]}" is {characters} characters; the limit is {LABEL_LIMIT_CHARACTERS}. Break it onto a second line or cut it')
        elif characters > LABEL_TARGET_CHARACTERS:
            warnings.append(f'"{text["text"]}" is {characters} characters; aim for {LABEL_TARGET_CHARACTERS}')
        if text["left"] < margin - 0.5 or text["right"] > canvas_width - margin + 0.5 or text["top"] < 0 or text["bottom"] > canvas_height:
            problems.append(f'{theme_id}: "{text["text"]}" crosses the {margin}px margin')
        if text["ground"] != text["groundLeft"] or text["ground"] != text["groundRight"]:
            problems.append(f'{theme_id}: "{text["text"]}" hangs over the edge of the shape behind it')
        minimum_ratio = 3.0 if phone_size >= 24 else 4.5
        for ground in (text["ground"], text["groundLeft"], text["groundRight"]):
            if ground is None or text["fill"] is None:
                problems.append(f'{theme_id}: "{text["text"]}" has no solid fill behind it')
                break
            ratio = contrast_ratio(text["fill"], ground)
            if ratio < minimum_ratio:
                problems.append(f'{theme_id}: "{text["text"]}" has contrast {ratio:.2f}:1; it needs {minimum_ratio}:1')
                break
    for index, first in enumerate(texts):
        for second in texts[index + 1:]:
            overlap_width = min(first["right"], second["right"]) - max(first["left"], second["left"])
            overlap_height = min(first["bottom"], second["bottom"]) - max(first["top"], second["top"])
            if overlap_width > 1 and overlap_height > (first["bottom"] - first["top"]) * 0.45:
                problems.append(f'{theme_id}: "{first["text"]}" overlaps "{second["text"]}"')
    minimum_line = canvas["phone_line_min"] / phone_scale
    for line in measurements["lines"]:
        if line["width"] and line["width"] < minimum_line - 0.05:
            problems.append(f'{theme_id}: a {line["tag"]} is {line["width"]}px; the thinnest allowed here is {minimum_line:.1f}px')
    return problems, warnings


def png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path.name} is not a PNG")
    return struct.unpack(">II", header[16:24])


def picture_problems(light_path: Path, dark_path: Path) -> list[str]:
    """The light and dark pictures must both exist, share a ratio and stay under the upload limit."""
    problems = []
    for path, theme_id in ((light_path, "light"), (dark_path, "dark")):
        if not path.is_file():
            problems.append(f"the {theme_id} picture {path.name} was not written; a figure needs both")
    if problems:
        return problems
    light_width, light_height = png_size(light_path)
    dark_width, dark_height = png_size(dark_path)
    light_ratio, dark_ratio = light_width / light_height, dark_width / dark_height
    if abs(light_ratio - dark_ratio) / light_ratio > MAX_RATIO_DIFFERENCE:
        problems.append(f"light and dark ratios differ: {light_ratio:.4f} and {dark_ratio:.4f}")
    for path in (light_path, dark_path):
        if path.stat().st_size >= MAX_PICTURE_BYTES:
            problems.append(f"{path.name} is 10 MB or more")
    return problems


def image_directive(metadata: dict) -> str:
    credit = metadata["credit"].replace("{approved_by}", metadata["approved_by"] or "<name>")
    return (
        f'::image{{\n  src="{metadata["slug"]}.png"\n  layout="{metadata["layout"]}"\n'
        f'  alt="{metadata["alt"]}"\n  caption="{metadata["caption"]}"\n  credit="{credit}"\n}}'
    )
