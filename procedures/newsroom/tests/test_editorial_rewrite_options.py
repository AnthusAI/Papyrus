import json
import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.editorial_diagnosis import diagnose_draft, record_finding_decision
from papyrus_content.editorial_options_schema import (
    EditorialOptionsValidationError,
    stable_option_id,
    validate_decisions,
    validate_options,
)
from papyrus_content.editorial_rewrite_options import (
    generate_rewrite_options,
    load_rewrite_skill,
    options_contain_evasion_tactics,
)
from papyrus_content.editorial_style import load_style_profile


class FakeOptionsResolver:
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
        if finding.get("kind") == "empty_leadin":
            return [
                {
                    "patch": {"span": span, "replacement": ""},
                    "reason": "Delete the empty lead-in.",
                    "factVerificationRequired": False,
                    "unresolvedQuestions": [],
                },
                {
                    "patch": {"span": span, "replacement": "Engineering teams are evaluating agent workflows."},
                    "reason": "Open with a concrete stake.",
                    "factVerificationRequired": False,
                    "unresolvedQuestions": [],
                },
            ]
        return [
            {
                "patch": {"span": span, "replacement": "Teams can verify latency tradeoffs directly."},
                "reason": "Use operational language aligned with the profile.",
                "factVerificationRequired": False,
                "unresolvedQuestions": [],
            },
            {
                "patch": {"span": span, "replacement": "The claim needs attributable evidence before publication."},
                "reason": "Flag unsupported certainty instead of restating hype.",
                "factVerificationRequired": True,
                "unresolvedQuestions": ["Which source supports the original claim?"],
            },
        ]


class EditorialRewriteOptionsTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture_root = REPO_ROOT / "features_backend" / "fixtures" / "editorial-options"
        self.draft_text = (fixture_root / "article.md").read_text(encoding="utf-8")
        self.diagnosis = json.loads((fixture_root / "diagnosis.json").read_text(encoding="utf-8"))
        self.decisions = json.loads((fixture_root / "decisions.json").read_text(encoding="utf-8"))
        self.style_profile = load_style_profile(
            REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis" / "style-profile.yml"
        )
        self.skill_path = REPO_ROOT / "publications" / "anthus" / "editorial-rewrite-skill.yml"

    def test_stable_option_id_is_deterministic(self) -> None:
        first = stable_option_id("finding-abc", "replacement", "reason")
        second = stable_option_id("finding-abc", "replacement", "reason")
        self.assertEqual(first, second)
        self.assertRegex(first, r"^option-[a-f0-9]{16}$")

    def test_validate_decisions_rejects_invalid_decision(self) -> None:
        with self.assertRaises(EditorialOptionsValidationError):
            validate_decisions(
                [
                    {
                        "schemaVersion": 1,
                        "finding_id": "finding-abc1234567890ab",
                        "decision": "maybe",
                    }
                ]
            )

    def test_generate_rewrite_options_only_for_marked_findings(self) -> None:
        options = generate_rewrite_options(
            self.draft_text,
            style_profile=self.style_profile,
            diagnosis=self.diagnosis,
            decisions=self.decisions,
            skill_path=self.skill_path,
            llm_resolver=FakeOptionsResolver(),
        )
        rewrite_ids = {
            entry["finding_id"]
            for entry in self.decisions
            if entry.get("decision") == "rewrite"
        }
        option_ids = {entry["findingId"] for entry in options["findings"]}
        self.assertEqual(option_ids, rewrite_ids)
        self.assertNotIn("revised_text", json.dumps(options))

    def test_empty_leadin_includes_deletion_option(self) -> None:
        fixture_root = REPO_ROOT / "features_backend" / "fixtures" / "editorial-options"
        decisions = json.loads((fixture_root / "empty-leadin-decisions.json").read_text(encoding="utf-8"))
        options = generate_rewrite_options(
            self.draft_text,
            style_profile=self.style_profile,
            diagnosis=self.diagnosis,
            decisions=decisions,
            skill_path=self.skill_path,
            llm_resolver=FakeOptionsResolver(),
        )
        replacements = [
            option["patch"]["replacement"]
            for entry in options["findings"]
            for option in entry["options"]
        ]
        self.assertTrue(any(not replacement.strip() for replacement in replacements))

    def test_validate_options_rejects_revised_text(self) -> None:
        payload = {
            "schemaVersion": 1,
            "findings": [],
            "revised_text": "whole draft rewrite",
        }
        with self.assertRaises(EditorialOptionsValidationError):
            validate_options(payload)

    def test_rewrite_skill_loads_constraints(self) -> None:
        skill = load_rewrite_skill(self.skill_path)
        combined = " ".join(skill.constraints).lower()
        self.assertIn("do not invent anecdotes", combined)
        self.assertIn("prefer deletion", combined)

    def test_options_contain_evasion_tactics_detects_slang(self) -> None:
        diagnosis = diagnose_draft(self.draft_text, style_profile=self.style_profile)
        finding = diagnosis["generic_passages"][0]
        decisions = record_finding_decision([], finding["id"], "rewrite")

        class EvasiveResolver(FakeOptionsResolver):
            def __call__(self, **kwargs):
                span = kwargs["finding"]["span"]
                return [
                    {
                        "patch": {"span": span, "replacement": "lol kinda transformative tbh"},
                        "reason": "Add slang.",
                        "factVerificationRequired": False,
                        "unresolvedQuestions": [],
                    },
                    {
                        "patch": {"span": span, "replacement": "Concrete operational wording."},
                        "reason": "Stay precise.",
                        "factVerificationRequired": False,
                        "unresolvedQuestions": [],
                    },
                ]

        options = generate_rewrite_options(
            self.draft_text,
            style_profile=self.style_profile,
            diagnosis=diagnosis,
            decisions=decisions,
            skill_path=self.skill_path,
            llm_resolver=EvasiveResolver(),
        )
        self.assertTrue(options_contain_evasion_tactics(options))


if __name__ == "__main__":
    unittest.main()
