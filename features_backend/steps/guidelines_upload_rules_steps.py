"""The S3 fake applies the upload function's rules (features_backend/guidelines-upload-rules.feature). No network."""
from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.guidelines.fakes import FakeBackend, FakeFiles  # noqa: E402
from papyrus_content.model_attachments import build_model_payload_attachment  # noqa: E402


@given("an S3 side that applies the upload function's rules")
def step_files(context):
    context.backend = FakeBackend()
    context.files = FakeFiles(context.backend)
    context.refusal = None


@then('the saved file is a "{role}" of JSON, which the upload function\'s rules accept')
def step_stored(context, role):
    assert [(a["role"], a["mediaType"]) for a in context.backend.attachments] == [(role, "application/json")]


@when('a "{role}" file of type "{media_type}" is offered to the upload function')
def step_upload(context, role, media_type):
    entry = build_model_payload_attachment({"ownerKind": "item", "ownerId": "item-1", "role": role, "sortKey": "x", "filename": "x.bin", "content": b"x", "mediaType": media_type})
    context.refusal = None
    try:
        context.files.put(entry["attachment"], entry["body"])
    except RuntimeError as error:
        context.refusal = str(error)


@then("the upload function would accept it")
def step_accepted(context):
    assert context.refusal is None, context.refusal


@then("the upload function would refuse it because of the media type")
def step_refused_type(context):
    assert context.refusal and "mediaType" in context.refusal, context.refusal


@then('the upload function would refuse it with "{message}"')
def step_refused(context, message):
    assert context.refusal and message in context.refusal, context.refusal
