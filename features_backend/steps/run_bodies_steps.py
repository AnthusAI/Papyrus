"""A run's bodies in S3 (features_backend/agents/run-bodies-in-s3.feature)."""
from __future__ import annotations

from behave import given, then, when

from papyrus_content import run_bodies


class BodyStore:
    def __init__(self):
        self.attachments, self.files = [], {}

    def list_by_index(self, index, key, limit=100):
        return [attachment for attachment in self.attachments if attachment["ownerId"] == key]


@given("a store for run bodies")
def store(context):
    context.store, context.read, context.failure = BodyStore(), None, None

    def upload(client, attachment, body):
        context.store.attachments = [row for row in context.store.attachments if row["id"] != attachment["id"]] + [attachment]
        context.store.files[attachment["id"]] = body
        return attachment

    original_upload, original_download = run_bodies.upload_attachment_body, run_bodies.download_attachment_buffer
    run_bodies.upload_attachment_body = upload
    run_bodies.download_attachment_buffer = lambda client, attachment: context.store.files[attachment["id"]]
    context.add_cleanup(setattr, run_bodies, "upload_attachment_body", original_upload)
    context.add_cleanup(setattr, run_bodies, "download_attachment_buffer", original_download)


@when('the body of run "{run_id}" is stored with the input "{given_input}" and the output "{output}"')
def stored(context, run_id, given_input, output):
    run_bodies.write_run_body(context.store, run_id, {"input": {"story": given_input}, "output": {"title": output}}, now="2026-11-20T00:00:00Z")


@when('the body of run "{run_id}" is read')
def read(context, run_id):
    try:
        context.read = run_bodies.read_run_body(context.store, run_id)
    except run_bodies.RunBodyMissing as error:
        context.failure = error


@then('reading the body of run "{run_id}" gives the input "{given_input}" and the output "{output}"')
def reads_back(context, run_id, given_input, output):
    body = run_bodies.read_run_body(context.store, run_id)
    assert body["input"] == {"story": given_input} and body["output"] == {"title": output}, body


@then("the run has exactly one stored body")
def one_body(context):
    assert len(context.store.attachments) == 1, context.store.attachments


@then('the read fails saying that run "{run_id}" has no stored body')
def missing(context, run_id):
    assert isinstance(context.failure, run_bodies.RunBodyMissing) and run_id in str(context.failure) and "no stored body" in str(context.failure), context.failure
