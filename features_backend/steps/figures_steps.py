"""Figures (features_backend/figures.feature): the commands, the design-system seam and the dark-picture warning. Rendering uses a real Chromium and skips without one."""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shlex
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus import cli  # noqa: E402
from papyrus_content.figures import checks  # noqa: E402
from papyrus_content.figures.design_system import load_design_system  # noqa: E402
from papyrus_content.figures.neutral import MAPPING, neutral_design_system  # noqa: E402
from papyrus_content.figures.renderer import RendererUnavailable, open_browser  # noqa: E402

SOURCE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="680" height="160" viewBox="0 0 680 160" role="img" aria-labelledby="t d">\n'
    '<title id="t">One tile</title>\n<desc id="d">A single tile with a word on it.</desc>\n<!--primitives-->\n'
    '<rect width="680" height="160" rx="22" fill="{ground}"/>\n<rect x="24" y="24" width="400" height="64" rx="12" fill="{inset}"/>\n'
    '<text x="48" y="66" class="t-label" fill="{ink}">Hello</text>\n</svg>\n'
)
METADATA = {
    "slug": "plain", "kind": "diagram", "audience": "A lay reader", "shows": "One tile", "complements": "Adds a picture", "surrounding_text": "There is one tile.",
    "alt": "One tile", "caption": "A tile.", "credit": "Drafted by AI. Approved by {approved_by}.", "labelled_as": "none", "approved_by": None, "layout": "inline",
}


def _work(context) -> Path:
    if getattr(context, "figures_work", None) is None:
        context.figures_work = Path(tempfile.mkdtemp(prefix="figures-bdd-"))
        context.tmp_dirs.append(context.figures_work)
    return context.figures_work


def _run(context, line: str, working_folder: Path | None = None) -> None:
    arguments = shlex.split(line)[1:]
    out, err = io.StringIO(), io.StringIO()
    environment = {name: value for name, value in os.environ.items() if not name.startswith(("PAPYRUS_", "AWS_"))}
    previous = Path.cwd()
    try:
        if working_folder is not None:
            os.chdir(working_folder)
        with patch.dict(os.environ, environment, clear=True), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                context.status = cli.main(arguments)
            except SystemExit as stop:
                context.status = int(stop.code or 0)
            except ValueError as error:
                context.status = 1
                print(error, file=err)
    finally:
        os.chdir(previous)
    context.guide_output, context.guide_error = out.getvalue(), err.getvalue()


def _write_design_system(folder: Path, mutate=None) -> None:
    mapping = json.loads(json.dumps(MAPPING))
    mapping["tokens_file"] = "tokens.json"
    tokens = json.loads(json.dumps(neutral_design_system().tokens))
    if mutate:
        mutate(mapping, tokens)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "mapping.json").write_text(json.dumps(mapping))
    (folder / "tokens.json").write_text(json.dumps(tokens))


def _set_token(tokens: dict, name: str, light: str | None, dark: str | None) -> None:
    for token in tokens["color"]["tokens"]:
        if token["name"] == name:
            if light:
                token["value"]["light"] = light
            if dark:
                token["value"]["dark"] = dark


@given("a Chromium is available to render with")
def chromium_available(context):
    try:
        with open_browser():
            pass
    except RendererUnavailable as error:
        context.scenario.skip(f"No Chromium to render with: {error}")


@given('a figure folder "{name}" holding a clean one-tile figure')
def clean_figure(context, name):
    folder = _work(context) / name
    folder.mkdir()
    (folder / "figure.svg").write_text(SOURCE)
    (folder / "figure.json").write_text(json.dumps(METADATA))


@given('a figure folder "{name}" holding a figure that uses a raw color')
def raw_color_figure(context, name):
    folder = _work(context) / name
    folder.mkdir()
    (folder / "figure.svg").write_text(SOURCE.replace('fill="{ink}"', 'fill="#112233"'))
    (folder / "figure.json").write_text(json.dumps(METADATA))


@given('a design system folder "{name}" with a light ink of "{light}" and a dark ink of "{dark}"')
def design_system_with_ink(context, name, light, dark):
    _write_design_system(_work(context) / name, lambda _mapping, tokens: _set_token(tokens, "ink", light, dark))


@given('a design system folder "{name}" whose dark ink is almost the same color as its dark tile')
def design_system_with_bad_dark(context, name):
    _write_design_system(_work(context) / name, lambda _mapping, tokens: _set_token(tokens, "ink", None, "#171a1f"))


@given('a design system folder "{name}" in which one color has no dark value')
def design_system_without_dark(context, name):
    def drop(_mapping, tokens):
        del tokens["color"]["tokens"][0]["value"]["dark"]

    _write_design_system(_work(context) / name, drop)


@given("a design system source that keeps its files in memory")
def in_memory_source(context):
    class InMemory:
        description = "in memory"
        read_files = 0

        def read_text(self, name):
            return json.dumps({**MAPPING, "tokens": neutral_design_system().tokens})

        def read_bytes(self, name):
            raise AssertionError("the neutral mapping names no font file")

        def list_examples(self):
            return []

    context.design_source = InMemory()


@when('an agent runs the figures command "{line}" in the working folder')
def run_in_working_folder(context, line):
    _run(context, line, _work(context))


@when("the design system is loaded through the seam")
def load_through_seam(context):
    context.loaded = load_design_system(context.design_source)


@then('the printed text names no site, brand or font of any publication')
def names_no_brand(context):
    for word in ("Machines on Machines", "Anton", "Archivo", "Shipped", "Distinctive"):
        assert word not in context.guide_output, word


@then("no picture was written")
def no_picture(context):
    assert not list(_work(context).rglob("*.png")), list(_work(context).rglob("*.png"))


@then('the folder "{name}" holds "{light}", "{dark}" and "{sidecar}"')
def folder_holds(context, name, light, dark, sidecar):
    for file_name in (light, dark, sidecar):
        assert (_work(context) / name / file_name).is_file(), (file_name, context.guide_output)


@then("the light and dark pictures have the same size, twice the canvas width wide")
def same_size(context):
    folder = _work(context) / "pictures"
    assert checks.png_size(folder / "plain.png") == checks.png_size(folder / "plain.dark.png")
    assert checks.png_size(folder / "plain.png")[0] == 1360


@then("the light and dark pictures differ")
def pictures_differ(context):
    folder = _work(context) / "pictures"
    assert (folder / "plain.png").read_bytes() != (folder / "plain.dark.png").read_bytes()


@then('"{name}" lists the themes "{first}" and "{second}"')
def lists_themes(context, name, first, second):
    sidecar = json.loads((_work(context) / "pictures" / name).read_text())
    assert sidecar["themes"] == [first, second]


@then('the printed JSON names the design system "{name}" with figure "{slug}" ok')
def json_names(context, name, slug):
    data = json.loads(context.guide_output)
    assert data["design_system"] == name or data["design_system"], data
    assert any(figure["slug"] == slug and figure["ok"] for figure in data["figures"]), data


@then('the printed text does not contain "{text}"')
def text_does_not_contain(context, text):
    assert text not in context.guide_output, context.guide_output


@then('it has the neutral canvas and its source is "{description}"')
def has_neutral_canvas(context, description):
    assert context.loaded.canvas["diagram_width"] == 680 and context.loaded.source.description == description


@then("no folder was read")
def no_folder_read(context):
    assert not hasattr(context.loaded.source, "root")


# -- saving a version with pictures ----------------------------------------------------------------------------------

def _picture(path: Path) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 20), (1, 2, 3)).save(path)


def _pictures(context, name: str, dark: bool, figure: bool) -> None:
    folder = _work(context) / "pictures"
    _picture(folder / f"{name}.png")
    if dark:
        _picture(folder / f"{name}.dark.png")
    if figure:
        (folder / f"{name}.figure.json").write_text(json.dumps({"slug": name, "themes": ["light", "dark"]}))


@given('a pictures folder holding the figure "{name}" with a light picture only')
def figure_light_only(context, name):
    _pictures(context, name, dark=False, figure=True)


@given('a pictures folder holding the figure "{name}" with both pictures')
def figure_both(context, name):
    _pictures(context, name, dark=True, figure=True)


@given('a pictures folder holding the photograph "{name}" with a light picture only')
def photograph_light_only(context, name):
    _pictures(context, name, dark=False, figure=False)


def _save(context, flags: list[str], environment: dict[str, str]) -> None:
    from fake_client import FakeAuthoringClient
    from papyrus_content import story_commands

    lineage = "item-figure-story"
    client = FakeAuthoringClient({"Item": [{
        "id": f"{lineage}-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current", "headline": "A story", "title": "A story",
        "stage": "idea", "slug": "a-story", "type": "untyped", "section": "news"}]})
    client.endpoint = "https://example.test/graphql"
    work = _work(context)
    (work / "body.md").write_text('::image{src="chart.png" alt="A chart" layout="inline"}\n')
    out = io.StringIO()
    context.save_error = None
    with contextlib.redirect_stdout(out), patch.dict(os.environ, environment), \
            patch.object(story_commands, "create_authoring_client", return_value=(client, {})), \
            patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=False):
        try:
            story_commands.stories_save_version(["--story", lineage, "--body-file", str(work / "body.md"), "--reason", "r", "--author-label", "ops",
                                                 "--images", str(work / "pictures"), "--dry-run", *flags])
        except ValueError as error:
            context.save_error = str(error)
    context.save_output = out.getvalue()


@when("a story version is saved with those pictures as a dry run")
def save_plain(context):
    _save(context, [], {})


@when("a story version is saved with those pictures as a dry run, requiring dark figures")
def save_requiring(context):
    _save(context, ["--require-dark-figures"], {})


@when("a story version is saved with those pictures as a dry run, with PAPYRUS_REQUIRE_DARK_FIGURES set")
def save_with_environment(context):
    _save(context, [], {"PAPYRUS_REQUIRE_DARK_FIGURES": "1"})


@then("the save went ahead")
def save_went_ahead(context):
    assert context.save_error is None and "dry run" in context.save_output, (context.save_error, context.save_output)


@then('the output warns that "{name}" is a figure with no dark picture')
def output_warns(context, name):
    assert re.search(rf"figure-light-only\t{re.escape(name)}\tWARNING: this figure has no dark picture", context.save_output), context.save_output


@then('the save was refused naming "{name}" and saying dark pictures are required')
def save_refused(context, name):
    assert context.save_error and name in context.save_error and "dark pictures are required" in context.save_error, context.save_error
    assert context.save_output == ""


@then("the output has no figure warning")
def no_figure_warning(context):
    assert "figure-light-only" not in context.save_output


# -- the skill and the procedure -------------------------------------------------------------------------------------

@given('the figures skill in "{path}"')
def the_skill(context, path):
    context.skill_text = (REPO_ROOT / path).read_text(encoding="utf-8")


@then("the skill covers deciding whether to draw, choosing a form, acceptance criteria, drawing, checking, approval and saving into a Story")
def skill_covers(context):
    text = context.skill_text
    for heading in ("## 2. Decide whether to draw", "## 3. Choose a form", "acceptance criteria", "## 4. Draw", "## 5. Check and look", "## 6. Get a person's approval", "## 7. Save it into the Story"):
        assert heading in text, heading


@then("the skill says that light and dark are both mandatory")
def skill_light_dark(context):
    assert "**Light and dark are both mandatory.**" in context.skill_text and "There is no light-only figure." in context.skill_text


@then("the skill says to read the site's design system and never to invent a brand")
def skill_design_system(context):
    assert "## 1. Find the site's design system" in context.skill_text and "**Never invent a brand.**" in context.skill_text


@then('"{link}" is the same folder as "{target}"')
def symlink_target(context, link, target):
    assert (REPO_ROOT / link).resolve() == (REPO_ROOT / target).resolve()


@then("the copywriting skill links to the figures skill")
def copywriting_links(context):
    assert "../figures/SKILL.md" in (REPO_ROOT / ".agents/skills/copywriting/SKILL.md").read_text(encoding="utf-8")


@then("the story procedure's illustration step links to the figures skill")
def procedure_links(context):
    rows = [line for line in (REPO_ROOT / "docs/story-procedure.md").read_text(encoding="utf-8").splitlines() if line.startswith("| illustration |")]
    assert rows and ".agents/skills/figures/SKILL.md" in rows[0]
    from papyrus_content.newsroom_process import STEP_BY_KEY

    assert ".agents/skills/figures/SKILL.md" in STEP_BY_KEY["illustration"].note
