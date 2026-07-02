import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content import cli as papyrus_content_cli
from papyrus_content.catalog import build_prepared_reference_catalog, build_reference_catalog_registration_records, catalog_items
from papyrus_content.ids import hash_short, knowledge_corpus_id, reference_lineage_id_for
from papyrus_content.model_attachments import build_text_model_payload_attachment
from papyrus_content.papyrus_config import (
    build_newsroom_reference_public_url,
    load_papyrus_config,
    normalize_papyrus_config,
    resolve_public_site_base_url,
    resolve_topics_ignore_terms,
)
from papyrus_content.seed_edition import build_seed_edition_records, load_seed_payload, seed_edition_config
from papyrus_content.source_readiness import reference_source_readiness
from papyrus_content.steering import load_steering_config, require_corpus_config, resolve_corpus_local_path


class PapyrusContentTests(unittest.TestCase):
    def test_is_ported_command(self) -> None:
        self.assertTrue(papyrus_content_cli.is_ported_command("corpora", "status"))
        self.assertTrue(papyrus_content_cli.is_ported_command("references", "create-from-catalog"))
        self.assertTrue(papyrus_content_cli.is_ported_command("references", "process-status"))
        self.assertTrue(papyrus_content_cli.is_ported_command("references", "process-accession-now"))
        self.assertTrue(papyrus_content_cli.is_ported_command("content", "inspect"))
        self.assertTrue(papyrus_content_cli.is_ported_command("content", "seed-edition"))
        self.assertTrue(papyrus_content_cli.is_ported_command("assignments", "list"))
        self.assertTrue(papyrus_content_cli.is_ported_command("assignments", "process-proposals"))
        self.assertTrue(papyrus_content_cli.is_ported_command("assignments", "orphan-research-packets"))
        self.assertFalse(papyrus_content_cli.is_ported_command("references", "register-catalog"))
        self.assertFalse(papyrus_content_cli.is_ported_command("references", "source-status"))
        self.assertFalse(papyrus_content_cli.is_ported_command("references", "accession-now"))
        self.assertFalse(papyrus_content_cli.is_ported_command("assignments", "intake-proposals"))

    def test_seed_edition_payload_builds_current_edition_records(self) -> None:
        payload = load_seed_payload(REPO_ROOT / "amplify" / "seed" / "seed-edition-content.json")
        records = build_seed_edition_records(payload)
        by_model = {}
        for record in records:
            by_model.setdefault(record["modelName"], []).append(record["expected"])
        self.assertEqual(payload["id"], "edition-current")
        self.assertEqual(len(by_model["Item"]), len(payload["articles"]))
        self.assertEqual(len(by_model["PublishedItem"]), len(payload["articles"]))
        self.assertEqual(len(by_model["EditionItem"]), len(payload["articles"]))
        self.assertIn("papyrus-data-ownership", [article["slug"] for article in payload["articles"]])
        self.assertEqual(by_model["Edition"][0]["status"], "published")
        self.assertTrue(by_model["Edition"][0]["contentHash"].startswith("sha256:"))

    def test_seed_edition_layout_plan_references_seeded_items(self) -> None:
        payload = load_seed_payload(REPO_ROOT / "amplify" / "seed" / "seed-edition-content.json")
        article_ids = {article["slug"] for article in payload["articles"]}
        config = seed_edition_config(payload)
        referenced = set()
        for page in config["layoutPlan"]["pages"]:
            for region in page["regions"]:
                for block in region["blocks"]:
                    if block.get("itemId"):
                        referenced.add(block["itemId"])
        self.assertFalse(referenced - article_ids)

    def test_analysis_profiles_load(self) -> None:
        from papyrus_content.analysis_profiles import load_analysis_profiles, summarize_analysis_profiles

        config = load_analysis_profiles(REPO_ROOT / "corpora" / "papyrus-analysis-profiles.yml")
        summaries = summarize_analysis_profiles(config)
        self.assertGreaterEqual(len(summaries), 1)

    def test_steering_config_loads(self) -> None:
        config = load_steering_config(str(REPO_ROOT / "corpora" / "papyrus-steering.yml"))
        self.assertIsNotNone(config)
        assert config is not None
        self.assertGreaterEqual(len(config["corpora"]), 1)

    def test_build_reference_catalog_registration_records(self) -> None:
        config = load_steering_config(str(REPO_ROOT / "corpora" / "papyrus-steering.yml"))
        assert config is not None
        corpus = require_corpus_config(config, config["canonicalTopicSet"]["corpusKey"])
        catalog = {
            "items": [
                {
                    "item_id": "item-1",
                    "title": "Sample paper",
                    "source_uri": "https://arxiv.org/abs/0000.00001",
                    "ingestion_rationale": "Prospect for the pilot corpus.",
                }
            ]
        }
        plan = build_reference_catalog_registration_records(
            catalog,
            {
                "corpusConfig": corpus,
                "corpusId": knowledge_corpus_id(corpus),
                "classifierId": config["canonicalTopicSet"]["classifierId"],
                "status": "pending",
                "actor": "test",
            },
        )
        self.assertEqual(plan["itemCount"], 1)
        models = {entry["modelName"] for entry in plan["records"]}
        self.assertIn("Reference", models)
        self.assertIn("Assignment", models)
        self.assertIn("KnowledgeImportRun", models)

    def test_prepare_catalog_adds_missing_rationale(self) -> None:
        prepared = build_prepared_reference_catalog(
            {"items": [{"item_id": "x", "title": "Title", "source_uri": "https://example.com/paper"}]},
            {"corpusKey": "demo", "publicationName": "Demo Publication"},
        )
        item = catalog_items(prepared)[0]
        self.assertIn("ingestion_rationale", item)

    def test_prepare_catalog_assigns_youtube_item_id_and_media_type(self) -> None:
        prepared = build_prepared_reference_catalog(
            {
                "items": [
                    {
                        "title": "Neural networks",
                        "source_uri": "https://www.youtube.com/watch?v=aircAruvnKk",
                    }
                ]
            },
            {"corpusKey": "demo", "publicationName": "Demo Publication"},
        )
        item = catalog_items(prepared)[0]
        self.assertEqual(item["item_id"], "yt-aircaruvnkk")
        self.assertEqual(item["media_type"], "video/youtube")

    def test_catalog_external_item_id_for_url_only_source(self) -> None:
        from papyrus_content.catalog import catalog_external_item_id_for
        from papyrus_content.ids import hash_short

        source_uri = "https://example.com/paper.pdf"
        self.assertEqual(
            catalog_external_item_id_for({"source_uri": source_uri}),
            f"url-ref-{hash_short(source_uri)}",
        )

    def test_resolve_process_source_uri_uses_youtube_source_uri_without_find_metadata(self) -> None:
        from papyrus_content.reference_url_text import _resolve_process_source_uri

        uri, error = _resolve_process_source_uri(
            {
                "sourceUri": "https://youtu.be/jGwO_UgTS7I",
                "mediaType": "video/youtube",
            },
            [],
        )
        self.assertIsNone(error)
        self.assertEqual(uri, "https://www.youtube.com/watch?v=jGwO_UgTS7I")

    def test_resolve_corpus_local_path_ignores_process_cwd(self) -> None:
        steering_config = load_steering_config("corpora/papyrus-steering.yml")
        self.assertIsNotNone(steering_config)
        corpus_config = require_corpus_config(steering_config, "threat-intelligence", "--corpus-key")
        with tempfile.TemporaryDirectory() as temp_dir:
            previous_cwd = pathlib.Path.cwd()
            try:
                os.chdir(temp_dir)
                resolved = resolve_corpus_local_path(corpus_config, steering_config)
            finally:
                os.chdir(previous_cwd)
        self.assertTrue(resolved.exists())
        self.assertIn("threat-intelligence", resolved.as_posix())
        self.assertNotIn(temp_dir, resolved.as_posix())

    @mock.patch("papyrus_content.accession.subprocess.Popen")
    def test_run_biblicus_reindex_for_accession_streams_logs_and_raises_on_failure(self, mock_popen) -> None:
        from papyrus_content.accession import ReferenceAccessionError, run_biblicus_reindex_for_accession

        process = mock.MagicMock()
        process.wait.return_value = 2
        mock_popen.return_value = process

        def _write_failure_logs(*_args, **_kwargs) -> mock.MagicMock:
            stderr_log = run_dir / "biblicus-reindex.stderr.log"
            stdout_log = run_dir / "biblicus-reindex.stdout.log"
            stderr_log.write_text("Not a Biblicus corpus\n", encoding="utf-8")
            stdout_log.write_text("", encoding="utf-8")
            process = mock.MagicMock()
            process.wait.return_value = 2
            return process

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = pathlib.Path(temp_dir)
            mock_popen.side_effect = _write_failure_logs
            with self.assertRaises(ReferenceAccessionError) as error:
                run_biblicus_reindex_for_accession(
                    corpus_path=pathlib.Path("/tmp/example-corpus"),
                    biblicus_workdir=pathlib.Path("/tmp/Biblicus"),
                    run_dir=run_dir,
                )
        self.assertIn("exit 2", str(error.exception))
        self.assertIn("Not a Biblicus corpus", str(error.exception))
        mock_popen.assert_called_once()

    def test_source_download_uri_for_reference_uses_acm_pdf_url(self) -> None:
        from papyrus_content.accession import source_download_uri_for_reference

        download_uri = source_download_uri_for_reference(
            {
                "id": "reference-acm",
                "title": "ACM test paper",
                "sourceUri": "https://dl.acm.org/doi/10.1145/122344.122377",
            }
        )
        self.assertEqual(
            download_uri,
            "https://dl.acm.org/doi/pdf/10.1145/122344.122377?download=true",
        )

    def test_reference_source_readiness_url_only(self) -> None:
        reference = {
            "id": "reference-1-v1",
            "lineageId": reference_lineage_id_for("knowledge-corpus-demo", "item-1"),
            "externalItemId": "item-1",
            "sourceUri": "https://example.com/paper.pdf",
            "versionState": "current",
        }
        readiness = reference_source_readiness(reference, [], None)
        self.assertEqual(readiness["state"], "url_only")

    def test_hash_short_is_stable(self) -> None:
        self.assertEqual(hash_short(["a", "b"]), hash_short(["a", "b"]))

    def test_topics_ignore_terms_include_paper_and_url(self) -> None:
        terms = set(resolve_topics_ignore_terms())
        self.assertIn("paper", terms)
        self.assertIn("url", terms)

    def test_normalize_papyrus_config_public_site(self) -> None:
        config = normalize_papyrus_config(
            {
                "schemaVersion": 1,
                "topics": {},
                "publicSite": {"baseUrl": "https://p.apyr.us/"},
            },
            "/tmp/config.yaml",
        )
        self.assertEqual(config["publicSite"]["baseUrl"], "https://p.apyr.us")

    def test_build_newsroom_reference_public_url(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"PAPYRUS_PUBLIC_SITE_BASE_URL": "https://staging.example.com"},
            clear=False,
        ):
            url = build_newsroom_reference_public_url("reference-lineage-1")
        self.assertEqual(url, "https://staging.example.com/newsroom/references/reference-lineage-1")

    def test_resolve_public_site_base_url_from_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = pathlib.Path(tmp) / ".papyrus"
            config_dir.mkdir()
            config_path = config_dir / "config.yaml"
            config_path.write_text(
                "schemaVersion: 1\npublicSite:\n  baseUrl: https://from-config.example.com\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("PAPYRUS_PUBLIC_SITE_BASE_URL", None)
                os.environ["PAPYRUS_CONFIG"] = str(config_path)
                try:
                    loaded = load_papyrus_config()
                    assert loaded is not None
                    self.assertEqual(loaded["publicSite"]["baseUrl"], "https://from-config.example.com")
                    self.assertEqual(resolve_public_site_base_url(), "https://from-config.example.com")
                finally:
                    os.environ.pop("PAPYRUS_CONFIG", None)

    def test_normalize_papyrus_config_openai_block(self) -> None:
        from papyrus_content.papyrus_config import normalize_papyrus_config

        config = normalize_papyrus_config(
            {
                "schemaVersion": 1,
                "openai": {
                    "api_key": "test-key",
                    "model": "gpt-4o-mini-tts",
                    "voice": "alloy",
                },
            },
            "/tmp/config.yaml",
        )
        self.assertEqual(config["openai"]["apiKey"], "test-key")
        self.assertEqual(config["openai"]["model"], "gpt-4o-mini-tts")
        self.assertEqual(config["openai"]["voice"], "alloy")

    def test_resolve_openai_api_key_env_overrides_config(self) -> None:
        from papyrus_content.papyrus_config import resolve_openai_api_key

        with tempfile.TemporaryDirectory() as tmp:
            config_path = pathlib.Path(tmp) / "config.yaml"
            config_path.write_text(
                "schemaVersion: 1\nopenai:\n  api_key: from-config\n",
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ,
                {"PAPYRUS_CONFIG": str(config_path), "OPENAI_API_KEY": "from-env"},
                clear=False,
            ):
                self.assertEqual(resolve_openai_api_key(), "from-env")


if __name__ == "__main__":
    unittest.main()
