from __future__ import annotations

import copy
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus_content import procedure_registry as registry_module  # noqa: E402

_FIRST = "first.tac"
_SECOND = "second.tac"


def _problems(context) -> list[str]:
    return registry_module.check_procedure_registry(context.registry, context.sources)


@given("the procedure files and the registry of this checkout")
def step_real(context):
    context.registry = registry_module.load_registry_config()
    context.sources = registry_module.discover_procedure_files()


@then("the registry and the procedure files agree")
def step_agree(context):
    assert _problems(context) == []


@then("every procedure file declares its kind on its first line")
def step_declared(context):
    assert context.sources
    assert [path for path, source in context.sources.items() if registry_module.declared_kind(source) is None] == []


@then("every command in requiredCliProcedures resolves to a file that declares its kind")
def step_commands(context):
    for alias, kind in context.registry["requiredCliProcedures"].items():
        path = context.registry["procedures"].get(kind)
        assert path, f"{alias} needs {kind}, which has no file"
        assert registry_module.declared_kind(context.sources[path]) == kind, alias


@given("a registry of two kinds, each with a file that declares it")
def step_fake(context):
    context.registry = {
        "procedures": {"demo.first": _FIRST, "demo.second": _SECOND},
        "requiredCliProcedures": {"demo.run-first": "demo.first", "demo.run-second": "demo.second"},
        "procedureMetadata": {
            kind: {"title": "Demo", "category": "newsroom", "description": "A demo.", "parameterSchema": {"type": "object"}, "defaults": {}}
            for kind in ("demo.first", "demo.second")
        },
    }
    context.sources = {
        _FIRST: "-- papyrus-procedure-kind: demo.first\nProcedure {}\n",
        _SECOND: "-- papyrus-procedure-kind: demo.second\nProcedure {}\n",
    }
    context.root = Path(__import__("tempfile").mkdtemp(prefix="papyrus-registry-"))
    context.tmp_dirs.append(context.root)
    assert _problems(context) == []


@when("the first file loses its kind line")
def step_lose(context):
    context.sources[_FIRST] = "Procedure {}\n"


@when("the first file gets a comment above its kind line")
def step_comment_above(context):
    context.sources[_FIRST] = "-- a note\n" + context.sources[_FIRST]


@then("the check names that file as declaring no kind")
def step_names_undeclared(context):
    assert any(_FIRST in problem and "does not declare its kind" in problem for problem in _problems(context)), _problems(context)


@when("the second file declares the first file's kind")
def step_duplicate(context):
    context.sources[_SECOND] = context.sources[_FIRST]


@then("the check names both files as declaring the same kind")
def step_names_duplicate(context):
    assert any(_FIRST in problem and _SECOND in problem and "both declare the kind demo.first" in problem for problem in _problems(context)), _problems(context)


@when("the registry swaps the two files")
def step_swap(context):
    context.registry["procedures"] = {"demo.first": _SECOND, "demo.second": _FIRST}


@then("the check says each kind points at a file that declares the other")
def step_swapped(context):
    problems = _problems(context)
    assert any("demo.first" in p and _SECOND in p and "declares demo.second" in p for p in problems), problems
    assert any("demo.second" in p and _FIRST in p and "declares demo.first" in p for p in problems), problems


@when("the registry sends the first kind to a file that is not there")
def step_missing(context):
    context.registry["procedures"]["demo.first"] = "gone.tac"


@then("the check says the first kind points at a file that is not a procedure file")
def step_missing_named(context):
    assert any("demo.first" in p and "gone.tac" in p and "not a procedure file" in p for p in _problems(context)), _problems(context)


@when("a third procedure file is added that the registry does not list")
def step_third(context):
    context.sources["third.tac"] = "-- papyrus-procedure-kind: demo.third\nProcedure {}\n"


@then("the check names the third file as not listed")
def step_third_named(context):
    assert any("third.tac" in p and "does not list" in p for p in _problems(context)), _problems(context)


@when("a CLI command is added for a kind the registry does not list")
def step_command(context):
    context.registry["requiredCliProcedures"]["demo.run-ghost"] = "demo.ghost"


@then("the check names that command")
def step_command_named(context):
    assert any("demo.run-ghost" in p and "demo.ghost" in p for p in _problems(context)), _problems(context)


@when("the first file is edited to declare another kind")
def step_edit_on_disk(context):
    from unittest import mock

    from papyrus_content import env

    directory = context.root / "procedures" / "newsroom"
    directory.mkdir(parents=True)
    (directory / _FIRST).write_text("-- papyrus-procedure-kind: demo.other\nProcedure {}\n", encoding="utf-8")
    for patcher in (
        mock.patch.object(registry_module, "load_registry_config", lambda: copy.deepcopy(context.registry)),
        mock.patch.object(env, "PAPYRUS_ROOT", context.root),
    ):
        patcher.start()
        context.add_cleanup(patcher.stop)


@then("loading the first kind refuses it")
def step_refuses(context):
    try:
        registry_module.procedure_file_for_kind("demo.first")
    except registry_module.ProcedureRegistryError as error:
        assert "does not declare the kind demo.first" in str(error)
    else:
        raise AssertionError("expected a refusal")
