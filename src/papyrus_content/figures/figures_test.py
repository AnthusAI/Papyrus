"""Figures: the design-system seam, the checks, the renderer's page, the commands. One test renders in a real browser and skips when there is none."""
from __future__ import annotations

import io
import json
import struct
import zlib
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from papyrus_content.figures import checks
from papyrus_content.figures.cli import command, resolve_design_system
from papyrus_content.figures.design_system import DesignSystemError, DirectorySource, load_design_system
from papyrus_content.figures.neutral import MAPPING, neutral_design_system
from papyrus_content.figures.renderer import figure_document, open_browser, packaged_text, render_figure, RendererUnavailable

@pytest.fixture(autouse=True)
def no_site(monkeypatch):
    """These tests never reach a site: with no flag the render command would read the signed-in site's design system, so it finds none here."""
    from papyrus_content.figures import records

    def unavailable():
        raise RuntimeError("no site in this test")

    monkeypatch.setattr(records, "open_records", unavailable)


METADATA = {
    "slug": "plain", "kind": "diagram", "audience": "A lay reader", "shows": "One tile", "complements": "Adds a picture", "surrounding_text": "There is one tile.",
    "alt": "One tile", "caption": "A tile.", "credit": "Drafted by AI. Approved by {approved_by}.", "labelled_as": "none", "approved_by": None, "layout": "inline",
}
SOURCE = """<svg xmlns="http://www.w3.org/2000/svg" width="680" height="160" viewBox="0 0 680 160" role="img" aria-labelledby="t d">
<title id="t">One tile</title>
<desc id="d">A single tile with a word on it.</desc>
<!--primitives-->
<rect width="680" height="160" rx="22" fill="{ground}"/>
<rect x="24" y="24" width="400" height="64" rx="12" fill="{inset}"/>
<text x="48" y="66" class="t-label" fill="{ink}">Hello</text>
</svg>
"""


def png(path: Path, width: int, height: int) -> Path:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


def write_design_system(folder: Path, mutate=None) -> Path:
    mapping = json.loads(json.dumps(MAPPING))
    mapping["tokens_file"] = "tokens.json"
    neutral = neutral_design_system()
    tokens = json.loads(json.dumps(neutral.tokens))
    if mutate:
        mutate(mapping, tokens)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "mapping.json").write_text(json.dumps(mapping))
    (folder / "tokens.json").write_text(json.dumps(tokens))
    return folder


# -- the design system and its loading seam ---------------------------------------------------------------------------

def test_a_directory_design_system_loads_and_lists_its_examples(tmp_path):
    folder = write_design_system(tmp_path / "ds")
    (folder / "examples" / "one").mkdir(parents=True)
    (folder / "examples" / "one" / "figure.svg").write_text(SOURCE)
    design_system = load_design_system(DirectorySource(folder))
    assert design_system.examples == ["examples/one"]
    assert design_system.role_colors("dark")["ink"] == "#f1f1f1"
    assert design_system.role_colors("light")["ink"] == "#111111"


def test_a_design_system_can_come_from_any_source_with_the_three_methods():
    class InMemory:
        description = "in memory"

        def __init__(self):
            self.files = {"mapping.json": json.dumps({**MAPPING, "tokens": neutral_design_system().tokens})}

        def read_text(self, name):
            return self.files[name]

        def read_bytes(self, name):
            raise AssertionError("the neutral mapping names no font file")

        def list_examples(self):
            return []

    design_system = load_design_system(InMemory())
    assert design_system.canvas["diagram_width"] == 680 and design_system.source.description == "in memory"


def test_a_color_with_no_dark_value_is_refused_because_dark_is_mandatory(tmp_path):
    def drop_dark(_mapping, tokens):
        del tokens["color"]["tokens"][0]["value"]["dark"]

    with pytest.raises(DesignSystemError, match="no dark value; light and dark are both mandatory"):
        load_design_system(DirectorySource(write_design_system(tmp_path / "ds", drop_dark)))


def test_a_missing_role_or_token_is_named(tmp_path):
    def break_roles(mapping, _tokens):
        del mapping["figure_roles"]["focal"]
        mapping["figure_roles"]["ink"] = "no-such-token"

    with pytest.raises(DesignSystemError) as error:
        load_design_system(DirectorySource(write_design_system(tmp_path / "ds", break_roles)))
    assert "figure_roles is missing ['focal']" in str(error.value) and "no-such-token" in str(error.value)


def test_a_design_system_cannot_read_outside_its_folder(tmp_path):
    source = DirectorySource(write_design_system(tmp_path / "ds"))
    with pytest.raises(DesignSystemError, match="outside"):
        source.read_text("../secret.txt")
    with pytest.raises(DesignSystemError, match="cannot read"):
        DirectorySource(tmp_path / "missing").read_text("mapping.json")


def test_the_neutral_default_is_unbranded_and_embeds_no_font():
    design_system = neutral_design_system()
    assert not design_system.embeds_fonts and design_system.font_face_rules() == ""
    assert ".t-head{font-family:sans-serif" in design_system.type_style_rules(680)
    assert "text-transform:uppercase" in design_system.type_style_rules(680).split(".t-head")[1].split("\n")[0]


def test_type_sizes_scale_with_the_canvas_width():
    design_system = neutral_design_system()
    assert ".t-label{font-family:sans-serif;font-size:26.00px" in design_system.type_style_rules(680)
    assert ".t-label{font-family:sans-serif;font-size:36.71px" in design_system.type_style_rules(960)


def test_the_design_system_flags(tmp_path):
    with pytest.raises(ValueError, match="never invent a brand"):
        resolve_design_system({})
    with pytest.raises(ValueError, match="not both"):
        resolve_design_system({"--design-system": str(tmp_path), "--neutral-default": True})
    assert resolve_design_system({"--neutral-default": True}).name.startswith("Neutral default")
    assert resolve_design_system({"--design-system": str(write_design_system(tmp_path / "ds"))}).canvas["export_scale"] == 2


# -- the page the renderer builds -------------------------------------------------------------------------------------

def test_one_source_becomes_a_light_page_and_a_dark_page():
    design_system = neutral_design_system()
    light = figure_document(SOURCE, design_system, "light", "plain")
    dark = figure_document(SOURCE, design_system, "dark", "plain")
    assert "#e9ecef" in light and "#1d2127" in dark and "#1d2127" not in light
    for page in (light, dark):
        assert "{ground}" not in page and "{ink}" not in page and "<symbol" in page and ".t-label" in page


# -- checks: the source ------------------------------------------------------------------------------------------------

def source_problems(source: str = SOURCE, **changes) -> list[str]:
    return checks.source_problems(source, {**METADATA, **changes}, neutral_design_system())


def test_a_clean_source_has_no_problems():
    assert source_problems() == []


@pytest.mark.parametrize("edit, expected", [
    (lambda s: s.replace('fill="{ink}"', 'fill="#112233"'), "raw color"),
    (lambda s: s.replace('fill="{ink}"', 'fill="{teal}"'), "unknown color roles"),
    (lambda s: s.replace('class="t-label"', 'class="t-label" font-size="20"'), "t-<role> classes"),
    (lambda s: s.replace('rx="12"', 'rx="12" opacity="0.5"'), "no opacity"),
    (lambda s: s.replace("<!--primitives-->", ""), "primitives"),
    (lambda s: s.replace('viewBox="0 0 680 160"', 'viewBox="0 0 600 160"'), "canvas width must be 680"),
    (lambda s: s.replace('viewBox="0 0 680 160"', 'viewBox="0 0 680 1200"'), "split the figure"),
    (lambda s: s.replace("<rect x=\"24\"", "<filter id=\"f\"/><rect x=\"24\""), "<filter> is not allowed"),
    (lambda s: s.replace("<rect x=\"24\"", "<g transform=\"rotate(3)\"/><rect x=\"24\""), "nothing tilts"),
    (lambda s: s.replace("<rect x=\"24\"", "<rect data-focal=\"true\"/><rect data-focal=\"true\"/><rect x=\"24\""), "2 focal marks"),
    (lambda s: s.replace('fill="{ground}"', 'fill="{brand}"'), "brand color appears only in illustrations"),
    (lambda s: s.replace("<title id=\"t\">One tile</title>\n", ""), "<title> and <desc>"),
])
def test_source_problems(edit, expected):
    assert any(expected in problem for problem in source_problems(edit(SOURCE))), source_problems(edit(SOURCE))


def test_metadata_problems():
    assert any("missing alt" in problem for problem in source_problems(alt=""))
    assert any("kind must be" in problem for problem in source_problems(kind="photo"))
    assert any("labelled_as must be" in problem for problem in source_problems(labelled_as="sort-of"))
    assert any("FORECAST, NOT DATA" in problem for problem in source_problems(labelled_as="forecast"))
    assert source_problems(labelled_as="framed") == []


def test_an_illustration_uses_the_illustration_canvas():
    big = SOURCE.replace('width="680" height="160" viewBox="0 0 680 160"', 'width="960" height="540" viewBox="0 0 960 540"')
    assert source_problems(big, kind="illustration") == []
    assert any("canvas width must be 680" in problem for problem in source_problems(big))


# -- checks: what the browser measured ---------------------------------------------------------------------------------

def measured(**changes) -> dict:
    text = {"text": "Hello", "left": 48, "right": 120, "top": 40, "bottom": 70, "fontFamily": "sans-serif", "fontSize": 26, "fontWeight": "600",
            "textRole": "t-label", "fill": [17, 17, 17], "ground": [255, 255, 255], "groundLeft": [255, 255, 255], "groundRight": [255, 255, 255]}
    return {"texts": [{**text, **changes}], "lines": [], "scale": 1, "fontsLoaded": []}


def rendered(measurements: dict, theme_id: str = "dark"):
    return checks.rendered_problems(measurements, 680, 160, neutral_design_system(), theme_id)


def test_good_text_passes_in_both_themes():
    assert rendered(measured()) == ([], [])


@pytest.mark.parametrize("changes, expected", [
    ({"fontSize": 20}, "on a phone; the floor is 13px"),
    ({"right": 670}, "crosses the 24px margin"),
    ({"fill": [200, 200, 200]}, "contrast"),
    ({"groundRight": [0, 0, 0]}, "hangs over the edge"),
    ({"ground": None, "groundLeft": None, "groundRight": None}, "no solid fill"),
    ({"textRole": ""}, "no t-<role> class"),
    ({"fontFamily": "Papyrus"}, "not in a design system font"),
    ({"text": "x" * 31}, "limit is 30"),
])
def test_rendered_problems(changes, expected):
    problems, _ = rendered(measured(**changes))
    assert any(expected in problem for problem in problems), problems
    assert all(problem.startswith("dark: ") or "characters" in problem for problem in problems)


def test_a_long_label_is_a_note_and_overlapping_text_a_problem():
    _, warnings = rendered(measured(text="x" * 27))
    assert warnings and "aim for 25" in warnings[0]
    both = measured()
    both["texts"].append({**both["texts"][0], "text": "Other"})
    assert any("overlaps" in problem for problem in rendered(both)[0])


def test_thin_lines_and_failed_fonts_are_problems():
    thin = measured()
    thin["lines"] = [{"tag": "line", "width": 3}]
    thin["fontsLoaded"] = ["Anton:error"]
    problems, _ = rendered(thin)
    assert any("thinnest allowed" in problem for problem in problems) and any("failed to load" in problem for problem in problems)


def test_contrast_ratio_is_the_wcag_one():
    assert checks.contrast_ratio([0, 0, 0], [255, 255, 255]) == pytest.approx(21.0)
    assert checks.contrast_ratio([119, 119, 119], [255, 255, 255]) == pytest.approx(4.48, abs=0.02)


# -- checks: the two pictures ------------------------------------------------------------------------------------------

def test_both_pictures_are_required_and_must_share_a_ratio(tmp_path):
    light = png(tmp_path / "a.png", 20, 10)
    assert "a.dark.png was not written" in checks.picture_problems(light, tmp_path / "a.dark.png")[0]
    assert checks.picture_problems(light, png(tmp_path / "a.dark.png", 20, 10)) == []
    assert "ratios differ" in checks.picture_problems(light, png(tmp_path / "a.dark.png", 20, 12))[0]


def test_the_directive_names_the_approver_or_a_placeholder():
    assert 'credit="Drafted by AI. Approved by <name>."' in checks.image_directive(METADATA)
    assert 'Approved by Ada.' in checks.image_directive({**METADATA, "approved_by": "Ada"})
    assert checks.image_directive(METADATA).startswith('::image{\n  src="plain.png"')


# -- the commands ------------------------------------------------------------------------------------------------------

def run(*args: str) -> tuple[int, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        status = command(list(args))
    return status, out.getvalue()


def test_rules_state_outright_that_light_and_dark_are_both_mandatory():
    status, text = run("rules", "--packaged")
    assert status == 0
    assert "## 0. Light and dark are both mandatory" in text
    assert "Every figure ships in a light picture and a dark picture, always." in text
    assert "Never invent a brand" in text or "**Never invent a brand**" in text
    for brand_word in ("Machines on Machines", "Anton", "Archivo"):
        assert brand_word not in text


def test_primitives_are_the_shape_library():
    _, text = run("primitives")
    assert 'id="machine"' in text and 'id="person"' in text and "arrow-head" in text and "hatch-pattern" in text


def test_directive_prints_the_image_line(tmp_path):
    (tmp_path / "figure.json").write_text(json.dumps(METADATA))
    _, text = run("directive", str(tmp_path))
    assert 'src="plain.png"' in text and 'alt="One tile"' in text
    with pytest.raises(ValueError, match="takes one figure folder"):
        run("directive")


def test_unknown_commands_and_flags_are_refused():
    with pytest.raises(ValueError, match="Unsupported papyrus command: figures nope"):
        run("nope")
    with pytest.raises(ValueError, match="Unknown flag --light-only"):
        run("render", "folder", "--neutral-default", "--light-only")
    with pytest.raises(ValueError, match="needs at least one figure folder"):
        run("render", "--neutral-default")
    with pytest.raises(ValueError, match="never invent a brand"):
        run("render", "folder")


def test_packaged_rules_and_primitives_exist():
    assert packaged_text("rules.md").startswith("# Figure rules") and packaged_text("primitives.svg").startswith("<defs")


# -- a real browser ----------------------------------------------------------------------------------------------------

def test_render_writes_a_light_and_a_dark_picture_and_a_sidecar(tmp_path):
    folder = tmp_path / "plain"
    folder.mkdir()
    (folder / "figure.svg").write_text(SOURCE)
    (folder / "figure.json").write_text(json.dumps(METADATA))
    try:
        with open_browser() as browser:
            result = render_figure(browser, folder, neutral_design_system(), tmp_path / "out")
    except RendererUnavailable as error:
        pytest.skip(str(error))
    assert result.ok, result.problems
    light, dark = tmp_path / "out" / "plain.png", tmp_path / "out" / "plain.dark.png"
    assert checks.png_size(light) == (1360, 320) == checks.png_size(dark)
    assert light.read_bytes() != dark.read_bytes()
    sidecar = json.loads((tmp_path / "out" / "plain.figure.json").read_text())
    assert sidecar["themes"] == ["light", "dark"] and sidecar["slug"] == "plain"
    assert any("generic font" in note for note in result.warnings)


def test_a_failing_figure_writes_no_sidecar(tmp_path):
    folder = tmp_path / "bad"
    folder.mkdir()
    (folder / "figure.svg").write_text(SOURCE.replace("Hello", "A label that is much too long to read"))
    (folder / "figure.json").write_text(json.dumps(METADATA))
    try:
        with open_browser() as browser:
            result = render_figure(browser, folder, neutral_design_system())
    except RendererUnavailable as error:
        pytest.skip(str(error))
    assert not result.ok and any("limit is 30" in problem for problem in result.problems)
    assert not (folder / "plain.figure.json").exists()
