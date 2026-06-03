"""Tests for Slack console agent channel helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import unittest
from unittest import mock

from papyrus_newsroom import slack_agent


class SlackAgentTests(unittest.TestCase):
    def test_newsroom_package_init_is_lazy(self):
        import papyrus_newsroom

        self.assertNotIn("main", papyrus_newsroom.__dict__)
        self.assertNotIn("execute_tactus", papyrus_newsroom.__dict__)

    def test_verify_slack_request_signature_accepts_valid_payload(self):
        secret = "test-signing-secret"
        body = b'{"type":"event_callback"}'
        timestamp = str(int(time.time()))
        base = f"v0:{timestamp}:{body.decode('utf-8')}"
        digest = hmac.new(secret.encode("utf-8"), base.encode("utf-8"), hashlib.sha256).hexdigest()
        signature = f"v0={digest}"
        self.assertTrue(
            slack_agent.verify_slack_request_signature(
                signing_secret=secret,
                timestamp=timestamp,
                raw_body=body,
                signature=signature,
            )
        )

    def test_verify_slack_request_signature_rejects_stale_timestamp(self):
        secret = "test-signing-secret"
        body = b"{}"
        timestamp = str(int(time.time()) - 60 * 10)
        signature = "v0=deadbeef"
        self.assertFalse(
            slack_agent.verify_slack_request_signature(
                signing_secret=secret,
                timestamp=timestamp,
                raw_body=body,
                signature=signature,
            )
        )

    def test_should_ignore_bot_messages(self):
        self.assertEqual(
            slack_agent.should_ignore_slack_event({"subtype": "bot_message", "user": "U1", "text": "hi"}),
            "bot-or-non-user-message",
        )

    def test_slack_agent_instructions_are_console_style_not_email_intake(self):
        instructions = slack_agent.slack_agent_instructions().lower()
        self.assertIn("editorial assistant", instructions)
        self.assertIn("web console", instructions)
        self.assertIn("not inbound email", instructions)
        self.assertNotIn("for papyrus reference intake", instructions)
        self.assertNotIn("register scholarly references for each relevant", instructions)
        self.assertIn("reference.list", instructions)

    def test_build_slack_prompt_includes_console_style_instructions(self):
        prompt = slack_agent.build_slack_prompt(
            event={"user": "U1", "text": "What are the latest references?"},
            team_id="T1",
            channel_id="C1",
            thread_ts="1.0",
        )
        lowered = prompt.lower()
        self.assertIn("editorial assistant", lowered)
        self.assertNotIn("for papyrus reference intake", lowered)

    def test_enqueue_console_chat_for_slack_message(self):
        client = mock.Mock()
        client.get_record.return_value = None
        event = {
            "user": "U123",
            "channel": "C123",
            "ts": "1710000000.000100",
            "text": "Please file https://example.org/paper",
        }
        with mock.patch.dict(
            "os.environ",
            {"PAPYRUS_CONSOLE_RESPONSE_TARGET": "cloud"},
            clear=False,
        ):
            result = slack_agent.enqueue_console_chat_for_slack_message(
                client,
                event=event,
                team_id="T123",
                event_id="Ev123",
            )
        self.assertTrue(result["queued"])
        self.assertEqual(result["threadId"], "thread-slack-T123-C123-1710000000-000100")
        client.graphql.assert_called()
        create_call = client.graphql.call_args_list[-1]
        message_input = create_call[0][1]["input"]
        self.assertEqual(message_input["messageKind"], "console_chat_turn")
        self.assertEqual(message_input["responseTarget"], "cloud")
        metadata = json.loads(message_input["metadata"])
        self.assertEqual(metadata["channel"], "slack")
        self.assertEqual(metadata["slackChannelId"], "C123")
        self.assertIn("execute_tactus", message_input["content"])

    def test_stream_delivery_skips_metadata_modify_loop(self):
        message = {
            "id": "message-console-assistant-1",
            "role": "ASSISTANT",
            "responseStatus": "COMPLETED",
            "metadata": {"slackDeliveredAt": "2026-06-02T12:00:00Z"},
        }
        should_process, reason = slack_agent.should_process_slack_delivery_stream_record(
            event_name="MODIFY",
            assistant_message=message,
            previous_message={
                "responseStatus": "COMPLETED",
                "metadata": {},
            },
        )
        self.assertFalse(should_process)
        self.assertEqual(reason, "already-delivered")

    def test_stream_delivery_skips_completed_metadata_touch(self):
        should_process, reason = slack_agent.should_process_slack_delivery_stream_record(
            event_name="MODIFY",
            assistant_message={
                "role": "ASSISTANT",
                "responseStatus": "COMPLETED",
                "metadata": {},
            },
            previous_message={
                "role": "ASSISTANT",
                "responseStatus": "COMPLETED",
                "metadata": {},
            },
        )
        self.assertFalse(should_process)
        self.assertEqual(reason, "completed-metadata-touch")

    def test_stream_delivery_accepts_completed_insert(self):
        should_process, reason = slack_agent.should_process_slack_delivery_stream_record(
            event_name="INSERT",
            assistant_message={
                "role": "ASSISTANT",
                "responseStatus": "COMPLETED",
                "metadata": {},
            },
        )
        self.assertTrue(should_process)
        self.assertIsNone(reason)

    def test_stream_delivery_accepts_running_to_completed_modify(self):
        should_process, reason = slack_agent.should_process_slack_delivery_stream_record(
            event_name="MODIFY",
            assistant_message={
                "role": "ASSISTANT",
                "responseStatus": "COMPLETED",
                "metadata": {},
            },
            previous_message={
                "role": "ASSISTANT",
                "responseStatus": "RUNNING",
                "metadata": {},
            },
        )
        self.assertTrue(should_process)
        self.assertIsNone(reason)

    def test_deliver_slack_reply_skips_non_slack_thread(self):
        client = mock.Mock()
        client.get_record.return_value = {"metadata": json.dumps({"channel": "email_intake"})}
        outcome = slack_agent.deliver_slack_reply_for_assistant_message(
            client,
            assistant_message={
                "id": "message-console-assistant-1",
                "role": "ASSISTANT",
                "responseStatus": "COMPLETED",
                "threadId": "thread-1",
                "content": "Done.",
                "metadata": {},
            },
        )
        self.assertTrue(outcome.get("skipped"))

    def test_deliver_slack_reply_posts_message(self):
        client = mock.Mock()
        client.get_record.return_value = {
            "metadata": json.dumps(
                {
                    "channel": "slack",
                    "slackChannelId": "C123",
                    "slackThreadTs": "1710000000.000100",
                }
            )
        }
        with mock.patch(
            "papyrus_newsroom.slack_agent.post_slack_thread_reply",
            return_value={"ok": True, "ts": "1710000001.000200"},
        ) as post:
            outcome = slack_agent.deliver_slack_reply_for_assistant_message(
                client,
                assistant_message={
                    "id": "message-console-assistant-1",
                    "role": "ASSISTANT",
                    "responseStatus": "COMPLETED",
                    "threadId": "thread-slack-T-C-1",
                    "content": "Registered one reference.",
                    "metadata": {},
                },
            )
        self.assertTrue(outcome.get("posted"))
        post.assert_called_once_with(
            channel_id="C123",
            thread_ts="1710000000.000100",
            text="Registered one reference.",
        )
        client.graphql.assert_called()


if __name__ == "__main__":
    unittest.main()
