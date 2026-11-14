"""The app-shell pipeline: check_cdk_manifest.py (exactly one expected stack) and the shape of app-shell-deploy.yml.

Nothing here calls AWS; the cloud assemblies are fixtures built in tmp_path.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "infra" / "pipeline" / "check_cdk_manifest.py"
WORKFLOW = ROOT / ".github" / "workflows" / "app-shell-deploy.yml"
spec = importlib.util.spec_from_file_location("check_cdk_manifest", SCRIPT)
ccm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ccm)

STACK = "demo-cms"


def assembly(tmp_path: Path, artifacts: dict) -> Path:
    out = tmp_path / "cdk.out"
    out.mkdir()
    (out / "manifest.json").write_text(json.dumps({"version": "40.0.0", "artifacts": artifacts}))
    return out


def stack(name: str) -> dict:
    return {name: {"type": "aws:cloudformation:stack", "properties": {"templateFile": f"{name}.template.json"}}}


TREE = {"Tree": {"type": "cdk:tree", "properties": {"file": "tree.json"}}}


def run(out: Path, expect: str = STACK) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--out", str(out), "--expect", expect], capture_output=True, text=True)


def test_one_expected_stack_passes_and_other_artifact_types_are_ignored(tmp_path):
    out = assembly(tmp_path, {**stack(STACK), **TREE, "Assets": {"type": "cdk:asset-manifest"}})
    result = run(out)
    assert result.returncode == 0, result.stderr
    assert STACK in result.stdout


def test_no_stack_is_refused(tmp_path):
    result = run(assembly(tmp_path, TREE))
    assert result.returncode == 2
    assert "no CloudFormation stack" in result.stderr


def test_two_stacks_are_refused_even_when_one_is_expected(tmp_path):
    result = run(assembly(tmp_path, {**stack(STACK), **stack("demo-github-deploy")}))
    assert result.returncode == 2
    assert "2 CloudFormation stacks" in result.stderr and "demo-github-deploy" in result.stderr


def test_a_different_single_stack_is_refused(tmp_path):
    result = run(assembly(tmp_path, stack("demo-github-deploy")))
    assert result.returncode == 2
    assert "demo-github-deploy" in result.stderr and STACK in result.stderr


def test_missing_manifest_is_refused(tmp_path):
    out = tmp_path / "cdk.out"
    out.mkdir()
    result = run(out)
    assert result.returncode == 2
    assert "does not exist" in result.stderr


@pytest.mark.parametrize("text", ["not json", "[]", json.dumps({"version": "1"}), json.dumps({"artifacts": []})])
def test_invalid_manifest_is_refused(tmp_path, text):
    out = tmp_path / "cdk.out"
    out.mkdir()
    (out / "manifest.json").write_text(text)
    assert run(out).returncode == 2


def test_check_function_returns_none_for_a_good_assembly(tmp_path):
    assert ccm.check(assembly(tmp_path, stack(STACK)), STACK) is None


# ---- the workflow file -------------------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def wf():
    return yaml.safe_load(WORKFLOW.read_text())


def triggers(doc):
    return doc.get("on", doc.get(True))


def test_workflow_is_a_reusable_workflow_with_the_documented_inputs(wf):
    call = triggers(wf)["workflow_call"]
    inputs = call["inputs"]
    assert {"prefix", "aws-account-id", "papyrus-ref", "site", "stack-name", "node-version", "region",
            "start-amplify-build", "site-id"} <= set(inputs)
    assert inputs["stack-name"]["required"] and inputs["prefix"]["required"]
    assert inputs["papyrus-ref"]["default"] == "main" and inputs["site"]["default"] == "infra/site.json"
    assert "access-token-parameter" not in inputs and inputs["start-amplify-build"]["default"] is False
    assert "app-id" in call["outputs"]


def test_workflow_has_synth_deploy_build(wf):
    assert set(wf["jobs"]) == {"synth", "deploy", "build"}
    assert wf["jobs"]["deploy"]["needs"] == "synth" and wf["jobs"]["build"]["needs"] == "deploy"
    assert "start-amplify-build" in wf["jobs"]["build"]["if"]


def test_every_action_is_pinned_by_commit_sha(wf):
    for name, job in wf["jobs"].items():
        uses = [job["uses"]] if "uses" in job else []
        uses += [s["uses"] for s in job.get("steps", []) if "uses" in s]
        for ref in uses:
            if ref.startswith("AnthusAI/Papyrus/"):
                continue   # our own reusable workflow, versioned with this repository
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), f"{name}: {ref} is not pinned by SHA"


def test_deploy_is_main_only_and_never_cancelled(wf):
    deploy = wf["jobs"]["deploy"]
    cond = deploy["if"]
    assert "refs/heads/main" in cond and "pull_request" not in cond
    assert "push" in cond and "workflow_dispatch" in cond
    assert deploy["concurrency"]["cancel-in-progress"] is False
    assert deploy["permissions"]["id-token"] == "write"


def test_synth_holds_no_aws_credentials(wf):
    synth = wf["jobs"]["synth"]
    assert "if" not in synth                       # runs on pull requests too
    assert "id-token" not in synth.get("permissions", {})
    assert not any("configure-aws-credentials" in s.get("uses", "") for s in synth["steps"])
    text = "\n".join(s.get("run", "") for s in synth["steps"])
    assert "papyrus-infra synth" in text and "check_cdk_manifest.py" in text and "--expect" in text
    assert text.index("papyrus-infra synth") < text.index("check_cdk_manifest.py")


def test_no_token_flow_and_cdk_deploys_the_checked_assembly(wf):
    text = WORKFLOW.read_text()
    for word in ("RepositoryAccessToken", "add-mask", "ssm get-parameter", "github-amplify-token"):
        assert word not in text
    run_text = next(s["run"] for s in wf["jobs"]["deploy"]["steps"] if s.get("name", "").startswith("Deploy the stack"))
    assert "--require-approval never" in run_text and "--app cdk.out" in run_text


def test_baseline_has_no_token_statement_but_keeps_the_cdk_roles():
    text = (ROOT / "infra" / "account" / "baseline.yaml").read_text()
    assert "github-amplify-token" not in text and "CdkQualifier" in text
    assert "cdk-${CdkQualifier}-deploy-role" in text and "file-publishing-role" in text
    assert "image-publishing" not in text and "lookup-role" not in text


def test_the_stack_name_is_the_artifact_property_not_the_construct_id(tmp_path):
    """The real synth names the artifact after the construct (AmplifyAppShell-<site>) and puts the CloudFormation name in properties.stackName."""
    art = {"AmplifyAppShell-demo": {"type": "aws:cloudformation:stack", "properties": {"stackName": STACK, "templateFile": "x.template.json"}}}
    assert ccm.check(assembly(tmp_path, art), STACK) is None
    other = {"AmplifyAppShell-demo": {"type": "aws:cloudformation:stack", "properties": {"stackName": "something-else", "templateFile": "x"}}}
    assert "something-else" in ccm.check(assembly(tmp_path / "b", other) if (tmp_path / "b").mkdir() is None else tmp_path, STACK)


def test_deploy_uses_all_because_the_manifest_check_allows_one_stack():
    text = (ROOT / ".github" / "workflows" / "app-shell-deploy.yml").read_text(encoding="utf-8")
    assert "deploy --all --app cdk.out" in text


def test_the_deploy_role_may_read_the_cdk_bootstrap_version():
    """The CDK CLI confirms the bootstrap version with the caller's own credentials (found on the first Humorus app-shell deploy)."""
    text = (ROOT / "infra" / "account" / "baseline.yaml").read_text(encoding="utf-8")
    assert "parameter/cdk-bootstrap/${CdkQualifier}/version" in text and "stack/CDKToolkit/*" in text
