from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from papyrus_content.editorial_diagnosis import diagnose_draft
from papyrus_content.editorial_markup import (
    EDITORIAL_ANNOTATION_NS,
    collect_findings_from_diagnosis,
    inject_markus_findings,
    render_annotated_markus,
    render_annotated_xml,
)
from papyrus_content.editorial_style import load_style_profile


class EditorialMarkupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile_path = (
            __import__("pathlib").Path(__file__).resolve().parents[3]
            / "publications"
            / "anthus"
            / "style-profile.yml"
        )
        self.profile = load_style_profile(self.profile_path)

    def test_collect_findings_includes_repetition_members(self) -> None:
        diagnosis = {
            "generic_passages": [
                {
                    "id": "finding-0123456789abcdef",
                    "kind": "empty_leadin",
                    "excerpt": "In today's world",
                    "span": {"start": 0, "end": 16},
                    "rationale": "Empty lead-in",
                }
            ],
            "unsupported_claims": [],
            "voice_observations": [],
            "required_facts": [],
            "repetition_groups": [
                {
                    "id": "finding-fedcba9876543210",
                    "kind": "redundancy",
                    "rationale": "Repeated phrase",
                    "members": [
                        {
                            "id": "finding-abcdef0123456789",
                            "kind": "redundancy",
                            "excerpt": "alpha beta",
                            "span": {"start": 20, "end": 30},
                            "rationale": "Repeated phrase",
                        }
                    ],
                }
            ],
        }
        findings = collect_findings_from_diagnosis(diagnosis)
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[1]["group_id"], "finding-fedcba9876543210")

    def test_render_markus_wraps_span_findings(self) -> None:
        draft = "Before flagged text after."
        findings = [
            {
                "id": "finding-0123456789abcdef",
                "kind": "voice_mismatch",
                "excerpt": "flagged text",
                "span": {"start": 7, "end": 19},
                "rationale": "Passive voice",
            }
        ]
        rendered = inject_markus_findings(draft, findings)
        self.assertIn(":::editorial-finding{", rendered)
        self.assertIn('id="finding-0123456789abcdef"', rendered)
        self.assertIn("flagged text", rendered)
        self.assertIn("Before ", rendered)
        self.assertIn(" after.", rendered)

    def test_document_level_finding_emits_leaf_directive(self) -> None:
        draft = "Short body."
        findings = [
            {
                "id": "finding-0123456789abcdef",
                "kind": "low_lexical_density",
                "excerpt": draft,
                "span": {"start": 0, "end": len(draft)},
                "rationale": "Low density",
            }
        ]
        rendered = inject_markus_findings(draft, findings)
        self.assertTrue(rendered.startswith("::editorial-finding{"))
        self.assertIn("Short body.", rendered)

    def test_render_xml_contains_namespace_and_findings(self) -> None:
        draft = "Everyone knows this is vague."
        diagnosis = diagnose_draft(draft, style_profile=self.profile)
        xml_text = render_annotated_xml(draft, diagnosis)
        root = ET.fromstring(xml_text)
        self.assertEqual(root.tag, f"{{{EDITORIAL_ANNOTATION_NS}}}editorialAnnotation")
        findings = root.find(f"{{{EDITORIAL_ANNOTATION_NS}}}findings")
        assert findings is not None
        self.assertGreater(len(list(findings)), 0)
        markus = root.find(f"{{{EDITORIAL_ANNOTATION_NS}}}markusAnnotated")
        assert markus is not None
        self.assertIn("editorial-finding", markus.text or "")

    def test_diagnose_to_markus_roundtrip_on_fixture(self) -> None:
        draft = "In today's fast-moving world, it is important to note that teams leverage synergies."
        diagnosis = diagnose_draft(draft, style_profile=self.profile)
        markus = render_annotated_markus(draft, diagnosis)
        self.assertIn("editorial-finding", markus)


if __name__ == "__main__":
    unittest.main()
