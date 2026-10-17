from __future__ import annotations

import pathlib
import sys
import unittest
from unittest import mock

SRC_ROOT = pathlib.Path(__file__).resolve().parents[3] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_newsroom import coverage_theme, reference_curation_signals

COMPLETE_RESEARCH_PACKET = {
    "summary": "Cloud research",
    "recommended_angle": "Use the section lens.",
    "open_questions": [],
    "coverage_gaps": [],
}
COMPLETE_REPORTING_PACKET = {
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


def fake_cloud_run(research_packet: dict, reporting_packet: dict, calls: list[str]):
    def fake_start(**kwargs: object) -> dict:
        alias = str(kwargs["alias"])
        calls.append(alias)
        output_key, packet = (
            ("research_packet", research_packet) if alias == "story-cycle.research" else ("reporting_context_packet", reporting_packet)
        )
        return {
            "id": f"run-{len(calls)}",
            "procedureKey": alias,
            "procedureVersionId": "version",
            "procedureVersionNumber": 1,
            "runStatus": "completed",
            "output": {output_key: packet},
        }

    return fake_start


def run_theme(**overrides: object) -> dict:
    options = {
        "date": "2026-05-23",
        "topic": "Story cycle packet test",
        "corpus_key": "test-corpus",
        "category_key": "test-corpus",
        "coverage_key": "coverage.story.cycle.packets",
        "sections": ["arts"],
        "section_budgets": {"arts": 1},
        "run_id": "story-cycle-packets-test",
        "through": "reporting",
        "research_mode": "internal_brief",
        "now": "2026-05-23T10:00:00.000Z",
    }
    options.update(overrides)
    return coverage_theme.coverage_theme_run(**options)


class PacketValidationTests(unittest.TestCase):
    def test_empty_research_packet_fails_with_require_agent_success(self) -> None:
        calls: list[str] = []
        with mock.patch.object(coverage_theme, "_create_cloud_procedure_client", return_value=object()), \
             mock.patch.object(coverage_theme, "_start_cloud_procedure_run", side_effect=fake_cloud_run({"summary": "only a summary"}, COMPLETE_REPORTING_PACKET, calls)):
            result = run_theme(through="research", require_agent_success=True)

        self.assertFalse(result["ok"])
        self.assertIn("missing required keys", result["error"]["message"])

    def test_empty_reporting_packet_fails_with_require_agent_success(self) -> None:
        calls: list[str] = []
        with mock.patch.object(coverage_theme, "_create_cloud_procedure_client", return_value=object()), \
             mock.patch.object(coverage_theme, "_start_cloud_procedure_run", side_effect=fake_cloud_run(COMPLETE_RESEARCH_PACKET, {"summary": "only a summary"}, calls)):
            result = run_theme(require_agent_success=True)

        self.assertFalse(result["ok"])
        self.assertIn("Reporting packet", result["error"]["message"])
        self.assertIn("editor_recommendation", result["error"]["message"])

    def test_unknown_editor_recommendation_is_rejected(self) -> None:
        calls: list[str] = []
        packet = {**COMPLETE_REPORTING_PACKET, "editor_recommendation": "publish"}
        with mock.patch.object(coverage_theme, "_create_cloud_procedure_client", return_value=object()), \
             mock.patch.object(coverage_theme, "_start_cloud_procedure_run", side_effect=fake_cloud_run(COMPLETE_RESEARCH_PACKET, packet, calls)):
            result = run_theme()

        self.assertFalse(result["ok"])
        self.assertIn("editor_recommendation", result["error"]["message"])

    def test_empty_values_for_present_keys_are_accepted(self) -> None:
        calls: list[str] = []
        packet = {**COMPLETE_REPORTING_PACKET, "editor_recommendation": "hold", "copywriter_brief": ""}
        with mock.patch.object(coverage_theme, "_create_cloud_procedure_client", return_value=object()), \
             mock.patch.object(coverage_theme, "_start_cloud_procedure_run", side_effect=fake_cloud_run(COMPLETE_RESEARCH_PACKET, packet, calls)):
            result = run_theme()

        self.assertTrue(result["ok"])


class PersistedPacketReuseTests(unittest.TestCase):
    def _run_applied(self, calls: list[str], *, packets_persisted: bool, **overrides: object) -> dict:
        with mock.patch.object(coverage_theme, "_create_cloud_procedure_client", return_value=object()), \
             mock.patch.object(coverage_theme, "_start_cloud_procedure_run", side_effect=fake_cloud_run(COMPLETE_RESEARCH_PACKET, COMPLETE_REPORTING_PACKET, calls)), \
             mock.patch.object(coverage_theme, "load_live_state", return_value={}), \
             mock.patch.object(coverage_theme, "_packet_message_already_persisted", return_value=packets_persisted), \
             mock.patch.object(coverage_theme, "apply_records", return_value={"apply": True, "applied": [], "warnings": [], "failures": []}):
            return run_theme(apply=True, **overrides)

    def test_applied_rerun_with_persisted_packets_makes_no_agent_calls(self) -> None:
        calls: list[str] = []
        result = self._run_applied(calls, packets_persisted=True)

        self.assertTrue(result["ok"])
        self.assertEqual(calls, [])
        self.assertTrue(all(run["reusedPersistedPacket"] for run in result["researchRuns"]))
        self.assertTrue(all(run["reusedPersistedPacket"] for run in result["reportingRuns"]))
        packet_message_kinds = {"research_packet", "reporting_context_packet"}
        packet_records = [
            record
            for record in result["records"]
            if record["modelName"] == "Message" and record["input"].get("messageKind") in packet_message_kinds
        ]
        self.assertEqual(packet_records, [])

    def test_refresh_packets_regenerates_persisted_packets(self) -> None:
        calls: list[str] = []
        result = self._run_applied(calls, packets_persisted=True, refresh_packets=True)

        self.assertTrue(result["ok"])
        self.assertIn("story-cycle.research", calls)
        self.assertIn("story-cycle.reporting", calls)

    def test_first_applied_run_dispatches_agents(self) -> None:
        calls: list[str] = []
        result = self._run_applied(calls, packets_persisted=False)

        self.assertTrue(result["ok"])
        self.assertEqual(calls.count("story-cycle.research"), 1)
        self.assertGreaterEqual(calls.count("story-cycle.reporting"), 1)

    def test_dry_run_never_consults_persisted_state(self) -> None:
        calls: list[str] = []
        with mock.patch.object(coverage_theme, "_create_cloud_procedure_client", return_value=object()), \
             mock.patch.object(coverage_theme, "_start_cloud_procedure_run", side_effect=fake_cloud_run(COMPLETE_RESEARCH_PACKET, COMPLETE_REPORTING_PACKET, calls)), \
             mock.patch.object(coverage_theme, "_packet_message_already_persisted", side_effect=AssertionError("dry run must not read live state")):
            result = run_theme()

        self.assertTrue(result["ok"])
        self.assertIn("story-cycle.research", calls)


class ParallelDispatchTests(unittest.TestCase):
    def test_dispatch_preserves_input_order_with_parallel_workers(self) -> None:
        assignments = [{"id": f"assignment-{index}"} for index in range(6)]
        results = coverage_theme.run_packet_dispatch(assignments, lambda assignment: {"id": assignment["id"]}, 4)

        self.assertEqual([result["id"] for result in results], [assignment["id"] for assignment in assignments])

    def test_dispatch_never_exceeds_requested_parallelism(self) -> None:
        import threading

        active = 0
        peak = 0
        guard = threading.Lock()
        release = threading.Barrier(2, timeout=5)

        def produce(assignment: dict) -> dict:
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            try:
                release.wait()
            except threading.BrokenBarrierError:
                pass
            with guard:
                active -= 1
            return {"id": assignment["id"]}

        coverage_theme.run_packet_dispatch([{"id": str(index)} for index in range(4)], produce, 2)

        self.assertEqual(peak, 2)

    def test_sequential_dispatch_stops_at_first_error(self) -> None:
        seen: list[str] = []

        def produce(assignment: dict) -> dict:
            seen.append(assignment["id"])
            return {"ok": False} if assignment["id"] == "b" else {"ok": True}

        results = coverage_theme.run_packet_dispatch([{"id": "a"}, {"id": "b"}, {"id": "c"}], produce, 1)

        self.assertEqual(seen, ["a", "b"])
        self.assertEqual(len(results), 2)

    def test_max_parallel_flags_reach_the_dispatcher(self) -> None:
        calls: list[str] = []
        observed: list[int] = []
        real_dispatch = coverage_theme.run_packet_dispatch

        def spy(assignments, produce, max_parallel):
            observed.append(max_parallel)
            return real_dispatch(assignments, produce, max_parallel)

        with mock.patch.object(coverage_theme, "_create_cloud_procedure_client", return_value=object()), \
             mock.patch.object(coverage_theme, "_start_cloud_procedure_run", side_effect=fake_cloud_run(COMPLETE_RESEARCH_PACKET, COMPLETE_REPORTING_PACKET, calls)), \
             mock.patch.object(coverage_theme, "run_packet_dispatch", side_effect=spy):
            run_theme(max_parallel_research=3, max_parallel_reporting=5)

        self.assertEqual(observed, [3, 5])


class ApplyRecordsResumeTests(unittest.TestCase):
    def _records(self) -> list[dict]:
        return [
            {"modelName": "SemanticRelation", "action": "upsert", "input": {"id": "relation-1", "subjectId": "assignment-1", "objectId": "message-1"}},
            {"modelName": "ModelAttachment", "action": "upload", "input": {"id": "attachment-1", "ownerId": "message-1"}, "body": "text"},
            {"modelName": "Message", "action": "upsert", "input": {"id": "message-1"}},
        ]

    def test_records_apply_in_dependency_order(self) -> None:
        order: list[str] = []
        with mock.patch.object(coverage_theme, "_record_exists", return_value=False), \
             mock.patch.object(coverage_theme, "_create_record", side_effect=lambda model, payload: order.append(model)), \
             mock.patch.object(coverage_theme, "_upload_model_attachment", side_effect=lambda payload, body: order.append("ModelAttachment")):
            result = coverage_theme.apply_records(self._records())

        self.assertEqual(order, ["Message", "ModelAttachment", "SemanticRelation"])
        self.assertEqual(result["failures"], [])
        self.assertNotIn("ok", result)

    def test_failed_message_reports_failures_and_skips_dependents(self) -> None:
        def create(model: str, payload: dict) -> None:
            if model == "Message":
                raise RuntimeError("throttled")

        with mock.patch.object(coverage_theme, "_record_exists", return_value=False), \
             mock.patch.object(coverage_theme, "_create_record", side_effect=create), \
             mock.patch.object(coverage_theme, "_upload_model_attachment") as upload:
            result = coverage_theme.apply_records(self._records())

        upload.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual([failure["modelName"] for failure in result["failures"]], ["Message", "ModelAttachment", "SemanticRelation"])
        self.assertIn("throttled", result["failures"][0]["error"])
        self.assertEqual(len(result["warnings"]), 3)

    def test_rerun_after_partial_failure_resumes_without_duplicates(self) -> None:
        created: set[str] = {"message-1"}

        def exists(model: str, record_id: str) -> bool:
            return record_id in created

        def create(model: str, payload: dict) -> None:
            created.add(payload["id"])

        with mock.patch.object(coverage_theme, "_record_exists", side_effect=exists), \
             mock.patch.object(coverage_theme, "_create_record", side_effect=create) as create_record, \
             mock.patch.object(coverage_theme, "_update_record") as update_record, \
             mock.patch.object(coverage_theme, "_upload_model_attachment"):
            result = coverage_theme.apply_records(self._records())

        self.assertEqual(result["failures"], [])
        create_record.assert_called_once()
        self.assertEqual(create_record.call_args.args[0], "SemanticRelation")
        update_record.assert_called_once()

    def test_create_action_for_existing_record_is_skipped_not_failed(self) -> None:
        with mock.patch.object(coverage_theme, "_record_exists", return_value=True), \
             mock.patch.object(coverage_theme, "_create_record") as create_record:
            result = coverage_theme.apply_records([{"modelName": "Assignment", "action": "create", "input": {"id": "assignment-1"}}])

        create_record.assert_not_called()
        self.assertEqual(result["applied"][0]["action"], "exists")
        self.assertEqual(result["failures"], [])


class ReferenceListingPaginationTests(unittest.TestCase):
    def _pages(self, page_count: int, page_size: int):
        pages = []
        for page_index in range(page_count):
            items = [{"id": f"ref-{page_index}-{item}", "versionState": "current"} for item in range(page_size)]
            token = f"token-{page_index + 1}" if page_index < page_count - 1 else None
            pages.append({"listReferencesByCorpusAndExternalItem": {"items": items, "nextToken": token}})
        return pages

    def test_listing_without_limit_paginates_to_exhaustion(self) -> None:
        pages = self._pages(page_count=13, page_size=100)
        with mock.patch.object(reference_curation_signals, "execute_graphql", side_effect=pages):
            references = reference_curation_signals.list_references_by_corpus("corpus-1")

        self.assertEqual(len(references), 1300)

    def test_explicit_limit_still_bounds_the_listing(self) -> None:
        pages = self._pages(page_count=13, page_size=100)
        with mock.patch.object(reference_curation_signals, "execute_graphql", side_effect=pages):
            references = reference_curation_signals.list_references_by_corpus("corpus-1", limit=250)

        self.assertEqual(len(references), 300)


if __name__ == "__main__":
    unittest.main()
