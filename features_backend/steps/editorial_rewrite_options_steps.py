from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
FIXTURE_ROOT = REPO_ROOT / "features_backend" / "fixtures" / "editorial-options"
STYLE_PROFILE_PATH = REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis" / "style-profile.yml"
SKILL_PATH = REPO_ROOT / "publications" / "anthus" / "editorial-rewrite-skill.yml"


class FakeOptionsResolver:
    def __init__(self, *, include_evasion: bool = False) -> None:
        self.include_evasion = include_evasion

    def __call__(
        self,
        *,
        draft_text: str,
        finding: dict,
        style_profile,
        skill,
        model: str,
    ) -> list[dict]:
        span = finding["span"]
        kind = finding["kind"]
        if kind == "empty_leadin":
            return [
                {
                    "patch": {"span": span, "replacement": ""},
                    "reason": "Delete the empty lead-in and open with the next concrete sentence.",
                    "factVerificationRequired": False,
                    "unresolvedQuestions": [],
                },
                {
                    "patch": {
                        "span": span,
                        "replacement": "Teams are rethinking how they ship agent workflows.",
                    },
                    "reason": "Replace boilerplate with a concrete opening stake.",
                    "factVerificationRequired": False,
                    "unresolvedQuestions": [],
                },
            ]
        if self.include_evasion:
            return [
                {
                    "patch": {"span": span, "replacement": "lol this is kinda transformative tbh"},
                    "reason": "Add slang to sound human.",
                    "factVerificationRequired": False,
                    "unresolvedQuestions": [],
                },
                {
                    "patch": {"span": span, "replacement": "Teams can verify latency tradeoffs directly."},
                    "reason": "Use operational language aligned with the profile.",
                    "factVerificationRequired": False,
                    "unresolvedQuestions": [],
                },
            ]
        return [
            {
                "patch": {"span": span, "replacement": "Teams can verify latency tradeoffs directly."},
                "reason": "Replace vague transformation language with an operational check.",
                "factVerificationRequired": False,
                "unresolvedQuestions": [],
            },
            {
                "patch": {"span": span, "replacement": "The claim needs attributable evidence before publication."},
                "reason": "Flag the unsupported certainty instead of restating hype.",
                "factVerificationRequired": True,
                "unresolvedQuestions": ["Which source supports the original claim?"],
            },
        ]


def _import_rewrite_modules():
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    from papyrus_content.editorial_diagnosis import findings_marked_rewrite, record_finding_decision
    from papyrus_content.editorial_options_schema import stable_option_id
    from papyrus_content.editorial_rewrite_options import (
        generate_rewrite_options,
        load_rewrite_skill,
        options_contain_evasion_tactics,
    )
    from papyrus_content.editorial_style import load_style_profile

    return {
        "findings_marked_rewrite": findings_marked_rewrite,
        "record_finding_decision": record_finding_decision,
        "stable_option_id": stable_option_id,
        "generate_rewrite_options": generate_rewrite_options,
        "load_rewrite_skill": load_rewrite_skill,
        "options_contain_evasion_tactics": options_contain_evasion_tactics,
        "load_style_profile": load_style_profile,
    }


@given("a draft file, style profile, diagnosis, and mixed steering decisions")
def step_given_mixed_fixture_bundle(context):
    context.draft_path = FIXTURE_ROOT / "article.md"
    context.draft_snapshot = context.draft_path.read_bytes()
    context.draft_text = context.draft_path.read_text(encoding="utf-8")
    context.style_profile_path = STYLE_PROFILE_PATH
    context.diagnosis = json.loads((FIXTURE_ROOT / "diagnosis.json").read_text(encoding="utf-8"))
    context.decisions = json.loads((FIXTURE_ROOT / "decisions.json").read_text(encoding="utf-8"))
    context.skill = _import_rewrite_modules()["load_rewrite_skill"](SKILL_PATH)


@when("rewrite options are generated for findings marked rewrite")
def step_when_generate_options_for_rewrite(context):
    modules = _import_rewrite_modules()
    style_profile = modules["load_style_profile"](context.style_profile_path)
    context.options_payload = modules["generate_rewrite_options"](
        context.draft_text,
        style_profile=style_profile,
        diagnosis=context.diagnosis,
        decisions=context.decisions,
        skill_path=SKILL_PATH,
        llm_resolver=FakeOptionsResolver(),
    )
    context.rewrite_finding_ids = [
        finding["id"]
        for finding in modules["findings_marked_rewrite"](context.diagnosis, context.decisions)
    ]


@then("options exist only for findings marked rewrite")
def step_then_options_only_for_rewrite(context):
    option_finding_ids = [entry["findingId"] for entry in context.options_payload["findings"]]
    assert option_finding_ids == context.rewrite_finding_ids
    latest_decisions: dict[str, str] = {}
    for entry in context.decisions:
        latest_decisions[entry["finding_id"]] = entry["decision"]
    skipped_ids = {
        finding_id
        for finding_id, decision in latest_decisions.items()
        if decision != "rewrite"
    }
    assert not any(finding_id in skipped_ids for finding_id in option_finding_ids)


@then("the skill constraints forbid evasion tactics")
def step_then_skill_forbids_evasion(context):
    modules = _import_rewrite_modules()
    skill_text = " ".join(context.skill.constraints).lower()
    assert "fake typos" in skill_text or "manufactured imperfections" in skill_text
    assert not modules["options_contain_evasion_tactics"](context.options_payload)


@given("an empty lead-in finding marked for rewrite")
def step_given_empty_leadin_rewrite(context):
    context.draft_path = FIXTURE_ROOT / "article.md"
    context.draft_snapshot = context.draft_path.read_bytes()
    context.draft_text = context.draft_path.read_text(encoding="utf-8")
    context.style_profile_path = STYLE_PROFILE_PATH
    context.diagnosis = json.loads((FIXTURE_ROOT / "diagnosis.json").read_text(encoding="utf-8"))
    context.decisions = json.loads(
        (FIXTURE_ROOT / "empty-leadin-decisions.json").read_text(encoding="utf-8")
    )


@when("rewrite options are generated")
def step_when_generate_options(context):
    modules = _import_rewrite_modules()
    style_profile = modules["load_style_profile"](context.style_profile_path)
    context.options_payload = modules["generate_rewrite_options"](
        context.draft_text,
        style_profile=style_profile,
        diagnosis=context.diagnosis,
        decisions=context.decisions,
        skill_path=SKILL_PATH,
        llm_resolver=FakeOptionsResolver(),
    )


@then("at least one option uses empty or minimal replacement")
def step_then_has_deletion_option(context):
    finding_entry = context.options_payload["findings"][0]
    replacements = [option["patch"]["replacement"] for option in finding_entry["options"]]
    assert any(not replacement.strip() for replacement in replacements)
