"""CLI publish honesty: a signed-in publish projects through the newsroom mutation, a failed projection exits non-zero,
a placeholder slug is refused, and a board move to `published` warns that no page is published."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contextlib
import io
import json
import unittest
from unittest import mock

from papyrus_content.projection_trigger import trigger_projection_as_user
from papyrus_content.publish_commands import content_publish, content_unpublish, is_placeholder_slug
from papyrus_content.publishing import ItemFields, publish_item, save_item
from papyrus_content.story_commands import stories_move, stories_set_slug
from fake_client import FakeAuthoringClient  # noqa: E402

NOW = "2026-10-05T12:00:00Z"
ITEM = "item-articles-hello"
PLACEHOLDER = "draft-unsectioned-1a2b3c4d5e6f7a8b"
USER_LANE = {
    "PAPYRUS_PUBLICATION_KIND": "s3-projection",
    "PAPYRUS_GRAPHQL_AUTH": "user",
    "PAPYRUS_CONTENT_ACTIONS_FUNCTION": "content-actions-fn",
}
IAM_LANE = {**USER_LANE, "PAPYRUS_GRAPHQL_AUTH": "iam"}


class MutationClient(FakeAuthoringClient):
    """A fake that also answers the newsroom's publish and unpublish mutations."""

    def __init__(self, response=None, error: Exception | None = None, job_states: list[dict] | None = None) -> None:
        super().__init__()
        self.mutations: list[tuple[str, dict]] = []
        self.response = {"ok": True, "changed": False, "projected": True, "live": True, "url": "https://site.example/hello/"} if response is None else response
        self.error = error
        self.job_states = list(job_states or [])

    def graphql(self, query, variables=None):
        name = "unpublishItem" if "unpublishItem" in query else "publishItem"
        payload = json.loads(variables["input"])
        self.mutations.append((name, payload))
        if self.error:
            raise self.error
        if payload.get("jobStatus"):
            return {name: json.dumps({"ok": True, "projection": self.job_states.pop(0)})}
        return {name: json.dumps(self.response)}


def job_client(slug: str = "hello") -> MutationClient:
    """A newsroom whose publishItem starts a background build (job-1), then answers two jobStatus questions: running, then done."""
    return saved(MutationClient(
        {"ok": True, "changed": False, "url": "https://site.example/hello/", "projection": {"jobId": "job-1", "state": "queued"}},
        job_states=[{"jobId": "job-1", "state": "running"}, {"jobId": "job-1", "state": "done", "paths": ["/hello/"]}],
    ), slug=slug)


ASYNC_PUBLISH = ("publishItem", {"id": ITEM, "async": True})
JOB_STATUS = ("publishItem", {"id": ITEM, "jobStatus": True})


def saved(client: FakeAuthoringClient, slug: str = "hello") -> FakeAuthoringClient:
    save_item(client, ItemFields(
        type="article", slug=slug, section="articles", front_matter_yaml="title: Hello\n",
        body_markus="Hello.\n", aliases=[], id=ITEM,
    ), actor="t", now=NOW)
    return client


def run(command, client, flags, environment, invoke_error=None):
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with mock.patch.dict("os.environ", environment, clear=False), \
            mock.patch("papyrus_content.publish_commands.create_authoring_client", return_value=(client, {})), \
            mock.patch("papyrus_content.projection_trigger._invoke_lambda", side_effect=invoke_error) as invoke, \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            command(flags)
        except SystemExit as exit_:
            code = exit_.code
    return out.getvalue(), err.getvalue(), code, invoke


class SignedInProjectionTests(unittest.TestCase):
    def test_publish_asks_the_publish_mutation_and_invokes_no_function(self) -> None:
        client = saved(MutationClient())
        out, _err, code, invoke = run(content_publish, client, ["--id", ITEM, "--json"], USER_LANE)
        self.assertEqual(code, 0)
        self.assertEqual(client.mutations, [ASYNC_PUBLISH])
        invoke.assert_not_called()
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["projection"]["via"], "publishItem mutation")
        self.assertEqual(client.get_record("Item", ITEM)["status"], "published")

    def test_publish_starts_a_background_build_and_asks_about_the_job_until_it_is_done(self) -> None:
        client = job_client()
        with mock.patch("time.sleep") as sleep:
            out, _err, code, invoke = run(content_publish, client, ["--id", ITEM, "--json"], USER_LANE)
        self.assertEqual(code, 0)
        self.assertEqual(client.mutations, [ASYNC_PUBLISH, JOB_STATUS, JOB_STATUS])
        self.assertEqual(sleep.call_count, 2)
        invoke.assert_not_called()
        projection = json.loads(out)["projection"]
        self.assertEqual((projection["via"], projection["jobId"], projection["jobState"]), ("publishItem job", "job-1", "done"))
        self.assertEqual(projection["url"], "https://site.example/hello/")

    def test_a_failed_job_exits_non_zero_with_the_retry(self) -> None:
        client = saved(MutationClient(
            {"ok": True, "projection": {"jobId": "job-2", "state": "running"}},
            job_states=[{"jobId": "job-2", "state": "failed", "error": "bucket denied"}],
        ))
        with mock.patch("time.sleep"):
            _out, err, code, _invoke = run(content_publish, client, ["--id", ITEM], USER_LANE)
        self.assertEqual(code, 4)
        self.assertIn("bucket denied", err)
        self.assertIn(f"papyrus ops content publish --id {ITEM}", err)

    def test_unpublish_asks_the_unpublish_mutation(self) -> None:
        client = saved(MutationClient())
        publish_item(client, ITEM, actor="t", now=NOW)
        _out, _err, code, invoke = run(content_unpublish, client, ["--id", ITEM, "--json"], USER_LANE)
        self.assertEqual(code, 0)
        self.assertEqual(client.mutations, [("unpublishItem", {"id": ITEM, "async": True})])
        invoke.assert_not_called()

    def test_iam_lane_is_unchanged(self) -> None:
        client = saved(MutationClient())
        _out, _err, code, invoke = run(content_publish, client, ["--id", ITEM, "--json"], IAM_LANE)
        self.assertEqual(code, 0)
        self.assertEqual(client.mutations, [])
        invoke.assert_called_once()

    def test_projection_the_newsroom_could_not_finish_exits_non_zero(self) -> None:
        client = saved(MutationClient({"ok": True, "projected": False, "error": "bucket denied"}))
        out, err, code, _invoke = run(content_publish, client, ["--id", ITEM], USER_LANE)
        self.assertEqual(code, 4)
        self.assertIn("data is published but the page is not live", err)
        self.assertIn("bucket denied", err)
        self.assertIn(f"papyrus ops content publish --id {ITEM}", err)

    def test_a_refusal_or_transport_error_is_a_failure_with_a_retry(self) -> None:
        for client in (
            MutationClient({"ok": False, "errors": [{"code": "x", "message": "not allowed"}]}),
            MutationClient(error=RuntimeError("401 LoginRefreshRequired")),
        ):
            outcome = trigger_projection_as_user(client, {"task": "item", "itemId": ITEM, "unpublished": False})
            self.assertFalse(outcome["ok"])
            self.assertEqual(outcome["retry"], f"papyrus ops content publish --id {ITEM}")

    def test_a_server_without_projection_configured_is_not_a_failure(self) -> None:
        client = saved(MutationClient({"ok": True, "changed": False}))
        _out, _err, code, _invoke = run(content_publish, client, ["--id", ITEM], USER_LANE)
        self.assertEqual(code, 0)


class FailedProjectionTests(unittest.TestCase):
    def failing(self, flags, command=content_publish):
        client = saved(FakeAuthoringClient())
        if command is content_unpublish:
            publish_item(client, ITEM, actor="t", now=NOW)
        return client, *run(command, client, flags, IAM_LANE, invoke_error=RuntimeError("denied"))[:3]

    def test_text_output_says_data_published_page_not_and_gives_the_retry(self) -> None:
        client, out, err, code = self.failing(["--id", ITEM])
        self.assertEqual(code, 4)
        self.assertIn("changed", out)
        self.assertIn("the data is published but the page is not live", err)
        self.assertIn(f"Retry with: papyrus ops content publish --id {ITEM}", err)

    def test_json_output_carries_the_same_facts(self) -> None:
        _client, out, _err, code = self.failing(["--id", ITEM, "--json"])
        self.assertEqual(code, 4)
        payload = json.loads(out)
        self.assertEqual((payload["ok"], payload["dataPublished"], payload["pagePublished"]), (False, True, False))
        self.assertEqual(payload["retry"], f"papyrus ops content publish --id {ITEM}")

    def test_unpublish_failure_names_the_unpublish_retry(self) -> None:
        _client, _out, err, code = self.failing(["--id", ITEM], content_unpublish)
        self.assertEqual(code, 4)
        self.assertIn(f"papyrus ops content unpublish --id {ITEM}", err)

    def test_no_trigger_is_still_a_success(self) -> None:
        client = saved(FakeAuthoringClient())
        _out, _err, code, invoke = run(content_publish, client, ["--id", ITEM, "--no-trigger"], IAM_LANE)
        self.assertEqual(code, 0)
        invoke.assert_not_called()


class PlaceholderSlugTests(unittest.TestCase):
    def test_recognises_the_generated_slug_only(self) -> None:
        self.assertTrue(is_placeholder_slug(PLACEHOLDER))
        self.assertTrue(is_placeholder_slug("draft-articles-1a2b3c4d5e6f7a8b"))
        for real in ("hello", "draft-horse-diaries", "my-draft-unsectioned-story", "", None):
            self.assertFalse(is_placeholder_slug(real), real)

    def test_publish_refuses_and_writes_nothing(self) -> None:
        client = saved(MutationClient(), slug=PLACEHOLDER)
        client.calls.clear()
        out, err, code, invoke = run(content_publish, client, ["--id", ITEM], USER_LANE)
        self.assertEqual(code, 1)
        self.assertIn("stories set-slug", out)
        self.assertIn(PLACEHOLDER, out)
        self.assertEqual(client.write_calls(), [])
        self.assertEqual(client.mutations, [])
        invoke.assert_not_called()

    def test_dry_run_and_json_refuse_too(self) -> None:
        client = saved(FakeAuthoringClient(), slug=PLACEHOLDER)
        _out, _err, code, _ = run(content_publish, client, ["--id", ITEM, "--dry-run"], IAM_LANE)
        self.assertEqual(code, 1)
        out, _err, code, _ = run(content_publish, client, ["--id", ITEM, "--json"], IAM_LANE)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["code"], "placeholder-slug")

    def test_unpublish_is_not_blocked(self) -> None:
        client = saved(FakeAuthoringClient(), slug=PLACEHOLDER)
        publish_item(client, ITEM, actor="t", now=NOW)
        _out, _err, code, _ = run(content_unpublish, client, ["--id", ITEM], IAM_LANE)
        self.assertEqual(code, 0)


class StoriesMoveWarningTests(unittest.TestCase):
    def move(self, stage: str, *extra: str):
        client = saved(FakeAuthoringClient())
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("papyrus_content.story_commands.create_authoring_client", return_value=(client, {})), \
                mock.patch("papyrus_content.story_triggers.deliver_from_environment"), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            stories_move(["--story", ITEM, "--stage", stage, *extra])
        return client, out.getvalue(), err.getvalue()

    def test_real_run_warns_on_stderr_and_keeps_stdout_format(self) -> None:
        client, out, err = self.move("published")
        self.assertIn("No page is published", err)
        self.assertIn("papyrus ops content publish", err)
        self.assertNotIn("warning", out)
        self.assertTrue(all(line.startswith(("stories\tmove\t", "next\t", "skipped\t")) for line in out.splitlines()))
        self.assertEqual(client.get_record("Item", ITEM)["stage"], "published")

    def test_dry_run_warns_and_writes_nothing(self) -> None:
        client, out, err = self.move("published", "--dry-run")
        self.assertIn("papyrus ops content publish", err)
        self.assertIn("dry run", out)
        self.assertNotEqual(client.get_record("Item", ITEM)["stage"], "published")

    def test_other_stages_print_no_warning(self) -> None:
        _client, _out, err = self.move("reporting")
        self.assertEqual(err, "")


class SetSlugProjectionTests(unittest.TestCase):
    """A slug change republishes the page under its new path, a full build like a publish, so it uses the same background job and must not time out."""

    def set_slug(self, client):
        publish_item(client, ITEM, actor="t", now=NOW)
        out = io.StringIO()
        with mock.patch.dict("os.environ", USER_LANE), \
                mock.patch("papyrus_content.story_commands.create_authoring_client", return_value=(client, {})), \
                mock.patch("papyrus_content.projection_trigger._invoke_lambda") as invoke, \
                mock.patch("time.sleep"), \
                contextlib.redirect_stdout(out):
            stories_set_slug(["--story", ITEM, "--slug", "real-slug", "--force"])
        invoke.assert_not_called()
        return client

    def test_signed_in_set_slug_projects_through_the_mutation(self) -> None:
        client = self.set_slug(saved(MutationClient(), slug=PLACEHOLDER))
        self.assertEqual(client.mutations, [ASYNC_PUBLISH])

    def test_set_slug_waits_for_the_background_build_like_a_publish(self) -> None:
        client = self.set_slug(job_client(slug=PLACEHOLDER))
        self.assertEqual(client.mutations, [ASYNC_PUBLISH, JOB_STATUS, JOB_STATUS])
        self.assertEqual(client.job_states, [])


if __name__ == "__main__":
    unittest.main()
