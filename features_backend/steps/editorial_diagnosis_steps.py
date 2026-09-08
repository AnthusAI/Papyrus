from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
FIXTURE_ROOT = REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis"
FORBIDDEN_OUTPUT_KEYS = {
    "revised_text",
    "rewritten_prose",
    "revisedProse",
    "revisedText",
    "options",
    "patches",
}
STABLE_ID_PATTERN = re.compile(r"^finding-[a-f0-9]{16}$")
REQUIRED_KINDS = {
    "vague_claim",
    "empty_leadin",
    "uniform_cadence",
    "list_shaped_prose",
    "unsupported_certainty",
    "redundancy",
    "voice_mismatch",
}


def _run_diagnose_cli(draft_path: Path, profile_path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{SRC_ROOT}:{REPO_ROOT}"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "papyrus.cli",
            "editorial",
            "diagnose",
            "--draft",
            str(draft_path),
            "--profile",
            str(profile_path),
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _collect_kinds(diagnosis: dict) -> set[str]:
    kinds: set[str] = set()
    for key in ("generic_passages", "unsupported_claims", "voice_observations", "required_facts"):
        for finding in diagnosis.get(key, []):
            kinds.add(finding.get("kind"))
    for group in diagnosis.get("repetition_groups", []):
        kinds.add(group.get("kind"))
        for member in group.get("members", []):
            kinds.add(member.get("kind"))
    return kinds


def _collect_finding_ids(diagnosis: dict) -> list[str]:
    ids: list[str] = []
    for key in ("generic_passages", "unsupported_claims", "voice_observations", "required_facts"):
        for finding in diagnosis.get(key, []):
            ids.append(finding["id"])
    for group in diagnosis.get("repetition_groups", []):
        ids.append(group["id"])
        for member in group.get("members", []):
            ids.append(member["id"])
    return ids


def _walk_forbidden_keys(value, path=""):
    if isinstance(value, dict):
        for key, nested in value.items():
            current = f"{path}.{key}" if path else key
            assert key not in FORBIDDEN_OUTPUT_KEYS, current
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            assert not re.search(
                r"(detector|detectorscore|ai_detector|aidetector|perplexity_score|burstiness|ai_score|human_score)",
                normalized,
            ), current
            _walk_forbidden_keys(nested, current)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _walk_forbidden_keys(nested, f"{path}[{index}]")


def _collect_all_findings(diagnosis: dict) -> list[dict]:
    findings: list[dict] = []
    for key in ("generic_passages", "unsupported_claims", "voice_observations", "required_facts"):
        findings.extend(diagnosis.get(key, []))
    return findings


def _findings_by_kind(diagnosis: dict, kind: str) -> list[dict]:
    return [finding for finding in _collect_all_findings(diagnosis) if finding.get("kind") == kind]


@given('a draft containing "Keep always-on rules thin" and "Grok Bot is always-available"')
def step_given_always_on_draft(context):
    context.draft_path = FIXTURE_ROOT / "always-on-compounds.md"
    assert context.draft_path.is_file()


@given("a loadable style profile")
def step_given_loadable_style_profile(context):
    context.profile_path = FIXTURE_ROOT / "style-profile.yml"
    assert context.profile_path.is_file()


@given("a draft whose only numbers are markdown list markers 1. and 2.")
def step_given_list_ordinals_draft(context):
    context.draft_path = FIXTURE_ROOT / "list-ordinals-only.md"
    context.profile_path = FIXTURE_ROOT / "style-profile.yml"
    assert context.draft_path.is_file()


@given("the Anth.us style profile with uniform cadence disabled")
def step_given_anthus_cadence_off_profile(context):
    context.profile_path = FIXTURE_ROOT / "anthus-cadence-off-profile.yml"
    assert context.profile_path.is_file()


@given("a draft of five consecutive short punchy sentences")
def step_given_punchy_cadence_draft(context):
    context.draft_path = FIXTURE_ROOT / "punchy-cadence.md"
    assert context.draft_path.is_file()


@given(
    'a draft that says "This will revolutionize workflows" and "Everyone knows agents will transform the industry"'
)
def step_given_brochure_slop_draft(context):
    context.draft_path = FIXTURE_ROOT / "brochure-slop.md"
    context.profile_path = FIXTURE_ROOT / "style-profile.yml"
    assert context.draft_path.is_file()


@given('a draft that repeats a short heading "It did not manage it" as a refrain')
def step_given_rhetorical_refrain_draft(context):
    context.draft_path = FIXTURE_ROOT / "rhetorical-refrain.md"
    context.profile_path = FIXTURE_ROOT / "style-profile.yml"
    assert context.draft_path.is_file()


@then("there is no unsupported_certainty finding whose excerpt is only those compounds")
def step_then_no_unsupported_certainty_for_compounds(context):
    findings = _findings_by_kind(context.diagnosis, "unsupported_certainty")
    for finding in findings:
        excerpt = finding.get("excerpt", "").strip().lower()
        assert excerpt not in {
            "keep always-on rules thin",
            "grok bot is always-available",
            "grok bot is always-available when the queue is idle.",
        }


@then("there is no missing_attribution finding for those markers")
def step_then_no_missing_attribution_for_markers(context):
    findings = _findings_by_kind(context.diagnosis, "missing_attribution")
    assert not findings


@then("there is no uniform_cadence finding")
def step_then_no_uniform_cadence(context):
    findings = _findings_by_kind(context.diagnosis, "uniform_cadence")
    assert not findings


@then("findings include vague_claim or voice_mismatch for the avoided lexicon")
def step_then_brochure_lexicon_findings(context):
    kinds = _collect_kinds(context.diagnosis)
    assert "vague_claim" in kinds or "voice_mismatch" in kinds
    findings = _collect_all_findings(context.diagnosis)
    excerpts = " ".join(finding.get("excerpt", "").lower() for finding in findings)
    assert "revolutionize" in excerpts or "transform" in excerpts


@then('findings include unsupported_certainty for "Everyone knows"')
def step_then_everyone_knows_certainty(context):
    findings = _findings_by_kind(context.diagnosis, "unsupported_certainty")
    assert any("everyone knows" in finding.get("excerpt", "").lower() for finding in findings)


@then("that refrain is not a redundancy group")
def step_then_refrain_not_redundancy(context):
    refrain = "it did not manage it"
    for group in context.diagnosis.get("repetition_groups", []):
        member_excerpts = [member.get("excerpt", "").strip().lower() for member in group.get("members", [])]
        if member_excerpts and all(refrain in excerpt for excerpt in member_excerpts):
            raise AssertionError(f"refrain was flagged as redundancy: {group}")


@given("a draft file and a loadable style profile")
def step_given_draft_and_profile(context):
    context.draft_path = FIXTURE_ROOT / "sloppy-draft.md"
    context.profile_path = FIXTURE_ROOT / "style-profile.yml"
    assert context.draft_path.is_file()
    assert context.profile_path.is_file()
    context.draft_snapshot = context.draft_path.read_bytes()


@when("I run the diagnose command")
def step_when_run_diagnose_command(context):
    completed = _run_diagnose_cli(context.draft_path, context.profile_path)
    context.cli_result = completed
    assert completed.returncode == 0, completed.stderr
    context.diagnosis = json.loads(completed.stdout)


@then(
    "it writes versioned JSON with document_intent, audience, generic_passages, unsupported_claims, repetition_groups, voice_observations, and required_facts"
)
def step_then_versioned_json_keys(context):
    diagnosis = context.diagnosis
    assert diagnosis["schemaVersion"] == 1
    for key in (
        "document_intent",
        "audience",
        "generic_passages",
        "unsupported_claims",
        "repetition_groups",
        "voice_observations",
        "required_facts",
    ):
        assert key in diagnosis


@then("each finding has a stable id")
def step_then_stable_ids(context):
    diagnosis = context.diagnosis
    ids = _collect_finding_ids(diagnosis)
    assert ids, "expected at least one finding id"
    for finding_id in ids:
        assert STABLE_ID_PATTERN.match(finding_id)

    rerun = _run_diagnose_cli(context.draft_path, context.profile_path)
    assert rerun.returncode == 0, rerun.stderr
    rerun_ids = _collect_finding_ids(json.loads(rerun.stdout))
    assert rerun_ids == ids


@then(
    "the findings cover vague claims, empty lead-ins, uniform cadence, list-shaped prose, unsupported certainty, redundancy, and voice mismatch"
)
def step_then_findings_cover_required_kinds(context):
    kinds = _collect_kinds(context.diagnosis)
    assert REQUIRED_KINDS.issubset(kinds), f"missing kinds: {sorted(REQUIRED_KINDS - kinds)}"


@then("the result does not include rewritten prose")
def step_then_no_rewritten_prose(context):
    _walk_forbidden_keys(context.diagnosis)


@then("the draft file is unchanged")
def step_then_draft_unchanged(context):
    assert context.draft_path.read_bytes() == context.draft_snapshot


@given("diagnostic JSON from a completed diagnose pass")
def step_given_diagnostic_json(context):
    if not getattr(context, "diagnosis", None):
        completed = _run_diagnose_cli(FIXTURE_ROOT / "sloppy-draft.md", FIXTURE_ROOT / "style-profile.yml")
        assert completed.returncode == 0, completed.stderr
        context.diagnosis = json.loads(completed.stdout)
    context.steering_decisions = []


@when("an operator or agent records skip, rewrite, delete, or keep against a finding id")
def step_when_record_decisions(context):
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))

    from papyrus_content.editorial_diagnosis import record_finding_decision

    finding_ids = _collect_finding_ids(context.diagnosis)
    assert len(finding_ids) >= 4, "need at least four findings for steering decisions"
    decisions = context.steering_decisions
    decisions = record_finding_decision(decisions, finding_ids[0], "skip", note="leave for now")
    decisions = record_finding_decision(decisions, finding_ids[1], "rewrite", note="needs options")
    decisions = record_finding_decision(decisions, finding_ids[2], "delete", note="cut repetition")
    decisions = record_finding_decision(decisions, finding_ids[3], "keep", note="acceptable")
    context.steering_decisions = decisions
    context.rewrite_finding_id = finding_ids[1]


@then("later option generation can address only the findings marked rewrite")
def step_then_only_rewrite_findings(context):
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))

    from papyrus_content.editorial_diagnosis import findings_marked_rewrite

    rewrite_findings = findings_marked_rewrite(context.diagnosis, context.steering_decisions)
    assert len(rewrite_findings) == 1
    assert rewrite_findings[0]["id"] == context.rewrite_finding_id
