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


class FakeProcedureClient:
    def __init__(self, definition: dict | None) -> None:
        self.definition = definition
        self.calls: list[tuple[str, dict]] = []
        self.update_inputs: list[dict] = []

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        variables = variables or {}
        self.calls.append((query, variables))
        if "getNewsroomProcedureDefinition" in query:
            return {"getNewsroomProcedureDefinition": self.definition}
        if "startNewsroomProcedureRun" in query:
            return {"startNewsroomProcedureRun": {"runId": "procedure-run-test-1"}}
        if "updateProcedureRun" in query:
            self.update_inputs.append(variables["input"])
            return {
                "updateProcedureRun": {
                    "id": variables["input"]["id"],
                    "runStatus": variables["input"]["runStatus"],
                    "output": variables["input"].get("output"),
                    "error": variables["input"].get("error"),
                }
            }
        raise AssertionError(f"Unexpected GraphQL query: {query}")


class CloudProcedureExecutionTests(unittest.TestCase):
    def test_missing_required_procedure_points_to_seed_command(self) -> None:
        client = FakeProcedureClient(None)
        with self.assertRaisesRegex(ValueError, "papyrus procedures seed-required --apply"):
            start_cloud_procedure_run(
                client=client,
                alias="assignments.run-research",
                actor_label="test",
                title="Run research",
                summary="summary",
                input_payload={"corpus_key": "AI-ML-research"},
            )

    def test_stale_source_points_to_seed_command(self) -> None:
        client = FakeProcedureClient({
            "id": "procedure-definition-newsroom-research-explorer",
            "procedureKey": "newsroom.research.explorer",
            "currentVersion": {
                "id": "procedure-version-newsroom-research-explorer-1",
                "versionNumber": 1,
                "tactusSource": "-- stale stub",
            },
        })
        with self.assertRaisesRegex(ValueError, "papyrus procedures seed-required --apply"):
            start_cloud_procedure_run(
                client=client,
                alias="assignments.run-research",
                actor_label="test",
                title="Run research",
                summary="summary",
                input_payload={"corpus_key": "AI-ML-research"},
            )

    def test_run_research_executes_cloud_source_and_updates_run_record(self) -> None:
        client = FakeProcedureClient({
            "id": "procedure-definition-newsroom-research-explorer",
            "procedureKey": "newsroom.research.explorer",
            "currentVersion": {
                "id": "procedure-version-newsroom-research-explorer-1",
                "versionNumber": 1,
                "tactusSource": "Procedure {\n  function(input)\n    return {}\n  end\n}\n",
            },
        })
        stdout = json.dumps({
            "assignment_item_id": "assignment-1",
            "corpus_key": "AI-ML-research",
            "dry_run": True,
            "item_status": "researched",
            "research_packet": {"summary": "Cloud research packet"},
            "research_record_plan": {},
            "summary": "Cloud research packet",
        })
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch("papyrus_content.cloud_procedures.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(args=["tactus"], returncode=0, stdout=stdout, stderr="")
            source_path = pathlib.Path(tmpdir) / "research.cloud.tac"
            result = start_cloud_procedure_run(
                client=client,
                alias="assignments.run-research",
                actor_label="test",
                title="Run research",
                summary="summary",
                input_payload={"assignment_item_id": "assignment-1", "corpus_key": "AI-ML-research"},
                run_dir=pathlib.Path(tmpdir),
                source_path=source_path,
                stdout_path=pathlib.Path(tmpdir) / "research.stdout.log",
                stderr_path=pathlib.Path(tmpdir) / "research.stderr.log",
            )

            self.assertEqual(result["runStatus"], "completed")
            self.assertTrue(source_path.read_text(encoding="utf-8").startswith("Procedure {"))
            self.assertEqual(run.call_args.args[0][0:2], ["tactus", "run"])
            self.assertEqual(run.call_args.args[0][2], str(source_path))
            self.assertEqual(result["output"]["source"], "ProcedureVersion.tactusSource")
            self.assertIn("research_packet", result["output"])
            self.assertEqual(json.loads(client.update_inputs[0]["output"])["mode"], "cli_tactus_source")
            self.assertEqual(result["llmContextCallCount"], 0)
            self.assertTrue(pathlib.Path(result["llmContextSummaryPath"]).exists())
            self.assertTrue(pathlib.Path(result["llmContextCallsPath"]).exists())

    def test_run_reporting_executes_cloud_source_and_updates_run_record(self) -> None:
        client = FakeProcedureClient({
            "id": "procedure-definition-newsroom-reporting-context",
            "procedureKey": "newsroom.reporting.context",
            "currentVersion": {
                "id": "procedure-version-newsroom-reporting-context-1",
                "versionNumber": 1,
                "tactusSource": "Procedure {\n  function(input)\n    return {}\n  end\n}\n",
            },
        })
        stdout = json.dumps({
            "assignment_item_id": "assignment-2",
            "dry_run": True,
            "item_status": "reported",
            "reporting_context_packet": {
                "summary": "Cloud reporting packet",
                "section_key": "news",
                "edition_id": "edition-2026-05-25-v1",
                "recommended_angle": "Reader impact.",
                "editor_recommendation": "hold",
                "coverage_gaps": [],
                "open_questions": [],
                "risk_flags": [],
                "accepted_reference_ids": [],
                "proposed_references": [],
                "copywriter_brief": "Use after editor selection.",
            },
            "summary": "Cloud reporting packet",
        })
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch("papyrus_content.cloud_procedures.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(args=["tactus"], returncode=0, stdout=stdout, stderr="")
            source_path = pathlib.Path(tmpdir) / "reporting.cloud.tac"
            result = start_cloud_procedure_run(
                client=client,
                alias="assignments.run-reporting",
                actor_label="test",
                title="Run reporting",
                summary="summary",
                input_payload={"assignment_item_id": "assignment-2", "corpus_key": "AI-ML-research"},
                run_dir=pathlib.Path(tmpdir),
                source_path=source_path,
                stdout_path=pathlib.Path(tmpdir) / "reporting.stdout.log",
                stderr_path=pathlib.Path(tmpdir) / "reporting.stderr.log",
            )

            self.assertEqual(result["runStatus"], "completed")
            self.assertEqual(run.call_args.args[0][0:2], ["tactus", "run"])
            self.assertEqual(run.call_args.args[0][2], str(source_path))
            self.assertIn("reporting_context_packet", result["output"])
            self.assertEqual(result["llmContextCallCount"], 0)
            self.assertTrue(pathlib.Path(result["llmContextSummaryPath"]).exists())
            self.assertTrue(pathlib.Path(result["llmContextCallsPath"]).exists())

    def test_run_research_extracts_execute_tactus_call_traces(self) -> None:
        client = FakeProcedureClient({
            "id": "procedure-definition-newsroom-research-explorer",
            "procedureKey": "newsroom.research.explorer",
            "currentVersion": {
                "id": "procedure-version-newsroom-research-explorer-1",
                "versionNumber": 1,
                "tactusSource": "Procedure {\n  function(input)\n    return {}\n  end\n}\n",
            },
        })
        stdout = "\n".join(
            [
                "Running procedure: research_explorer.tac (lua format)",
                "→ Agent newsroom_research_explorer: Waiting for response...",
                "→ Tool execute_tactus",
                "  Args: {",
                '  "harness": "raw",',
                '  "assignment_id": "assignment-1",',
                '  "corpus_key": "AI-ML-research",',
                '  "research_mode": "source_discovery",',
                '  "tactus": "local context = assignment_context{ id = \\"assignment-1\\" }"',
                "}",
                "  Result: {'ok': True, 'value': {'assignment_context': {}}}",
                json.dumps(
                    {
                        "assignment_item_id": "assignment-1",
                        "corpus_key": "AI-ML-research",
                        "dry_run": True,
                        "item_status": "researched",
                        "research_packet": {"summary": "Cloud research packet"},
                        "research_record_plan": {},
                        "summary": "Cloud research packet",
                    }
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch("papyrus_content.cloud_procedures.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(args=["tactus"], returncode=0, stdout=stdout, stderr="")
            source_path = pathlib.Path(tmpdir) / "research.cloud.tac"
            result = start_cloud_procedure_run(
                client=client,
                alias="assignments.run-research",
                actor_label="test",
                title="Run research",
                summary="summary",
                input_payload={"assignment_item_id": "assignment-1", "corpus_key": "AI-ML-research"},
                run_dir=pathlib.Path(tmpdir),
                source_path=source_path,
                stdout_path=pathlib.Path(tmpdir) / "research.stdout.log",
                stderr_path=pathlib.Path(tmpdir) / "research.stderr.log",
            )

            self.assertEqual(result["runStatus"], "completed")
            self.assertEqual(result["llmContextCallCount"], 1)
            self.assertEqual(result["llmContextLlmCallCount"], 0)
            summary = json.loads(pathlib.Path(result["llmContextSummaryPath"]).read_text(encoding="utf-8"))
            self.assertEqual(summary["executeTactusCallCount"], 1)
            self.assertEqual(summary["llmCallCount"], 0)
            self.assertEqual(summary["calls"][0]["agent"], "newsroom_research_explorer")
            calls = pathlib.Path(result["llmContextCallsPath"]).read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(calls), 1)
            first = json.loads(calls[0])
            self.assertEqual(first["assignmentId"], "assignment-1")
            self.assertEqual(first["harness"], "raw")
            self.assertIn("assignment_context", first["tactusSnippet"])

    def test_run_reporting_extracts_llm_message_history_and_lenient_execute_tactus_args(self) -> None:
        client = FakeProcedureClient({
            "id": "procedure-definition-newsroom-reporting-context",
            "procedureKey": "newsroom.reporting.context",
            "currentVersion": {
                "id": "procedure-version-newsroom-reporting-context-1",
                "versionNumber": 1,
                "tactusSource": "Procedure {\n  function(input)\n    return {}\n  end\n}\n",
            },
        })
        stdout = "\n".join(
            [
                "Running procedure: reporting.tac (lua format)",
                "→ Agent newsroom_reporter: Waiting for response...",
                "→ Tool execute_tactus",
                "  Args: {",
                '  "tactus": "local ctx = assignment_context{}',
                'return { ok = true }",',
                '  "harness": "raw",',
                '  "assignment_id": "assignment-1",',
                '  "corpus_key": "AI-ML-research",',
                '  "research_mode": "reporting"',
                "}",
                "  Result: {'ok': True, 'value': {'ok': True}}",
                json.dumps(
                    {
                        "assignment_item_id": "assignment-1",
                        "dry_run": True,
                        "item_status": "reported",
                        "reporting_context_packet": {
                            "summary": "Reporting packet",
                            "editor_recommendation": "hold",
                            "recommended_angle": "Angle",
                            "coverage_gaps": [],
                            "open_questions": [],
                            "risk_flags": [],
                            "accepted_reference_ids": [],
                            "proposed_references": [],
                            "source_trail": [],
                            "knowledge_queries": ["q1"],
                            "papyrus_uris_inspected": [],
                            "copywriter_brief": "brief",
                        },
                        "summary": "Reporting packet",
                    }
                ),
            ]
        )
        stderr = "\n".join(
            [
                "2026-05-27 00:10:52,799 DEBUG tactus.dspy.agent: Agent 'newsroom_reporter' turn 1",
                "2026-05-27 00:10:52,800 DEBUG tactus.dspy.module: [RAWMODULE] Passing 1 tools to LM with tool_choice=auto",
                "2026-05-27 00:10:52,801 DEBUG tactus.dspy.module: [RAWMODULE] LLM messages payload:",
                "[",
                '  {"role": "system", "content": "Reporter system prompt"},',
                '  {"role": "user", "content": "Build the reporting packet"}',
                "]",
            ]
        )
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch("papyrus_content.cloud_procedures.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(args=["tactus"], returncode=0, stdout=stdout, stderr=stderr)
            result = start_cloud_procedure_run(
                client=client,
                alias="assignments.run-reporting",
                actor_label="test",
                title="Run reporting",
                summary="summary",
                input_payload={"assignment_item_id": "assignment-1", "corpus_key": "AI-ML-research"},
                run_dir=pathlib.Path(tmpdir),
                source_path=pathlib.Path(tmpdir) / "reporting.cloud.tac",
                stdout_path=pathlib.Path(tmpdir) / "reporting.stdout.log",
                stderr_path=pathlib.Path(tmpdir) / "reporting.stderr.log",
            )

            self.assertEqual(result["runStatus"], "completed")
            self.assertEqual(result["llmContextCallCount"], 1)
            self.assertEqual(result["llmContextLlmCallCount"], 1)
            summary = json.loads(pathlib.Path(result["llmContextSummaryPath"]).read_text(encoding="utf-8"))
            self.assertEqual(summary["executeTactusCallCount"], 1)
            self.assertEqual(summary["llmCallCount"], 1)
            llm_calls_path = pathlib.Path(result["llmContextLlmCallsPath"])
            self.assertTrue(llm_calls_path.exists())
            llm_calls = llm_calls_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(llm_calls), 1)
            llm_first = json.loads(llm_calls[0])
            self.assertEqual(llm_first["agent"], "newsroom_reporter")
            self.assertEqual(llm_first["toolCount"], 1)
            self.assertEqual(llm_first["messageCount"], 2)
            self.assertEqual(llm_first["systemPrompt"], "Reporter system prompt")
            calls = pathlib.Path(result["llmContextCallsPath"]).read_text(encoding="utf-8").strip().splitlines()
            first = json.loads(calls[0])
            self.assertEqual(first["assignmentId"], "assignment-1")
            self.assertEqual(first["harness"], "raw")
            self.assertIn("assignment_context", first["tactusSnippet"])


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
            self.assertEqual(calls[0]["input_payload"]["assignment_json"]["assignmentTypeKey"], "research.edition-candidate")
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
