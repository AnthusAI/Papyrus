from __future__ import annotations

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

_WHEEL: dict[str, Path] = {}


@given("the wheel built from this checkout")
def step_wheel(context):
    if "wheel" not in _WHEEL:
        _WHEEL["directory"] = Path(tempfile.mkdtemp(prefix="papyrus-wheel-"))
        _WHEEL["wheel"] = support.build_wheel(_WHEEL["directory"])
    context.wheel = _WHEEL["wheel"]


@then("the wheel contains the file {member}")
def step_contains(context, member):
    assert member in support.wheel_members(context.wheel)


@then("the wheel contains every default configuration file that the code names")
def step_contains_all(context):
    members = support.wheel_members(context.wheel)
    missing = [name for name in support.runtime_default_corpora_names() if f"{support.PACKAGED_DIRECTORY}/{name}" not in members]
    assert not missing, missing


@when("the wheel is installed away from the checkout and the relation types are loaded")
def step_installed(context):
    root = Path(tempfile.mkdtemp(prefix="papyrus-installed-"))
    target, workdir = root / "site-packages", root / "elsewhere"
    workdir.mkdir()
    support.install_wheel(context.wheel, target)
    environment = {key: value for key, value in os.environ.items() if key not in {"PAPYRUS_ROOT", "PYTHONPATH"}}
    code = (
        "from papyrus_content import relation_types\n"
        "print(relation_types.DEFAULT_RELATION_TYPES_PATH)\n"
        "print(len(relation_types.load_semantic_relation_type_seeds()))\n"
    )
    context.installed = support.run_installed(target, workdir, code, environment)
    context.installed_target = target


@then("the relation types file comes from the installed package")
def step_from_package(context):
    assert context.installed.returncode == 0, context.installed.stderr
    path = Path(context.installed.stdout.splitlines()[0])
    assert path.is_file() and path.resolve().is_relative_to(context.installed_target.resolve()), path


@then("the relation types load")
def step_types_load(context):
    assert int(context.installed.stdout.splitlines()[1]) > 0


@given("a checkout with its own corpora/papyrus-steering.yml")
def step_checkout(context):
    from unittest import mock

    from papyrus_content import env

    context.checkout = Path(tempfile.mkdtemp(prefix="papyrus-checkout-"))
    (context.checkout / "corpora").mkdir()
    (context.checkout / "corpora" / "papyrus-steering.yml").write_text("custom: true\n")
    patcher = mock.patch.object(env, "PAPYRUS_ROOT", context.checkout)
    patcher.start()
    context.add_cleanup(patcher.stop)


@then("the steering config resolves to the checkout file")
def step_resolves_checkout(context):
    from papyrus_content import env

    assert env.resolve_corpora_file("corpora/papyrus-steering.yml") == context.checkout / "corpora" / "papyrus-steering.yml"


@when("that checkout file is removed")
def step_remove(context):
    (context.checkout / "corpora" / "papyrus-steering.yml").unlink()


@then("the steering config resolves to the packaged default")
def step_resolves_packaged(context):
    from papyrus_content import env

    assert env.resolve_corpora_file("corpora/papyrus-steering.yml") == env.packaged_corpora_file("papyrus-steering.yml")


@then("the wheel requires cli-login at exactly version 0.1.0, with the Linux extra on Linux")
def step_requires_cli_login(context):
    import zipfile

    with zipfile.ZipFile(context.wheel) as archive:
        name = next(member for member in archive.namelist() if member.endswith(".dist-info/METADATA"))
        metadata = archive.read(name).decode()
    requirements = [line.split(": ", 1)[1].replace('"', "'") for line in metadata.splitlines() if line.startswith("Requires-Dist: cli-login")]
    assert len(requirements) == 2, requirements
    plain = [line for line in requirements if "[linux]" not in line]
    linux = [line for line in requirements if "[linux]" in line]
    assert len(plain) == 1 and len(linux) == 1, requirements
    for line in requirements:
        assert "==0.1.0" in line.replace(" ", "").replace("(", "").replace(")", ""), line
    assert "sys_platform == 'linux'" in linux[0] and "sys_platform != 'linux'" in plain[0], requirements


_WITHOUT_CLI_LOGIN = r'''
import importlib.abc, importlib.util, json, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == "cli_login" or name.startswith("cli_login."):
            raise ModuleNotFoundError(f"No module named {name!r}")
        return None
sys.meta_path.insert(0, Block())
sys.path.insert(0, sys.argv[1])
spec = importlib.util.spec_from_file_location("content_actions_handler", sys.argv[2])
spec.loader.exec_module(importlib.util.module_from_spec(spec))
from papyrus_content.graphql_http import authoring_credentials_available, graphql_request_headers
from papyrus_content.operator_errors import credential_recovery_guidance
assert authoring_credentials_available()
credential_recovery_guidance()
headers = graphql_request_headers(endpoint="https://example.appsync-api.us-east-1.amazonaws.com/graphql", body=b"{}")
print(json.dumps({"headers": sorted(headers), "imported": sorted(m for m in sys.modules if m.split(".")[0] == "cli_login")}))
'''


@given("a Python process that cannot import cli_login and has no signed-in user session")
def step_without_cli_login(context):
    state = Path(tempfile.mkdtemp(prefix="papyrus-no-session-"))
    context.lambda_env = {
        key: value for key, value in os.environ.items() if not key.startswith(("AWS_", "PAPYRUS_GRAPHQL_AUTH"))
    } | {
        "PAPYRUS_CLI_STATE_DIR": str(state),
        "AWS_ACCESS_KEY_ID": "AKIDEXAMPLE",
        "AWS_SECRET_ACCESS_KEY": "example-secret",
        "AWS_REGION": "us-east-1",
        "AWS_DEFAULT_REGION": "us-east-1",
    }


@when("it imports the content-actions handler and signs a GraphQL request with IAM")
def step_sign_without_cli_login(context):
    import json
    import subprocess

    handler = REPO_ROOT / "amplify" / "functions" / "content-actions" / "handler.py"
    result = subprocess.run(
        [sys.executable, "-c", _WITHOUT_CLI_LOGIN, str(REPO_ROOT / "src"), str(handler)],
        capture_output=True, text=True, env=context.lambda_env, cwd=tempfile.gettempdir(), check=False,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    context.lambda_result = json.loads(result.stdout.strip().splitlines()[-1])


@then("the request carries an IAM signature")
def step_iam_signature(context):
    assert "Authorization" in context.lambda_result["headers"], context.lambda_result


@then("cli_login was never imported")
def step_cli_login_not_imported(context):
    assert context.lambda_result["imported"] == [], context.lambda_result
