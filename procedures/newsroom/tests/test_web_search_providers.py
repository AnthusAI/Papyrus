import json
import os
import unittest
from unittest import mock

from papyrus_newsroom import web_search_providers


class WebSearchProvidersTests(unittest.TestCase):
    def test_normalize_defaults_to_tavily(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(web_search_providers.normalize_web_search_provider(None), "tavily")

    def test_normalize_respects_env_override(self):
        with mock.patch.dict(os.environ, {"WEB_SEARCH_PROVIDER": "openai"}, clear=False):
            self.assertEqual(web_search_providers.normalize_web_search_provider(None), "openai")

    def test_normalize_explicit_provider_wins(self):
        with mock.patch.dict(os.environ, {"WEB_SEARCH_PROVIDER": "openai"}, clear=False):
            self.assertEqual(web_search_providers.normalize_web_search_provider("tavily"), "tavily")

    @mock.patch("urllib.request.urlopen")
    def test_tavily_search_maps_results(self, urlopen):
        response_body = json.dumps({
            "query": "ancient language ai decipherment",
            "answer": "Recent work on AI-assisted decipherment.",
            "results": [
                {
                    "title": "Ithaca Nature paper",
                    "url": "https://example.org/ithaca",
                    "content": "A deep learning approach.",
                    "score": 0.91,
                }
            ],
            "response_time": 1.2,
        }).encode("utf-8")
        urlopen.return_value.__enter__.return_value.read.return_value = response_body
        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test", "WEB_SEARCH_PROVIDER": "tavily"}, clear=False):
            payload = web_search_providers.reference_web_search(query="ancient language ai decipherment", max_results=5)

        self.assertEqual(payload["query"], "ancient language ai decipherment")
        self.assertEqual(payload["results"][0]["url"], "https://example.org/ithaca")
        self.assertEqual(payload["results"][0]["title"], "Ithaca Nature paper")
        self.assertEqual(payload["metadata"]["answer"], "Recent work on AI-assisted decipherment.")
        self.assertEqual(payload["metadata"]["web_search_provider"], "tavily")
        self.assertEqual(payload["provider"], "tavily")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_full_url(), "https://api.tavily.com/search")
        sent = json.loads(request.data.decode("utf-8"))
        self.assertEqual(sent["query"], "ancient language ai decipherment")
        self.assertTrue(sent["include_answer"])

    @mock.patch("urllib.request.urlopen")
    def test_openai_search_maps_source_urls(self, urlopen):
        response_body = json.dumps({
            "output": [
                {
                    "type": "web_search_call",
                    "action": {
                        "sources": [
                            {"url": "https://openai.com/index/example"},
                        ],
                    },
                },
                {
                    "content": [{"text": "OpenAI found relevant pages."}],
                },
            ],
            "model": "gpt-5.4-mini",
            "id": "resp_123",
        }).encode("utf-8")
        urlopen.return_value.__enter__.return_value.read.return_value = response_body
        with mock.patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-test", "WEB_SEARCH_PROVIDER": "openai"},
            clear=False,
        ):
            payload = web_search_providers.reference_web_search(
                query="agentic ai protocols",
                max_results=3,
                provider="openai",
            )

        self.assertEqual(payload["results"][0]["url"], "https://openai.com/index/example")
        self.assertEqual(payload["metadata"]["web_search_provider"], "openai")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_full_url(), "https://api.openai.com/v1/responses")

    def test_normalize_reads_the_first_name_of_the_chain(self):
        with mock.patch.dict(os.environ, {"WEB_SEARCH_PROVIDERS": "perplexity,tavily", "WEB_SEARCH_PROVIDER": "openai"}, clear=True):
            self.assertEqual(web_search_providers.normalize_web_search_provider(None), "perplexity")
            self.assertEqual(web_search_providers.web_search_chain_names(None), ["perplexity", "tavily"])
            self.assertEqual(web_search_providers.web_search_chain_names("gemini"), ["gemini"])

    @mock.patch("urllib.request.urlopen")
    def test_reference_web_search_falls_back_when_the_first_plan_is_exhausted(self, urlopen):
        import io
        import urllib.error
        exhausted = urllib.error.HTTPError("https://api.tavily.com/search", 432, "limit", {}, io.BytesIO(b"{}"))
        answered = mock.MagicMock()
        answered.__enter__.return_value.read.return_value = json.dumps({"results": [{"title": "P", "url": "https://example.org/p", "snippet": "S"}]}).encode()
        urlopen.side_effect = [exhausted, answered]
        env = {"WEB_SEARCH_PROVIDERS": "tavily,perplexity", "TAVILY_API_KEY": "t", "PERPLEXITY_API_KEY": "p"}
        with mock.patch.dict(os.environ, env, clear=True):
            payload = web_search_providers.reference_web_search(query="q", max_results=3)
        self.assertEqual(payload["provider"], "perplexity")
        self.assertEqual(payload["results"][0]["snippet"], "S")
        self.assertEqual(payload["metadata"]["web_search_chain"], ["tavily", "perplexity"])
        self.assertEqual([s["message"] for s in payload["metadata"]["web_search_skipped"]], ["tavily: plan exhausted (432)"])

    def test_tavily_requires_api_key(self):
        with mock.patch.dict(os.environ, {"WEB_SEARCH_PROVIDER": "tavily"}, clear=True):
            os.environ.pop("TAVILY_API_KEY", None)
            with self.assertRaisesRegex(RuntimeError, "TAVILY_API_KEY"):
                web_search_providers.reference_web_search(query="test query")

    @mock.patch("papyrus_newsroom.web_search_providers.reference_web_search")
    def test_title_subtitle_web_context_uses_reference_search(self, reference_web_search):
        reference_web_search.return_value = {
            "results": [{"url": "https://example.org/paper"}],
            "metadata": {"answer": "A paper about decipherment."},
        }
        urls, answer = web_search_providers.web_search_urls_for_title_subtitle(
            reference={"title": "Ithaca", "sourceUri": "https://example.org/ithaca"},
            catalog_entry={"doi": "10.1234/example"},
            known_title="Ithaca",
        )
        self.assertEqual(urls, ["https://example.org/paper"])
        self.assertEqual(answer, "A paper about decipherment.")
        reference_web_search.assert_called_once()

    @unittest.skipUnless(os.environ.get("TAVILY_LIVE_TEST") == "1", "set TAVILY_LIVE_TEST=1 to hit api.tavily.com")
    def test_tavily_live_search(self):
        with mock.patch.dict(os.environ, {"WEB_SEARCH_PROVIDER": "tavily"}, clear=False):
            payload = web_search_providers.reference_web_search(
                query="mechatronics artificial intelligence robotics",
                max_results=3,
            )
        self.assertGreaterEqual(len(payload.get("results") or []), 1)
        self.assertEqual(payload.get("provider"), "tavily")
        metadata = payload.get("metadata") or {}
        self.assertTrue(metadata.get("request_id"))


if __name__ == "__main__":
    unittest.main()
