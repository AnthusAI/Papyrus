"""A site's design system as backend data: the stored document and fonts, the BackendSource, push, pull, show, the settings and the context entry.
A fake backend that fails on any table scan; no network, no AWS."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from papyrus import cli
from papyrus_content.figures import cli as figures_cli
from papyrus_content.figures import design_system_cli, records
from papyrus_content.figures.context_entry import design_system_entry
from papyrus_content.figures.design_system import DesignSystemError, DirectorySource, load_design_system
from papyrus_content.figures.neutral import MAPPING, neutral_design_system
from papyrus_content.figures.records import BackendSource, DesignSystemRecords, collect, validate_design_system_document
from papyrus_content.guidelines import GuidelineError, kind_names, slug_for
from papyrus_content.guidelines.fakes import FakeBackend, FakeFiles
from papyrus_content.story_images import dark_figures_required

FONT = b"\x00\x01\x00\x00 not really a font " * 20
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="680" height="160"><!--primitives--><rect width="680" height="160" fill="{ground}"/></svg>\n'
EXAMPLE_JSON = json.dumps({"slug": "one", "kind": "diagram"})


def write_folder(folder: Path, *, font: bytes = FONT, mutate=None, settings: dict | None = None, examples: tuple[str, ...] = ("one",)) -> Path:
    mapping = json.loads(json.dumps(MAPPING))
    mapping["tokens_file"] = "tokens.json"
    mapping["fonts"] = {"display": {"family": "Test Display", "file": "fonts/Display.ttf", "weight": "700"},
                        "text": {"family": "Test Text", "file": "fonts/Text.ttf", "weight": "400 800"}}
    tokens = json.loads(json.dumps(neutral_design_system().tokens))
    if mutate:
        mutate(mapping, tokens)
    (folder / "fonts").mkdir(parents=True, exist_ok=True)
    (folder / "mapping.json").write_text(json.dumps(mapping, indent=2))
    (folder / "tokens.json").write_text(json.dumps(tokens, indent=2))
    (folder / "fonts" / "Display.ttf").write_bytes(font)
    (folder / "fonts" / "Text.ttf").write_bytes(font + b"2")
    for name in examples:
        (folder / "examples" / name).mkdir(parents=True, exist_ok=True)
        (folder / "examples" / name / "figure.svg").write_text(SVG)
        (folder / "examples" / name / "figure.json").write_text(EXAMPLE_JSON)
    if settings is not None:
        (folder / "settings.json").write_text(json.dumps(settings))
    return folder


def make(**kwargs):
    backend = FakeBackend(**kwargs)
    return backend, DesignSystemRecords(backend, FakeFiles(backend))


def push(store, folder, reason="First design system", **kwargs):
    return store.push(DirectorySource(folder), actor="Ada Admin", reason=reason, settings=records.read_settings_file(folder), now="2026-11-10T10:00:00Z", **kwargs)


def tree(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


# --- the kind and the document ---------------------------------------------------------------------------------------------------------------------

def test_the_design_system_is_a_registered_guideline_kind():
    assert "design-system" in kind_names()
    assert slug_for("design-system") == "editorial-doctrine-design-system"


@pytest.mark.parametrize("change,path", [
    ({"files": {"mapping.json": "{}", "../x": "y"}}, "files.../x"),
    ({"files": {"mapping.json": "{}", "/etc/passwd": "y"}}, "files./etc/passwd"),
    ({"files": {"mapping.json": 3}}, "files.mapping.json"),
    ({"files": {}}, "files.mapping.json"),
    ({"mystery": 1}, "mystery"),
    ({"settings": {"requireLight": True}}, "settings.requireLight"),
    ({"settings": {"requireDarkFigures": "yes"}}, "settings.requireDarkFigures"),
    ({"settings": {"illustrationRequiredTypes": "article"}}, "settings.illustrationRequiredTypes"),
    ({"settings": {"illustrationRequiredTypes": ["article", ""]}}, "settings.illustrationRequiredTypes"),
    ({"media": {"fonts/a.ttf": {"sha256": "nope", "byteSize": 1}}}, "media.fonts/a.ttf"),
    ({"media": {"fonts/A B.ttf": {"sha256": "0" * 64, "byteSize": 1}, "fonts/a-b.ttf": {"sha256": "0" * 64, "byteSize": 1}}}, "media.fonts/a-b.ttf"),
])
def test_document_problems_are_named_by_field(change, path):
    document = {"schemaVersion": 1, "files": {"mapping.json": "{}"}, **change}
    assert path in {p.path for p in validate_design_system_document(document)}


def test_the_illustration_setting_is_a_list_of_story_types():
    document = {"schemaVersion": 1, "files": {"mapping.json": "{}"}, "settings": {"illustrationRequiredTypes": ["article", "post"], "requireDarkFigures": True}}
    assert validate_design_system_document(document) == []


def test_a_section_has_no_design_system():
    assert [p.code for p in validate_design_system_document({"schemaVersion": 1, "files": {"mapping.json": "{}"}}, "section")] == ["publication_only"]


# --- pushing: a catalog row in the database, the content in S3 ---------------------------------------------------------------------------------------

def test_push_stores_one_catalog_row_and_the_content_in_s3(tmp_path):
    backend, store = make()
    result = push(store, write_folder(tmp_path / "ds"))
    assert result["changed"] and result["reference"]["versionNumber"] == 1
    [row] = backend.items
    assert (row["slug"], row["type"], row["status"], row["versionState"]) == ("editorial-doctrine-design-system", "doctrine", "private", "current")
    assert row["bodyMarkus"] == "" and row["body"] == [] and json.loads(row["metadata"]) == {}
    assert [a["role"] for a in backend.attachments].count("doctrine_document") == 1
    assert sorted(a["sortKey"] for a in backend.attachments if a["role"] == "doctrine_asset") == ["fonts/Display.ttf", "fonts/Text.ttf"]
    # no text of the design system is in the database rows
    assert "figure.svg" not in json.dumps(backend.items) and "Test Display" not in json.dumps(backend.items)
    assert [w[:2] for w in backend.writes] == [("create", "Item")]


def test_nothing_is_stored_for_a_design_system_that_cannot_draw(tmp_path):
    def drop_dark(_mapping, tokens):
        del tokens["color"]["tokens"][0]["value"]["dark"]

    backend, store = make()
    with pytest.raises(DesignSystemError, match="no dark value; light and dark are both mandatory"):
        push(store, write_folder(tmp_path / "ds", mutate=drop_dark))
    assert backend.items == [] and backend.attachments == []


def test_an_unchanged_push_makes_no_version_and_a_new_font_makes_one(tmp_path):
    backend, store = make()
    folder = write_folder(tmp_path / "ds")
    push(store, folder)
    assert push(store, folder)["changed"] is False and len(backend.items) == 1
    write_folder(folder, font=FONT + b"changed")
    second = push(store, folder, reason="New font")
    assert second["changed"] and second["reference"]["versionNumber"] == 2
    assert [r["versionState"] for r in backend.items] == ["superseded", "current"]
    assert store.read(1).source.read_bytes("fonts/Display.ttf") == FONT          # the older version stays readable
    assert store.read().source.read_bytes("fonts/Display.ttf") == FONT + b"changed"
    assert [h["reason"] for h in store.history()] == ["New font", "First design system"]


# --- reading: the BackendSource ------------------------------------------------------------------------------------------------------------------

def test_a_backend_source_answers_the_three_questions_like_the_folder(tmp_path):
    backend, store = make()
    folder = write_folder(tmp_path / "ds", examples=("one", "two"))
    push(store, folder)
    source = store.read().source
    directory = DirectorySource(folder)
    assert isinstance(source, BackendSource)
    assert source.read_text("mapping.json") == directory.read_text("mapping.json")
    assert source.read_bytes("fonts/Text.ttf") == directory.read_bytes("fonts/Text.ttf")
    assert source.read_text("examples/two/figure.svg") == SVG
    assert source.list_examples() == directory.list_examples() == ["examples/one", "examples/two"]


def test_a_stored_design_system_loads_and_draws_like_the_folder(tmp_path):
    backend, store = make()
    folder = write_folder(tmp_path / "ds")
    push(store, folder)
    stored, original = load_design_system(store.read().source), load_design_system(DirectorySource(folder))
    assert stored.mapping == original.mapping and stored.tokens == original.tokens and stored.fonts == original.fonts
    assert stored.examples == original.examples == ["examples/one"]
    assert stored.type_style_rules(680) == original.type_style_rules(680) and stored.role_colors("dark") == original.role_colors("dark")


def test_a_missing_file_or_a_changed_font_is_refused(tmp_path):
    backend, store = make()
    push(store, write_folder(tmp_path / "ds"))
    source = store.read().source
    with pytest.raises(DesignSystemError, match="has no file nope.json"):
        source.read_text("nope.json")
    tampered = next(path for path in backend.bodies if path.endswith("fonts-display-ttf"))
    backend.bodies[tampered] = b"someone changed this"
    with pytest.raises(DesignSystemError, match="does not match its hash"):
        store.read().source.read_bytes("fonts/Display.ttf")


def test_nothing_is_read_by_scanning_a_table(tmp_path):
    backend, store = make()
    push(store, write_folder(tmp_path / "ds"))
    backend.reads.clear()
    store.read().source.read_bytes("fonts/Display.ttf")
    store.settings(), store.history(), store.current_row()
    assert {index for index, _ in backend.reads} == {"itemBySlug", "modelAttachmentsByOwnerRoleAndSortKey"}


def test_a_site_with_no_design_system_reads_as_none():
    backend, store = make()
    assert store.read() is None and store.settings() == {} and store.current_row() is None


# --- tenants ---------------------------------------------------------------------------------------------------------------------------------------

def test_the_catalog_row_carries_the_tenant_slug_and_another_tenant_cannot_read_it(tmp_path):
    backend, store = make(tenant_id="tenant-a")
    backend.tenant_slug = "acme"
    push(store, write_folder(tmp_path / "ds"))
    assert backend.items[0]["tenantSlug"] == "acme" and backend.items[0]["tenantId"] == "tenant-a"
    backend.tenant_id = "tenant-b"
    with pytest.raises(ValueError, match="tenant does not match"):
        store.read()


# --- pull ------------------------------------------------------------------------------------------------------------------------------------------

def test_pull_writes_back_the_folder_that_was_pushed(tmp_path):
    backend, store = make()
    folder = write_folder(tmp_path / "ds")
    (folder / "settings.json").write_text(json.dumps({"requireDarkFigures": True}, indent=2) + "\n")    # pull writes settings.json in this form
    push(store, folder)
    written = store.read().write_to(tmp_path / "out")
    assert tree(tmp_path / "out") == tree(folder) and "settings.json" in written


def test_pull_refuses_to_leave_the_folder(tmp_path):
    backend, store = make()
    push(store, write_folder(tmp_path / "ds"))
    stored = store.read()
    stored.source._files["../escape.txt"] = "x"
    with pytest.raises(DesignSystemError, match="outside the folder"):
        stored.write_to(tmp_path / "out")


# --- the settings -----------------------------------------------------------------------------------------------------------------------------------

def test_the_site_setting_is_pushed_and_read(tmp_path):
    backend, store = make()
    folder = write_folder(tmp_path / "ds", settings={"requireDarkFigures": True})
    push(store, folder)
    assert store.settings() == {"requireDarkFigures": True}


def test_a_push_with_no_settings_file_keeps_the_sites_settings_and_an_explicit_false_turns_it_off(tmp_path):
    backend, store = make()
    folder = write_folder(tmp_path / "ds", settings={"requireDarkFigures": True})
    push(store, folder)
    (folder / "settings.json").unlink()
    write_folder(folder, font=FONT + b"v2")
    push(store, folder, reason="Font")
    assert store.settings() == {"requireDarkFigures": True}
    (folder / "settings.json").write_text(json.dumps({"requireDarkFigures": False}))
    push(store, folder, reason="Allow light")
    assert store.settings() == {"requireDarkFigures": False}


def test_a_settings_file_with_an_unknown_setting_is_refused(tmp_path):
    backend, store = make()
    with pytest.raises(DesignSystemError, match="not a figure setting"):
        push(store, write_folder(tmp_path / "ds", settings={"requireLight": True}))
    assert backend.items == []


def test_site_requires_dark_figures_reads_the_stored_setting(tmp_path, monkeypatch):
    backend, store = make()
    monkeypatch.setattr(records, "DesignSystemRecords", lambda client: DesignSystemRecords(client, FakeFiles(backend)))
    assert records.site_requires_dark_figures(backend) is False
    push(store, write_folder(tmp_path / "ds", settings={"requireDarkFigures": True}))
    assert records.site_requires_dark_figures(backend) is True


@pytest.mark.parametrize("flag,environment,site,expected", [
    (False, None, False, (False, "")),
    (False, None, True, (True, "this site's requireDarkFigures setting")),
    (True, None, False, (True, "--require-dark-figures")),
    (False, "1", False, (True, "PAPYRUS_REQUIRE_DARK_FIGURES")),
    (False, "0", True, (False, "PAPYRUS_REQUIRE_DARK_FIGURES")),      # the variable is an override in both directions
    (True, "0", True, (True, "--require-dark-figures")),
])
def test_the_refusal_decision(flag, environment, site, expected):
    assert dark_figures_required(flag, environment, lambda: site) == expected


def test_the_site_setting_is_not_read_when_a_flag_or_variable_decides():
    def boom():
        raise AssertionError("read the site")

    assert dark_figures_required(True, None, boom)[0] and dark_figures_required(False, "1", boom)[0] and not dark_figures_required(False, "off", boom)[0]


# --- the context pack ---------------------------------------------------------------------------------------------------------------------------------

def test_the_context_entry_is_a_pointer_from_the_catalog_row_alone(tmp_path):
    backend, store = make()
    assert design_system_entry(backend, store.store) is None
    push(store, write_folder(tmp_path / "ds"))
    backend.reads.clear()
    entry = design_system_entry(backend, store.store)
    assert "design-system show" in entry["text"] and "version 1" in entry["text"] and "Never invent a brand" in entry["text"]
    assert entry["row"]["id"] == backend.items[0]["id"]
    assert {index for index, _ in backend.reads} == {"itemBySlug"}       # one index query; nothing downloaded


# --- the commands -------------------------------------------------------------------------------------------------------------------------------------

def run_command(function, tokens, store, **environment):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), patch("papyrus_content.story_commands._version_author", return_value="Ada Admin"):
        status = function(tokens, store)
    return status, out.getvalue()


def test_push_dry_run_writes_nothing_and_push_writes_a_version(tmp_path):
    backend, store = make()
    store.client = backend
    folder = write_folder(tmp_path / "ds")
    status, text = run_command(design_system_cli.design_system_push, [str(folder), "--reason", "First", "--dry-run"], store)
    assert status == 0 and "dry run\tversion 1" in text and "fonts/Display.ttf" in text and backend.items == []
    status, text = run_command(design_system_cli.design_system_push, [str(folder), "--reason", "First"], store)
    assert "saved\tversion 1" in text and len(backend.items) == 1 and backend.items[0]["versionCreatedBy"] == "Ada Admin"
    _, text = run_command(design_system_cli.design_system_push, [str(folder), "--reason", "Again"], store)
    assert "unchanged\tversion 1" in text
    _, text = run_command(design_system_cli.design_system_push, [str(folder), "--reason", "Again", "--dry-run"], store)
    assert "unchanged at version 1" in text


def test_push_needs_a_folder_and_a_reason(tmp_path):
    backend, store = make()
    with pytest.raises(ValueError, match="needs the design system folder"):
        run_command(design_system_cli.design_system_push, ["--reason", "x"], store)
    with pytest.raises(ValueError, match="--reason is required"):
        run_command(design_system_cli.design_system_push, [str(write_folder(tmp_path / "ds"))], store)
    with pytest.raises(ValueError, match="cannot read mapping.json"):
        run_command(design_system_cli.design_system_push, [str(tmp_path / "empty"), "--reason", "x"], store)


def test_show_describes_the_stored_design_system_or_says_there_is_none(tmp_path):
    backend, store = make()
    _, text = run_command(design_system_cli.design_system_show, [], store)
    assert "This site has no design system" in text and "--neutral-default" in text
    push(store, write_folder(tmp_path / "ds", settings={"requireDarkFigures": True}))
    _, text = run_command(design_system_cli.design_system_show, [], store)
    assert "version 1" in text and "examples/one" in text and "requireDarkFigures = true" in text and "fonts/Display.ttf" in text
    _, text = run_command(design_system_cli.design_system_show, ["--json"], store)
    data = json.loads(text)
    assert data["version"] == 1 and data["settings"] == {"requireDarkFigures": True} and "ground" in data["figureRoles"] and data["examples"] == ["examples/one"]


def test_pull_writes_a_new_folder_and_refuses_a_full_one(tmp_path):
    backend, store = make()
    folder = write_folder(tmp_path / "ds")
    push(store, folder)
    _, text = run_command(design_system_cli.design_system_pull, [str(tmp_path / "out")], store)
    assert "wrote\tmapping.json" in text and tree(tmp_path / "out") == tree(folder)
    with pytest.raises(ValueError, match="is not empty"):
        run_command(design_system_cli.design_system_pull, [str(tmp_path / "out")], store)
    run_command(design_system_cli.design_system_pull, [str(tmp_path / "out"), "--force"], store)
    with pytest.raises(ValueError, match="needs the design system folder"):
        run_command(design_system_cli.design_system_pull, [], store)


def test_unknown_design_system_commands_are_refused():
    with pytest.raises(ValueError, match="Unsupported papyrus command: design-system nope"):
        design_system_cli.command(["nope"])


# --- figures render uses the stored design system ---------------------------------------------------------------------------------------------------------

def test_render_defaults_to_the_stored_design_system(tmp_path, capsys):
    backend, store = make()
    push(store, write_folder(tmp_path / "ds"))
    with patch.object(records, "open_records", return_value=store):
        design_system = figures_cli.resolve_design_system({})
    assert design_system.name == "Neutral default (unbranded)" and design_system.embeds_fonts
    assert "using the site's stored design system" in capsys.readouterr().err


def test_a_folder_overrides_the_stored_design_system(tmp_path):
    folder = write_folder(tmp_path / "ds", mutate=lambda mapping, _t: mapping.update(publication="From the folder"))
    with patch.object(records, "open_records", side_effect=AssertionError("read the site")):
        assert figures_cli.resolve_design_system({"--design-system": str(folder)}).name == "From the folder"
        assert figures_cli.resolve_design_system({"--neutral-default": True}).name == "Neutral default (unbranded)"


def test_render_with_no_stored_design_system_never_invents_one():
    backend, store = make()
    with patch.object(records, "open_records", return_value=store):
        with pytest.raises(ValueError, match="the site stores none") as raised:
            figures_cli.resolve_design_system({})
    assert "never invent a brand" in str(raised.value) and "--neutral-default" in str(raised.value)


def test_render_says_why_the_site_could_not_be_read():
    with patch.object(records, "open_records", side_effect=RuntimeError("not signed in")):
        with pytest.raises(ValueError, match="reading the site's design system failed \\(not signed in\\).*never invent a brand"):
            figures_cli.resolve_design_system({})


def test_the_group_is_routed_by_the_cli(tmp_path):
    backend, store = make()
    out = io.StringIO()
    with patch.object(records, "open_records", return_value=store), contextlib.redirect_stdout(out):
        assert cli.main(["design-system", "show"]) == 0
    assert "This site has no design system" in out.getvalue()
