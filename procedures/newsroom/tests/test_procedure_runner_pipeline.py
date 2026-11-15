"""The procedure runner is deployed by the release: its image is built from this commit and its role may call every site's API.

Nothing here calls AWS. features_backend/procedure-runner-in-the-pipeline.feature tells the same story in prose.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
PIPELINE = ROOT / "infra" / "pipeline"
TEMPLATE = ROOT / "infra" / "procedures" / "papyrus-procedure-runner.yaml"
SITES = ("Distinctive", "AnthUs", "MachinesOnMachines", "ThreatIntel", "DataParade", "Pilobolus", "Shipped")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_image = load("build_image", ROOT / "infra" / "procedures" / "build_image.py")
sd = load("stack_deploy", PIPELINE / "stack_deploy.py")


def template_text():
    return TEMPLATE.read_text()


def stacks():
    return {s["name"]: s for s in json.loads((PIPELINE / "stacks.json").read_text())["stacks"]}


def test_the_image_tag_comes_from_the_inputs_so_it_cannot_go_stale(monkeypatch, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("one")
    monkeypatch.setattr(build_image, "ROOT", tmp_path)
    first = build_image.image_tag(["src/a.py"])
    assert build_image.image_tag(["src/a.py"]) == first and first.startswith("src-")
    (tmp_path / "src" / "a.py").write_text("two")
    assert build_image.image_tag(["src/a.py"]) != first


def test_the_tag_covers_everything_the_dockerfile_copies():
    dockerfile = (ROOT / "infra" / "procedures" / "Dockerfile").read_text()
    copied = set(re.findall(r"^COPY (.+?) \$\{LAMBDA_TASK_ROOT\}", dockerfile, re.M))
    covered = {name for part in copied for name in part.split()}
    assert {"pyproject.toml", "README.md", "src", "corpora"} <= covered
    assert set(build_image.INPUTS) >= {"pyproject.toml", "README.md", "src", "corpora", "infra/procedures/Dockerfile"}


def test_the_role_may_call_every_site_api_and_the_template_names_no_api_id():
    text = template_text()
    for site in SITES:
        assert f"${{{site}ApiId}}/types/Query/fields/*" in text and f"${{{site}ApiId}}/types/Mutation/fields/*" in text, site
    assert not re.search(r"[a-z0-9]{26}", text)   # no API id literal: the release passes them from the monitoring stack's outputs
    assert "Default:" not in text.split("Resources:")[0].replace("Default: 0", "")


def test_the_release_feeds_the_runner_from_the_monitoring_stack_and_builds_its_image():
    runner = stacks()["papyrus-procedure-runner"]
    names = list(stacks())
    assert names.index("papyrus-monitoring") < names.index("papyrus-procedure-runner-repository") < names.index("papyrus-procedure-runner")
    assert runner["builds"] == [{"parameter": "ImageUri", "script": "infra/procedures/build_image.py", "kind": "image", "args": []}]
    for site in SITES:
        assert runner["parameters"][f"{site}ApiId"] == {"fromStackOutput": {"stack": "papyrus-monitoring", "output": f"ApiId{site}"}}
    outputs = yaml.safe_load(re.sub(r"!\w+", "", (ROOT / "infra" / "monitoring" / "papyrus-monitoring.yaml").read_text()))["Outputs"]
    assert all(f"ApiId{site}" in outputs for site in SITES)


def test_the_repository_is_imported_not_recreated():
    repository = stacks()["papyrus-procedure-runner-repository"]
    assert repository["import"]["lookup"] == {"kind": "ecrRepositoryByName", "name": "papyrus-procedure-runner"}
    assert "DeletionPolicy: Retain" in (ROOT / repository["template"]).read_text()


def test_an_image_build_is_run_without_an_upload_and_its_uri_is_the_parameter():
    calls = []

    class Done:
        returncode = 0
        stdout = "CodeKey 1.dkr.example/papyrus-procedure-runner@sha256:abc\n"
        stderr = ""

    ctx = type("Ctx", (), {"runner": lambda self, command, **kw: (calls.append(command), Done())[1], "root": ROOT})()
    keys = sd.build_keys(ctx, stacks()["papyrus-procedure-runner"], "bucket")
    assert keys == {"ImageUri": "1.dkr.example/papyrus-procedure-runner@sha256:abc"} and "--upload" not in calls[0]


def test_the_release_can_build_an_arm64_image():
    workflow = (ROOT / ".github" / "workflows" / "stack-deploy.yml").read_text()
    assert "docker/setup-qemu-action@" in workflow and "docker/setup-buildx-action@" in workflow


def test_the_hand_build_script_is_gone():
    assert not (ROOT / "infra" / "procedures" / "build_image.sh").exists()
