import json
import io
import pathlib
import subprocess
import sys
import unittest
from typing import Any
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.reference_assignments import (  # noqa: E402
    doi_backfill_compatibility_flags,
    normalize_extraction_stages,
    normalize_identifier_types,
    timestamp_for_path,
)
from papyrus_content.reference_exports import (  # noqa: E402
    build_reference_analysis_manifest,
    build_reference_scope_training_export,
    reference_manifest_item,
)
from papyrus_content.reference_url_text import (  # noqa: E402
    ARTICLE_TEXT_SUBPROCESS_TIMEOUT_SECONDS,
    ReferenceUrlTextExtractionError,
    _extract_url_text,
    _filter_article_text,
    _normalize_publication_date_token,
    _run_biblicus_article_text,
    build_reference_identifier_dedupe_records,
    build_reference_citation_count_records,
    _plan_grobid_citation_graph_records,
    build_reference_url_text_attachment_plans,
    build_reference_extracted_text_filter_attachment_plans,
    resolve_storage_bucket_name,
)
from papyrus_content.reference_metadata_generation import (  # noqa: E402
    run_reference_metadata_generation_from_extracted_text,
)
from papyrus_content.reference_citation_resolution import (  # noqa: E402
    build_reference_citation_resolution_records,
    resolve_citation_reference,
)
from papyrus_content.source_site_plugins import resolve_source_site_enrichment  # noqa: E402
from papyrus_content.source_readiness import select_extracted_text_attachment  # noqa: E402
from papyrus_content.reference_labels import (  # noqa: E402
    build_manual_authoritative_label_relation,
    build_classification_prediction_rows,
)
from papyrus_content.model_defaults import (  # noqa: E402
    DEFAULT_REFERENCE_FILTER_MODEL,
    DEFAULT_REFERENCE_SUMMARY_MODEL,
)
from papyrus_content.references_commands import (  # noqa: E402
    _ensure_cli_grobid_runtime,
    _resolve_grobid_url,
    references_fetch_url_text,
    references_filter_extracted_text,
    references_generate_metadata_from_text,
    extract_last_json_object,
)


class ReferenceCommandsTests(unittest.TestCase):
    @mock.patch("papyrus_content.references_commands._ensure_cli_grobid_runtime")
    @mock.patch("papyrus_content.references_commands.run_reference_identifier_dedupe")
    @mock.patch("papyrus_content.references_commands.run_reference_url_text_extraction")
    @mock.patch("papyrus_content.references_commands.create_authoring_client")
    @mock.patch("papyrus_content.references_commands.require_steering_config")
    @mock.patch("papyrus_content.references_commands.load_steering_config")
    @mock.patch("papyrus_content.references_commands._require_reference_process_runtime")
    def test_references_fetch_url_text_defaults_to_filter_model(
        self,
        _mock_runtime,
        mock_load_steering,
        mock_require_steering,
        mock_client_factory,
        mock_run_extraction,
        mock_run_dedupe,
        _mock_grobid_runtime,
    ):
        mock_load_steering.return_value = None
        mock_require_steering.return_value = {"corpora": []}
        mock_client = mock.Mock()
        mock_client.list_records.return_value = []
        mock_client_factory.return_value = (mock_client, {})
        mock_run_extraction.return_value = {
            "eligibleCount": 0,
            "skippedExistingCount": 0,
            "skippedMissingSourceCount": 0,
            "skippedNonPdfCount": 0,
            "plannedCount": 0,
            "plannedAttachmentCount": 0,
            "plannedReferenceMetadataCount": 0,
            "authorsParsedCount": 0,
            "authorsLinkedCount": 0,
            "citationsParsedCount": 0,
            "citationsUpsertedCount": 0,
            "citationsSkippedLowConfidenceCount": 0,
            "citationRelationsCreatedCount": 0,
            "citationGraphWarnings": [],
            "filteredCount": 0,
            "fallbackRawCount": 0,
            "changeCount": 0,
            "graphChangeCount": 0,
            "referenceMetadataChangeCount": 0,
            "attachmentChangeCount": 0,
            "failures": [],
            "failedGrobidCount": 0,
            "doiResolvedCount": 0,
            "doiPdfSelectedCount": 0,
            "doiPdfMissedCount": 0,
            "doiSearchUsedCount": 0,
            "doiSearchHitCount": 0,
            "doiApiFallbackUsedCount": 0,
            "doiPaywalledOrBlockedCount": 0,
            "changes": [],
            "items": [],
            "graphRecords": [],
            "filterFallbacks": [],
        }
        mock_run_dedupe.return_value = {
            "duplicateGroupCount": 0,
            "referencesMergedCount": 0,
            "relationsRewiredCount": 0,
            "losersBlockedCount": 0,
        }

        references_fetch_url_text(["--dry-run"])

        self.assertEqual(mock_run_extraction.call_args.kwargs["model"], DEFAULT_REFERENCE_FILTER_MODEL)

    @mock.patch("papyrus_content.references_commands.run_reference_metadata_generation_from_extracted_text")
    @mock.patch("papyrus_content.references_commands.update_newsroom_summary_after_extracted_text_attachments")
    @mock.patch("papyrus_content.references_commands.run_reference_extracted_text_filtering")
    @mock.patch("papyrus_content.references_commands.create_authoring_client")
    @mock.patch("papyrus_content.references_commands.require_steering_config")
    @mock.patch("papyrus_content.references_commands.load_steering_config")
    @mock.patch("papyrus_content.references_commands._require_reference_process_runtime")
    def test_references_filter_text_defaults_filter_and_metadata_models(
        self,
        _mock_runtime,
        mock_load_steering,
        mock_require_steering,
        mock_client_factory,
        mock_run_filtering,
        _mock_summary_update,
        mock_run_metadata,
    ):
        mock_load_steering.return_value = None
        mock_require_steering.return_value = {"corpora": []}
        mock_client = mock.Mock()
        mock_client.list_records.return_value = []
        mock_client_factory.return_value = (mock_client, {})
        mock_run_filtering.return_value = {
            "attemptedCount": 1,
            "plannedCount": 1,
            "plannedAttachmentCount": 1,
            "filteredCount": 1,
            "fallbackRawCount": 0,
            "skippedMissingSourceCount": 0,
            "changeCount": 1,
            "failures": [],
            "items": [],
            "changes": [],
            "processedReferenceIds": {"reference-1"},
            "filterFallbacks": [],
        }
        mock_run_metadata.return_value = {
            "attemptedCount": 1,
            "generatedCount": 1,
            "skippedMissingTextCount": 0,
            "generationFailureCount": 0,
            "items": [],
        }

        references_filter_extracted_text([])

        self.assertEqual(mock_run_filtering.call_args.kwargs["model"], DEFAULT_REFERENCE_FILTER_MODEL)
        self.assertEqual(mock_run_metadata.call_args.kwargs["model"], DEFAULT_REFERENCE_SUMMARY_MODEL)

    @mock.patch("papyrus_content.references_commands.run_reference_metadata_generation_from_extracted_text")
    @mock.patch("papyrus_content.references_commands.create_authoring_client")
    @mock.patch("papyrus_content.references_commands.require_steering_config")
    @mock.patch("papyrus_content.references_commands.load_steering_config")
    @mock.patch("papyrus_content.references_commands._require_reference_process_runtime")
    def test_references_generate_metadata_defaults_to_summary_model(
        self,
        _mock_runtime,
        mock_load_steering,
        mock_require_steering,
        mock_client_factory,
        mock_run_metadata,
    ):
        mock_load_steering.return_value = None
        mock_require_steering.return_value = {"corpora": []}
        mock_client = mock.Mock()
        mock_client.list_records.return_value = []
        mock_client_factory.return_value = (mock_client, {})
        mock_run_metadata.return_value = {
            "attemptedCount": 0,
            "generatedCount": 0,
            "skippedMissingTextCount": 0,
            "generationFailureCount": 0,
            "items": [],
        }

        references_generate_metadata_from_text(["--dry-run"])

        self.assertEqual(mock_run_metadata.call_args.kwargs["model"], DEFAULT_REFERENCE_SUMMARY_MODEL)

    def test_normalize_identifier_types_accepts_aliases(self):
        self.assertEqual(normalize_identifier_types("doi, arxiv, isbn13"), ["doi", "arxiv_id", "isbn13"])

    def test_doi_backfill_compatibility_flags_maps_only_missing_doi(self):
        flags = doi_backfill_compatibility_flags(["--corpus-key", "AI-ML-research", "--only-missing-doi", "true"])
        self.assertIn("--only-missing", flags)
        self.assertIn("true", flags)
        self.assertIn("--types", flags)
        self.assertEqual(flags[flags.index("--types") + 1], "doi")

    def test_normalize_extraction_stages_defaults(self):
        self.assertEqual(
            normalize_extraction_stages(None),
            ["pass-through-text", "pdf-text", "metadata-text"],
        )
        self.assertEqual(normalize_extraction_stages("pdf-text,metadata-text"), ["pdf-text", "metadata-text"])

    @mock.patch("papyrus_content.reference_citation_resolution._fetch_json")
    def test_resolve_citation_reference_prefers_strong_identifier_match(self, mock_fetch_json):
        mock_fetch_json.side_effect = [
            {
                "message": {
                    "items": [
                        {
                            "title": ["Building a Large Annotated Corpus of English: The Penn Treebank"],
                            "DOI": "10.1162/coli.1993.19.2.313",
                            "URL": "https://aclanthology.org/J93-2004.pdf",
                            "author": [
                                {"given": "Mitchell", "family": "Marcus"},
                                {"given": "Beatrice", "family": "Santorini"},
                            ],
                            "issued": {"date-parts": [[1993]]},
                        }
                    ]
                }
            },
            {"results": []},
        ]
        reference = {
            "title": "Building a large annotated corpus of english: The Penn treebank",
            "authors": ["MaryMitchell P Marcus", "BeatriceSantorini"],
        }
        result = resolve_citation_reference(reference)
        self.assertEqual(result["status"], "resolved")
        best = result["bestCandidate"]
        self.assertEqual(best["source"], "crossref")
        self.assertEqual(best["doi"], "10.1162/coli.1993.19.2.313")
        self.assertGreaterEqual(float(best["score"]), 0.55)

    @mock.patch("papyrus_content.reference_citation_resolution.resolve_citation_reference")
    def test_build_reference_citation_resolution_records_updates_metadata_and_source(self, mock_resolve):
        mock_resolve.return_value = {
            "status": "resolved",
            "bestCandidate": {
                "doi": "10.1162/coli.1993.19.2.313",
                "arxiv_id": None,
                "isbn": None,
                "source_uri": "https://aclanthology.org/J93-2004.pdf",
                "score": 0.91,
            },
            "candidates": [],
            "notes": [],
        }
        references = [
            {
                "id": "reference-citation-v1",
                "lineageId": "reference-citation",
                "versionState": "current",
                "versionNumber": 1,
                "corpusId": "knowledge-corpus-ai-ml-research",
                "curationStatus": "pending",
                "externalItemId": "citation:abc",
                "title": "Building a Large Annotated Corpus of English: The Penn Treebank",
                "authors": ["Mitchell Marcus"],
                "sourceUri": None,
                "metadata": "{}",
            }
        ]
        result = build_reference_citation_resolution_records(
            references=references,
            corpus_id="knowledge-corpus-ai-ml-research",
            curation_status="all",
            force=True,
            promote_external_id=True,
        )
        self.assertEqual(result["attemptedCount"], 1)
        self.assertEqual(result["resolvedCount"], 1)
        expected = result["records"][0]["expected"]
        self.assertEqual(expected["id"], "reference-citation-v1")
        self.assertEqual(expected["sourceUri"], "https://aclanthology.org/J93-2004.pdf")
        self.assertEqual(expected["externalItemId"], "doi:10.1162/coli.1993.19.2.313")
        metadata = json.loads(expected["metadata"])
        self.assertEqual(metadata["citationResolution"]["status"], "resolved")
        self.assertEqual(metadata["identifiers"]["resolved"]["doi"], "10.1162/coli.1993.19.2.313")

    def test_timestamp_for_path_strips_punctuation(self):
        self.assertRegex(timestamp_for_path("2026-05-23T12:00:00.000Z"), r"^2026-05-23T12-00-00-000Z$")

    def test_normalize_publication_date_token_accepts_full_month_and_year(self):
        self.assertEqual(_normalize_publication_date_token("2025-07-09")["value"], "2025-07-09")
        self.assertEqual(_normalize_publication_date_token("2025-07")["value"], "2025-07-01")
        self.assertEqual(_normalize_publication_date_token("2025")["value"], "2025-01-01")

    def test_normalize_publication_date_token_rejects_malformed_values(self):
        self.assertIsNone(_normalize_publication_date_token("2025-13-09")["value"])
        self.assertIsNone(_normalize_publication_date_token("Spring 2025")["value"])

    def test_build_reference_analysis_manifest_requires_text_attachments(self):
        corpus_config = {"key": "AI-ML-research", "name": "AI-ML-research", "path": "corpora/AI-ML-research"}
        corpus_id = "knowledge-corpus-ai-ml-research"
        references = [
            {
                "id": "reference-1",
                "lineageId": "reference-lineage-1",
                "corpusId": corpus_id,
                "versionState": "current",
                "curationStatus": "accepted",
                "externalItemId": "item-1",
                "storagePath": "corpora/AI-ML-research/imports/item-1.pdf",
            }
        ]
        attachments = []
        with self.assertRaisesRegex(ValueError, "lack extracted_text attachments"):
            build_reference_analysis_manifest(
                corpus_config=corpus_config,
                corpus_id=corpus_id,
                references=references,
                attachments=attachments,
            )

    def test_select_extracted_text_attachment_accepts_non_snapshot_paths(self):
        reference = {"id": "reference-1", "lineageId": "lineage-1", "externalItemId": "item-1"}
        attachments = [
            {
                "id": "attachment-1",
                "referenceLineageId": "lineage-1",
                "role": "extracted_text",
                "storagePath": "corpora/AI-ML-research/extracted/markitdown/text/lineage-1/extracted_text.md",
                "importedAt": "2026-05-27T00:00:00Z",
            }
        ]
        selected = select_extracted_text_attachment(reference, attachments)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["id"], "attachment-1")

    @mock.patch("papyrus_content.reference_url_text._extract_url_text")
    @mock.patch("papyrus_content.reference_url_text._filter_article_text")
    def test_build_reference_url_text_attachment_plans(self, mock_filter, mock_extract):
        mock_extract.return_value = {
            "text": "Example plain text",
            "markdown": "# Example plain text",
            "title": "Example Title",
        }
        mock_filter.return_value = {
            "status": "ok",
            "text": "Filtered article text",
            "spanCount": 1,
            "promptVersion": "article-text-v1",
            "warnings": [],
            "retryTrace": [],
            "retryFailureCount": 0,
            "retryRoundsUsed": 2,
            "retryLastCode": None,
            "agenticLoop": {"version": "article-text-react-v1", "rounds_used": 1, "actions": [{"action": "done"}]},
            "error": None,
            "model": "gpt-5.4-nano",
        }
        references = [
            {
                "id": "reference-1",
                "lineageId": "lineage-1",
                "versionNumber": 1,
                "versionState": "current",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "item-1",
                "sourceUri": "https://example.com/article",
            }
        ]
        result = build_reference_url_text_attachment_plans(
            references=references,
            attachments=[],
            corpus_key_by_id={"knowledge-corpus-ai-ml-research": "AI-ML-research"},
            corpus_id="knowledge-corpus-ai-ml-research",
            curation_status="all",
            force=False,
        )
        self.assertEqual(result["plannedCount"], 1)
        self.assertEqual(result["plannedAttachmentCount"], 2)
        by_role = {plan["record"]["expected"]["role"]: plan for plan in result["plans"]}
        self.assertIn("extracted_text_raw", by_role)
        self.assertIn("extracted_text", by_role)

        raw_expected = by_role["extracted_text_raw"]["record"]["expected"]
        self.assertEqual(raw_expected["mediaType"], "text/markdown")
        self.assertIn("markitdown/raw/lineage-1/extracted_text_raw.md", raw_expected["storagePath"])
        self.assertEqual(raw_expected["filename"], "extracted_text_raw.md")
        raw_metadata = json.loads(raw_expected["metadata"])
        self.assertEqual(raw_metadata["source"], "biblicus-url-text")
        self.assertEqual(raw_metadata["sourceUri"], "https://example.com/article")

        canonical_expected = by_role["extracted_text"]["record"]["expected"]
        self.assertIn("markitdown/text/lineage-1/extracted_text.md", canonical_expected["storagePath"])
        self.assertEqual(canonical_expected["filename"], "extracted_text.md")
        canonical_metadata = json.loads(canonical_expected["metadata"])
        self.assertEqual(canonical_metadata["source"], "biblicus-article-text-filter")
        self.assertEqual(canonical_metadata["filterStatus"], "filtered")
        self.assertEqual(canonical_metadata["filterRetryFailureCount"], 0)
        self.assertEqual(canonical_metadata["filterRetryRoundsUsed"], 2)
        self.assertIsNone(canonical_metadata["filterRetryLastCode"])
        self.assertEqual(canonical_metadata["filterAgenticLoop"]["version"], "article-text-react-v1")

    @mock.patch("papyrus_content.reference_url_text._download_source_attachment_from_uri", return_value=b"%PDF-test")
    @mock.patch("papyrus_content.reference_url_text._extract_url_text")
    @mock.patch("papyrus_content.reference_url_text._filter_article_text")
    def test_build_reference_url_text_attachment_plans_passthrough_for_pdf_sources(
        self,
        mock_filter,
        mock_extract,
        _mock_download,
    ):
        mock_extract.return_value = {
            "text": "PDF full text body",
            "markdown": "PDF full text body",
            "title": "Paper title",
            "contentType": "application/pdf",
            "sourceKind": "pdf",
            "structured": {
                "authors": [],
                "citations": [],
                "summary": {"authors_count": 0, "citations_count": 0, "citations_with_identifiers": 0},
                "warnings": [],
            },
        }
        references = [
            {
                "id": "reference-1",
                "lineageId": "lineage-1",
                "versionNumber": 1,
                "versionState": "current",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "item-1",
                "sourceUri": "https://example.com/paper.pdf",
            }
        ]
        result = build_reference_url_text_attachment_plans(
            references=references,
            attachments=[],
            corpus_key_by_id={"knowledge-corpus-ai-ml-research": "AI-ML-research"},
            corpus_id="knowledge-corpus-ai-ml-research",
            curation_status="all",
            force=False,
        )
        mock_filter.assert_not_called()
        self.assertEqual(result["plannedAttachmentCount"], 3)
        canonical_plan = next(
            plan for plan in result["plans"] if plan["record"]["expected"]["role"] == "extracted_text"
        )
        source_plan = next(
            plan for plan in result["plans"] if plan["record"]["expected"]["role"] == "source"
        )
        self.assertEqual(source_plan["record"]["expected"]["mediaType"], "application/pdf")
        canonical_body = canonical_plan["body"].decode("utf-8")
        self.assertEqual(canonical_body, "PDF full text body")
        metadata = json.loads(canonical_plan["record"]["expected"]["metadata"])
        self.assertEqual(metadata["filterStatus"], "filtered")
        self.assertEqual(metadata["filterPromptVersion"], "pdf-pass-through-v1")
        self.assertEqual(metadata["filterModel"], "passthrough")

    @mock.patch("papyrus_content.reference_url_text._extract_url_text")
    def test_build_reference_url_text_attachment_plans_pdf_only_skips_non_pdf_sources(
        self,
        mock_extract,
    ):
        references = [
            {
                "id": "reference-1",
                "lineageId": "lineage-1",
                "versionNumber": 1,
                "versionState": "current",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "item-1",
                "sourceUri": "https://example.com/article",
            }
        ]
        result = build_reference_url_text_attachment_plans(
            references=references,
            attachments=[],
            corpus_key_by_id={"knowledge-corpus-ai-ml-research": "AI-ML-research"},
            corpus_id="knowledge-corpus-ai-ml-research",
            curation_status="all",
            force=False,
            pdf_only=True,
        )
        mock_extract.assert_not_called()
        self.assertEqual(result["plannedCount"], 0)
        self.assertEqual(result["skippedNonPdfCount"], 1)

    @mock.patch("papyrus_content.reference_url_text._download_source_attachment_from_uri", return_value=b"%PDF-test")
    @mock.patch("papyrus_content.reference_url_text._filter_article_text")
    @mock.patch("papyrus_content.reference_url_text._extract_url_text")
    def test_build_reference_url_text_attachment_plans_records_grobid_metadata(
        self,
        mock_extract,
        mock_filter,
        _mock_download,
    ):
        mock_extract.return_value = {
            "text": "PDF full text body",
            "markdown": "PDF full text body",
            "title": "Paper title",
            "contentType": "application/pdf",
            "sourceKind": "pdf",
            "method": "grobid",
            "grobid": {
                "base_url": "http://127.0.0.1:8070",
                "endpoint": "http://127.0.0.1:8070/api/processFulltextDocument",
            },
            "structured": {
                "authors": [],
                "citations": [],
                "summary": {"authors_count": 0, "citations_count": 0, "citations_with_identifiers": 0},
                "warnings": [],
            },
        }
        mock_filter.return_value = {
            "status": "ok",
            "text": "PDF full text body",
            "spanCount": 1,
            "promptVersion": "pdf-pass-through-v1",
            "model": "passthrough",
            "warnings": [],
            "retryTrace": [],
            "retryFailureCount": 0,
            "retryRoundsUsed": 0,
            "retryLastCode": None,
            "agenticLoop": {"version": "pdf-pass-through-v1", "rounds_used": 0, "actions": []},
            "error": None,
        }
        references = [
            {
                "id": "reference-1",
                "lineageId": "lineage-1",
                "versionNumber": 1,
                "versionState": "current",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "item-1",
                "sourceUri": "https://example.com/paper.pdf",
            }
        ]
        result = build_reference_url_text_attachment_plans(
            references=references,
            attachments=[],
            corpus_key_by_id={"knowledge-corpus-ai-ml-research": "AI-ML-research"},
            corpus_id="knowledge-corpus-ai-ml-research",
            curation_status="all",
            force=False,
            grobid_url="http://127.0.0.1:8070",
        )
        mock_extract.assert_called_once_with(
            "https://example.com/paper.pdf",
            reference_title="",
            grobid_url="http://127.0.0.1:8070",
        )
        raw_plan = next(plan for plan in result["plans"] if plan["record"]["expected"]["role"] == "extracted_text_raw")
        raw_metadata = json.loads(raw_plan["record"]["expected"]["metadata"])
        self.assertEqual(raw_metadata["method"], "grobid")
        self.assertEqual(raw_metadata["grobid"]["base_url"], "http://127.0.0.1:8070")

    @mock.patch("papyrus_content.reference_url_text._download_source_attachment_from_uri", return_value=b"%PDF-test")
    @mock.patch("papyrus_content.reference_url_text._filter_article_text")
    @mock.patch("papyrus_content.reference_url_text._extract_url_text")
    def test_pdf_grobid_publication_date_overwrites_reference_source_published_at(
        self,
        mock_extract,
        mock_filter,
        _mock_download,
    ):
        mock_extract.return_value = {
            "text": "PDF full text body",
            "markdown": "PDF full text body",
            "title": "Paper title",
            "contentType": "application/pdf",
            "sourceKind": "pdf",
            "method": "grobid",
            "grobid": {
                "base_url": "http://127.0.0.1:8070",
                "publication_date": "2024-03",
            },
            "structured": {
                "summary": {"publication_date": "2024-03"},
                "authors": [],
                "citations": [],
                "warnings": [],
            },
        }
        mock_filter.return_value = {
            "status": "ok",
            "text": "PDF full text body",
            "spanCount": 1,
            "promptVersion": "pdf-pass-through-v1",
            "model": "passthrough",
            "warnings": [],
            "retryTrace": [],
            "retryFailureCount": 0,
            "retryRoundsUsed": 0,
            "retryLastCode": None,
            "agenticLoop": {"version": "pdf-pass-through-v1", "rounds_used": 0, "actions": []},
            "error": None,
        }
        references = [
            {
                "id": "reference-1",
                "lineageId": "lineage-1",
                "versionNumber": 1,
                "versionState": "current",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "item-1",
                "sourceUri": "https://example.com/paper.pdf",
                "sourcePublishedAt": "2019-01-01",
                "metadata": json.dumps({}),
            }
        ]
        result = build_reference_url_text_attachment_plans(
            references=references,
            attachments=[],
            corpus_key_by_id={"knowledge-corpus-ai-ml-research": "AI-ML-research"},
            corpus_id="knowledge-corpus-ai-ml-research",
            curation_status="all",
            force=True,
        )
        reference_record = result["referenceRecords"][0]["expected"]
        self.assertEqual(reference_record["sourcePublishedAt"], "2024-03-01")
        metadata = json.loads(reference_record["metadata"])
        resolution = metadata["papyrus"]["publication_date_resolution"]
        self.assertEqual(resolution["source"], "grobid")
        self.assertEqual(resolution["resolvedSourcePublishedAt"], "2024-03-01")
        self.assertEqual(resolution["selectedRaw"], "2024-03")

    @mock.patch("papyrus_content.reference_url_text._download_source_attachment_from_uri", return_value=b"%PDF-test")
    @mock.patch("papyrus_content.reference_url_text._filter_article_text")
    @mock.patch("papyrus_content.reference_url_text._extract_url_text")
    def test_pdf_grobid_publication_date_invalid_preserves_existing_reference_source_published_at(
        self,
        mock_extract,
        mock_filter,
        _mock_download,
    ):
        mock_extract.return_value = {
            "text": "PDF full text body",
            "markdown": "PDF full text body",
            "title": "Paper title",
            "contentType": "application/pdf",
            "sourceKind": "pdf",
            "method": "grobid",
            "grobid": {"base_url": "http://127.0.0.1:8070", "publication_date": "Spring 2024"},
            "structured": {"summary": {"publication_date": "Spring 2024"}, "authors": [], "citations": [], "warnings": []},
        }
        mock_filter.return_value = {
            "status": "ok",
            "text": "PDF full text body",
            "spanCount": 1,
            "promptVersion": "pdf-pass-through-v1",
            "model": "passthrough",
            "warnings": [],
            "retryTrace": [],
            "retryFailureCount": 0,
            "retryRoundsUsed": 0,
            "retryLastCode": None,
            "agenticLoop": {"version": "pdf-pass-through-v1", "rounds_used": 0, "actions": []},
            "error": None,
        }
        references = [
            {
                "id": "reference-1",
                "lineageId": "lineage-1",
                "versionNumber": 1,
                "versionState": "current",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "item-1",
                "sourceUri": "https://example.com/paper.pdf",
                "sourcePublishedAt": "2019-01-01",
                "metadata": json.dumps({}),
            }
        ]
        result = build_reference_url_text_attachment_plans(
            references=references,
            attachments=[],
            corpus_key_by_id={"knowledge-corpus-ai-ml-research": "AI-ML-research"},
            corpus_id="knowledge-corpus-ai-ml-research",
            curation_status="all",
            force=True,
        )
        reference_record = result["referenceRecords"][0]["expected"]
        self.assertNotIn("sourcePublishedAt", reference_record)
        metadata = json.loads(reference_record["metadata"])
        resolution = metadata["papyrus"]["publication_date_resolution"]
        self.assertEqual(resolution["source"], "fallback")
        self.assertEqual(resolution["fallbackSourcePublishedAt"], "2019-01-01")
        self.assertIn("grobid_date_parse_failed", resolution["warnings"])

    @mock.patch("papyrus_content.reference_url_text._extract_url_text")
    @mock.patch("papyrus_content.reference_url_text._filter_article_text")
    def test_non_pdf_does_not_override_reference_source_published_at(self, mock_filter, mock_extract):
        mock_extract.return_value = {
            "text": "Example plain text",
            "markdown": "Example plain text",
            "title": "Example Title",
            "contentType": "text/html",
            "sourceKind": "web",
            "structured": {"summary": {"publication_date": "2025-02-17"}, "authors": [], "citations": [], "warnings": []},
        }
        mock_filter.return_value = {
            "status": "ok",
            "text": "Filtered article text",
            "spanCount": 1,
            "promptVersion": "article-text-v1",
            "warnings": [],
            "retryTrace": [],
            "retryFailureCount": 0,
            "retryRoundsUsed": 0,
            "retryLastCode": None,
            "agenticLoop": {"version": "article-text-react-v1", "rounds_used": 0, "actions": [{"action": "done"}]},
            "error": None,
            "model": "gpt-5.4-mini",
        }
        references = [
            {
                "id": "reference-1",
                "lineageId": "lineage-1",
                "versionNumber": 1,
                "versionState": "current",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "item-1",
                "sourceUri": "https://example.com/article",
                "sourcePublishedAt": "2018-11-20",
                "metadata": json.dumps({}),
            }
        ]
        result = build_reference_url_text_attachment_plans(
            references=references,
            attachments=[],
            corpus_key_by_id={"knowledge-corpus-ai-ml-research": "AI-ML-research"},
            corpus_id="knowledge-corpus-ai-ml-research",
            curation_status="all",
            force=True,
        )
        reference_record = result["referenceRecords"][0]["expected"]
        self.assertNotIn("sourcePublishedAt", reference_record)

    def test_plan_grobid_citation_graph_records_creates_author_and_citation_records(self):
        source_reference = {
            "id": "reference-source-v1",
            "lineageId": "reference-source",
            "versionNumber": 1,
            "versionState": "current",
            "corpusId": "knowledge-corpus-ai-ml-research",
            "externalItemId": "source-item",
        }
        structured = {
            "authors": [
                {
                    "name": "Ada Lovelace",
                    "normalized_name": "ada lovelace",
                    "orcid": "0000-0001-2345-6789",
                }
            ],
            "citations": [
                {
                    "title": "Prior Work",
                    "authors": ["Alan Turing"],
                    "year": 2024,
                    "doi": "10.1000/xyz",
                    "venue": "Journal X",
                }
            ],
            "summary": {"authors_count": 1, "citations_count": 1, "citations_with_identifiers": 1},
            "warnings": [],
        }
        planned = _plan_grobid_citation_graph_records(
            source_reference=source_reference,
            all_references=[source_reference],
            semantic_relations=[],
            structured=structured,
            now="2026-05-28T00:00:00Z",
        )
        self.assertEqual(planned["authorsParsed"], 1)
        self.assertEqual(planned["authorsLinked"], 1)
        self.assertEqual(planned["citationsParsed"], 1)
        self.assertEqual(planned["citationsUpserted"], 1)
        self.assertEqual(planned["citationRelationsCreated"], 1)
        model_names = [record["modelName"] for record in planned["records"]]
        self.assertIn("SemanticNode", model_names)
        self.assertIn("Reference", model_names)
        self.assertIn("SemanticRelation", model_names)
        self.assertEqual(planned["referenceRecords"][0]["expected"]["outboundCitationCount"], 1)
        self.assertEqual(json.loads(next(
            record["expected"]["metadata"]
            for record in planned["records"]
            if record["modelName"] == "Reference"
        ))["citation_auto_created"], True)
        predicates = [
            record["expected"].get("predicate")
            for record in planned["records"]
            if record["modelName"] == "SemanticRelation"
        ]
        self.assertIn("authored_by", predicates)
        self.assertIn("cites", predicates)

    def test_plan_grobid_citation_graph_records_skips_low_confidence_citations(self):
        source_reference = {
            "id": "reference-source-v1",
            "lineageId": "reference-source",
            "versionNumber": 1,
            "versionState": "current",
            "corpusId": "knowledge-corpus-ai-ml-research",
            "externalItemId": "source-item",
        }
        structured = {
            "authors": [],
            "citations": [
                {
                    "title": "Tiny",
                    "authors": [],
                    "year": None,
                }
            ],
            "summary": {"authors_count": 0, "citations_count": 1, "citations_with_identifiers": 0},
            "warnings": [],
        }
        planned = _plan_grobid_citation_graph_records(
            source_reference=source_reference,
            all_references=[source_reference],
            semantic_relations=[],
            structured=structured,
            now="2026-05-28T00:00:00Z",
        )
        self.assertEqual(planned["citationsParsed"], 1)
        self.assertEqual(planned["citationsUpserted"], 0)
        self.assertEqual(planned["citationsSkippedLowConfidence"], 1)
        self.assertEqual(planned["citationRelationsCreated"], 0)
        warnings = planned.get("warnings") or []
        self.assertTrue(any(str(row.get("code") or "") == "citation_low_confidence" for row in warnings))

    def test_plan_grobid_citation_graph_records_supersedes_stale_cites_and_recounts(self):
        source_reference = {
            "id": "reference-source-v1",
            "lineageId": "reference-source",
            "versionNumber": 1,
            "versionState": "current",
            "corpusId": "knowledge-corpus-ai-ml-research",
            "externalItemId": "source-item",
            "inboundCitationCount": 0,
            "outboundCitationCount": 1,
        }
        existing_target = {
            "id": "reference-existing-v1",
            "lineageId": "reference-existing",
            "versionNumber": 1,
            "versionState": "current",
            "corpusId": "knowledge-corpus-ai-ml-research",
            "externalItemId": "doi:10.1000/existing",
            "inboundCitationCount": 1,
            "outboundCitationCount": 0,
        }
        stale_relation = {
            "id": "semantic-relation-stale",
            "relationState": "current",
            "predicate": "cites",
            "relationTypeKey": "cites",
            "subjectKind": "reference",
            "subjectId": source_reference["id"],
            "subjectLineageId": source_reference["lineageId"],
            "objectKind": "reference",
            "objectId": existing_target["id"],
            "objectLineageId": existing_target["lineageId"],
        }
        structured = {
            "authors": [],
            "citations": [
                {
                    "title": "Replacement Work",
                    "authors": ["Grace Hopper"],
                    "year": 2024,
                    "doi": "10.1000/replacement",
                }
            ],
            "summary": {"authors_count": 0, "citations_count": 1, "citations_with_identifiers": 1},
            "warnings": [],
        }
        planned = _plan_grobid_citation_graph_records(
            source_reference=source_reference,
            all_references=[source_reference, existing_target],
            semantic_relations=[stale_relation],
            structured=structured,
            now="2026-05-28T00:00:00Z",
        )
        superseded = [
            record for record in planned["records"]
            if record["modelName"] == "SemanticRelation"
            and record["expected"].get("relationState") == "superseded"
        ]
        self.assertEqual(len(superseded), 1)
        self.assertEqual(superseded[0]["expected"]["id"], "semantic-relation-stale")
        count_updates = {
            record["expected"]["id"]: record["expected"]
            for record in planned["referenceRecords"]
        }
        self.assertEqual(count_updates["reference-source-v1"]["outboundCitationCount"], 1)
        self.assertEqual(count_updates["reference-existing-v1"]["inboundCitationCount"], 0)
        replacement_reference = next(
            record["expected"]
            for record in planned["records"]
            if record["modelName"] == "Reference"
        )
        self.assertEqual(replacement_reference["inboundCitationCount"], 1)
        self.assertEqual(replacement_reference["outboundCitationCount"], 0)

    def test_build_reference_citation_count_records_recounts_current_cites_only(self):
        references = [
            {
                "id": "reference-a-v1",
                "lineageId": "reference-a",
                "versionState": "current",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "a",
                "curationStatus": "accepted",
            },
            {
                "id": "reference-b-v1",
                "lineageId": "reference-b",
                "versionState": "current",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "b",
                "curationStatus": "accepted",
            },
        ]
        semantic_relations = [
            {
                "id": "semantic-relation-1",
                "relationState": "current",
                "predicate": "cites",
                "relationTypeKey": "cites",
                "subjectLineageId": "reference-a",
                "objectLineageId": "reference-b",
            },
            {
                "id": "semantic-relation-2",
                "relationState": "superseded",
                "predicate": "cites",
                "relationTypeKey": "cites",
                "subjectLineageId": "reference-a",
                "objectLineageId": "reference-b",
            },
            {
                "id": "semantic-relation-3",
                "relationState": "current",
                "predicate": "supports",
                "relationTypeKey": "supports",
                "subjectLineageId": "reference-b",
                "objectLineageId": "reference-a",
            },
        ]
        recount = build_reference_citation_count_records(
            references=references,
            semantic_relations=semantic_relations,
            corpus_id="knowledge-corpus-ai-ml-research",
            curation_status="all",
        )
        records_by_id = {record["expected"]["id"]: record["expected"] for record in recount["records"]}
        self.assertEqual(records_by_id["reference-a-v1"]["outboundCitationCount"], 1)
        self.assertEqual(records_by_id["reference-a-v1"]["inboundCitationCount"], 0)
        self.assertEqual(records_by_id["reference-b-v1"]["inboundCitationCount"], 1)
        self.assertEqual(records_by_id["reference-b-v1"]["outboundCitationCount"], 0)

    def test_build_reference_identifier_dedupe_records_merges_and_rewires_cites(self):
        references = [
            {
                "id": "reference-winner-v1",
                "lineageId": "reference-winner",
                "versionNumber": 1,
                "versionState": "current",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "doi:10.1000/example",
                "curationStatus": "accepted",
                "sourceUri": "https://doi.org/10.1000/example",
                "metadata": json.dumps({"identifiers": {"resolved": {"doi": "10.1000/example"}}}),
            },
            {
                "id": "reference-loser-v1",
                "lineageId": "reference-loser",
                "versionNumber": 1,
                "versionState": "current",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "doi:10.1000/example",
                "curationStatus": "pending",
                "sourceUri": "https://doi.org/10.1000/example?utm_source=test",
                "metadata": "{}",
            },
            {
                "id": "reference-citing-v1",
                "lineageId": "reference-citing",
                "versionNumber": 1,
                "versionState": "current",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "doi:10.1000/citing",
                "curationStatus": "accepted",
            },
        ]
        attachments = [
            {
                "id": "reference-attachment-winner",
                "referenceLineageId": "reference-winner",
                "role": "extracted_text",
            }
        ]
        semantic_relations = [
            {
                "id": "semantic-relation-outgoing-loser",
                "relationState": "current",
                "predicate": "cites",
                "relationTypeKey": "cites",
                "subjectKind": "reference",
                "subjectId": "reference-loser-v1",
                "subjectLineageId": "reference-loser",
                "objectKind": "reference",
                "objectId": "reference-citing-v1",
                "objectLineageId": "reference-citing",
            },
            {
                "id": "semantic-relation-incoming-loser",
                "relationState": "current",
                "predicate": "cites",
                "relationTypeKey": "cites",
                "subjectKind": "reference",
                "subjectId": "reference-citing-v1",
                "subjectLineageId": "reference-citing",
                "objectKind": "reference",
                "objectId": "reference-loser-v1",
                "objectLineageId": "reference-loser",
            },
        ]
        dedupe = build_reference_identifier_dedupe_records(
            references=references,
            attachments=attachments,
            semantic_relations=semantic_relations,
            corpus_id="knowledge-corpus-ai-ml-research",
            curation_status="all",
            touched_reference_ids={"reference-loser-v1"},
            force=False,
        )
        self.assertEqual(dedupe["duplicateGroupCount"], 1)
        self.assertEqual(dedupe["referencesMergedCount"], 1)
        self.assertEqual(dedupe["losersBlockedCount"], 1)
        self.assertGreaterEqual(dedupe["relationsRewiredCount"], 2)

        reference_updates = [
            record["expected"]
            for record in dedupe["records"]
            if record["modelName"] == "Reference"
        ]
        loser_update = next(update for update in reference_updates if update["id"] == "reference-loser-v1")
        loser_metadata = json.loads(loser_update["metadata"])
        self.assertEqual(loser_metadata["mergedIntoReferenceId"], "reference-winner-v1")
        self.assertEqual(loser_metadata["mergeReason"], "identifier_dedupe")
        winner_count_update = next(update for update in reference_updates if update["id"] == "reference-winner-v1")
        self.assertEqual(winner_count_update["inboundCitationCount"], 1)
        self.assertEqual(winner_count_update["outboundCitationCount"], 1)

        superseded = [
            record["expected"]
            for record in dedupe["records"]
            if record["modelName"] == "SemanticRelation"
            and record["expected"].get("relationState") == "superseded"
        ]
        self.assertEqual(len(superseded), 2)

    @mock.patch("papyrus_content.reference_url_text._extract_url_text")
    @mock.patch("papyrus_content.reference_url_text._filter_article_text")
    def test_build_reference_url_text_attachment_plans_falls_back_to_raw_when_filter_fails(
        self,
        mock_filter,
        mock_extract,
    ):
        mock_extract.return_value = {
            "text": "Raw extracted text",
            "markdown": "Raw extracted text",
            "title": "Raw title",
        }
        mock_filter.return_value = {
            "status": "failed",
            "text": "",
            "spanCount": 0,
            "promptVersion": "article-text-v1",
            "warnings": [],
            "retryTrace": [
                {
                    "attempt": 1,
                    "max_rounds": 8,
                    "retries_left": 7,
                    "failure_code": "old_str_not_unique",
                    "error_message": "not unique",
                    "next_action": "Use longer unique old_str",
                }
            ],
            "retryFailureCount": 1,
            "retryRoundsUsed": 3,
            "retryLastCode": "old_str_not_unique",
            "agenticLoop": {"version": "article-text-react-v1", "rounds_used": 3, "actions": [{"action": "delete_pass"}]},
            "error": {
                "code": "empty_spans",
                "message": "No spans",
                "details": {"retry_trace": [{"failure_code": "old_str_not_unique"}]},
            },
            "model": "gpt-5.4-nano",
        }
        references = [
            {
                "id": "reference-1",
                "lineageId": "lineage-1",
                "versionNumber": 1,
                "versionState": "current",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "item-1",
                "sourceUri": "https://example.com/article",
            }
        ]
        result = build_reference_url_text_attachment_plans(
            references=references,
            attachments=[],
            corpus_key_by_id={"knowledge-corpus-ai-ml-research": "AI-ML-research"},
            corpus_id="knowledge-corpus-ai-ml-research",
            curation_status="all",
            force=False,
        )

        self.assertEqual(result["fallbackRawCount"], 1)
        self.assertEqual(len(result["filterFallbacks"]), 1)
        canonical_plan = next(
            plan for plan in result["plans"] if plan["record"]["expected"]["role"] == "extracted_text"
        )
        canonical_body = canonical_plan["body"].decode("utf-8")
        self.assertEqual(canonical_body, "Raw extracted text")
        metadata = json.loads(canonical_plan["record"]["expected"]["metadata"])
        self.assertEqual(metadata["filterStatus"], "fallback_raw")
        self.assertEqual(metadata["filterRetryFailureCount"], 1)
        self.assertEqual(metadata["filterRetryRoundsUsed"], 3)
        self.assertEqual(metadata["filterRetryLastCode"], "old_str_not_unique")
        self.assertEqual(metadata["filterAgenticLoop"]["rounds_used"], 3)
        self.assertEqual(result["filterFallbacks"][0]["reason"]["details"]["retry_trace"][0]["failure_code"], "old_str_not_unique")

    @mock.patch("papyrus_content.reference_url_text.resolve_storage_bucket_name", return_value="test-bucket")
    @mock.patch("papyrus_content.reference_url_text._filter_article_text")
    @mock.patch("papyrus_content.reference_url_text.boto3")
    def test_build_reference_extracted_text_filter_attachment_plans_uses_raw_then_refreshes_canonical(
        self,
        mock_boto3,
        mock_filter,
        _mock_bucket,
    ):
        mock_s3 = mock.Mock()
        mock_s3.get_object.return_value = {"Body": io.BytesIO(b"Raw attachment body text")}
        mock_boto3.client.return_value = mock_s3
        mock_filter.return_value = {
            "status": "ok",
            "text": "Filtered canonical text",
            "spanCount": 1,
            "promptVersion": "article-text-v1",
            "warnings": [],
            "retryTrace": [],
            "retryFailureCount": 0,
            "retryRoundsUsed": 1,
            "retryLastCode": None,
            "error": None,
            "model": "gpt-5.4-nano",
        }
        references = [
            {
                "id": "reference-1",
                "lineageId": "lineage-1",
                "versionState": "current",
                "versionNumber": 1,
                "corpusId": "knowledge-corpus-ai-ml-research",
                "curationStatus": "accepted",
                "externalItemId": "item-1",
                "sourceUri": "https://example.com/article",
            }
        ]
        attachments = [
            {
                "id": "attachment-raw",
                "referenceLineageId": "lineage-1",
                "role": "extracted_text_raw",
                "storagePath": "corpora/AI-ML-research/extracted/markitdown/raw/lineage-1/extracted_text_raw.md",
            },
            {
                "id": "attachment-canonical",
                "referenceLineageId": "lineage-1",
                "role": "extracted_text",
                "storagePath": "corpora/AI-ML-research/extracted/markitdown/text/lineage-1/extracted_text.md",
            },
        ]
        result = build_reference_extracted_text_filter_attachment_plans(
            references=references,
            attachments=attachments,
            corpus_id="knowledge-corpus-ai-ml-research",
            curation_status="all",
            model="gpt-5.4-nano",
        )

        self.assertEqual(result["plannedCount"], 1)
        self.assertEqual(result["filteredCount"], 1)
        self.assertEqual(result["fallbackRawCount"], 0)
        self.assertEqual(result["processedReferenceIds"], ["reference-1"])
        self.assertEqual(result["plannedAttachmentCount"], 2)
        by_role = {plan["record"]["expected"]["role"]: plan for plan in result["plans"]}
        self.assertIn("extracted_text_raw", by_role)
        self.assertIn("extracted_text", by_role)
        canonical_plan = by_role["extracted_text"]
        self.assertEqual(canonical_plan["body"].decode("utf-8"), "Filtered canonical text")
        canonical_metadata = json.loads(canonical_plan["record"]["expected"]["metadata"])
        self.assertEqual(canonical_metadata["filterRetryFailureCount"], 0)
        self.assertEqual(canonical_metadata["filterRetryRoundsUsed"], 1)
        raw_plan = by_role["extracted_text_raw"]
        self.assertEqual(raw_plan["body"].decode("utf-8"), "Raw attachment body text")
        self.assertIn("markitdown/raw/lineage-1/extracted_text_raw.md", raw_plan["record"]["expected"]["storagePath"])

    @mock.patch("papyrus_content.reference_url_text.resolve_storage_bucket_name", return_value="test-bucket")
    @mock.patch("papyrus_content.reference_url_text._extract_url_text")
    @mock.patch("papyrus_content.reference_url_text._filter_article_text")
    @mock.patch("papyrus_content.reference_url_text.boto3")
    def test_filter_plans_reconstruct_raw_from_source_uri_when_canonical_is_filtered(
        self,
        mock_boto3,
        mock_filter,
        mock_extract,
        _mock_bucket,
    ):
        mock_boto3.client.return_value = mock.Mock()
        mock_extract.return_value = {
            "text": "Reconstructed raw text",
            "markdown": "Reconstructed raw text",
            "title": "Example title",
        }
        mock_filter.return_value = {
            "status": "ok",
            "text": "Filtered canonical text",
            "spanCount": 1,
            "promptVersion": "article-text-v1",
            "warnings": [],
            "retryTrace": [],
            "retryFailureCount": 0,
            "retryRoundsUsed": 1,
            "retryLastCode": None,
            "error": None,
            "model": "gpt-5.4-nano",
        }
        references = [
            {
                "id": "reference-1",
                "lineageId": "lineage-1",
                "versionState": "current",
                "versionNumber": 1,
                "corpusId": "knowledge-corpus-ai-ml-research",
                "curationStatus": "accepted",
                "externalItemId": "item-1",
                "sourceUri": "https://example.com/article",
            }
        ]
        attachments = [
            {
                "id": "attachment-canonical",
                "referenceLineageId": "lineage-1",
                "role": "extracted_text",
                "storagePath": "corpora/AI-ML-research/extracted/markitdown/text/lineage-1/extracted_text.md",
                "metadata": json.dumps({"filterStatus": "filtered", "source": "biblicus-article-text-filter"}),
            },
        ]
        result = build_reference_extracted_text_filter_attachment_plans(
            references=references,
            attachments=attachments,
            corpus_id="knowledge-corpus-ai-ml-research",
            curation_status="all",
            model="gpt-5.4-nano",
        )

        self.assertEqual(result["plannedCount"], 1)
        self.assertEqual(result["plannedAttachmentCount"], 2)
        mock_extract.assert_called_once_with("https://example.com/article", reference_title="")
        by_role = {plan["record"]["expected"]["role"]: plan for plan in result["plans"]}
        raw_plan = by_role["extracted_text_raw"]
        self.assertEqual(raw_plan["body"].decode("utf-8"), "Reconstructed raw text")
        raw_metadata = json.loads(raw_plan["record"]["expected"]["metadata"])
        self.assertEqual(raw_metadata["reconstructedFromSourceUri"], "https://example.com/article")

    @mock.patch("papyrus_content.reference_url_text.resolve_storage_bucket_name", return_value="test-bucket")
    @mock.patch("papyrus_content.reference_url_text.boto3")
    def test_filter_plans_skip_when_raw_missing_and_source_uri_missing_for_filtered_canonical(
        self,
        mock_boto3,
        _mock_bucket,
    ):
        mock_boto3.client.return_value = mock.Mock()
        references = [
            {
                "id": "reference-1",
                "lineageId": "lineage-1",
                "versionState": "current",
                "versionNumber": 1,
                "corpusId": "knowledge-corpus-ai-ml-research",
                "curationStatus": "accepted",
                "externalItemId": "item-1",
                "sourceUri": None,
            }
        ]
        attachments = [
            {
                "id": "attachment-canonical",
                "referenceLineageId": "lineage-1",
                "role": "extracted_text",
                "storagePath": "corpora/AI-ML-research/extracted/markitdown/text/lineage-1/extracted_text.md",
                "metadata": json.dumps({"filterStatus": "filtered", "source": "biblicus-article-text-filter"}),
            },
        ]
        result = build_reference_extracted_text_filter_attachment_plans(
            references=references,
            attachments=attachments,
            corpus_id="knowledge-corpus-ai-ml-research",
            curation_status="all",
            model="gpt-5.4-nano",
        )

        self.assertEqual(result["plannedCount"], 0)
        self.assertEqual(result["skippedMissingSourceCount"], 1)
        self.assertEqual(result["items"][0]["status"], "skipped_missing_source")

    @mock.patch("papyrus_content.reference_url_text._run_biblicus_article_text")
    def test_filter_article_text_includes_bounded_retry_trace_in_failure_reason(self, mock_run_article_text):
        mock_run_article_text.return_value = {
            "status": "failed",
            "text": "",
            "span_count": 0,
            "prompt_version": "article-text-v1",
            "warnings": [],
            "retry_failure_count": 3,
            "retry_rounds_used": 8,
            "agentic_loop": {"version": "article-text-react-v1", "rounds_used": 4, "actions": [{"action": "redo_extraction"}]},
            "retry_trace": [
                {
                    "attempt": 1,
                    "max_rounds": 8,
                    "retries_left": 7,
                    "failure_code": "old_str_not_found",
                    "error_message": "not found",
                    "next_action": "Call view",
                },
                {
                    "attempt": 2,
                    "max_rounds": 8,
                    "retries_left": 6,
                    "failure_code": "old_str_not_unique",
                    "error_message": "not unique",
                    "next_action": "Use longer old_str",
                },
            ],
            "error": {"code": "empty_spans", "message": "No spans"},
        }
        result = _filter_article_text(
            extracted_text="Noisy text",
            source_uri="https://example.com/article",
            reference_title="Title",
            original_title="Original title",
            original_subtitle="Original subtitle",
            model="gpt-5.4-nano",
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["retryFailureCount"], 3)
        self.assertEqual(result["retryRoundsUsed"], 8)
        self.assertEqual(result["retryLastCode"], "old_str_not_unique")
        self.assertEqual(result["agenticLoop"]["rounds_used"], 4)
        self.assertEqual(result["error"]["details"]["retry_trace"][0]["failure_code"], "old_str_not_found")

    @mock.patch("papyrus_content.reference_url_text._biblicus_python_executable", return_value="/usr/bin/python3")
    @mock.patch("papyrus_content.reference_url_text.BIBLICUS_ROOT", pathlib.Path("/tmp"))
    @mock.patch("papyrus_content.reference_url_text.subprocess.run")
    def test_run_biblicus_article_text_times_out(self, mock_run, _mock_python):
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["python3", "-m", "biblicus", "extract", "article-text"],
            timeout=ARTICLE_TEXT_SUBPROCESS_TIMEOUT_SECONDS,
        )
        with self.assertRaisesRegex(
            RuntimeError,
            f"timed out after {ARTICLE_TEXT_SUBPROCESS_TIMEOUT_SECONDS} seconds",
        ):
            _run_biblicus_article_text({"extracted_text": "hello"})

    @mock.patch("papyrus_content.reference_metadata_generation.resolve_storage_bucket_name", return_value="test-bucket")
    @mock.patch("papyrus_content.reference_metadata_generation.reference_curation_signals.reference_generate_metadata_from_extracted_text")
    @mock.patch("papyrus_content.reference_metadata_generation.boto3.client")
    def test_run_reference_metadata_generation_from_extracted_text_skips_missing_and_generates(
        self,
        mock_boto_client,
        mock_generate,
        _mock_bucket,
    ):
        mock_s3 = mock.Mock()
        mock_s3.get_object.return_value = {"Body": io.BytesIO(b"Full extracted text from attachment")}
        mock_boto_client.return_value = mock_s3
        mock_generate.return_value = {
            "status": "generated",
            "generated": {"title": "Generated title", "subtitle": "Generated subtitle", "summary": "Generated summary"},
        }
        references = [
            {
                "id": "reference-1",
                "lineageId": "lineage-1",
                "versionState": "current",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "curationStatus": "accepted",
                "externalItemId": "item-1",
                "title": "Original title",
            },
            {
                "id": "reference-2",
                "lineageId": "lineage-2",
                "versionState": "current",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "curationStatus": "accepted",
                "externalItemId": "item-2",
            },
        ]
        attachments = [
            {
                "id": "attachment-1",
                "referenceLineageId": "lineage-1",
                "role": "extracted_text",
                "storagePath": "corpora/AI-ML-research/extracted/markitdown/text/lineage-1/extracted_text.md",
            }
        ]
        result = run_reference_metadata_generation_from_extracted_text(
            references=references,
            attachments=attachments,
            corpus_id="knowledge-corpus-ai-ml-research",
            curation_status="all",
            model="gpt-5.4-nano",
            apply=True,
        )

        self.assertEqual(result["attemptedCount"], 2)
        self.assertEqual(result["generatedCount"], 1)
        self.assertEqual(result["skippedMissingTextCount"], 1)
        self.assertEqual(result["generationFailureCount"], 0)
        mock_generate.assert_called_once()
        call_kwargs = mock_generate.call_args.kwargs
        self.assertEqual(call_kwargs["reference_id"], "reference-1")
        self.assertEqual(call_kwargs["original_title"], "Original title")
        self.assertIn("Full extracted text", call_kwargs["extracted_text"])
        statuses = [item["status"] for item in result["items"]]
        self.assertIn("generated", statuses)
        self.assertIn("skipped_missing_text", statuses)

    def test_build_reference_scope_training_export_labels(self):
        corpus_config = {"key": "AI-ML-research", "name": "AI-ML-research", "path": "corpora/AI-ML-research"}
        corpus_id = "knowledge-corpus-ai-ml-research"
        references = [
            {
                "id": "reference-accepted",
                "lineageId": "lineage-accepted",
                "corpusId": corpus_id,
                "versionState": "current",
                "curationStatus": "accepted",
                "externalItemId": "accepted-1",
            },
            {
                "id": "reference-rejected",
                "lineageId": "lineage-rejected",
                "corpusId": corpus_id,
                "versionState": "current",
                "curationStatus": "rejected",
                "externalItemId": "rejected-1",
                "metadata": json.dumps({"reasonCode": "out_of_scope"}),
            },
        ]
        payload = build_reference_scope_training_export(
            corpus_config=corpus_config,
            corpus_id=corpus_id,
            references=references,
            attachments=[],
            messages=[],
            relations=[],
        )
        self.assertEqual(payload["counts"]["positive"], 1)
        self.assertEqual(payload["counts"]["negative"], 1)
        labels = {item["item_id"]: item["scope_training_label"] for item in payload["items"]}
        self.assertEqual(labels["accepted-1"], "in_scope")
        self.assertEqual(labels["rejected-1"], "out_of_scope")

    @mock.patch("papyrus_content.reference_url_text.storage_bucket_from_amplify_outputs", return_value="outputs-bucket")
    @mock.patch("papyrus_content.reference_url_text._graphql_endpoint_overrides_amplify_outputs", return_value=True)
    def test_resolve_storage_bucket_name_requires_explicit_bucket_when_endpoint_overridden(
        self,
        _mock_endpoint_override,
        _mock_outputs_bucket,
    ):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Pass --bucket or set PAPYRUS_MEDIA_BUCKET_NAME"):
                resolve_storage_bucket_name()

    @mock.patch("papyrus_content.reference_url_text.storage_bucket_from_amplify_outputs", return_value="outputs-bucket")
    @mock.patch("papyrus_content.reference_url_text._graphql_endpoint_overrides_amplify_outputs", return_value=True)
    def test_resolve_storage_bucket_name_prefers_explicit_bucket_when_endpoint_overridden(
        self,
        _mock_endpoint_override,
        _mock_outputs_bucket,
    ):
        with mock.patch.dict("os.environ", {"PAPYRUS_MEDIA_BUCKET_NAME": "explicit-bucket"}, clear=True):
            self.assertEqual(resolve_storage_bucket_name(), "explicit-bucket")

    @mock.patch("papyrus_content.reference_url_text._biblicus_python_executable", return_value="/usr/bin/python3")
    @mock.patch("papyrus_content.reference_url_text.BIBLICUS_ROOT", pathlib.Path("/tmp"))
    @mock.patch("papyrus_content.reference_url_text.subprocess.run")
    def test_extract_url_text_uses_biblicus_cli_success(self, mock_run, _mock_python):
        mock_run.return_value = mock.Mock(
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "ok",
                    "text": "Extracted from Biblicus",
                    "markdown": "# Extracted from Biblicus",
                    "title": "Example",
                    "source_kind": "web",
                    "strategy": "markdown-then-html-then-direct",
                    "content_type": "text/html",
                    "prompt_version": "url-text-v1",
                    "attempts": [{"step": "web_markdown_fetch", "result": "ok"}],
                }
            ),
            stderr="",
        )
        extracted = _extract_url_text("https://example.com/article", reference_title="Example")
        self.assertEqual(extracted["text"], "Extracted from Biblicus")
        self.assertEqual(extracted["sourceKind"], "web")
        self.assertEqual(extracted["strategy"], "markdown-then-html-then-direct")
        self.assertEqual(extracted["promptVersion"], "url-text-v1")

    def test_resolve_grobid_url_prefers_option_then_env_then_default(self):
        with mock.patch.dict("os.environ", {"BIBLICUS_GROBID_URL": "http://env:8070"}, clear=True):
            self.assertEqual(_resolve_grobid_url({}), "http://env:8070")
            self.assertEqual(_resolve_grobid_url({"grobid-url": "http://flag:8070"}), "http://flag:8070")
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(_resolve_grobid_url({}), "http://127.0.0.1:8070")

    @mock.patch("papyrus_content.references_commands._await_grobid_ready")
    @mock.patch("papyrus_content.references_commands._start_or_reuse_local_grobid_container")
    @mock.patch("papyrus_content.references_commands._grobid_is_alive")
    def test_ensure_cli_grobid_runtime_starts_local_container_when_unavailable(
        self,
        mock_alive,
        mock_start,
        mock_await,
    ):
        mock_alive.return_value = False
        _ensure_cli_grobid_runtime("http://127.0.0.1:8070")
        mock_start.assert_called_once_with(port=8070)
        mock_await.assert_called_once_with("http://127.0.0.1:8070")

    @mock.patch("papyrus_content.references_commands._grobid_is_alive", return_value=False)
    def test_ensure_cli_grobid_runtime_remote_endpoint_requires_live_service(self, _mock_alive):
        with self.assertRaisesRegex(RuntimeError, "not reachable"):
            _ensure_cli_grobid_runtime("http://grobid.internal:8070")

    @mock.patch("papyrus_content.reference_url_text._biblicus_python_executable", return_value="/usr/bin/python3")
    @mock.patch("papyrus_content.reference_url_text.BIBLICUS_ROOT", pathlib.Path("/tmp"))
    @mock.patch("papyrus_content.reference_url_text.subprocess.run")
    def test_extract_url_text_uses_biblicus_structured_failure(self, mock_run, _mock_python):
        mock_run.return_value = mock.Mock(
            returncode=2,
            stdout=json.dumps({"status": "failed", "error": {"code": "blocked", "message": "blocked by source"}}),
            stderr="blocked by source",
        )
        with self.assertRaises(ReferenceUrlTextExtractionError) as context:
            _extract_url_text("https://example.com/article")
        self.assertEqual(context.exception.reason["code"], "blocked")

    @mock.patch("papyrus_content.reference_url_text._biblicus_python_executable", return_value="/usr/bin/python3")
    @mock.patch("papyrus_content.reference_url_text.BIBLICUS_ROOT", pathlib.Path("/tmp"))
    @mock.patch("papyrus_content.reference_url_text.subprocess.run")
    def test_extract_url_text_passes_grobid_url_to_biblicus_env(self, mock_run, _mock_python):
        mock_run.return_value = mock.Mock(
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "ok",
                    "text": "Extracted from Biblicus",
                    "markdown": "Extracted from Biblicus",
                    "source_kind": "pdf",
                    "strategy": "pdf-grobid-only",
                    "content_type": "application/pdf",
                    "method": "grobid",
                    "grobid": {"base_url": "http://127.0.0.1:8070"},
                }
            ),
            stderr="",
        )
        _extract_url_text(
            "https://example.com/paper.pdf",
            reference_title="Example",
            grobid_url="http://127.0.0.1:8070",
        )
        call_kwargs = mock_run.call_args.kwargs
        self.assertEqual(call_kwargs["env"]["BIBLICUS_GROBID_URL"], "http://127.0.0.1:8070")

    def test_source_site_enrichment_default_tracks_uri_identifiers(self):
        result = resolve_source_site_enrichment(
            reference={"id": "reference-1"},
            source_uri="https://example.com/story",
        )
        self.assertEqual(result["pluginKey"], "default")
        self.assertEqual(result["canonicalSourceUri"], "https://example.com/story")
        self.assertEqual(result["identifiers"]["resolved"]["source_uri"], "https://example.com/story")
        self.assertEqual(result["identifiers"]["resolved"]["canonical_uri"], "https://example.com/story")
        self.assertEqual(result["identifiers"]["primary"]["type"], "canonical_uri")

    def test_source_site_enrichment_arxiv_resolves_urls_abstract_and_identifiers(self):
        abs_html = """
            <html><head>
            <script type=\"application/ld+json\">
            {
              \"@context\": \"https://schema.org\",
              \"@type\": \"ScholarlyArticle\",
              \"description\": \"A structured abstract from JSON-LD.\",
              \"identifier\": {\"@type\": \"PropertyValue\", \"propertyID\": \"doi\", \"value\": \"10.1234/example-doi\"}
            }
            </script>
            </head></html>
        """
        result = resolve_source_site_enrichment(
            reference={"id": "reference-1"},
            source_uri="https://arxiv.org/html/2504.16736v2",
            fetcher=lambda _url: abs_html,
        )
        self.assertEqual(result["pluginKey"], "arxiv")
        self.assertEqual(result["canonicalSourceUri"], "https://arxiv.org/pdf/2504.16736v2.pdf")
        self.assertEqual(result["identifiers"]["resolved"]["arxiv_id"], "2504.16736v2")
        self.assertEqual(result["identifiers"]["resolved"]["doi"], "10.1234/example-doi")
        self.assertEqual(result["metadata"]["abstract"], "A structured abstract from JSON-LD.")
        self.assertEqual(result["identifiers"]["primary"], {"type": "arxiv_id", "value": "2504.16736v2"})

    def test_source_site_enrichment_youtube_stub_resolves_video_id(self):
        result = resolve_source_site_enrichment(
            reference={"id": "reference-yt"},
            source_uri="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )
        self.assertEqual(result["pluginKey"], "youtube")
        self.assertEqual(result["canonicalSourceUri"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(result["identifiers"]["resolved"]["youtube_video_id"], "dQw4w9WgXcQ")
        warning_codes = {str(entry.get("code") or "") for entry in result["warnings"] if isinstance(entry, dict)}
        self.assertIn("youtube_transcript_via_markitdown", warning_codes)

    def test_source_site_enrichment_acl_anthology_prefers_pdf(self):
        result = resolve_source_site_enrichment(
            reference={"id": "reference-acl"},
            source_uri="https://aclanthology.org/2024.findings-acl.890/",
        )
        self.assertEqual(result["pluginKey"], "acl_anthology")
        self.assertEqual(result["canonicalSourceUri"], "https://aclanthology.org/2024.findings-acl.890.pdf")
        self.assertEqual(result["identifiers"]["resolved"]["acl_anthology_id"], "2024.findings-acl.890")
        self.assertEqual(result["sourceVariants"]["canonicalLandingUrl"], "https://aclanthology.org/2024.findings-acl.890/")

    @mock.patch(
        "papyrus_content.source_site_plugins._select_verified_pdf_candidate",
        return_value=("https://dl.acm.org/doi/pdf/10.1145/122344.122377?download=true", "acm_canonical", False),
    )
    def test_source_site_enrichment_acm_resolves_urls_abstract_and_identifiers(self, _mock_select):
        landing_html = """
            <html><head>
            <script type=\"application/ld+json\">
            {
              \"@context\": \"https://schema.org\",
              \"@type\": \"ScholarlyArticle\",
              \"description\": \"An ACM abstract from JSON-LD.\"
            }
            </script>
            </head>
            <body>
            <div class=\"article__abstract\"><p>Fallback abstract paragraph.</p></div>
            </body></html>
        """
        result = resolve_source_site_enrichment(
            reference={"id": "reference-acm"},
            source_uri="https://dl.acm.org/doi/10.1145/122344.122377",
            fetcher=lambda _url: landing_html,
        )
        self.assertEqual(result["pluginKey"], "acm")
        self.assertEqual(
            result["canonicalSourceUri"],
            "https://dl.acm.org/doi/pdf/10.1145/122344.122377?download=true",
        )
        self.assertEqual(result["identifiers"]["resolved"]["doi"], "10.1145/122344.122377")
        self.assertEqual(result["metadata"]["abstract"], "An ACM abstract from JSON-LD.")
        self.assertEqual(result["identifiers"]["primary"], {"type": "doi", "value": "10.1145/122344.122377"})
        self.assertEqual(
            result["sourceVariants"]["canonicalLandingUrl"],
            "https://dl.acm.org/doi/10.1145/122344.122377",
        )

    @mock.patch(
        "papyrus_content.source_site_plugins._select_verified_pdf_candidate",
        return_value=("https://dl.acm.org/doi/pdf/10.1145/122344.122377?download=true", "acm_canonical", False),
    )
    def test_source_site_enrichment_acm_beats_generic_doi_plugin(self, _mock_select):
        result = resolve_source_site_enrichment(
            reference={"id": "reference-acm-doi"},
            source_uri="https://dl.acm.org/doi/abs/10.1145/122344.122377",
            fetcher=lambda _url: "<html></html>",
        )
        self.assertEqual(result["pluginKey"], "acm")
        self.assertEqual(result["identifiers"]["resolved"]["doi"], "10.1145/122344.122377")

    @mock.patch("papyrus_content.source_site_plugins._search_pdf_candidates")
    @mock.patch("papyrus_content.source_site_plugins._metadata_pdf_candidates", return_value=[])
    def test_source_site_enrichment_acm_pdf_fallback_when_publisher_blocked(
        self,
        _mock_metadata,
        mock_search,
    ) -> None:
        mock_search.return_value = ["http://incompleteideas.net/papers/sutton-90.pdf"]

        def _probe(url: str) -> dict[str, Any]:
            if "dl.acm.org" in url:
                return {"ok": False, "isPdf": False, "status": 403, "contentType": "text/html", "blocked": True}
            if url.endswith(".pdf"):
                return {"ok": True, "isPdf": True, "status": 200, "contentType": "application/pdf", "blocked": False}
            return {"ok": False, "isPdf": False, "status": 404, "contentType": "text/html", "blocked": False}

        with mock.patch("papyrus_content.source_site_plugins._probe_pdf_url", side_effect=_probe):
            result = resolve_source_site_enrichment(
                reference={
                    "id": "reference-acm",
                    "title": "Dyna, an integrated architecture for learning, planning, and reacting",
                },
                source_uri="https://dl.acm.org/doi/10.1145/122344.122377",
                fetcher=lambda _url: "<html></html>",
            )
        self.assertEqual(result["pluginKey"], "acm")
        self.assertEqual(result["canonicalSourceUri"], "http://incompleteideas.net/papers/sutton-90.pdf")
        self.assertTrue(result["metadata"]["pdfResolution"]["searchHit"])
        warning_codes = {entry.get("code") for entry in result["warnings"] if isinstance(entry, dict)}
        self.assertIn("acm_pdf_fallback", warning_codes)

    @mock.patch("papyrus_content.source_site_plugins._metadata_pdf_candidates", return_value=[])
    @mock.patch("papyrus_content.source_site_plugins._search_pdf_candidates", return_value=[])
    @mock.patch("papyrus_content.source_site_plugins._pdf_links_from_landing_page", return_value=[])
    @mock.patch("papyrus_content.source_site_plugins._pdf_candidates_from_final_url", return_value=[])
    @mock.patch(
        "papyrus_content.source_site_plugins._select_verified_pdf_candidate",
        return_value=("https://aclanthology.org/2020.emnlp-main.550.pdf", "delegated_plugin", False),
    )
    @mock.patch(
        "papyrus_content.source_site_plugins._resolve_redirect_chain",
        return_value={
            "chain": [{"url": "https://doi.org/10.18653/v1/2020.emnlp-main.550", "status": 302}],
            "finalUrl": "https://aclanthology.org/2020.emnlp-main.550/",
            "contentType": "text/html; charset=utf-8",
        },
    )
    def test_source_site_enrichment_doi_resolves_to_acl_pdf(
        self,
        _mock_redirect,
        _mock_select,
        _mock_candidates,
        _mock_landing,
        _mock_search,
        _mock_metadata,
    ):
        result = resolve_source_site_enrichment(
            reference={"id": "reference-doi"},
            source_uri="https://doi.org/10.18653/v1/2020.emnlp-main.550",
        )
        self.assertEqual(result["pluginKey"], "doi")
        self.assertEqual(result["canonicalSourceUri"], "https://aclanthology.org/2020.emnlp-main.550.pdf")
        resolution = result["metadata"]["doiResolution"]
        self.assertEqual(resolution["outcome"], "pdf_selected")
        self.assertFalse(resolution["searchUsed"])
        self.assertFalse(resolution["apiFallbackUsed"])

    @mock.patch("papyrus_content.source_site_plugins._metadata_pdf_candidates", return_value=[])
    @mock.patch(
        "papyrus_content.source_site_plugins._search_pdf_candidates",
        return_value=["https://example.org/paper.pdf"],
    )
    @mock.patch("papyrus_content.source_site_plugins._pdf_links_from_landing_page", return_value=[])
    @mock.patch("papyrus_content.source_site_plugins._pdf_candidates_from_final_url", return_value=[])
    @mock.patch(
        "papyrus_content.source_site_plugins._select_verified_pdf_candidate",
        side_effect=[("", "", False), ("https://example.org/paper.pdf", "web_search", False)],
    )
    @mock.patch(
        "papyrus_content.source_site_plugins._resolve_redirect_chain",
        return_value={
            "chain": [{"url": "https://doi.org/10.1234/example", "status": 302}],
            "finalUrl": "https://publisher.example.com/article",
            "contentType": "text/html; charset=utf-8",
        },
    )
    def test_source_site_enrichment_doi_uses_search_fallback(
        self,
        _mock_redirect,
        _mock_select,
        _mock_candidates,
        _mock_landing,
        _mock_search,
        _mock_metadata,
    ):
        result = resolve_source_site_enrichment(
            reference={
                "id": "reference-doi",
                "title": "A useful paper",
                "authors": ["Ada Lovelace", "Alan Turing"],
                "metadata": json.dumps({"subtitle": "Practical retrieval systems"}),
            },
            source_uri="https://doi.org/10.1234/example",
        )
        self.assertEqual(result["pluginKey"], "doi")
        resolution = result["metadata"]["doiResolution"]
        self.assertEqual(resolution["outcome"], "pdf_selected")
        self.assertTrue(resolution["searchUsed"])
        self.assertTrue(resolution["searchHit"])
        self.assertFalse(resolution["apiFallbackUsed"])
        search_candidates = [row for row in (resolution.get("candidates") or []) if row.get("source") == "web_search"]
        self.assertTrue(search_candidates)
        self.assertIn("A useful paper", str(search_candidates[0].get("query") or ""))
        self.assertIn("PDF", str(search_candidates[0].get("query") or ""))

    @mock.patch(
        "papyrus_content.source_site_plugins._metadata_pdf_candidates",
        return_value=[{"url": "https://repo.example.org/paper.pdf", "source": "crossref"}],
    )
    @mock.patch("papyrus_content.source_site_plugins._search_pdf_candidates", return_value=[])
    @mock.patch("papyrus_content.source_site_plugins._pdf_links_from_landing_page", return_value=[])
    @mock.patch("papyrus_content.source_site_plugins._pdf_candidates_from_final_url", return_value=[])
    @mock.patch(
        "papyrus_content.source_site_plugins._select_verified_pdf_candidate",
        side_effect=[("", "", False), ("", "", False), ("https://repo.example.org/paper.pdf", "crossref", False)],
    )
    @mock.patch(
        "papyrus_content.source_site_plugins._resolve_redirect_chain",
        return_value={
            "chain": [{"url": "https://doi.org/10.5678/example", "status": 302}],
            "finalUrl": "https://publisher.example.com/article",
            "contentType": "text/html; charset=utf-8",
        },
    )
    def test_source_site_enrichment_doi_uses_metadata_fallback(
        self,
        _mock_redirect,
        _mock_select,
        _mock_candidates,
        _mock_landing,
        _mock_search,
        _mock_metadata,
    ):
        result = resolve_source_site_enrichment(
            reference={"id": "reference-doi"},
            source_uri="https://doi.org/10.5678/example",
        )
        resolution = result["metadata"]["doiResolution"]
        self.assertEqual(resolution["outcome"], "pdf_selected")
        self.assertTrue(resolution["searchUsed"])
        self.assertFalse(resolution["searchHit"])
        self.assertTrue(resolution["apiFallbackUsed"])

    @mock.patch("papyrus_content.source_site_plugins._metadata_pdf_candidates", return_value=[])
    @mock.patch("papyrus_content.source_site_plugins._pdf_links_from_landing_page", return_value=["https://example.org/from-page.pdf"])
    @mock.patch("papyrus_content.source_site_plugins._pdf_candidates_from_final_url", return_value=[])
    @mock.patch(
        "papyrus_content.source_site_plugins._search_pdf_candidates",
        return_value=["https://example.org/landing"],
    )
    @mock.patch(
        "papyrus_content.source_site_plugins._select_verified_pdf_candidate",
        side_effect=[("", "", False), ("https://example.org/from-page.pdf", "web_search_landing_page", False)],
    )
    @mock.patch(
        "papyrus_content.source_site_plugins._resolve_redirect_chain",
        return_value={
            "chain": [{"url": "https://doi.org/10.4321/example", "status": 302}],
            "finalUrl": "https://publisher.example.com/article",
            "contentType": "text/html; charset=utf-8",
        },
    )
    def test_source_site_enrichment_doi_search_checks_landing_pages(
        self,
        _mock_redirect,
        _mock_select,
        _mock_candidates,
        _mock_landing,
        _mock_search,
        _mock_metadata,
    ):
        result = resolve_source_site_enrichment(
            reference={
                "id": "reference-doi",
                "title": "A useful paper",
                "authors": ["Ada Lovelace", "Alan Turing"],
                "metadata": json.dumps({"subtitle": "Practical retrieval systems"}),
            },
            source_uri="https://doi.org/10.4321/example",
        )
        resolution = result["metadata"]["doiResolution"]
        self.assertEqual(resolution["outcome"], "pdf_selected")
        self.assertTrue(resolution["searchUsed"])
        self.assertTrue(resolution["searchHit"])
        self.assertEqual(resolution["selectedPdfSource"], "web_search_landing_page")

    @mock.patch("papyrus_content.reference_url_text.resolve_source_site_enrichment")
    @mock.patch("papyrus_content.reference_url_text._extract_url_text")
    @mock.patch("papyrus_content.reference_url_text._filter_article_text")
    def test_build_reference_url_text_attachment_plans_uses_enrichment_canonical_uri_and_reference_metadata(
        self,
        mock_filter,
        mock_extract,
        mock_enrich,
    ):
        mock_enrich.return_value = {
            "pluginKey": "arxiv",
            "canonicalSourceUri": "https://arxiv.org/pdf/2504.16736v2.pdf",
            "sourceVariants": {
                "inputUrl": "https://arxiv.org/html/2504.16736v2",
                "canonicalPdfUrl": "https://arxiv.org/pdf/2504.16736v2.pdf",
                "canonicalAbsUrl": "https://arxiv.org/abs/2504.16736v2",
                "canonicalHtmlUrl": "https://arxiv.org/html/2504.16736v2",
            },
            "identifiers": {
                "resolved": {
                    "arxiv_id": "2504.16736v2",
                    "source_uri": "https://arxiv.org/html/2504.16736v2",
                    "canonical_uri": "https://arxiv.org/pdf/2504.16736v2.pdf",
                },
                "candidates": [
                    {
                        "type": "arxiv_id",
                        "value": "2504.16736v2",
                        "source": "arxiv_url",
                        "confidence": 1.0,
                        "rank": 10,
                    }
                ],
                "primary": {"type": "arxiv_id", "value": "2504.16736v2"},
                "warnings": [],
            },
            "metadata": {
                "paperId": "2504.16736v2",
                "abstract": "An abstract.",
            },
            "attachmentMetadata": {
                "sitePlugin": "arxiv",
            },
            "warnings": [],
        }
        mock_extract.return_value = {
            "text": "Example plain text",
            "markdown": "# Example plain text",
            "title": "Example Title",
            "sourceKind": "pdf",
            "contentType": "application/pdf",
            "structured": {
                "authors": [],
                "citations": [],
                "summary": {"authors_count": 0, "citations_count": 0, "citations_with_identifiers": 0},
                "warnings": [],
            },
        }
        mock_filter.return_value = {
            "status": "ok",
            "text": "Filtered article text",
            "spanCount": 1,
            "promptVersion": "article-text-v1",
            "warnings": [],
            "retryTrace": [],
            "retryFailureCount": 0,
            "retryRoundsUsed": 2,
            "retryLastCode": None,
            "error": None,
            "model": "gpt-5.4-nano",
        }
        references = [
            {
                "id": "reference-1",
                "lineageId": "lineage-1",
                "versionNumber": 1,
                "versionState": "current",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "item-1",
                "sourceUri": "https://arxiv.org/html/2504.16736v2",
                "metadata": json.dumps({}),
            }
        ]
        result = build_reference_url_text_attachment_plans(
            references=references,
            attachments=[],
            corpus_key_by_id={"knowledge-corpus-ai-ml-research": "AI-ML-research"},
            corpus_id="knowledge-corpus-ai-ml-research",
            curation_status="all",
            force=False,
        )
        mock_extract.assert_called_once_with(
            "https://arxiv.org/pdf/2504.16736v2.pdf",
            reference_title="",
            grobid_url=None,
        )
        self.assertEqual(result["plannedReferenceMetadataCount"], 1)
        reference_record = result["referenceRecords"][0]["expected"]
        metadata = json.loads(reference_record["metadata"])
        self.assertEqual(metadata["papyrus"]["source_resolution"]["arxiv"]["paperId"], "2504.16736v2")
        self.assertEqual(metadata["identifiers"]["resolved"]["source_uri"], "https://arxiv.org/html/2504.16736v2")
        self.assertEqual(metadata["identifiers"]["resolved"]["canonical_uri"], "https://arxiv.org/pdf/2504.16736v2.pdf")
        raw_plan = next(plan for plan in result["plans"] if plan["record"]["expected"]["role"] == "extracted_text_raw")
        raw_metadata = json.loads(raw_plan["record"]["expected"]["metadata"])
        self.assertEqual(raw_metadata["sourceUri"], "https://arxiv.org/pdf/2504.16736v2.pdf")
        self.assertEqual(raw_metadata["sourceUriOriginal"], "https://arxiv.org/html/2504.16736v2")
        self.assertEqual(raw_metadata["sourcePlugin"], "arxiv")

    @mock.patch("papyrus_content.reference_url_text._download_source_attachment_from_uri", return_value=b"%PDF-test")
    @mock.patch("papyrus_content.reference_url_text.resolve_source_site_enrichment")
    @mock.patch("papyrus_content.reference_url_text._extract_url_text")
    @mock.patch("papyrus_content.reference_url_text._filter_article_text")
    def test_build_reference_url_text_attachment_plans_tracks_doi_resolution_counters(
        self,
        mock_filter,
        mock_extract,
        mock_enrich,
        _mock_download,
    ):
        mock_enrich.return_value = {
            "pluginKey": "doi",
            "canonicalSourceUri": "https://example.org/paper.pdf",
            "sourceVariants": {"inputUrl": "https://doi.org/10.1111/example", "selectedPdfUrl": "https://example.org/paper.pdf"},
            "identifiers": {"resolved": {"doi": "10.1111/example"}, "candidates": [], "primary": {"type": "doi", "value": "10.1111/example"}, "warnings": []},
            "metadata": {"doi": "10.1111/example", "doiResolution": {"outcome": "pdf_selected", "searchUsed": True, "searchHit": True, "apiFallbackUsed": False, "paywalledOrBlocked": False}},
            "attachmentMetadata": {"sitePlugin": "doi"},
            "warnings": [],
        }
        mock_extract.return_value = {"text": "pdf text", "markdown": "pdf text", "sourceKind": "pdf", "contentType": "application/pdf"}
        mock_filter.return_value = {
            "status": "ok",
            "text": "pdf text",
            "spanCount": 1,
            "promptVersion": "pdf-pass-through-v1",
            "warnings": [],
            "retryTrace": [],
            "retryFailureCount": 0,
            "retryRoundsUsed": 0,
            "retryLastCode": None,
            "error": None,
            "model": "passthrough",
        }
        result = build_reference_url_text_attachment_plans(
            references=[
                {
                    "id": "reference-1",
                    "lineageId": "lineage-1",
                    "versionNumber": 1,
                    "versionState": "current",
                    "corpusId": "knowledge-corpus-ai-ml-research",
                    "externalItemId": "doi:10.1111/example",
                    "sourceUri": "https://doi.org/10.1111/example",
                    "metadata": json.dumps({}),
                }
            ],
            attachments=[],
            corpus_key_by_id={"knowledge-corpus-ai-ml-research": "AI-ML-research"},
            corpus_id="knowledge-corpus-ai-ml-research",
            curation_status="all",
            force=True,
        )
        self.assertEqual(result["doiResolvedCount"], 1)
        self.assertEqual(result["doiPdfSelectedCount"], 1)
        self.assertEqual(result["doiPdfMissedCount"], 0)
        self.assertEqual(result["doiSearchUsedCount"], 1)
        self.assertEqual(result["doiSearchHitCount"], 1)
        self.assertEqual(result["doiApiFallbackUsedCount"], 0)
        self.assertEqual(result["doiPaywalledOrBlockedCount"], 0)

    def test_build_manual_authoritative_label_relation_shape(self):
        relation = build_manual_authoritative_label_relation(
            reference={"id": "reference-1", "lineageId": "lineage-1", "versionNumber": 1},
            category={"id": "category-1", "lineageId": "category-lineage-1", "versionNumber": 1, "categoryKey": "topic.ml"},
            category_set={"id": "category-set-1", "classifierId": "ai-ml-v1"},
            note="manual label",
            actor="tester",
        )
        self.assertEqual(relation["predicate"], "authoritative_label")
        self.assertEqual(relation["subjectId"], "reference-1")
        self.assertEqual(relation["objectId"], "category-1")

    def test_build_classification_prediction_rows_filters_by_corpus(self):
        relations = [
            {
                "id": "relation-1",
                "relationState": "current",
                "relationTypeKey": "classified_as",
                "subjectKind": "reference",
                "objectKind": "category",
                "subjectLineageId": "lineage-1",
                "objectLineageId": "category-lineage-1",
                "subjectStateKey": "reference#lineage-1#current",
                "objectStateKey": "category#category-lineage-1#current",
            }
        ]
        references = [
            {
                "id": "reference-1",
                "lineageId": "lineage-1",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "versionState": "current",
                "externalItemId": "item-1",
            }
        ]
        categories = [
            {
                "id": "category-1",
                "lineageId": "category-lineage-1",
                "categorySetId": "category-set-1",
                "versionState": "current",
                "categoryKey": "topic.ml",
            }
        ]
        rows = build_classification_prediction_rows(
            relations=relations,
            references=references,
            categories=categories,
            corpus_id="knowledge-corpus-ai-ml-research",
            category_set_id="category-set-1",
            status="current",
            limit=None,
        )
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["hasAuthoritativeLabel"])

    def test_reference_manifest_item_includes_attachments(self):
        reference = {"id": "reference-1", "lineageId": "lineage-1", "externalItemId": "item-1", "title": "Title"}
        attachments = [
            {"referenceLineageId": "lineage-1", "role": "source", "sortKey": "100-source", "storagePath": "corpora/x/y.pdf"}
        ]
        item = reference_manifest_item(reference, attachments)
        self.assertEqual(item["item_id"], "item-1")
        self.assertEqual(len(item["attachments"]), 1)

    def test_extract_last_json_object_reads_trailing_json_line(self):
        payload = extract_last_json_object('log line\n{"ok": true, "runId": "abc"}\n')
        self.assertEqual(payload, {"ok": True, "runId": "abc"})

    @mock.patch("papyrus_content.references_commands.subprocess.run")
    def test_curate_recent_prints_summary_from_json(self, mock_run):
        from papyrus_content.references_commands import references_curate_recent

        mock_run.return_value = mock.Mock(
            returncode=0,
            stdout='{"runId":"run-1","manifestPath":"/tmp/manifest.json","apply":false,"ok":true,"degraded":false,"summary":{"selectedCount":2,"processedCount":2,"succeededCount":2,"failedCount":0},"items":[],"warnings":[]}\n',
            stderr="",
        )
        with mock.patch("builtins.print") as mock_print:
            references_curate_recent(["--corpus-key", "AI-ML-research"])
        printed = "\n".join(str(call.args[0]) for call in mock_print.call_args_list)
        self.assertIn("references\tcurate-recent\trun\trun-1", printed)
        self.assertRegex(printed, r"references\tcurate-recent\tselected\t\d+")


if __name__ == "__main__":
    unittest.main()
