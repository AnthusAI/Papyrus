from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from papyrus_content import procedure_registry as registry

REPO_ROOT = Path(__file__).resolve().parents[2]
A, B = "a.tac", "b.tac"


def config(**changes):
    metadata = {kind: {"title": "T", "category": "c", "description": "d", "parameterSchema": {}, "defaults": {}} for kind in ("k.a", "k.b")}
    base = {"procedures": {"k.a": A, "k.b": B}, "requiredCliProcedures": {"cmd.a": "k.a", "cmd.b": "k.b"}, "procedureMetadata": metadata}
    return {**base, **changes}


def files(**changes):
    base = {A: "-- papyrus-procedure-kind: k.a\nProcedure {}\n", B: "-- papyrus-procedure-kind: k.b\nProcedure {}\n"}
    return {**base, **changes}


def test_agreeing_registry_has_no_problems():
    assert registry.check_procedure_registry(config(), files()) == []


@pytest.mark.parametrize("source,expected", [
    ("-- papyrus-procedure-kind: x.y\nrest", "x.y"),
    ("--papyrus-procedure-kind:   x.y  \r\nrest", "x.y"),
    ("-- note\n-- papyrus-procedure-kind: x.y\n", None),
    ("Procedure {}\n", None),
    ("", None),
])
def test_declared_kind_reads_only_the_first_line(source, expected):
    assert registry.declared_kind(source) == expected


def test_file_without_a_kind_is_reported():
    problems = registry.check_procedure_registry(config(), files(**{A: "Procedure {}\n"}))
    assert any(A in p and "does not declare its kind" in p for p in problems)


def test_kind_below_the_first_line_is_reported():
    problems = registry.check_procedure_registry(config(), files(**{A: "-- note\n-- papyrus-procedure-kind: k.a\n"}))
    assert any(A in p and "does not declare its kind" in p for p in problems)


def test_two_files_declaring_one_kind_are_reported():
    problems = registry.check_procedure_registry(config(), files(**{B: files()[A]}))
    assert any(A in p and B in p and "both declare the kind k.a" in p for p in problems)


def test_registry_entry_pointing_at_the_wrong_file_is_reported():
    problems = registry.check_procedure_registry(config(procedures={"k.a": B, "k.b": A}), files())
    assert len(problems) == 2 and all("declares k." in p for p in problems)


def test_registry_entry_pointing_at_a_missing_file_is_reported():
    problems = registry.check_procedure_registry(config(procedures={"k.a": "gone.tac", "k.b": B}), files())
    assert any("gone.tac" in p and "not a procedure file" in p for p in problems)
    assert any(A in p and "does not list" in p for p in problems)


def test_unlisted_file_is_reported():
    problems = registry.check_procedure_registry(config(), files(**{"c.tac": "-- papyrus-procedure-kind: k.c\n"}))
    assert problems == ["c.tac is a procedure file the registry does not list."]


def test_cli_command_for_an_unlisted_kind_is_reported():
    problems = registry.check_procedure_registry(config(requiredCliProcedures={"cmd.x": "k.ghost"}), files())
    assert problems == ["The CLI command cmd.x needs the kind k.ghost, which the registry does not list."]


def test_missing_maps_are_reported():
    assert registry.check_procedure_registry({"requiredCliProcedures": {}}, files())
    assert any("requiredCliProcedures" in p for p in registry.check_procedure_registry({"procedures": {"k.a": A}}, {A: files()[A]}))


def test_shipped_registry_matches_the_shipped_files():
    registry.validate_procedure_registry()


def test_validate_raises_with_every_problem(monkeypatch):
    monkeypatch.setattr(registry, "load_registry_config", lambda: config(procedures={"k.a": A}, requiredCliProcedures={"cmd.a": "k.a"}))
    monkeypatch.setattr(registry, "discover_procedure_files", lambda: {A: "Procedure {}\n"})
    with pytest.raises(registry.ProcedureRegistryError, match="does not declare its kind"):
        registry.validate_procedure_registry()


def test_every_registered_kind_resolves_to_a_file_that_declares_it():
    for kind in registry.load_registry_config()["procedures"]:
        path = registry.procedure_file_for_kind(kind)
        assert registry.declared_kind(path.read_text(encoding="utf-8")) == kind
        assert registry.procedure_source_for_kind(kind) == path.read_text(encoding="utf-8")


def test_unknown_kind_is_refused():
    with pytest.raises(registry.ProcedureRegistryError, match="No procedure is registered for the kind nope"):
        registry.procedure_file_for_kind("nope")


def test_a_registered_file_missing_from_the_install_is_refused(monkeypatch):
    monkeypatch.setattr(registry, "load_registry_config", lambda: config(procedures={"k.a": "not-shipped.tac"}))
    with pytest.raises(registry.ProcedureRegistryError, match="not in this install"):
        registry.procedure_file_for_kind("k.a")


def test_a_file_in_the_root_wins_over_the_packaged_one(tmp_path, monkeypatch):
    from papyrus_content import env

    kind = "newsroom.reporting.context"
    packaged = registry.procedure_file_for_kind(kind)
    directory = tmp_path / "procedures" / "newsroom"
    directory.mkdir(parents=True)
    (directory / "reporter.tac").write_text(f"-- papyrus-procedure-kind: {kind}\nProcedure {{}}\n", encoding="utf-8")
    monkeypatch.setattr(env, "PAPYRUS_ROOT", tmp_path)
    assert registry.procedure_file_for_kind(kind) == directory / "reporter.tac" != packaged


def test_the_repository_path_and_the_packaged_path_are_one_file():
    repository = REPO_ROOT / "procedures" / "newsroom"
    packaged = REPO_ROOT / "src" / "papyrus_content" / "data" / "procedures"
    assert {path.name for path in repository.glob("*.tac")} == {path.name for path in packaged.glob("*.tac")}
    for path in repository.glob("*.tac"):
        assert path.is_symlink() and path.resolve() == (packaged / path.name).resolve(), path


def test_ci_entry_point_passes_on_the_checkout():
    env = {"PYTHONPATH": str(REPO_ROOT / "src"), "PATH": ""}
    passed = subprocess.run([sys.executable, "-m", "papyrus_content.procedure_registry"], env=env, capture_output=True, text=True)
    assert passed.returncode == 0, passed.stderr


def test_ci_entry_point_fails_on_a_mismatch(monkeypatch, capsys):
    monkeypatch.setattr(registry, "discover_procedure_files", lambda: {"stray.tac": "Procedure {}\n"})
    assert registry.main() == 1
    assert "stray.tac" in capsys.readouterr().err


def test_every_core_kind_is_registered_with_metadata_that_matches_its_tactus_input():
    """The metadata is the one source of the schema a deploy registers; it must be the input the file declares. A default may be overridden
    on purpose (a site's corpus key, a smaller token budget), but never left out, and never name a field the file does not declare."""
    pytest.importorskip("tactus")
    from papyrus_content.site_procedures import parameter_schema_from_tactus, tactus_registry

    for kind in registry.registered_kinds():
        metadata = registry.procedure_metadata_for_kind(kind)
        schema, defaults = parameter_schema_from_tactus(tactus_registry(registry.procedure_source_for_kind(kind)).input_schema or {})
        assert metadata["parameterSchema"] == schema, kind
        assert set(defaults) <= set(metadata["defaults"]) <= set(schema["properties"]), kind


def test_metadata_with_an_unknown_default_token_is_reported():
    base = config()
    base["procedureMetadata"]["k.a"]["defaults"] = {"model": "$defaultNothing"}
    problems = registry.check_procedure_registry(base, files())
    assert any("$defaultNothing" in p for p in problems)
