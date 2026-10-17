from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from papyrus_content import rebuild_trigger  # noqa: E402


class StubAmplify:
    def __init__(self, statuses=(), start_error=None, list_error=None):
        self.statuses = list(statuses)
        self.start_error = start_error
        self.list_error = list_error
        self.started = []
        self.listed = []

    def list_jobs(self, **kwargs):
        self.listed.append(kwargs)
        if self.list_error:
            raise self.list_error
        return {"jobSummaries": [{"jobId": str(index + 1), "status": status} for index, status in enumerate(self.statuses)]}

    def start_job(self, **kwargs):
        if self.start_error:
            raise self.start_error
        self.started.append(kwargs)
        return {"jobSummary": {"jobId": "42"}}


class TriggerRebuildTest(unittest.TestCase):
    def test_starts_a_release_job_when_none_is_pending(self) -> None:
        amplify = StubAmplify(statuses=["SUCCEED", "RUNNING"])
        result = rebuild_trigger.trigger_rebuild(reader_app_id="app1", boto_client=amplify)
        self.assertEqual(result, {"started": True, "jobId": "42"})
        self.assertEqual(amplify.started, [{"appId": "app1", "branchName": "main", "jobType": "RELEASE"}])
        self.assertEqual(amplify.listed, [{"appId": "app1", "branchName": "main", "maxResults": 5}])

    def test_skips_when_a_pending_job_exists(self) -> None:
        amplify = StubAmplify(statuses=["PENDING", "SUCCEED"])
        result = rebuild_trigger.trigger_rebuild(reader_app_id="app1", reader_branch="live", boto_client=amplify)
        self.assertEqual(result, {"started": False, "jobId": "1", "reason": "pending-job-exists"})
        self.assertEqual(amplify.started, [])

    def test_reports_the_error_instead_of_raising(self) -> None:
        amplify = StubAmplify(start_error=RuntimeError("no repository connected"))
        result = rebuild_trigger.trigger_rebuild(reader_app_id="app1", boto_client=amplify)
        self.assertFalse(result["started"])
        self.assertIn("no repository connected", result["error"])

    def test_reports_a_listing_error_instead_of_raising(self) -> None:
        amplify = StubAmplify(list_error=RuntimeError("AccessDenied"))
        result = rebuild_trigger.trigger_rebuild(reader_app_id="app1", boto_client=amplify)
        self.assertIn("AccessDenied", result["error"])

    def test_without_a_reader_app_nothing_is_called(self) -> None:
        amplify = StubAmplify()
        result = rebuild_trigger.trigger_rebuild(reader_app_id=None, boto_client=amplify)
        self.assertEqual(result, {"started": False, "reason": "not-configured"})
        self.assertEqual(amplify.listed, [])

    def test_staging_build_uses_the_staging_branch(self) -> None:
        amplify = StubAmplify()
        result = rebuild_trigger.trigger_staging_build(cms_app_id="cms1", boto_client=amplify)
        self.assertTrue(result["started"])
        self.assertEqual(amplify.started[0]["branchName"], "staging")

    def test_many_publishes_start_one_job_while_the_first_is_pending(self) -> None:
        amplify = StubAmplify()
        first = rebuild_trigger.trigger_rebuild(reader_app_id="app1", boto_client=amplify)
        amplify.statuses = ["PENDING"]
        outcomes = [rebuild_trigger.trigger_rebuild(reader_app_id="app1", boto_client=amplify) for _ in range(127)]
        self.assertTrue(first["started"])
        self.assertTrue(all(outcome["reason"] == "pending-job-exists" for outcome in outcomes))
        self.assertEqual(len(amplify.started), 1)


class PretextRevalidationTest(unittest.TestCase):
    def test_returns_none_when_unconfigured(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch(
            "papyrus_content.reader_revalidation.resolve_reader_cache_revalidate_secret", return_value=None
        ), mock.patch("papyrus_content.reader_revalidation.load_dotenv"):
            self.assertIsNone(rebuild_trigger.trigger_pretext_revalidation(["a"], None, base_url="https://x.test"))

    def test_posts_slugs_without_edition_date(self) -> None:
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"ok": true}'

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["body"] = request.data
            return Response()

        with mock.patch("papyrus_content.reader_revalidation.resolve_reader_cache_revalidate_secret", return_value="s"), mock.patch(
            "papyrus_content.reader_revalidation.load_dotenv"
        ), mock.patch("urllib.request.urlopen", fake_urlopen):
            result = rebuild_trigger.trigger_pretext_revalidation(["hello"], None, base_url="https://x.test/")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(captured["url"], "https://x.test/api/revalidate")
        self.assertNotIn(b"editionDate", captured["body"])
        self.assertIn(b'"articleSlugs": ["hello"]', captured["body"])


if __name__ == "__main__":
    unittest.main()
