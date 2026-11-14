"""``papyrus ops content publish`` reports each stage on its own, with an exit code per failed stage (PPY-f3b296, PPY-4611d5, PPY-0515e1).

The page-building function is a fake: it answers with the same JSON the content-actions function does, or it is too slow for the client.
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest import mock

import pytest

from papyrus_content import publish_stages
from papyrus_content.operator_errors import GraphQLRequestError, GraphQLTimeoutError
from papyrus_content.projection_trigger import projection_timeout_seconds
from papyrus_content.publish_commands import content_publish
from papyrus_content.publishing import ItemFields, save_item
from procedures.newsroom.tests.fake_client import FakeAuthoringClient

ITEM = "item-articles-hello"
NOW = "2026-10-05T12:00:00Z"
SIGNED_IN = {"PAPYRUS_PUBLICATION_KIND": "s3-projection", "PAPYRUS_GRAPHQL_AUTH": "user", "PAPYRUS_SITE_PUBLIC_URL": "https://site.example"}


class SlowOrFakeFunction(FakeAuthoringClient):
    """The authoring client, with a ``publishItem`` mutation that answers like the content-actions function, or is too slow for the client."""

    def __init__(self, response: dict | None = None, *, error: Exception | None = None, errors: list[Exception] | None = None) -> None:
        super().__init__()
        self.response = response
        self.errors = list(errors) if errors is not None else ([error] if error else [])
        self.waited: list[float] = []
        self.mutations = 0

    @contextlib.contextmanager
    def long_call(self, seconds: float):
        self.waited.append(seconds)
        yield

    def graphql(self, query, variables=None):
        self.mutations += 1
        if self.errors:
            raise self.errors.pop(0)
        return {"publishItem": json.dumps(as_job(self.response))}


def as_job(response: dict) -> dict:
    """The answer the current backend gives for a sync-style test response: the save, and a job that has already ended with the build's outcome."""
    if "projected" not in response:
        return response
    outcome = {key: response[key] for key in ("paths", "itemPaths", "invalidation", "url", "error") if key in response}
    state = "done" if response["projected"] else "failed"
    kept = {key: value for key, value in response.items() if key not in ("projected", "paths", "invalidation", "error", "live")}
    return {**kept, "projection": {"jobId": "job-1", "state": state, **outcome}}


def written(version_note: str = "") -> dict:
    return {
        "ok": True, "changed": True, "projected": True, "live": True, "url": "https://site.example/articles/hello/",
        "paths": ["articles/hello/index.html", "articles/hello/index.md", "index.html", "_papyrus/state.json"],
        "itemPaths": ["articles/hello/index.html", "articles/hello/index.md"],
        "invalidation": {"status": "ok", "paths": ["/articles/hello/", "/articles/hello/index.html", "/articles/hello/index.md", "/", "/index.html"]},
    }


def saved(client: FakeAuthoringClient) -> FakeAuthoringClient:
    save_item(client, ItemFields(type="article", slug="hello", section="articles", front_matter_yaml="title: Hello\n", body_markus="Hello.\n", aliases=[], id=ITEM), actor="t", now=NOW)
    return client


def public(version: int | None):
    def fetch(url: str):
        body = b"<html></html>\n" + (f"<!-- papyrus-source-version: {version} -->\n".encode() if version else b"")
        return 200, {"age": "3", "x-cache": "Hit from cloudfront"}, body

    return fetch


def publish(client, flags: list[str], *, version: int | None = 1, environment: dict | None = None):
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with mock.patch.dict("os.environ", {**SIGNED_IN, **(environment or {})}), \
            mock.patch("papyrus_content.projection_trigger.projection_unknown", return_value=False), \
            mock.patch("papyrus_content.publish_commands.projection_unknown", return_value=False), \
            mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=True), \
            mock.patch("papyrus_content.publish_commands.create_authoring_client", return_value=(client, {})), \
            mock.patch("papyrus_content.projection.runtime.render_preflight"), \
            mock.patch("papyrus_content.publish_stages._fetch", public(version)), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            content_publish(["--id", ITEM, *flags])
        except SystemExit as exit_:
            code = exit_.code
    return code, out.getvalue(), err.getvalue()


class StageReportTests(unittest.TestCase):
    def test_every_stage_ok_lists_the_pages_written_the_paths_purged_and_the_verified_version(self) -> None:
        client = saved(SlowOrFakeFunction(written()))
        code, out, _err = publish(client, ["--json", "--verify", "--verify-seconds", "0"], version=1)
        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        stages = payload["stages"]
        self.assertEqual(stages["saved"]["status"], "ok")
        self.assertEqual(stages["projected"]["status"], "ok")
        self.assertEqual(stages["projected"]["pages"], written()["paths"])
        self.assertEqual(stages["invalidated"]["status"], "ok")
        self.assertIn("/articles/hello/index.html", stages["invalidated"]["paths"])
        self.assertEqual(stages["verified"]["status"], "current")
        self.assertTrue(payload["verdict"].startswith("LIVE"))

    def test_the_text_report_has_one_line_per_stage(self) -> None:
        code, out, _err = publish(saved(SlowOrFakeFunction(written())), [], version=1)
        self.assertEqual(code, 0)
        for prefix in ("  saved: ok", "  projected: ok", "  cache invalidated: ok", "  publicly verified: current"):
            self.assertTrue(any(line.startswith(prefix) for line in out.splitlines()), (prefix, out))

    def test_a_failed_purge_is_not_a_failed_write(self) -> None:
        response = {**written(), "invalidation": {"status": "failed", "reason": "the purge was refused", "paths": []}}
        code, out, err = publish(saved(SlowOrFakeFunction(response)), ["--json"])
        payload = json.loads(out)
        self.assertEqual(code, publish_stages.EXIT_INVALIDATION_FAILED)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failedStage"], "invalidation-failed")
        self.assertEqual(payload["stages"]["projected"]["status"], "ok")
        self.assertTrue(payload["dataPublished"] and payload["pagePublished"])
        self.assertIn("Not a write failure", payload["message"])

    def test_a_capped_purge_names_the_paths_it_skipped(self) -> None:
        response = {**written(), "invalidation": {"status": "capped", "paths": ["/a/"], "skippedPaths": ["/b/", "/c/"]}}
        code, out, _err = publish(saved(SlowOrFakeFunction(response)), ["--json"])
        payload = json.loads(out)
        self.assertEqual(code, publish_stages.EXIT_INVALIDATION_FAILED)
        self.assertEqual(payload["stages"]["invalidated"]["skippedPaths"], ["/b/", "/c/"])

    def test_a_purge_the_site_leaves_off_is_skipped_not_failed(self) -> None:
        response = {**written(), "invalidation": {"status": "skipped", "reason": "off", "paths": []}}
        code, out, _err = publish(saved(SlowOrFakeFunction(response)), ["--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["stages"]["invalidated"]["status"], "skipped")

    def test_verify_waits_and_a_stale_public_page_has_its_own_exit_code(self) -> None:
        code, out, _err = publish(saved(SlowOrFakeFunction(written())), ["--json", "--verify", "--verify-seconds", "0"], version=None)
        payload = json.loads(out)
        self.assertEqual(code, publish_stages.EXIT_VERIFICATION_FAILED)
        self.assertEqual(payload["stages"]["verified"]["status"], "stale")
        self.assertEqual(payload["stages"]["projected"]["status"], "ok")

    def test_without_verify_a_stale_page_is_expected_and_not_a_failure(self) -> None:
        code, out, _err = publish(saved(SlowOrFakeFunction(written())), ["--json"], version=None)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["stages"]["verified"]["status"], "stale")

    def test_no_public_address_means_not_checked(self) -> None:
        response = {**written(), "url": None}
        with mock.patch.dict("os.environ", {}, clear=False):
            code, out, _err = publish(saved(SlowOrFakeFunction(response)), ["--json"], environment={"PAPYRUS_SITE_PUBLIC_URL": ""})
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["stages"]["verified"]["status"], "not-checked")

    def test_each_failed_stage_has_its_own_code(self) -> None:
        codes = {publish_stages.EXIT_CODES[name] for name in publish_stages.EXIT_CODES}
        self.assertEqual(len(codes), len(publish_stages.EXIT_CODES))
        self.assertEqual(
            [publish_stages.EXIT_CODES[name] for name in ("ok", "save-failed", "request-refused", "checklist-open", "projection-failed", "projection-running", "invalidation-failed", "verification-failed")],
            [0, 1, 2, 3, 4, 5, 6, 7],
        )


class SlowFunctionTests(unittest.TestCase):
    def test_the_projection_call_waits_longer_than_the_ordinary_timeout(self) -> None:
        client = saved(SlowOrFakeFunction(written()))
        publish(client, ["--json"])
        self.assertEqual(client.waited, [120.0])
        self.assertEqual(projection_timeout_seconds({"PAPYRUS_PROJECTION_TIMEOUT_SECONDS": "200"}), 200.0)
        self.assertEqual(projection_timeout_seconds({"PAPYRUS_PROJECTION_TIMEOUT_SECONDS": "junk"}), 120.0)

    def test_a_client_timeout_is_still_running_and_not_failed(self) -> None:
        client = saved(SlowOrFakeFunction(error=GraphQLTimeoutError("GraphQL request failed: The read operation timed out")))
        code, out, err = publish(client, ["--json"])
        payload = json.loads(out)
        self.assertEqual(code, publish_stages.EXIT_PROJECTION_RUNNING)
        self.assertEqual(payload["stages"]["projected"]["status"], "still-running")
        self.assertEqual(payload["failedStage"], "projection-running")
        self.assertTrue(payload["dataPublished"])
        self.assertIn("STILL RUNNING", payload["message"])
        self.assertNotIn("FAILED", payload["message"])
        self.assertEqual(client.get_record("Item", ITEM)["status"], "published")

    def test_a_timeout_cannot_be_confirmed_without_a_page_address(self) -> None:
        client = saved(SlowOrFakeFunction(error=GraphQLTimeoutError("GraphQL request failed: The read operation timed out")))
        # No itemPaths came back, so the address is unknown: the command says it cannot confirm, and stays "still running".
        code, out, _err = publish(client, ["--json", "--verify", "--verify-seconds", "0"])
        self.assertEqual(code, publish_stages.EXIT_PROJECTION_RUNNING)
        self.assertEqual(json.loads(out)["stages"]["verified"]["status"], "not-checked")

    def test_a_late_page_seen_at_the_published_version_settles_as_ok(self) -> None:
        stages = {"projected": {"status": "still-running", "pages": []}, "verified": {"status": "current"}, "invalidated": {"status": "unknown"}}
        publish_stages.settle_late_projection(stages)
        self.assertEqual(stages["projected"]["status"], "ok")
        self.assertEqual(publish_stages.exit_code_of(stages, verify=True), (0, "ok"))
        stages["verified"] = {"status": "stale"}
        stages["projected"] = {"status": "still-running", "pages": []}
        publish_stages.settle_late_projection(stages)
        self.assertEqual(publish_stages.exit_code_of(stages, verify=True), (publish_stages.EXIT_PROJECTION_RUNNING, "projection-running"))

    def test_running_the_command_again_after_a_timeout_finishes_and_changes_nothing_twice(self) -> None:
        client = saved(SlowOrFakeFunction(written(), errors=[GraphQLTimeoutError("GraphQL request failed: The read operation timed out")]))
        first, _out, _err = publish(client, ["--json"])
        second, out, _err = publish(client, ["--json"])
        self.assertEqual((first, second), (publish_stages.EXIT_PROJECTION_RUNNING, 0))
        payload = json.loads(out)
        self.assertFalse(payload["changed"])   # the data was published by the first run; the second only asks for the page
        self.assertEqual(payload["stages"]["projected"]["pages"], written()["paths"])

    def test_the_functions_own_timeout_is_a_failure_with_a_safe_retry(self) -> None:
        client = saved(SlowOrFakeFunction(error=GraphQLRequestError("GraphQL request failed: Lambda:ExecutionTimeout Task timed out after 75.00 seconds")))
        code, out, _err = publish(client, ["--json"])
        payload = json.loads(out)
        self.assertEqual(code, publish_stages.EXIT_PROJECTION_FAILED)
        self.assertEqual(payload["stages"]["projected"]["status"], "timed-out")
        self.assertIn("safe", payload["stages"]["projected"]["error"])

    def test_the_real_client_turns_a_socket_timeout_into_a_timeout_error(self) -> None:
        from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient

        client = PapyrusGraphQLAuthoringClient(endpoint="https://x.appsync-api.us-east-1.amazonaws.com/graphql", header_factory=lambda body: {}, tenant_id="t")

        class Slow:
            def request(self, *args, **kwargs):
                raise TimeoutError("The read operation timed out")

            def close(self):
                pass

        with mock.patch.object(client, "_open_connection", return_value=Slow()):
            with self.assertRaises(GraphQLTimeoutError):
                client.graphql("query { x }")
        with client.long_call(120):
            self.assertEqual(client.timeout_seconds, 120)
        self.assertLess(client.timeout_seconds, 120)


def test_a_checklist_open_rejection_has_its_own_exit_code_and_lists_the_open_steps(real_checklist_gate, capsys):
    from papyrus_content.story_reporting import create_story

    client = FakeAuthoringClient()
    story = create_story(client, title="A Story", section_key=None, actor="AI")
    client.tables["Item"][story["id"]]["type"] = "article"
    with mock.patch("papyrus_content.publish_commands.create_authoring_client", return_value=(client, {})), \
            mock.patch("papyrus_content.publish_commands.refuse_placeholder_slug"), \
            mock.patch("papyrus_content.projection.runtime.render_preflight"):
        with pytest.raises(SystemExit) as raised:
            content_publish(["--id", story["id"], "--json"])
    assert raised.value.code == publish_stages.EXIT_CHECKLIST_OPEN == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False and payload["code"] == "checklist-open" and payload["exitCode"] == 3 and payload["stage"] == "saved"
    keys = [step["key"] for step in payload["openSteps"]]
    assert {"review_people", "review_reader_agents", "review_search", "review_social"} <= set(keys)
    assert all(step["label"] for step in payload["openSteps"])
    assert client.tables.get("PublishedItem", {}) == {}


def test_the_text_report_lists_the_open_steps_too(real_checklist_gate, capsys):
    from papyrus_content.story_reporting import create_story

    client = FakeAuthoringClient()
    story = create_story(client, title="A Story", section_key=None, actor="AI")
    client.tables["Item"][story["id"]]["type"] = "article"
    with mock.patch("papyrus_content.publish_commands.create_authoring_client", return_value=(client, {})), \
            mock.patch("papyrus_content.publish_commands.refuse_placeholder_slug"), \
            mock.patch("papyrus_content.projection.runtime.render_preflight"):
        with pytest.raises(SystemExit) as raised:
            content_publish(["--id", story["id"]])
    assert raised.value.code == 3
    assert "open step: review_people: Reviewed for readers" in capsys.readouterr().out


def test_other_save_failures_keep_exit_code_one(capsys):
    client = FakeAuthoringClient()
    with mock.patch("papyrus_content.publish_commands.create_authoring_client", return_value=(client, {})):
        with pytest.raises(SystemExit) as raised:
            content_publish(["--id", "item-missing", "--json"])
    assert raised.value.code == 1
    assert json.loads(capsys.readouterr().out)["code"] == "not-found"


def _stages(projected: str, invalidated: str, verified: str, reason: str | None = None) -> dict:
    return {
        "saved": {"status": "ok"},
        "projected": {"status": projected, "pages": []},
        "invalidated": {"status": invalidated, "paths": [], **({"reason": reason} if reason else {})},
        "verified": {"status": verified, **({"reason": "no public page address is known"} if verified == "not-checked" else {})},
    }


@pytest.mark.parametrize(
    ("projected", "invalidated", "verified", "starts_with"),
    [
        ("failed", "not-applicable", "not-checked", "NOT LIVE"),
        ("timed-out", "not-applicable", "not-checked", "NOT LIVE"),
        ("still-running", "unknown", "not-checked", "STILL BUILDING"),
        ("skipped", "not-applicable", "not-checked", "NOT PROJECTED"),
        ("ok", "failed", "not-checked", "PROJECTED BUT NOT PURGED"),
        ("ok", "capped", "stale", "PROJECTED BUT NOT PURGED"),
        ("ok", "ok", "current", "LIVE"),
        ("ok", "ok", "stale", "PURGED BUT THE EDGE IS STILL STALE"),
        ("ok", "ok", "not-checked", "PURGED, NOT VERIFIED"),
        ("ok", "skipped", "current", "LIVE"),
        ("ok", "skipped", "stale", "NOT PURGED, THE PAGE IS STALE"),
        ("ok", "skipped", "not-checked", "PROJECTED, NOT PURGED, NOT VERIFIED"),
        ("scheduled", "unknown", "current", "LIVE"),
        ("scheduled", "unknown", "stale", "NOT PURGED, THE PAGE IS STALE"),
        ("scheduled", "unknown", "not-checked", "PROJECTED, NOT PURGED, NOT VERIFIED"),
    ],
)
def test_the_verdict_follows_the_stages(projected, invalidated, verified, starts_with):
    verdict = publish_stages.verdict_for(_stages(projected, invalidated, verified, reason="off"))
    assert verdict.startswith(starts_with), verdict


@pytest.mark.parametrize("invalidated", ["skipped", "unknown", "not-applicable"])
@pytest.mark.parametrize("verified", ["current", "stale", "not-checked"])
def test_a_purge_that_was_not_made_never_yields_a_purged_verdict(invalidated, verified):
    verdict = publish_stages.verdict_for(_stages("ok", invalidated, verified, reason="off"))
    assert not verdict.startswith("PURGED"), verdict


def test_a_skipped_purge_is_reported_as_not_purged_in_the_published_result(capsys):
    response = {**written(), "invalidation": {"status": "skipped", "reason": "off", "paths": []}}
    code, out, _err = publish(saved(SlowOrFakeFunction(response)), ["--json"], version=None)
    payload = json.loads(out)
    assert code == 0
    assert payload["stages"]["invalidated"]["status"] == "skipped"
    assert payload["stages"]["verified"]["status"] == "stale"
    assert payload["verdict"].startswith("NOT PURGED, THE PAGE IS STALE"), payload["verdict"]
