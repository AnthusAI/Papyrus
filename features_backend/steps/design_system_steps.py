"""A site's design system as backend data (features_backend/design-system-records.feature). An in-memory backend that fails on any table scan; no network, no AWS.

The figures steps (figures_steps.py) draw folders and run the render command; this file stores, shows, pulls and reads the design system. Both reach the
"signed-in site" through ``context.ds_store`` (see ``_site_opener`` in figures_steps.py).
"""
from __future__ import annotations

import contextlib
import io
import json
import shlex
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus import cli  # noqa: E402
from papyrus_content.figures import records  # noqa: E402
from papyrus_content.figures.context_entry import design_system_entry  # noqa: E402
from papyrus_content.figures.design_system import DesignSystemError, DirectorySource, load_design_system  # noqa: E402
from papyrus_content.figures.neutral import MAPPING, neutral_design_system  # noqa: E402
from papyrus_content.figures.records import DesignSystemRecords  # noqa: E402
from papyrus_content.guidelines.fakes import FakeBackend, FakeFiles  # noqa: E402

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="680" height="160"><!--primitives--><rect width="680" height="160" fill="{ground}"/></svg>\n'
FONT = b"\x00\x01\x00\x00 not really a font " * 20
FIGURE_JSON = json.dumps({"slug": "one", "kind": "diagram"})


def _work(context) -> Path:
    if getattr(context, "figures_work", None) is None:
        context.figures_work = Path(tempfile.mkdtemp(prefix="figures-bdd-"))
        context.tmp_dirs.append(context.figures_work)
    return context.figures_work


def _tree(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def _write_folder(folder: Path, font: bytes = FONT) -> None:
    mapping = json.loads(json.dumps(MAPPING))
    mapping["tokens_file"] = "tokens.json"
    mapping["fonts"] = {"display": {"family": "Test Display", "file": "fonts/Display.ttf", "weight": "700"},
                        "text": {"family": "Test Text", "file": "fonts/Text.ttf", "weight": "400 800"}}
    (folder / "fonts").mkdir(parents=True, exist_ok=True)
    (folder / "mapping.json").write_text(json.dumps(mapping, indent=2))
    (folder / "tokens.json").write_text(json.dumps(neutral_design_system().tokens, indent=2))
    (folder / "fonts" / "Display.ttf").write_bytes(font)
    (folder / "fonts" / "Text.ttf").write_bytes(FONT + b"2")
    (folder / "examples" / "one").mkdir(parents=True, exist_ok=True)
    (folder / "examples" / "one" / "figure.svg").write_text(SVG)
    (folder / "examples" / "one" / "figure.json").write_text(FIGURE_JSON)


def _push(context, name: str, reason: str, *, dry_run: bool = False) -> None:
    out, err = io.StringIO(), io.StringIO()
    context.push_error, context.push_output = None, ""
    arguments = ["design-system", "push", str(_work(context) / name), "--reason", reason, *(["--dry-run"] if dry_run else [])]
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), patch.object(records, "open_records", lambda: context.ds_store), \
            patch("papyrus_content.story_commands._version_author", return_value="Ada Admin"):
        try:
            status = cli.main(arguments)
        except ValueError as error:
            status = 1
            print(error, file=err)
    if status != 0:
        context.push_error = err.getvalue() or "the command failed"
    context.push_output = out.getvalue()


def _run(context, arguments: list[str]) -> None:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), patch.object(records, "open_records", lambda: context.ds_store):
        try:
            context.status = cli.main(arguments)
        except ValueError as error:
            context.status = 1
            print(error, file=err)
    context.guide_output, context.guide_error = out.getvalue(), err.getvalue()


# --- the site ---------------------------------------------------------------------------------------------------------------------------------------

@given("a site that stores no design system yet")
def a_site(context):
    context.ds_backend = FakeBackend()
    context.ds_store = DesignSystemRecords(context.ds_backend, FakeFiles(context.ds_backend))
    context.site_error, context.site_reads = None, 0


@given('the site belongs to the tenant "{tenant_id}" with the slug "{slug}"')
def tenant(context, tenant_id, slug):
    context.ds_backend.tenant_id, context.ds_backend.tenant_slug = tenant_id, slug


@given("the site cannot be read because the session is not signed in")
def unreadable(context):
    context.site_error = "not signed in"


# --- folders and pushes ------------------------------------------------------------------------------------------------------------------------------

@given('a design system folder "{name}" with two fonts and one worked example')
def folder_with_fonts(context, name):
    _write_folder(_work(context) / name)


@given('the folder "{name}" has the setting file {text}')
def setting_file(context, name, text):
    (_work(context) / name / "settings.json").write_text(text)


@given('the folder "{name}" has been pushed with the reason "{reason}"')
def has_been_pushed(context, name, reason):
    _push(context, name, reason)
    assert context.push_error is None, context.push_error


@when('the folder "{name}" is pushed with the reason "{reason}"')
def pushed(context, name, reason):
    _push(context, name, reason)


@when('the folder "{name}" is pushed as a dry run with the reason "{reason}"')
def pushed_dry(context, name, reason):
    _push(context, name, reason, dry_run=True)


@when('one font of "{name}" is replaced and the folder is pushed with the reason "{reason}"')
def font_replaced(context, name, reason):
    _write_folder(_work(context) / name, FONT + b"new display font")
    _push(context, name, reason)


@when('one font of "{name}" is replaced, the setting file removed, and the folder pushed with the reason "{reason}"')
def font_replaced_no_settings(context, name, reason):
    folder = _work(context) / name
    _write_folder(folder, FONT + b"another display font")
    (folder / "settings.json").unlink()
    _push(context, name, reason)
    assert context.push_error is None, context.push_error


@when('the folder "{name}" has the setting file {text} and is pushed with the reason "{reason}"')
def setting_and_push(context, name, text, reason):
    (_work(context) / name / "settings.json").write_text(text)
    _push(context, name, reason)
    assert context.push_error is None, context.push_error


@then("the push saved version {number:d}")
def push_saved(context, number):
    assert context.push_error is None, context.push_error
    assert f"saved\tversion {number}\t" in context.push_output, context.push_output


@then("the push reported the design system unchanged at version {number:d}")
def push_unchanged(context, number):
    assert f"unchanged\tversion {number}\t" in context.push_output, context.push_output


@then('the push was refused saying "{text}"')
def push_refused(context, text):
    assert context.push_error and text in context.push_error, (context.push_error, context.push_output)


@then("the output says it would save version {number:d} and lists the mapping, the example and both fonts")
def push_dry_output(context, number):
    assert f"dry run\tversion {number}\t" in context.push_output, context.push_output
    for name in ("mapping.json", "examples/one/figure.svg", "fonts/Display.ttf", "fonts/Text.ttf"):
        assert f"file\t{name}" in context.push_output, context.push_output


# --- what is stored -------------------------------------------------------------------------------------------------------------------------------------

@then('exactly one design system row is stored, for the slug "{slug}", with an empty body and no metadata')
def one_row(context, slug):
    [row] = context.ds_backend.items
    assert row["slug"] == slug and row["type"] == "doctrine" and row["status"] == "private"
    assert row["bodyMarkus"] == "" and row["body"] == [] and json.loads(row["metadata"]) == {}


@then('one file holding the mapping, the tokens and the worked example is stored in S3 as the "{role}" of that row')
def one_document(context, role):
    [attachment] = [a for a in context.ds_backend.attachments if a["role"] == role]
    document = json.loads(context.ds_backend.bodies[attachment["storagePath"]])
    assert {"mapping.json", "tokens.json", "examples/one/figure.svg", "examples/one/figure.json"} <= set(document["files"]), list(document["files"])


@then('each of the two fonts is stored in S3 as a "{role}" of that row')
def font_assets(context, role):
    stored = {a["sortKey"]: context.ds_backend.bodies[a["storagePath"]] for a in context.ds_backend.attachments if a["role"] == role}
    assert stored == {"fonts/Display.ttf": FONT, "fonts/Text.ttf": FONT + b"2"}, list(stored)


@then("nothing of the design system's text is in the database rows")
def no_text_in_rows(context):
    dumped = json.dumps(context.ds_backend.items)
    assert "figure.svg" not in dumped and "Test Display" not in dumped and "ground" not in dumped, dumped


@then("no row and no file is stored")
def nothing_stored(context):
    assert context.ds_backend.items == [] and context.ds_backend.attachments == []


@then("only one catalog row is stored")
def only_one_row(context):
    assert len(context.ds_backend.items) == 1


@then("version 2 is the current design system and version 1 is superseded")
def versions(context):
    assert [(r["versionNumber"], r["versionState"]) for r in context.ds_backend.items] == [(1, "superseded"), (2, "current")]


@then("reading version 1 returns the old font and reading the current one returns the new font")
def old_and_new_font(context):
    assert context.ds_store.read(1).source.read_bytes("fonts/Display.ttf") == FONT
    assert context.ds_store.read().source.read_bytes("fonts/Display.ttf") == FONT + b"new display font"


@then('the design system\'s history lists "{newer}" before "{older}"')
def history(context, newer, older):
    assert [h["reason"] for h in context.ds_store.history()] == [newer, older]


@then("the stored design system returns the same mapping text, the same font bytes and the same worked examples as the folder")
def same_answers(context):
    source, folder = context.ds_store.read().source, DirectorySource(_work(context) / "site-design")
    assert source.read_text("mapping.json") == folder.read_text("mapping.json")
    assert source.read_bytes("fonts/Display.ttf") == folder.read_bytes("fonts/Display.ttf")
    assert source.list_examples() == folder.list_examples() == ["examples/one"]
    assert source.read_text("examples/one/figure.svg") == folder.read_text("examples/one/figure.svg")


@then("loading the stored design system gives the same roles, tokens, fonts and type styles as loading the folder")
def same_loaded(context):
    stored = load_design_system(context.ds_store.read().source)
    original = load_design_system(DirectorySource(_work(context) / "site-design"))
    assert (stored.mapping, stored.tokens, stored.fonts) == (original.mapping, original.tokens, original.fonts)
    assert stored.type_style_rules(680) == original.type_style_rules(680) and stored.role_colors("dark") == original.role_colors("dark")


# --- show and pull --------------------------------------------------------------------------------------------------------------------------------------

@when("an agent shows the site's design system")
def show(context):
    _run(context, ["design-system", "show"])


@when("an agent shows the site's design system as JSON")
def show_json(context):
    _run(context, ["design-system", "show", "--json"])


@then('the printed JSON has version {number:d}, the setting requireDarkFigures true and the figure role "{role}"')
def show_json_fields(context, number, role):
    data = json.loads(context.guide_output)
    assert data["version"] == number and data["settings"] == {"requireDarkFigures": True} and role in data["figureRoles"], data


@when('an agent pulls the design system into the new folder "{name}"')
def pull(context, name):
    _run(context, ["design-system", "pull", str(_work(context) / name)])


@when('an agent pulls the design system into the new folder "{name}" again')
def pull_again(context, name):
    _run(context, ["design-system", "pull", str(_work(context) / name)])


@then('the folder "{pulled}" holds exactly the files of "{original}", with the same bytes')
def pulled_equals(context, pulled, original):
    pulled_files, original_files = _tree(_work(context) / pulled), _tree(_work(context) / original)
    # settings.json is data (pull writes it formatted), so compare it as data; every other file is compared byte for byte
    assert json.loads(pulled_files.pop("settings.json")) == json.loads(original_files.pop("settings.json"))
    assert pulled_files == original_files


# --- integrity, reads, tenants, settings ---------------------------------------------------------------------------------------------------------------

@when("a stored font file is changed in S3")
def tamper(context):
    path = next(a["storagePath"] for a in context.ds_backend.attachments if a["sortKey"] == "fonts/Display.ttf")
    context.ds_backend.bodies[path] = b"someone changed this"


@then("reading that font from the stored design system is refused because it does not match its hash")
def tamper_refused(context):
    try:
        context.ds_store.read().source.read_bytes("fonts/Display.ttf")
    except DesignSystemError as error:
        assert "does not match its hash" in str(error)
    else:
        raise AssertionError("the changed font was accepted")


@when("the design system, its history, its settings and its context entry are read")
def read_everything(context):
    context.ds_backend.reads.clear()
    stored = context.ds_store.read()
    stored.source.read_bytes("fonts/Display.ttf")
    context.ds_store.history()
    context.ds_store.settings()
    design_system_entry(context.ds_backend, context.ds_store.store)


@then("every design system read was a query on the slug index or the attachment owner index")
def only_indexes(context):
    assert {index for index, _ in context.ds_backend.reads} <= {"itemBySlug", "modelAttachmentsByOwnerRoleAndSortKey"}, context.ds_backend.reads
    assert context.ds_backend.reads


@then('the catalog row carries the tenant slug "{slug}"')
def row_tenant_slug(context, slug):
    assert context.ds_backend.items[0]["tenantSlug"] == slug


@then('a session of the tenant "{tenant_id}" cannot read it')
def other_tenant(context, tenant_id):
    context.ds_backend.tenant_id = tenant_id
    try:
        context.ds_store.read()
    except ValueError as error:
        assert "tenant does not match" in str(error)
    else:
        raise AssertionError("another tenant read the design system")


@then("the site requires dark figures")
def requires_dark(context):
    assert context.ds_store.settings().get("requireDarkFigures") is True


@then("the site does not require dark figures")
def does_not_require_dark(context):
    assert context.ds_store.settings().get("requireDarkFigures") is False


# --- the context pack -----------------------------------------------------------------------------------------------------------------------------------

@when("the editorial context entry for the design system is built")
def build_entry(context):
    context.ds_backend.reads.clear()
    context.ds_entry = design_system_entry(context.ds_backend, context.ds_store.store)


@then("there is no design system entry")
def no_entry(context):
    assert context.ds_entry is None


@then('the entry names version {number:d}, says to read it with "{command}" and says never to invent a brand')
def entry_text(context, number, command):
    text = context.ds_entry["text"]
    assert f"version {number}" in text and command in text and "Never invent a brand" in text, text


@then("building the entry made one index query and downloaded nothing")
def entry_cost(context):
    assert context.ds_backend.reads == [("itemBySlug", "editorial-doctrine-design-system")], context.ds_backend.reads


# --- the render command -----------------------------------------------------------------------------------------------------------------------------

@then("the site's design system was not read")
def site_not_read(context):
    assert context.site_reads == 0, context.site_reads
