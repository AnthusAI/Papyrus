from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.cloud_procedures import start_cloud_procedure_run
from papyrus_newsroom import coverage_theme


class CoverageThemeCloudProcedureTests(unittest.TestCase):
    def _run(self, **overrides: object) -> dict:
        options = {
            "date": "2026-05-23",
            "topic": "Cloud procedure test",
            "corpus_key": "AI-ML-research",
            "category_key": "AI-ML-research",
            "coverage_key": "coverage.cloud.procedure.test",
            "sections": ["arts"],
            "section_budgets": {"arts": 1},
            "run_id": "coverage-theme-cloud-test",
            "through": "reporting",
            "research_mode": "internal_brief",
            "allow_fallback": False,
            "require_agent_success": False,
            "refresh_packets": False,
            "apply": False,
            "now": "2026-05-23T10:00:00.000Z",
        }
        options.update(overrides)
        arts_section = {
            "id": "arts",
            "title": "Arts",
            "type": "canonical",
            "enabled": True,
            "sortOrder": 1,
            "editorialMission": "Creative workflows and player experience.",
        }
        with mock.patch.object(coverage_theme, "load_live_state", return_value={"newsroomSections": [arts_section]}):
            return coverage_theme.coverage_theme_run(**options)

    def test_coverage_theme_uses_cloud_procedure_aliases_by_default(self) -> None:
        calls: list[dict] = []

        def fake_start(**kwargs: object) -> dict:
            calls.append(dict(kwargs))
            alias = kwargs["alias"]
            if alias == "story-cycle.research":
                return {
                    "id": "procedure-run-research",
                    "procedureKey": "newsroom.research.explorer",
                    "procedureVersionId": "version-research",
                    "procedureVersionNumber": 1,
                    "runStatus": "completed",
                    "output": {
                        "research_packet": {
                            "summary": "Cloud research",
                            "recommended_angle": "Use the section lens.",
                            "open_questions": [],
                            "coverage_gaps": [],
                        }
                    },
                }
            if alias == "story-cycle.reporting":
                return {
                    "id": f"procedure-run-reporting-{len(calls)}",
                    "procedureKey": "newsroom.reporting.context",
                    "procedureVersionId": "version-reporting",
                    "procedureVersionNumber": 1,
                    "runStatus": "completed",
                    "output": {
                        "reporting_context_packet": {
                            "summary": "Cloud reporting",
                            "recommended_angle": "Reader impact",
                            "editor_recommendation": "brief",
                            "risk_flags": [],
                            "coverage_gaps": [],
                            "open_questions": [],
                            "accepted_reference_ids": [],
                            "proposed_references": [],
                            "copywriter_brief": "Use accepted references.",
                        }
                    },
                }
            raise AssertionError(f"Unexpected alias {alias}")

        with mock.patch.object(coverage_theme, "_create_cloud_procedure_client", return_value=object()), \
             mock.patch.object(coverage_theme, "_start_cloud_procedure_run", side_effect=fake_start):
            result = self._run()

            self.assertTrue(result["ok"])
            self.assertFalse(result["degraded"])
            self.assertEqual([call["alias"] for call in calls], [
                "story-cycle.research",
                "story-cycle.reporting",
                "story-cycle.reporting",
            ])
            self.assertEqual(calls[0]["input_payload"]["assignment_json"]["assignmentTypeKey"], "research.candidate")
            self.assertEqual(calls[1]["input_payload"]["source_research_packet_id"], result["researchRuns"][0]["messageId"])
            self.assertEqual(result["researchRuns"][0]["cloudProcedure"]["procedureKey"], "newsroom.research.explorer")
            self.assertEqual(result["reportingRuns"][0]["cloudProcedure"]["procedureKey"], "newsroom.reporting.context")

    def test_coverage_theme_fails_without_fallback_when_cloud_procedure_fails(self) -> None:
        with mock.patch.object(coverage_theme, "_create_cloud_procedure_client", return_value=object()), \
             mock.patch.object(coverage_theme, "_start_cloud_procedure_run", side_effect=ValueError("Missing required cloud procedure 'newsroom.research.explorer'. Run poetry run papyrus procedures seed-required --apply to preload standard procedures.")):
            result = self._run(through="research")

            self.assertFalse(result["ok"])
            self.assertEqual(result["error"]["code"], "cloud_procedure_failed")
            self.assertIn("papyrus procedures seed-required --apply", result["error"]["message"])

    def test_coverage_theme_uses_deterministic_packets_only_with_explicit_fallback(self) -> None:
        with mock.patch.object(coverage_theme, "_create_cloud_procedure_client", return_value=object()), \
             mock.patch.object(coverage_theme, "_start_cloud_procedure_run", side_effect=RuntimeError("cloud unavailable")):
            result = self._run(through="research", allow_fallback=True)

            self.assertTrue(result["ok"])
            self.assertTrue(result["degraded"])
            self.assertEqual(result["researchRuns"][0]["fallbackReason"], "deterministic_python_planner")


if __name__ == "__main__":
    unittest.main()
