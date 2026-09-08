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
ANTHUS_PROFILE_PATH = REPO_ROOT / "publications" / "anthus" / "style-profile.yml"
CORPUS_MANIFEST_PATH = REPO_ROOT / "publications" / "anthus" / "editorial-corpus" / "manifest.yml"
PROFILE_RULE_PREFIX = "Profile rule:"
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


def _run_diagnose_cli(
    profile_path: Path,
    *,
    draft_path: Path | None = None,
    text: str | None = None,
    output_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    if (draft_path is None) == (text is None):
        raise ValueError("exactly one of draft_path or text is required")

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{SRC_ROOT}:{REPO_ROOT}"
    env["PAPYRUS_ROOT"] = str(REPO_ROOT)
    command = [
        sys.executable,
        "-m",
        "papyrus.cli",
        "editorial",
        "diagnose",
        "--profile",
        str(profile_path),
    ]
    if draft_path is not None:
        command.extend(["--draft", str(draft_path)])
    else:
        command.extend(["--text", text])
    if output_path is not None:
        command.extend(["--output", str(output_path)])

    return subprocess.run(
        command,
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


def _profile_rule_findings(diagnosis: dict) -> list[dict]:
    return [
        finding
        for finding in _collect_all_findings(diagnosis)
        if str(finding.get("rationale", "")).startswith(PROFILE_RULE_PREFIX)
    ]


def _load_corpus_entry(kind: str, entry_id: str) -> dict:
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))

    from papyrus_content.editorial_corpus import load_editorial_corpus_manifest

    manifest = load_editorial_corpus_manifest(CORPUS_MANIFEST_PATH)
    entries = manifest["mustFail"] if kind == "mustFail" else manifest["mustPass"]
    for entry in entries:
        if entry["id"] == entry_id:
            return entry
    raise AssertionError(f"corpus entry not found: {kind}/{entry_id}")


@given('a style profile whose rules.bannedIntensifiers includes "seamless"')
def step_given_seamless_rules_profile(context):
    context.profile_path = FIXTURE_ROOT / "rules-seamless-profile.yml"
    assert context.profile_path.is_file()


@given('a draft that says "a seamless workflow for every team"')
def step_given_seamless_draft(context):
    context.draft_path = FIXTURE_ROOT / "seamless-draft.md"
    assert context.draft_path.is_file()


@given("the Anth.us style profile")
def step_given_anthus_style_profile(context):
    context.profile_path = ANTHUS_PROFILE_PATH
    assert context.profile_path.is_file()


@given('a draft that says "Check latency in the repository" and does not use banned intensifiers')
def step_given_engineering_vocab_draft(context):
    context.draft_path = FIXTURE_ROOT / "engineering-vocab-draft.md"
    assert context.draft_path.is_file()


@given('a must-fail corpus draft that uses "revolutionary" and "coming soon"')
def step_given_must_fail_corpus_draft(context):
    entry = _load_corpus_entry("mustFail", "brochure-hedges")
    context.draft_path = CORPUS_MANIFEST_PATH.parent / entry["path"]
    assert context.draft_path.is_file()


@given("a must-pass excerpt from an Anth.us reference sample")
def step_given_must_pass_corpus_excerpt(context):
    entry = _load_corpus_entry("mustPass", "latency-and-repo")
    context.draft_path = CORPUS_MANIFEST_PATH.parent / entry["path"]
    assert context.draft_path.is_file()


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
    completed = _run_diagnose_cli(context.profile_path, draft_path=context.draft_path)
    context.cli_result = completed
    assert completed.returncode == 0, completed.stderr
    context.diagnosis = json.loads(completed.stdout)


@when(
    'I run the diagnose command with --text "This seamless platform will revolutionize workflows" and no --draft'
)
def step_when_run_diagnose_with_text(context):
    completed = _run_diagnose_cli(
        context.profile_path,
        text="This seamless platform will revolutionize workflows",
    )
    context.cli_result = completed
    assert completed.returncode == 0, completed.stderr
    context.diagnosis = json.loads(completed.stdout)


@then('there is a finding whose excerpt includes "seamless"')
def step_then_finding_includes_seamless(context):
    excerpts = " ".join(finding.get("excerpt", "").lower() for finding in _collect_all_findings(context.diagnosis))
    assert "seamless" in excerpts


@then('there is no rules finding for "latency" or "repository"')
def step_then_no_rules_finding_for_engineering_vocab(context):
    for finding in _profile_rule_findings(context.diagnosis):
        excerpt = finding.get("excerpt", "").lower()
        assert "latency" not in excerpt
        assert "repository" not in excerpt
        assert "repo" not in excerpt


@then("findings include those banned terms")
def step_then_findings_include_banned_terms(context):
    excerpts = " ".join(finding.get("excerpt", "").lower() for finding in _collect_all_findings(context.diagnosis))
    assert "revolutionary" in excerpts
    assert "coming soon" in excerpts


@then("there are no findings produced by profile rules")
def step_then_no_profile_rule_findings(context):
    assert not _profile_rule_findings(context.diagnosis)


@then("it writes versioned diagnostic JSON")
def step_then_writes_versioned_json(context):
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

    rerun = _run_diagnose_cli(context.profile_path, draft_path=context.draft_path)
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
        completed = _run_diagnose_cli(
            FIXTURE_ROOT / "style-profile.yml",
            draft_path=FIXTURE_ROOT / "sloppy-draft.md",
        )
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
