"""The announcements write door runs in the image service function, which carries only the standard library, boto3 and papyrus_content (noDeps).
An approval through it must not import anything else: an earlier version imported the command line's login package and failed in production."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2]

PROBE = r'''
import json, sys
ALLOWED = set(sys.stdlib_module_names) | {"boto3", "botocore", "s3transfer", "jmespath", "dateutil", "urllib3", "six", "papyrus_content"}
class Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] not in ALLOWED and not name.startswith("_"):
            raise ModuleNotFoundError(f"No module named '{name}'")
sys.meta_path.insert(0, Block())
import papyrus_content.image_service as service
import papyrus_content.announcements.review_handlers as review_handlers
review_handlers._publication = lambda client: "publication"
class HeldDelivery:
    endpoint = None
    def get_record(self, model, record_id):
        return {"id": record_id, "state": "blocked", "blockedReason": "check failed", "textKey": "words", "version": 3, "revision": 4, "approval": "hard",
                "announcementId": "a", "channel": "x", "accountId": "1"}
    def update_record_if(self, model, payload, condition):
        return {**self.get_record(model, payload["id"]), **payload}
event = {"fieldName": "announcementsWrite", "identity": {"claims": {"email": "ada@example.test"}, "groups": ["admin"], "username": "ada"},
         "arguments": {"op": "announcements_delivery_review_set", "requestId": "r1", "actorKind": "agent",
                       "input": json.dumps({"delivery": "d1", "approval": "none", "onInstructionOf": "ada@example.test", "quote": "post it", "agent": "Claude"})}}
answer = service.handle(event, env={}, client_factory=lambda: HeldDelivery(), files_factory=lambda client: None)
print(json.dumps(answer))
'''


def test_an_approval_through_the_write_door_imports_only_what_the_image_service_carries():
    completed = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(SOURCE)!r}); exec({PROBE!r})"], capture_output=True, text=True, timeout=60)
    assert '"ok": true' in completed.stdout, completed.stdout + completed.stderr
    assert "ada@example.test via cli (Claude)" in completed.stdout


EDIT_PATH = r'''
import sys
ALLOWED = set(sys.stdlib_module_names) | {"boto3", "botocore", "s3transfer", "jmespath", "dateutil", "urllib3", "six", "papyrus_content"}
class Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] not in ALLOWED and not name.startswith("_"):
            raise ModuleNotFoundError(f"No module named '{name}'")
sys.meta_path.insert(0, Block())
from papyrus_content.announcements.review_handlers import door_write_handlers
from papyrus_content.announcements import edit_handlers, delivery_versions, delivery_text, delivery_lock, deliveries
from papyrus_content import model_attachments
print(",".join(sorted(door_write_handlers(object()))))
'''


def test_the_word_edits_the_write_door_serves_import_only_what_the_image_service_carries():
    completed = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(SOURCE)!r}); exec({EDIT_PATH!r})"], capture_output=True, text=True, timeout=60)
    assert "announcements_draft" in completed.stdout and "announcements_unlock" in completed.stdout, completed.stdout + completed.stderr
