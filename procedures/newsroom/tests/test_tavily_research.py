import json
import os
import unittest
from unittest import mock

from papyrus_newsroom import tavily_research
from papyrus_content.catalog import message_record
from papyrus_content.model_attachments import expand_private_payload_records
from papyrus_content.insight_forum import (
    INSIGHT_FORUM_TITLE_MAX_LEN,
    derive_insight_forum_title,
    format_tavily_insight_message_body,
    insight_summary_needs_title_repair,
)
from papyrus_content.tavily_deep_research import (
    TAVILY_DEEP_ASSIGNMENT_TYPE,
    build_research_packet_from_tavily_completed,
    is_tavily_deep_assignment,
    tavily_research_input_for_assignment,
)


class TavilyResearchApiTests(unittest.TestCase):
    @mock.patch("urllib.request.urlopen")
    def test_create_research_task(self, urlopen):
        body = json.dumps(
            {
                "request_id": "req-123",
                "status": "pending",
                "input": "robotics",
                "model": "auto",
            }
        ).encode("utf-8")
        urlopen.return_value.__enter__.return_value.read.return_value = body
        urlopen.return_value.__enter__.return_value.status = 201
        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test"}, clear=False):
            payload = tavily_research.create_tavily_research_task(input_text="robotics", model="auto")
        self.assertEqual(payload["request_id"], "req-123")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_full_url(), "https://api.tavily.com/research")
        sent = json.loads(request.data.decode("utf-8"))
        self.assertEqual(sent["input"], "robotics")
        self.assertEqual(sent["model"], "auto")

    @mock.patch("urllib.request.urlopen")
    def test_poll_until_completed(self, urlopen):
        pending = json.dumps({"request_id": "req-123", "status": "in_progress"}).encode("utf-8")
        completed = json.dumps(
            {
                "request_id": "req-123",
                "status": "completed",
                "content": "# Report\n\nBody",
                "sources": [{"title": "Paper", "url": "https://example.org/paper"}],
                "input": "robotics",
            }
        ).encode("utf-8")

        responses = [
            mock.Mock(status=202, read=mock.Mock(return_value=pending)),
            mock.Mock(status=200, read=mock.Mock(return_value=completed)),
        ]
        urlopen.return_value.__enter__.side_effect = responses

        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test"}, clear=False):
            with mock.patch("time.sleep"):
                payload = tavily_research.poll_tavily_research_task(
                    "req-123",
                    max_wait_seconds=60,
                    initial_interval_seconds=0.01,
                )
        self.assertEqual(payload["status"], "completed")
        self.assertIn("Report", payload["content"])


class TavilyDeepResearchWorkflowTests(unittest.TestCase):
    def test_assignment_type_detection(self):
        assignment = {"assignmentTypeKey": TAVILY_DEEP_ASSIGNMENT_TYPE}
        self.assertTrue(is_tavily_deep_assignment(assignment, {}))

    def test_build_packet_from_completed(self):
        assignment = {"id": "assignment-1", "title": "Robotics", "corpusId": "corpus-1"}
        completed = {
            "request_id": "req-1",
            "input": "world models in robotics",
            "content": "# Robotics world models\n\nSummary paragraph.",
            "sources": [
                {"title": "Survey", "url": "https://arxiv.org/abs/1234.5678"},
            ],
        }
        packet = build_research_packet_from_tavily_completed(
            assignment=assignment,
            assignment_meta={"corpusKey": "AI-ML-research"},
            completed=completed,
            research_mode="source_discovery",
        )
        self.assertEqual(len(packet["source_snapshots"]), 1)
        self.assertEqual(len(packet["proposed_references"]), 1)
        self.assertEqual(packet["_forum_title"], "world models in robotics")
        self.assertIn("Summary paragraph", packet["summary"])
        self.assertIn("Robotics world models", packet["_report_markdown"])

    def test_build_packet_uses_report_fallback_field(self):
        packet = build_research_packet_from_tavily_completed(
            assignment={"id": "assignment-1"},
            assignment_meta={},
            completed={
                "request_id": "req-2",
                "report": "# Fallback report\n\nDetails.",
                "sources": [],
            },
            research_mode="source_discovery",
        )
        self.assertIn("Fallback report", packet["_report_markdown"])

    def test_forum_title_ignores_h2_sources_heading(self):
        title = derive_insight_forum_title(
            report_markdown="## Sources\n\nBody text.",
            assignment_title="Tavily body fix smoke test",
        )
        self.assertEqual(title, "Tavily body fix smoke test")

    def test_forum_title_prefers_research_question_over_assignment(self):
        long_report = (
            "Retrieval-augmented generation (RAG) couples an external information retriever "
            "with a language-model generator by processing a user query."
        )
        title = derive_insight_forum_title(
            report_markdown=long_report,
            assignment_title="Tavily body fix smoke test",
            research_question="What is retrieval-augmented generation in one paragraph?",
        )
        self.assertEqual(title, "What is retrieval-augmented generation in one paragraph?")
        self.assertLessEqual(len(title), INSIGHT_FORUM_TITLE_MAX_LEN)
        self.assertTrue(insight_summary_needs_title_repair(long_report[:120], long_report))

    def test_forum_title_prefers_assignment_when_no_query(self):
        title = derive_insight_forum_title(
            report_markdown="Long report body without a heading.",
            assignment_title="World models in robotics",
            research_question="",
        )
        self.assertEqual(title, "World models in robotics")

    def test_format_tavily_insight_body_includes_task_and_report(self):
        body = format_tavily_insight_message_body(
            report_markdown="Full Tavily answer text.",
            research_question="What is retrieval-augmented generation?",
            assignment_title="Internal assignment name",
            tavily_request_id="req-abc",
            tavily_model="mini",
            source_count=5,
            task_message_id="message-tavily-task-1",
        )
        self.assertIn("## Research task", body)
        self.assertIn("What is retrieval-augmented generation?", body)
        self.assertIn("req-abc", body)
        self.assertIn("## Report", body)
        self.assertIn("Full Tavily answer text.", body)

    def test_message_record_expands_message_body_from_content(self):
        now = "2026-05-31T12:00:00Z"
        record = message_record(
            {
                "id": "message-insight-test",
                "messageKind": "insight",
                "messageDomain": "assignment_work",
                "summary": "Insight summary",
                "body": "# Tavily report\n\nFull body text.",
                "threadId": "message-insight-test",
                "sequenceNumber": 1,
                "createdAt": now,
                "updatedAt": now,
            }
        )
        self.assertEqual(record["expected"]["threadId"], "message-insight-test")
        self.assertEqual(record["expected"]["sequenceNumber"], 1)
        expanded = expand_private_payload_records([record])
        attachments = [row for row in expanded if row["modelName"] == "ModelAttachment"]
        body_attachments = [
            row for row in attachments if row["expected"].get("role") == "message_body"
        ]
        self.assertEqual(len(body_attachments), 1)
        self.assertEqual(
            body_attachments[0]["attachmentBody"].decode("utf-8"),
            "# Tavily report\n\nFull body text.",
        )
        self.assertEqual(body_attachments[0]["expected"]["filename"], "message.md")

    def test_research_input_prefers_instructions(self):
        assignment = {
            "title": "Title",
            "brief": "Brief",
            "instructions": "How does AI change mechatronics control?",
        }
        self.assertEqual(
            tavily_research_input_for_assignment(assignment, {}),
            "How does AI change mechatronics control?",
        )


if __name__ == "__main__":
    unittest.main()
