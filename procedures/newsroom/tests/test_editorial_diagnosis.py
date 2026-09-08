import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.editorial_diagnosis import (
    diagnose_draft,
    findings_marked_rewrite,
    record_finding_decision,
)
from papyrus_content.editorial_diagnosis_schema import (
    EditorialDiagnosisValidationError,
    stable_finding_id as schema_stable_finding_id,
    validate_diagnosis,
)
from papyrus_content.editorial_style import load_style_profile


class EditorialDiagnosisTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture_root = REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis"
        self.draft_text = (fixture_root / "sloppy-draft.md").read_text(encoding="utf-8")
        self.style_profile = load_style_profile(fixture_root / "style-profile.yml")

    def test_stable_finding_id_is_deterministic(self) -> None:
        first = schema_stable_finding_id("vague_claim", "sample text", 0, 6)
        second = schema_stable_finding_id("vague_claim", "sample text", 0, 6)
        self.assertEqual(first, second)
        self.assertRegex(first, r"^finding-[a-f0-9]{16}$")

    def test_diagnose_draft_returns_required_keys(self) -> None:
        diagnosis = diagnose_draft(self.draft_text, style_profile=self.style_profile)
        self.assertEqual(diagnosis["schemaVersion"], 1)
        self.assertTrue(diagnosis["document_intent"])
        self.assertEqual(diagnosis["audience"], self.style_profile.profile.audience)
        for key in (
            "generic_passages",
            "unsupported_claims",
            "repetition_groups",
            "voice_observations",
            "required_facts",
        ):
            self.assertIsInstance(diagnosis[key], list)

    def test_diagnose_draft_covers_required_kinds(self) -> None:
        diagnosis = diagnose_draft(self.draft_text, style_profile=self.style_profile)
        kinds = {entry["kind"] for entry in diagnosis["generic_passages"]}
        kinds.update(entry["kind"] for entry in diagnosis["unsupported_claims"])
        kinds.update(entry["kind"] for entry in diagnosis["voice_observations"])
        kinds.update(group["kind"] for group in diagnosis["repetition_groups"])
        required = {
            "vague_claim",
            "empty_leadin",
            "uniform_cadence",
            "list_shaped_prose",
            "unsupported_certainty",
            "redundancy",
            "voice_mismatch",
        }
        self.assertTrue(required.issubset(kinds))

    def test_validate_diagnosis_rejects_rewrite_fields(self) -> None:
        diagnosis = diagnose_draft(self.draft_text, style_profile=self.style_profile)
        diagnosis["revised_text"] = "rewritten"
        with self.assertRaises(EditorialDiagnosisValidationError):
            validate_diagnosis(diagnosis)

    def test_findings_marked_rewrite_filters_decisions(self) -> None:
        diagnosis = diagnose_draft(self.draft_text, style_profile=self.style_profile)
        finding_id = diagnosis["generic_passages"][0]["id"]
        decisions = record_finding_decision([], finding_id, "rewrite")
        decisions = record_finding_decision(decisions, diagnosis["unsupported_claims"][0]["id"], "skip")
        rewrite_findings = findings_marked_rewrite(diagnosis, decisions)
        self.assertEqual(len(rewrite_findings), 1)
        self.assertEqual(rewrite_findings[0]["id"], finding_id)


if __name__ == "__main__":
    unittest.main()
