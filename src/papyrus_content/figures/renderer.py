"""Render one figure source to a light and a dark PNG through headless Chromium, and measure the real layout for the checks.

One ``figure.svg`` written with ``{role}`` colors and ``t-<role>`` classes is resolved twice, once per theme, laid out in Chromium with the
design system's fonts embedded in the page (so the pixels hold the type and nothing depends on a web font at display time), checked, and
screenshotted at ``export_scale`` times the canvas size. Both themes are always produced; there is no light-only mode.

Playwright is imported only here, when a figure is rendered, so the rest of the CLI never needs it. Install it once with
``pip install playwright`` and either ``playwright install chromium`` or have Google Chrome installed.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Iterator

from .checks import PRIMITIVES_MARKER, RENDERED_CHECK_SCRIPT, picture_problems, rendered_problems, source_problems
from .design_system import THEME_IDS, DesignSystem

SIDECAR_SUFFIX = ".figure.json"


class RendererUnavailable(RuntimeError):
    """Playwright or a Chromium is missing; the message says how to get one."""


def packaged_text(name: str) -> str:
    return resources.files("papyrus_content").joinpath("data", "figures", name).read_text(encoding="utf-8")


def resolve_roles(source: str, colors: dict[str, str]) -> str:
    return re.sub(r"\{([a-z-]+)\}", lambda match: colors[match.group(1)], source)


def figure_document(figure_source: str, design_system: DesignSystem, theme_id: str, title: str) -> str:
    """The HTML page that holds the figure in one theme: roles resolved, primitives inlined, fonts embedded, type classes defined."""
    colors = design_system.role_colors(theme_id)
    canvas_width = int(re.search(r'viewBox="0 0 (\d+) ', figure_source).group(1))
    svg = figure_source.replace(PRIMITIVES_MARKER, resolve_roles(packaged_text("primitives.svg"), colors))
    svg = resolve_roles(svg, colors)
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title>'
        f"<style>{design_system.font_face_rules()}</style>"
        f"<style>html,body{{margin:0;background:transparent}}svg{{display:block}}\n{design_system.type_style_rules(canvas_width)}</style>"
        f"</head><body>{svg}</body></html>"
    )


@dataclass
class FigureResult:
    slug: str
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def as_dict(self) -> dict[str, Any]:
        return {"slug": self.slug, "ok": self.ok, "problems": self.problems, "notes": self.warnings, "files": self.files}


@contextmanager
def open_browser() -> Iterator[Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RendererUnavailable(
            "Rendering needs Playwright and a Chromium: run `pip install playwright`, then `playwright install chromium` "
            "(or install Google Chrome, which is used when no Chromium is found)."
        ) from error
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception:
            try:
                browser = playwright.chromium.launch(channel="chrome")
            except Exception as error:
                raise RendererUnavailable("No Chromium or Google Chrome could be started: run `playwright install chromium`.") from error
        try:
            yield browser
        finally:
            browser.close()


def load_metadata(folder: Path) -> dict:
    try:
        return json.loads((folder / "figure.json").read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"{folder}: needs figure.json ({error.strerror or error})") from error
    except ValueError as error:
        raise ValueError(f"{folder}/figure.json is not valid JSON: {error}") from error


def load_figure(folder: Path) -> tuple[str, dict]:
    metadata = load_metadata(folder)
    try:
        return (folder / "figure.svg").read_text(encoding="utf-8"), metadata
    except OSError as error:
        raise ValueError(f"{folder}: needs figure.svg ({error.strerror or error})") from error


def picture_names(slug: str) -> dict[str, str]:
    return {"light": f"{slug}.png", "dark": f"{slug}.dark.png"}


def render_figure(browser: Any, folder: Path, design_system: DesignSystem, out_dir: Path | None = None, write_pictures: bool = True) -> FigureResult:
    """Check ``folder``'s figure and, when ``write_pictures``, write ``<slug>.png``, ``<slug>.dark.png`` and ``<slug>.figure.json`` to ``out_dir``."""
    figure_source, metadata = load_figure(folder)
    slug = str(metadata.get("slug") or folder.name)
    result = FigureResult(slug)
    result.problems += source_problems(figure_source, metadata, design_system)
    if result.problems:
        return result
    if not design_system.embeds_fonts:
        result.warnings.append("this design system names a generic font and embeds none, so the pictures use this machine's own font")
    out_dir = out_dir or folder
    view_box = [float(value) for value in re.search(r'viewBox="([^"]+)"', figure_source).group(1).split()]
    canvas_width, canvas_height = int(view_box[2]), view_box[3]
    names = picture_names(slug)
    for theme_id in THEME_IDS:
        page = browser.new_page(viewport={"width": canvas_width, "height": int(canvas_height)}, device_scale_factor=design_system.canvas["export_scale"])
        try:
            page.set_content(figure_document(figure_source, design_system, theme_id, slug), wait_until="load")
            page.evaluate("document.fonts.ready")
            theme_problems, theme_warnings = rendered_problems(page.evaluate(RENDERED_CHECK_SCRIPT), canvas_width, canvas_height, design_system, theme_id)
            result.problems += theme_problems
            result.warnings += [warning for warning in theme_warnings if warning not in result.warnings]
            if write_pictures:
                out_dir.mkdir(parents=True, exist_ok=True)
                page.locator("svg").first.screenshot(path=str(out_dir / names[theme_id]), omit_background=True)
                result.files.append(str(out_dir / names[theme_id]))
        finally:
            page.close()
    if write_pictures:
        result.problems += picture_problems(out_dir / names["light"], out_dir / names["dark"])
        if result.ok:
            sidecar = out_dir / f"{slug}{SIDECAR_SUFFIX}"
            sidecar.write_text(json.dumps({**metadata, "themes": list(THEME_IDS), "design_system": design_system.name}, indent=2) + "\n", encoding="utf-8")
            result.files.append(str(sidecar))
    return result
