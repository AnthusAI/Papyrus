from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from papyrus_content import procedure_registry as registry

REPO_ROOT = Path(__file__).resolve().parents[2]
A, B = "procedures/newsroom/a.tac", "procedures/newsroom/b.tac"


def config(**changes):
    base = {"procedures": {"k.a": A, "k.b": B}, "requiredCliProcedures": {"cmd.a": "k.a", "cmd.b": "k.b"}}
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
    problems = registry.check_procedure_registry(config(procedures={"k.a": "procedures/newsroom/gone.tac", "k.b": B}), files())
    assert any("gone.tac" in p and "not a procedure file" in p for p in problems)
    assert any(A in p and "does not list" in p for p in problems)


def test_unlisted_file_is_reported():
    problems = registry.check_procedure_registry(config(), files(**{"procedures/newsroom/c.tac": "-- papyrus-procedure-kind: k.c\n"}))
    assert problems == ["procedures/newsroom/c.tac is a procedure file the registry does not list."]


def test_cli_command_for_an_unlisted_kind_is_reported():
    problems = registry.check_procedure_registry(config(requiredCliProcedures={"cmd.x": "k.ghost"}), files())
    assert problems == ["The CLI command cmd.x needs the kind k.ghost, which the registry does not list."]


def test_missing_maps_are_reported():
    assert registry.check_procedure_registry({"requiredCliProcedures": {}}, files())
    assert any("requiredCliProcedures" in p for p in registry.check_procedure_registry({"procedures": {"k.a": A}}, {A: files()[A]}))


def test_shipped_registry_matches_the_shipped_files():
    registry.validate_procedure_registry(REPO_ROOT)


def test_validate_raises_with_every_problem(tmp_path, monkeypatch):
    (tmp_path / "procedures" / "newsroom").mkdir(parents=True)
    (tmp_path / A).write_text("Procedure {}\n", encoding="utf-8")
    monkeypatch.setattr(registry, "load_registry_config", lambda: config(procedures={"k.a": A}, requiredCliProcedures={"cmd.a": "k.a"}))
    with pytest.raises(registry.ProcedureRegistryError, match="does not declare its kind"):
        registry.validate_procedure_registry(tmp_path)


def test_procedure_path_for_kind_refuses_an_unknown_kind():
    with pytest.raises(registry.ProcedureRegistryError, match="No procedure is registered for the kind nope"):
        registry.procedure_path_for_kind("nope", REPO_ROOT)


def test_ci_entry_point_passes_on_the_checkout_and_fails_on_a_mismatch(tmp_path):
    env = {"PYTHONPATH": str(REPO_ROOT / "src"), "PAPYRUS_ROOT": str(tmp_path), "PATH": ""}
    (tmp_path / "procedures" / "newsroom").mkdir(parents=True)
    (tmp_path / "procedures" / "newsroom" / "stray.tac").write_text("Procedure {}\n", encoding="utf-8")
    failed = subprocess.run([sys.executable, "-m", "papyrus_content.procedure_registry"], env=env, capture_output=True, text=True)
    assert failed.returncode == 1 and "stray.tac" in failed.stderr
    passed = subprocess.run([sys.executable, "-m", "papyrus_content.procedure_registry"], env={**env, "PAPYRUS_ROOT": str(REPO_ROOT)}, capture_output=True, text=True)
    assert passed.returncode == 0, passed.stderr
