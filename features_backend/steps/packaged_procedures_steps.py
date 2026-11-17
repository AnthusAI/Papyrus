from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import wheel_support as support  # noqa: E402

REPOSITORY_PROCEDURES = REPO_ROOT / "procedures" / "newsroom"
PACKAGED_PROCEDURES = REPO_ROOT / "src" / "papyrus_content" / "data" / "procedures"


def _registered_files() -> dict[str, str]:
    from papyrus_content import procedure_registry

    return procedure_registry.load_registry_config()["procedures"]


@then("every kind in the procedure registry has its file in the wheel")
def step_wheel_has_files(context):
    members = support.wheel_members(context.wheel)
    registered = _registered_files()
    assert registered
    missing = [name for name in registered.values() if f"{support.PACKAGED_PROCEDURES}/{name}" not in members]
    assert not missing, missing


@then("each packaged procedure in the wheel is the same text as the file in the checkout")
def step_wheel_text(context):
    import zipfile

    with zipfile.ZipFile(context.wheel) as archive:
        for name in _registered_files().values():
            assert archive.read(f"{support.PACKAGED_PROCEDURES}/{name}") == (PACKAGED_PROCEDURES / name).read_bytes(), name


_INSTALLED = r'''
import json
from pathlib import Path
import papyrus_content
from papyrus_content import procedure_registry, ontology_enrichment
from papyrus_content.env import PAPYRUS_ROOT
target = Path(sys.argv[1]).resolve()
result = {"inside": True, "declares": True, "check": "ok", "kinds": 0, "root_procedures": (PAPYRUS_ROOT / "procedures").exists(), "ontology": []}
for kind in procedure_registry.load_registry_config()["procedures"]:
    path = procedure_registry.procedure_file_for_kind(kind)
    result["kinds"] += 1
    result["inside"] &= path.resolve().is_relative_to(target)
    result["declares"] &= procedure_registry.declared_kind(procedure_registry.procedure_source_for_kind(kind)) == kind
try:
    procedure_registry.validate_procedure_registry()
except Exception as error:
    result["check"] = str(error)
class Client:
    def safe_list_records(self, name):
        return []
result["ontology"] = [check for check in ontology_enrichment.run_preflight_checks(Client()) if check["name"].startswith("procedure-")]
print(json.dumps(result))
'''


def _run_unpacked(context):
    root = Path(tempfile.mkdtemp(prefix="papyrus-installed-"))
    target, workdir = root / "site-packages", root / "elsewhere"
    workdir.mkdir()
    support.install_wheel(context.wheel, target)
    environment = {key: value for key, value in os.environ.items() if key not in {"PAPYRUS_ROOT", "PYTHONPATH"}}
    result = support.run_installed(target, workdir, f"import sys\nsys.argv = ['x', {str(target)!r}]\n{_INSTALLED}", environment)
    assert result.returncode == 0, result.stderr[-3000:]
    context.installed_report = json.loads(result.stdout.strip().splitlines()[-1])


@when("the wheel is unpacked away from the checkout and every registered kind is looked up")
def step_unpacked_lookup(context):
    _run_unpacked(context)


@when("the wheel is unpacked away from the checkout and the ontology preflight names its procedures")
def step_unpacked_ontology(context):
    _run_unpacked(context)


@then("every kind resolves to a file inside the unpacked wheel that declares that kind")
def step_unpacked_inside(context):
    report = context.installed_report
    assert report["kinds"] == len(_registered_files()) and report["inside"] and report["declares"], report


@then("the procedure registry check passes there")
def step_unpacked_check(context):
    assert context.installed_report["check"] == "ok", context.installed_report


@then("there is no procedures folder in the unpacked wheel's root")
def step_unpacked_no_folder(context):
    assert context.installed_report["root_procedures"] is False


@then("both ontology procedures are found in the unpacked wheel")
def step_unpacked_ontology_found(context):
    checks = context.installed_report["ontology"]
    assert sorted(check["name"] for check in checks) == ["procedure-ontology.concept-profiler", "procedure-ontology.relationship-explainer"], checks
    assert all(check["ok"] and "site-packages" in check["detail"] for check in checks), checks


@given("a root with its own procedures/newsroom/reporter.tac")
def step_root_override(context):
    from unittest import mock

    from papyrus_content import env

    context.override_root = Path(tempfile.mkdtemp(prefix="papyrus-override-"))
    context.tmp_dirs.append(context.override_root)
    directory = context.override_root / "procedures" / "newsroom"
    directory.mkdir(parents=True)
    (directory / "reporter.tac").write_text("-- papyrus-procedure-kind: newsroom.reporting.context\nProcedure {}\n", encoding="utf-8")
    patcher = mock.patch.object(env, "PAPYRUS_ROOT", context.override_root)
    patcher.start()
    context.add_cleanup(patcher.stop)


@then("the reporting procedure resolves to the root's file")
def step_resolves_root(context):
    from papyrus_content import procedure_registry

    assert procedure_registry.procedure_file_for_kind("newsroom.reporting.context") == context.override_root / "procedures" / "newsroom" / "reporter.tac"


@when("that root file is removed")
def step_remove_root_file(context):
    (context.override_root / "procedures" / "newsroom" / "reporter.tac").unlink()


@then("the reporting procedure resolves to the packaged file")
def step_resolves_packaged_procedure(context):
    from papyrus_content import env, procedure_registry

    assert procedure_registry.procedure_file_for_kind("newsroom.reporting.context") == env.packaged_procedure_file("reporter.tac")


@then("every procedure in procedures/newsroom/ is a link to the packaged file")
def step_links(context):
    names = {path.name for path in REPOSITORY_PROCEDURES.glob("*.tac")}
    assert names
    for name in names:
        link = REPOSITORY_PROCEDURES / name
        assert link.is_symlink() and link.resolve() == (PACKAGED_PROCEDURES / name).resolve(), name


@then("no packaged procedure lacks a repository path")
def step_no_orphans(context):
    assert {path.name for path in PACKAGED_PROCEDURES.glob("*.tac")} <= {path.name for path in REPOSITORY_PROCEDURES.glob("*.tac")}
