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

    def test_always_on_compounds_skip_unsupported_certainty(self) -> None:
        fixture_root = REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis"
        draft_text = (fixture_root / "always-on-compounds.md").read_text(encoding="utf-8")
        diagnosis = diagnose_draft(draft_text, style_profile=self.style_profile)
        certainty = [entry for entry in diagnosis["unsupported_claims"] if entry["kind"] == "unsupported_certainty"]
        self.assertEqual(certainty, [])

    def test_list_ordinals_skip_missing_attribution(self) -> None:
        fixture_root = REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis"
        draft_text = (fixture_root / "list-ordinals-only.md").read_text(encoding="utf-8")
        diagnosis = diagnose_draft(draft_text, style_profile=self.style_profile)
        self.assertEqual(diagnosis["required_facts"], [])

    def test_uniform_cadence_disabled_by_profile(self) -> None:
        fixture_root = REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis"
        draft_text = (fixture_root / "punchy-cadence.md").read_text(encoding="utf-8")
        profile = load_style_profile(fixture_root / "anthus-cadence-off-profile.yml")
        diagnosis = diagnose_draft(draft_text, style_profile=profile)
        cadence = [entry for entry in diagnosis["voice_observations"] if entry["kind"] == "uniform_cadence"]
        self.assertEqual(cadence, [])

    def test_brochure_slop_still_flags_certainty_and_lexicon(self) -> None:
        fixture_root = REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis"
        draft_text = (fixture_root / "brochure-slop.md").read_text(encoding="utf-8")
        diagnosis = diagnose_draft(draft_text, style_profile=self.style_profile)
        kinds = {entry["kind"] for entry in diagnosis["generic_passages"]}
        kinds.update(entry["kind"] for entry in diagnosis["unsupported_claims"])
        kinds.update(entry["kind"] for entry in diagnosis["voice_observations"])
        self.assertIn("unsupported_certainty", kinds)
        self.assertTrue("vague_claim" in kinds or "voice_mismatch" in kinds)

    def test_rhetorical_refrain_skips_redundancy(self) -> None:
        fixture_root = REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis"
        draft_text = (fixture_root / "rhetorical-refrain.md").read_text(encoding="utf-8")
        diagnosis = diagnose_draft(draft_text, style_profile=self.style_profile)
        refrain = "it did not manage it"
        for group in diagnosis["repetition_groups"]:
            excerpts = [member["excerpt"].strip().lower() for member in group["members"]]
            if excerpts and all(refrain in excerpt for excerpt in excerpts):
                self.fail(f"refrain flagged as redundancy: {group}")

    def test_sticker_number_skips_missing_attribution(self) -> None:
        draft_text = 'Think of a crate with an "Inspected By #247" sticker on the dock.'
        diagnosis = diagnose_draft(draft_text, style_profile=self.style_profile)
        self.assertEqual(diagnosis["required_facts"], [])

    def test_percent_claim_still_flags_missing_attribution(self) -> None:
        draft_text = "Our product reduces latency by 40% without any source attached."
        diagnosis = diagnose_draft(draft_text, style_profile=self.style_profile)
        attribution = [entry for entry in diagnosis["required_facts"] if entry["kind"] == "missing_attribution"]
        self.assertEqual(len(attribution), 1)

    def test_profile_checks_default_all_enabled(self) -> None:
        profile = load_style_profile(REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis" / "style-profile.yml")
        self.assertTrue(all(profile.profile.checks.values()))

    def test_anthus_profile_disables_uniform_cadence(self) -> None:
        profile = load_style_profile(REPO_ROOT / "publications" / "anthus" / "style-profile.yml")
        self.assertFalse(profile.profile.checks["uniformCadence"])


if __name__ == "__main__":
    unittest.main()
