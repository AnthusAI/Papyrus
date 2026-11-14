"""A site's design system for figures, and the seam it is loaded through.

A design system is data, not code: a ``mapping.json`` that names the figure roles (``ink``, ``inset``, ``focal`` ...) and type roles
(``head``, ``label`` ...) and points each at a token, the tokens themselves (every color has a light and a dark value), the font files,
and some worked examples (folders holding a ``figure.svg`` and a ``figure.json``).

``DesignSystemSource`` is the loading seam. ``DirectorySource`` reads a folder. A backend source (a site's design-system records, read
through the signed-in CLI) implements the same three methods and ``load_design_system`` needs no change. A source returns text and bytes by
a path relative to the design system's root, so a record store can answer the same names.

``mapping.json`` carries its tokens either inline (``"tokens": {...}``) or as ``"tokens_file": "tokens.json"``, relative to the root.
Font entries are ``{"family", "file", "weight"}`` with the file relative to the root; an entry with no ``file`` names a generic family
(``sans-serif``) and nothing is embedded (only the neutral default does this).
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

THEME_IDS = ("light", "dark")
FIGURE_ROLES = (
    "ground", "inset", "ink", "ink-muted", "focal", "on-focal", "machine-fill", "on-machine", "machine-mark",
    "human-fill", "on-human", "human-mark", "hatch", "brand", "on-brand",
)
TYPE_ROLES = ("numeral", "head", "statement", "label", "stamp")
CANVAS_KEYS = ("diagram_width", "illustration_width", "illustration_height", "phone_width", "max_height", "margin", "phone_text_min", "phone_line_min", "export_scale")
GENERIC_FAMILIES = ("sans-serif", "serif", "system-ui")


class DesignSystemError(ValueError):
    """The design system cannot be used to draw; the message says what to fix."""


class DesignSystemSource(Protocol):
    """Where a design system comes from. ``name`` is a path relative to the design system's root (``mapping.json``, ``fonts/X.ttf``)."""

    description: str

    def read_text(self, name: str) -> str: ...

    def read_bytes(self, name: str) -> bytes: ...

    def list_examples(self) -> list[str]:
        """The names of the worked examples, each a folder holding ``figure.svg`` and ``figure.json`` (read with ``read_text(f"{name}/figure.svg")``)."""
        ...


class DirectorySource:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.description = str(self.root)

    def _path(self, name: str) -> Path:
        path = (self.root / name).resolve()
        if self.root.resolve() not in path.parents and path != self.root.resolve():
            raise DesignSystemError(f"{name} points outside the design system folder {self.root}")
        return path

    def read_text(self, name: str) -> str:
        try:
            return self._path(name).read_text(encoding="utf-8")
        except OSError as error:
            raise DesignSystemError(f"design system {self.root}: cannot read {name}: {error.strerror or error}") from error

    def read_bytes(self, name: str) -> bytes:
        try:
            return self._path(name).read_bytes()
        except OSError as error:
            raise DesignSystemError(f"design system {self.root}: cannot read {name}: {error.strerror or error}") from error

    def list_examples(self) -> list[str]:
        folder = self.root / "examples"
        if not folder.is_dir():
            return []
        return sorted(f"examples/{path.parent.name}" for path in folder.glob("*/figure.svg"))


@dataclass
class DesignSystem:
    name: str
    mapping: dict
    tokens: dict
    fonts: dict[str, bytes | None]  # font key -> file bytes (None for a generic family)
    examples: list[str] = field(default_factory=list)
    source: DesignSystemSource | None = None

    @property
    def canvas(self) -> dict:
        return self.mapping["canvas"]

    def font_families(self) -> set[str]:
        return {font["family"] for font in self.mapping["fonts"].values()}

    def role_colors(self, theme_id: str) -> dict[str, str]:
        color_by_token = {token["name"]: token["value"][theme_id] for token in self.tokens["color"]["tokens"]}
        return {role: color_by_token[token_name] for role, token_name in self.mapping["figure_roles"].items()}

    def type_style_rules(self, canvas_width: int) -> str:
        size_scale = canvas_width / self.canvas["diagram_width"]
        styles = {style["name"]: (style, group["family"]) for group in self.tokens["type"]["groups"] for style in group["styles"]}
        rules = []
        for type_role, style_name in self.mapping["type_roles"].items():
            style, family_key = styles[style_name]
            family = self.mapping["fonts"][family_key]["family"]
            fallback = "" if family in GENERIC_FAMILIES else ",sans-serif"
            declarations = [
                f"font-family:{family if family in GENERIC_FAMILIES else chr(39) + family + chr(39)}{fallback}",
                f"font-size:{float(str(style['fontSize']).removesuffix('px')) * size_scale:.2f}px",
                f"font-weight:{style['fontWeight']}",
            ]
            if "letterSpacing" in style:
                declarations.append(f"letter-spacing:{style['letterSpacing']}")
            if type_role in self.mapping.get("uppercase_type_roles", []):
                declarations.append("text-transform:uppercase")
            rules.append(f".t-{type_role}{{{';'.join(declarations)}}}")
        return "\n".join(rules)

    def font_face_rules(self) -> str:
        rules = []
        for key, font in self.mapping["fonts"].items():
            data = self.fonts.get(key)
            if data is None:
                continue
            encoded = base64.b64encode(data).decode()
            rules.append(f"@font-face{{font-family:'{font['family']}';font-weight:{font['weight']};src:url(data:font/ttf;base64,{encoded}) format('truetype');font-display:block}}")
        return "\n".join(rules)

    @property
    def embeds_fonts(self) -> bool:
        return all(data is not None for data in self.fonts.values())


def load_design_system(source: DesignSystemSource) -> DesignSystem:
    """Read and validate a design system. Raises ``DesignSystemError`` naming the first thing to fix."""
    try:
        mapping = json.loads(source.read_text("mapping.json"))
    except ValueError as error:
        raise DesignSystemError(f"design system {source.description}: mapping.json is not valid JSON: {error}") from error
    if "tokens" in mapping:
        tokens = mapping["tokens"]
    elif "tokens_file" in mapping:
        try:
            tokens = json.loads(source.read_text(mapping["tokens_file"]))
        except ValueError as error:
            raise DesignSystemError(f"design system {source.description}: {mapping['tokens_file']} is not valid JSON: {error}") from error
    else:
        raise DesignSystemError(f"design system {source.description}: mapping.json needs \"tokens\" or \"tokens_file\"")
    fonts: dict[str, bytes | None] = {}
    for key, font in mapping.get("fonts", {}).items():
        if "family" not in font:
            raise DesignSystemError(f"design system {source.description}: font {key} has no family")
        fonts[key] = source.read_bytes(font["file"]) if font.get("file") else None
    design_system = DesignSystem(
        name=mapping.get("publication") or source.description, mapping=mapping, tokens=tokens, fonts=fonts,
        examples=source.list_examples(), source=source,
    )
    problems = design_system_problems(design_system)
    if problems:
        raise DesignSystemError(f"design system {source.description} cannot be used to draw:\n- " + "\n- ".join(problems))
    return design_system


def design_system_problems(design_system: DesignSystem) -> list[str]:
    mapping, tokens = design_system.mapping, design_system.tokens
    problems: list[str] = []
    missing_canvas = [key for key in CANVAS_KEYS if key not in mapping.get("canvas", {})]
    if missing_canvas:
        problems.append(f"canvas is missing {missing_canvas}")
    for roles, label in ((FIGURE_ROLES, "figure_roles"), (TYPE_ROLES, "type_roles")):
        absent = [role for role in roles if role not in mapping.get(label, {})]
        if absent:
            problems.append(f"{label} is missing {absent}")
    if not mapping.get("fonts"):
        problems.append("fonts is empty")
    try:
        color_tokens = {token["name"]: token["value"] for token in tokens["color"]["tokens"]}
        styles = {style["name"]: group["family"] for group in tokens["type"]["groups"] for style in group["styles"]}
    except (KeyError, TypeError):
        return problems + ["tokens need color.tokens[{name, value: {light, dark}}] and type.groups[{family, styles}]"]
    for token_name, value in color_tokens.items():
        for theme_id in THEME_IDS:
            if theme_id not in value:
                problems.append(f"color token {token_name} has no {theme_id} value; light and dark are both mandatory")
    for role, token_name in mapping.get("figure_roles", {}).items():
        if token_name not in color_tokens:
            problems.append(f"figure role {role} names color token {token_name}, which does not exist")
    for role, style_name in mapping.get("type_roles", {}).items():
        family_key = styles.get(style_name)
        if family_key is None:
            problems.append(f"type role {role} names style {style_name}, which does not exist")
        elif family_key not in mapping.get("fonts", {}):
            problems.append(f"type role {role} uses font family key {family_key}, which mapping fonts does not define")
    return problems
