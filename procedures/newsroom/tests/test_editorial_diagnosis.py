import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.editorial_corpus import load_editorial_corpus_manifest
from papyrus_content.editorial_diagnosis import (
    PROFILE_RULE_PREFIX,
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

    def test_jsx_citation_boilerplate_skips_redundancy(self) -> None:
        # Self-closing MDX components like <Citation data={{...}}/> repeat the same field
        # names (container-title, accessed, date-parts, issued...) across every citation in
        # a piece. Before masking JSX out of the shingle check, that shared boilerplate got
        # reported as "repeated phrasing" even though the actual prose has nothing in common.
        draft_text = (
            "A March 2026 paper gives a better way to measure this.<Citation\n"
            "data={{\n"
            '    type: "article-journal",\n'
            '    title: "The Price of Progress",\n'
            '    "container-title": "arXiv",\n'
            '    URL: "https://arxiv.org/abs/1",\n'
            "    accessed: { 'date-parts': [[2026, 8, 16]] },\n"
            "    issued: { 'date-parts': [[2025, 11]] }\n"
            "  }}\n"
            "/> The authors combine historical inference-price data with benchmark token use.\n\n"
            "A June 2026 benchmark reports dollars per resolved task, not list price.<Citation\n"
            "data={{\n"
            '    type: "article-journal",\n'
            '    title: "A Benchmark for Dialogue-Driven Coding Agents",\n'
            '    "container-title": "arXiv",\n'
            '    URL: "https://arxiv.org/abs/2",\n'
            "    accessed: { 'date-parts': [[2026, 8, 16]] },\n"
            "    issued: { 'date-parts': [[2026, 6]] }\n"
            "  }}\n"
            "/> That's much closer to what you actually pay.\n"
        )
        diagnosis = diagnose_draft(draft_text, style_profile=self.style_profile)
        self.assertEqual(diagnosis["repetition_groups"], [])

    def test_jsx_masking_preserves_real_redundancy_spans(self) -> None:
        # The masking fix must not swallow genuine repeated prose sitting next to JSX.
        draft_text = (
            "At the same time, agents got much better at staying on task for hours.<Citation\n"
            'data={{ type: "article-journal", title: "A", URL: "https://a" }}\n'
            "/> That changed everything.\n\n"
            "Meanwhile, at the same time, agents got much better at staying on task for hours "
            "in production settings too.\n"
        )
        diagnosis = diagnose_draft(draft_text, style_profile=self.style_profile)
        self.assertTrue(diagnosis["repetition_groups"])
        excerpt = diagnosis["repetition_groups"][0]["members"][0]["excerpt"]
        span = diagnosis["repetition_groups"][0]["members"][0]["span"]
        self.assertEqual(draft_text[span["start"] : span["end"]], excerpt)

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

    def test_rules_omitted_is_noop(self) -> None:
        fixture_root = REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis"
        profile = load_style_profile(fixture_root / "style-profile.yml")
        self.assertEqual(profile.profile.rules.banned_phrases, ())
        self.assertEqual(profile.profile.rules.banned_intensifiers, ())
        self.assertIsNone(profile.profile.rules.contrast_cap)

    def test_banned_intensifier_from_profile_rules(self) -> None:
        fixture_root = REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis"
        profile = load_style_profile(fixture_root / "rules-seamless-profile.yml")
        draft_text = (fixture_root / "seamless-draft.md").read_text(encoding="utf-8")
        diagnosis = diagnose_draft(draft_text, style_profile=profile)
        excerpts = " ".join(entry["excerpt"].lower() for entry in diagnosis["generic_passages"])
        self.assertIn("seamless", excerpts)
        self.assertTrue(
            any(entry["rationale"].startswith(PROFILE_RULE_PREFIX) for entry in diagnosis["generic_passages"])
        )

    def test_lexicon_avoid_dedup_skips_duplicate_rules_finding(self) -> None:
        profile = load_style_profile(REPO_ROOT / "publications" / "anthus" / "style-profile.yml")
        draft_text = "This game-changing release will ship next week."
        diagnosis = diagnose_draft(draft_text, style_profile=profile)
        game_changing_findings = [
            entry
            for entry in diagnosis["generic_passages"] + diagnosis["voice_observations"]
            if "game-changing" in entry["excerpt"].lower()
        ]
        self.assertGreaterEqual(len(game_changing_findings), 1)
        self.assertFalse(
            any(entry["rationale"].startswith(PROFILE_RULE_PREFIX) for entry in game_changing_findings)
        )

    def test_anthus_profile_has_brochure_rules_seed(self) -> None:
        profile = load_style_profile(REPO_ROOT / "publications" / "anthus" / "style-profile.yml")
        self.assertIn("coming soon", profile.profile.rules.banned_phrases)
        self.assertIn("seamless", profile.profile.rules.banned_intensifiers)
        self.assertNotIn("powerful", profile.profile.rules.banned_intensifiers)
        self.assertNotIn("robust", profile.profile.rules.banned_intensifiers)
        self.assertIsNone(profile.profile.rules.contrast_cap)

    def test_contrast_cap_disabled_for_anthus_house_voice(self) -> None:
        profile = load_style_profile(REPO_ROOT / "publications" / "anthus" / "style-profile.yml")
        draft_text = "Pick the economical choice, not the premium lane."
        diagnosis = diagnose_draft(draft_text, style_profile=profile)
        profile_rules = [
            entry
            for entry in diagnosis["voice_observations"]
            if entry["rationale"].startswith(PROFILE_RULE_PREFIX)
        ]
        self.assertEqual(profile_rules, [])

    def test_contrast_cap_emits_profile_rule_when_enabled(self) -> None:
        fixture_root = REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis"
        profile = load_style_profile(fixture_root / "rules-contrast-cap-profile.yml")
        draft_text = "Fast, not slow, and cheap, not costly."
        diagnosis = diagnose_draft(draft_text, style_profile=profile)
        profile_rules = [
            entry
            for entry in diagnosis["voice_observations"]
            if entry["rationale"].startswith(PROFILE_RULE_PREFIX)
        ]
        self.assertEqual(len(profile_rules), 1)

    def test_corpus_must_fail_terms_are_caught(self) -> None:
        manifest = load_editorial_corpus_manifest(
            REPO_ROOT / "publications" / "anthus" / "editorial-corpus" / "manifest.yml"
        )
        profile = load_style_profile(REPO_ROOT / "publications" / "anthus" / "style-profile.yml")
        entry = manifest["mustFail"][0]
        draft_path = REPO_ROOT / "publications" / "anthus" / "editorial-corpus" / entry["path"]
        diagnosis = diagnose_draft(draft_path.read_text(encoding="utf-8"), style_profile=profile)
        excerpts = " ".join(
            finding["excerpt"].lower()
            for finding in diagnosis["generic_passages"] + diagnosis["voice_observations"]
        )
        for term in entry["expectTerms"]:
            self.assertIn(term.lower(), excerpts)

    def test_corpus_must_pass_has_no_profile_rule_findings(self) -> None:
        manifest = load_editorial_corpus_manifest(
            REPO_ROOT / "publications" / "anthus" / "editorial-corpus" / "manifest.yml"
        )
        profile = load_style_profile(REPO_ROOT / "publications" / "anthus" / "style-profile.yml")
        for entry in manifest["mustPass"]:
            draft_path = REPO_ROOT / "publications" / "anthus" / "editorial-corpus" / entry["path"]
            diagnosis = diagnose_draft(draft_path.read_text(encoding="utf-8"), style_profile=profile)
            profile_rules = [
                finding
                for finding in diagnosis["generic_passages"] + diagnosis["voice_observations"]
                if finding["rationale"].startswith(PROFILE_RULE_PREFIX)
            ]
            self.assertEqual(profile_rules, [], entry["id"])

    def test_engineering_vocabulary_is_not_flagged_by_profile_rules(self) -> None:
        fixture_root = REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis"
        profile = load_style_profile(REPO_ROOT / "publications" / "anthus" / "style-profile.yml")
        draft_text = (fixture_root / "engineering-vocab-draft.md").read_text(encoding="utf-8")
        diagnosis = diagnose_draft(draft_text, style_profile=profile)
        profile_rules = [
            finding
            for finding in diagnosis["generic_passages"] + diagnosis["voice_observations"]
            if finding["rationale"].startswith(PROFILE_RULE_PREFIX)
        ]
        self.assertEqual(profile_rules, [])

    def test_information_density_check_default_enabled(self) -> None:
        profile = load_style_profile(
            REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis" / "style-profile.yml"
        )
        self.assertTrue(profile.profile.checks["informationDensity"])

    def test_diagnose_includes_density_summary_when_enabled(self) -> None:
        fixture_root = REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis"
        profile = load_style_profile(fixture_root / "density-enabled-profile.yml")
        draft_text = (fixture_root / "density-summary-draft.md").read_text(encoding="utf-8")
        diagnosis = diagnose_draft(draft_text, style_profile=profile)
        density = diagnosis.get("density")
        self.assertIsInstance(density, dict)
        for key in ("wordCount", "sentenceCount", "lexicalDensity", "gzipRatio"):
            self.assertIn(key, density)
        self.assertNotIn("embedder", diagnosis)

    def test_long_fluff_adds_density_findings(self) -> None:
        fixture_root = REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis"
        profile = load_style_profile(fixture_root / "density-enabled-profile.yml")
        draft_text = (fixture_root / "low-density-fluff.md").read_text(encoding="utf-8")
        diagnosis = diagnose_draft(draft_text, style_profile=profile)
        kinds = {entry["kind"] for entry in diagnosis["generic_passages"]}
        self.assertTrue({"low_lexical_density", "high_compressibility"} & kinds)

    def test_short_draft_skips_density_findings(self) -> None:
        fixture_root = REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis"
        profile = load_style_profile(fixture_root / "density-enabled-profile.yml")
        draft_text = (fixture_root / "short-density-draft.md").read_text(encoding="utf-8")
        diagnosis = diagnose_draft(draft_text, style_profile=profile)
        kinds = {entry["kind"] for entry in diagnosis["generic_passages"]}
        self.assertNotIn("low_lexical_density", kinds)
        self.assertNotIn("high_compressibility", kinds)

    def test_anthus_profile_has_density_thresholds(self) -> None:
        profile = load_style_profile(REPO_ROOT / "publications" / "anthus" / "style-profile.yml")
        self.assertEqual(profile.profile.density.min_words, 400)
        self.assertEqual(profile.profile.density.min_lexical_density, 0.45)
        self.assertEqual(profile.profile.density.max_gzip_ratio, 0.35)


if __name__ == "__main__":
    unittest.main()
