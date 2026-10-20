"""Papyrus callers read the Biblicus 1.15 failure envelope that typed commands print on standard output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from biblicus.web_transform import MODEL
from biblicus_runner_support import completed, fake_biblicus_subprocess

from papyrus_content import categories_steering
from papyrus_content import reference_url_text as extraction
from papyrus_content.biblicus_runner import BiblicusInvalidRequestError, BiblicusOperationFailedError
from papyrus_content.web_structured_metadata import WebStructuredMetadataError, _run_biblicus_web_metadata
from papyrus_newsroom import reference_curation_signals as signals

URL_TEXT_DETAILS = {
    "source_kind": "web",
    "strategy": "direct",
    "content_type": "text/html",
    "prompt_version": "url-text-v1",
    "attempts": [{"strategy": "direct", "ok": False}],
    "http_status": 403,
}
TRANSFORM_DETAILS = {
    "prompt_version": "article-text-v1",
    "model": MODEL,
    "task": None,
    "warnings": ["trimmed"],
    "map_reduce": {},
    "retry_trace": [{"attempt": 1, "failure_code": "old_str_not_found"}],
    "retry_failure_count": 1,
    "retry_rounds_used": 2,
}


def envelope(code: str, message: str, details: dict | None = None) -> str:
    return json.dumps({"status": "failed", "error": {"code": code, "message": message, "details": details or {}}})


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path / "workdir"


def test_url_text_failure_reason_carries_the_envelope_code_message_and_typed_details(monkeypatch, workdir) -> None:
    fake_biblicus_subprocess(monkeypatch, workdir, lambda *_a, **_k: completed(returncode=1, stdout=envelope("blocked", "blocked by source", URL_TEXT_DETAILS)))
    with pytest.raises(extraction.ReferenceUrlTextExtractionError) as caught:
        extraction._extract_url_text("https://example.com/article")
    assert caught.value.reason == {"code": "blocked", "message": "blocked by source", "details": URL_TEXT_DETAILS}


def test_url_text_request_rejection_is_an_invalid_request_error_with_the_reason(monkeypatch, workdir) -> None:
    fake_biblicus_subprocess(monkeypatch, workdir, lambda *_a, **_k: completed(returncode=2, stdout=envelope("missing_source_uri", "source_uri is required")))
    with pytest.raises(extraction.ReferenceUrlTextExtractionError) as caught:
        extraction._extract_url_text("https://example.com/article")
    assert isinstance(caught.value.__cause__, BiblicusInvalidRequestError)
    assert caught.value.reason == {"code": "missing_source_uri", "message": "source_uri is required", "details": {}}


def test_url_text_usage_error_without_an_envelope_reports_stderr(monkeypatch, workdir) -> None:
    fake_biblicus_subprocess(monkeypatch, workdir, lambda *_a, **_k: completed(returncode=2, stderr="usage: biblicus: error: unrecognized arguments"))
    with pytest.raises(extraction.ReferenceUrlTextExtractionError) as caught:
        extraction._extract_url_text("https://example.com/article")
    assert caught.value.reason["code"] == "invalid_biblicus_output"
    assert caught.value.reason["details"]["stderr"] == "usage: biblicus: error: unrecognized arguments"
    assert caught.value.reason["details"]["exit_code"] == 2


def test_article_text_failure_becomes_a_failed_filter_result_with_the_retry_diagnostics(monkeypatch, workdir) -> None:
    fake_biblicus_subprocess(monkeypatch, workdir, lambda *_a, **_k: completed(returncode=1, stdout=envelope("invalid_provider_output", "no spans", TRANSFORM_DETAILS)))
    result = extraction._filter_article_text(
        extracted_text="Noisy text",
        source_uri="https://example.com/a",
        reference_title="T",
        original_title="T",
        original_subtitle="",
        model=MODEL,
    )
    assert result["status"] == "failed"
    assert result["promptVersion"] == "article-text-v1"
    assert result["warnings"] == ["trimmed"]
    assert result["retryFailureCount"] == 1
    assert result["retryRoundsUsed"] == 2
    assert result["retryLastCode"] == "old_str_not_found"
    assert result["error"]["code"] == "invalid_provider_output"
    assert result["error"]["details"]["retry_trace"][0]["failure_code"] == "old_str_not_found"


def test_article_text_failure_without_an_envelope_is_the_generic_filter_failure(monkeypatch, workdir) -> None:
    fake_biblicus_subprocess(monkeypatch, workdir, lambda *_a, **_k: completed(returncode=2, stderr="usage: boom"))
    result = extraction._filter_article_text(
        extracted_text="Noisy text", source_uri="u", reference_title="T", original_title="T", original_subtitle="", model=MODEL
    )
    assert result["status"] == "failed"
    assert result["error"]["code"] == "biblicus_article_text_failed"
    assert "usage: boom" in result["error"]["message"]


def test_web_metadata_failure_reason_is_the_envelope_error(monkeypatch, workdir) -> None:
    fake_biblicus_subprocess(monkeypatch, workdir, lambda *_a, **_k: completed(returncode=1, stdout=envelope("web_metadata_failed", "page rejected", {"http_status": 500})))
    with pytest.raises(WebStructuredMetadataError) as caught:
        _run_biblicus_web_metadata({"source_uri": "https://example.com/a"})
    assert caught.value.reason == {"code": "web_metadata_failed", "message": "page rejected", "details": {"http_status": 500}}


def test_summarize_map_reduce_failure_names_the_envelope_message(monkeypatch, workdir) -> None:
    fake_biblicus_subprocess(monkeypatch, workdir, lambda *_a, **_k: completed(returncode=1, stdout=envelope("provider_failed", "provider said no", TRANSFORM_DETAILS)))
    with pytest.raises(RuntimeError, match="summarize map-reduce command failed: provider said no") as caught:
        signals._run_biblicus_summarize_map_reduce(
            output_kind="title", reference={"title": "T"}, context={"extractedText": "Body"}, model="model-x"
        )
    assert isinstance(caught.value.__cause__, BiblicusOperationFailedError)


def test_steering_export_failure_names_the_envelope_message(monkeypatch, workdir) -> None:
    fake_biblicus_subprocess(monkeypatch, workdir, lambda *_a, **_k: completed(returncode=2, stdout=envelope("invalid_request", "classifier_id: too short")))
    with pytest.raises(RuntimeError, match="Biblicus steering export failed:\nclassifier_id: too short"):
        categories_steering.load_steering_bundle_from_biblicus(corpus="corpora/notes", classifier="c")
