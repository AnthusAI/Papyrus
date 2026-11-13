"""A Reference whose article text cannot be filtered fails (features_backend/no-fallbacks-reference-text.feature)."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import reference_capture, reference_url_text  # noqa: E402


def held(context) -> SimpleNamespace:
    if not hasattr(context, "reftext"):
        context.reftext = SimpleNamespace(result=None, capture=None)
    return context.reftext


@given("a Reference with a raw extraction whose article-text filter fails")
def _failing_filter(context):
    held(context)


@when("the article text is planned")
def _plan(context):
    reference = {"id": "reference-1", "lineageId": "lineage-1", "versionState": "current", "versionNumber": 1,
                 "corpusId": "corpus-1", "curationStatus": "accepted", "externalItemId": "item-1", "sourceUri": "https://example.com/article"}
    attachments = [{"id": "attachment-raw", "referenceLineageId": "lineage-1", "role": "extracted_text_raw",
                    "storagePath": "corpora/example/extracted/markitdown/raw/lineage-1/extracted_text_raw.md"}]
    s3 = mock.Mock()
    s3.get_object.return_value = {"Body": io.BytesIO(b"Raw attachment body text")}
    failed = {"status": "failed", "text": "", "spanCount": 0, "promptVersion": "article-text-v1", "warnings": [],
              "error": {"code": "empty_spans", "message": "No spans"}, "model": "test-model"}
    with mock.patch.object(reference_url_text, "resolve_storage_bucket_name", return_value="bucket"), \
            mock.patch.object(reference_url_text, "boto3") as boto3, \
            mock.patch.object(reference_url_text, "_filter_article_text", return_value=failed):
        boto3.client.return_value = s3
        held(context).result = reference_url_text.build_reference_extracted_text_filter_attachment_plans(
            references=[reference], attachments=attachments, corpus_id="corpus-1", curation_status="all", model="test-model")


@then("the Reference is reported as failed with the filter's reason")
def _failed(context):
    result = held(context).result
    assert result["filteredCount"] == 0 and len(result["failures"]) == 1, result["failures"]
    assert result["failures"][0]["reason"]["code"] == "empty_spans"


@then("no article text attachment is planned")
def _no_text(context):
    roles = [plan["record"]["expected"]["role"] for plan in held(context).result["plans"]]
    assert "extracted_text" not in roles, roles


@then("no fallback-raw count or filter-fallback list is reported")
def _no_counts(context):
    result = held(context).result
    assert "fallbackRawCount" not in result and "filterFallbacks" not in result


@given("the page capture module")
def _module(context):
    held(context)


@then("it has no second text extractor for pages whose main text could not be read")
def _one_extractor(context):
    assert not hasattr(reference_capture, "_fallback_text")
