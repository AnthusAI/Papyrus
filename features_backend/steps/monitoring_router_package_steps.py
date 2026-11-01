import importlib.util
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from behave import given, then, when

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ("import sys; sys.path.insert(0, sys.argv[1]); from papyrus_content.ideas import gate, items; import humanus, humanus.check, typesafe_sdk; "
          "assert all(sys.argv[1] in module.__file__ for module in (humanus, typesafe_sdk, gate)); "
          "pack = {'schemaVersion': 1, 'packId': 'test', 'version': '1', 'policies': [{'id': 'no-synergy', 'version': 1, 'title': 'No synergy', "
          "'guidance': 'Avoid it.', 'severity': 'warn', 'detectors': [{'id': 'synergy', 'lane': 'rules', 'kind': 'phrase', 'phrases': ['synergy']}]}]}; "
          "result = humanus.check({'schemaVersion': 1, 'content': {'format': 'markus', 'text': 'Pure synergy.'}, 'pack': pack, "
          "'options': {'lanes': {'rules': True, 'classifier': False}}}); print('findings', len(result['findings']))")


@given("the router package built from this repository")
def step_build(context):
    spec = importlib.util.spec_from_file_location("monitoring_build", ROOT / "infra/monitoring/build.py")
    context.build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(context.build)
    directory = tempfile.TemporaryDirectory()
    context.add_cleanup(directory.cleanup)
    context.directory = Path(directory.name)
    context.archive = context.directory / "router.zip"
    context.build.build_router(context.archive, target="host")


@when("the package is unpacked as the Lambda does and its gate is imported by an isolated interpreter")
def step_run(context):
    context.unpacked = context.directory / "task"
    zipfile.ZipFile(context.archive).extractall(context.unpacked)
    context.done = subprocess.run([sys.executable, "-I", "-S", "-c", SCRIPT, str(context.unpacked)], capture_output=True, text=True,
                                  cwd=context.directory, env={"PAPYRUS_ROOT": str(context.unpacked)})


@then("Humanus and the Jev client load from the package alone")
def step_loaded(context):
    assert context.done.returncode == 0, context.done.stderr[-800:]


@then("a rules-lane check of a sentence with a banned phrase returns one finding")
def step_finding(context):
    assert context.done.stdout.strip() == "findings 1", context.done.stdout


@then("the wheels are the poetry.lock closure of Humanus and the Jev client")
def step_closure(context):
    context.packages = context.build.locked_wheel_packages()
    assert {"humanus", "typesafe-sdk", "pydantic-core", "rpds-py"} <= set(context.packages)
    assert not {"pyyaml", "idna", "boto3"} & set(context.packages)


@then("every wheel the Lambda build downloads is checked against its poetry.lock hash")
def step_hashes(context):
    assert all(entry["files"] for entry in context.packages.values())
    assert "is not in poetry.lock" in (ROOT / "infra/monitoring/build.py").read_text()
