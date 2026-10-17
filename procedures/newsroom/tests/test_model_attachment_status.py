"""Attachments the Python authoring tools write can be read back through the download API."""
import unittest

from papyrus_content.model_attachments import build_json_model_payload_attachment


class ModelAttachmentStatusTests(unittest.TestCase):
    def test_a_json_payload_built_by_the_cli_is_active(self):
        built = build_json_model_payload_attachment({
            "ownerKind": "message", "ownerId": "message-1", "ownerLineageId": "message-1",
            "role": "metadata", "sortKey": "metadata", "content": {"ok": True}, "now": "2026-10-09T00:00:00Z",
        })
        # createModelAttachmentDownload refuses any status other than active.
        self.assertEqual(built["attachment"]["status"], "active")

    def test_an_explicit_status_is_kept(self):
        built = build_json_model_payload_attachment({
            "ownerKind": "message", "ownerId": "message-1", "role": "metadata", "content": {},
            "status": "deleted", "now": "2026-10-09T00:00:00Z",
        })
        self.assertEqual(built["attachment"]["status"], "deleted")


if __name__ == "__main__":
    unittest.main()
