"""Tenancy mode: synthesise the real site backend and read the function environment."""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from behave import given, when, then

REPO_ROOT = Path(__file__).resolve().parents[2]
VARIABLE = 'PAPYRUS_TENANCY_MODE'


def _synth(backend):
    out = tempfile.TemporaryDirectory()
    result = subprocess.run(
        ['npx', 'tsx', 'scripts/synth-site-backend.mts', out.name, json.dumps(backend)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=600)
    return out, result


def _normalised(text):
    """Mask content hashes and the two timestamps a synth stamps (asset expiry, secret update time)."""
    text = re.sub(r'[0-9a-f]{64}', '<hash>', text)
    return re.sub(r'("Expires": |"secretLastUpdated": )\d+', r'\1<time>', text)


def _templates(directory):
    return {_normalised(p.name): _normalised(p.read_text()) for p in sorted(Path(directory).rglob('*.template.json'))}


@given('a site config with no tenancy setting')
def step_no_tenancy(context):
    context.backend = {}


@given('tenancy mode "{mode}"')
def step_mode(context, mode):
    # A shared stack is one of two tiers (docs/shared-stack.md); a mistyped mode still has none to name.
    context.backend = {'tenancy': {'mode': mode, **({'tier': 'staging'} if mode == 'shared' else {})}}


@when('the backend is synthesised')
def step_synth(context):
    context.synth_dir, context.synth_result = _synth(context.backend)
    context.add_cleanup(context.synth_dir.cleanup)


@when('content-actions starts')
def step_starts(context):
    step_synth(context)
    assert context.synth_result.returncode == 0, context.synth_result.stderr[-2000:]


@then("the template is identical to the previous release's")
def step_identical(context):
    assert context.synth_result.returncode == 0, context.synth_result.stderr[-2000:]
    mine = _templates(context.synth_dir.name)
    assert all(VARIABLE not in text for text in mine.values())
    # Set PAPYRUS_SYNTH_BASELINE_DIR to a synth of the previous release to compare byte for byte (a synth takes minutes).
    baseline = os.environ.get('PAPYRUS_SYNTH_BASELINE_DIR')
    if baseline:
        assert mine == _templates(baseline)


@then('the tenancy helper reports shared in Python and in TypeScript')
def step_reports(context):
    templates = _templates(context.synth_dir.name)
    assert any(f'"{VARIABLE}": "shared"' in text for text in templates.values()), 'no function carries the variable'
    environment = dict(os.environ, **{VARIABLE: 'shared'})
    python = subprocess.run(
        ['python3', '-c', 'from papyrus_content.tenancy import is_shared_stack; print(is_shared_stack())'],
        cwd=REPO_ROOT / 'src', capture_output=True, text=True, env=environment)
    assert python.stdout.strip() == 'True', python.stderr
    node = subprocess.run(
        ['npx', 'tsx', '-e', 'import { isSharedStack } from "./lib/tenant-keys"; console.log(isSharedStack())'],
        cwd=REPO_ROOT, capture_output=True, text=True, env=environment)
    assert node.stdout.strip() == 'true', node.stderr


@then('synthesis fails naming tenancy.mode')
def step_fails(context):
    assert context.synth_result.returncode != 0
    assert 'tenancy.mode' in context.synth_result.stderr
