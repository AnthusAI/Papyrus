"""Story versions: publishing never renumbers, "current" and "published" are explicit, and set-slug redirects."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content.projection.engine import ProjectionContext, project, project_all, reconcile
from papyrus_content.projection.item_state import item_state_key
from papyrus_content.projection.projector import DEFAULT_THEME, MarkusProjectorSettings, MarkusSiteProjector, read_static_files
from papyrus_content.projection.source import PublishedContentSource
from papyrus_content.publishing import ItemFields, publish_item, save_item
from papyrus_content.story_commands import stories_set_slug
from papyrus_content.story_reporting import (
    current_story_version,
    latest_story_version,
    published_story_version,
    repair_story_versions,
    save_story_version,
)
from fake_client import FakeAuthoringClient  # noqa: E402
from incremental_site import FakeRedirectStore  # noqa: E402
from projection_fixtures import RecordingWriter  # noqa: E402

LINEAGE = "story-1"
NOW = "2026-10-05T12:00:00Z"


def make_story(client: FakeAuthoringClient, versions: int = 1) -> None:
    """Records `<lineage>-v1` and, through save_story_version, later drafts."""
    save_item(
        client,
        ItemFields(type="article", slug="hello", section="articles", front_matter_yaml="title: Hello\n",
                   body_markus="Version 1.\n", aliases=[], id=f"{LINEAGE}-v1"),
        actor="t", now=NOW,
    )
    client.update_record("Item", {"id": f"{LINEAGE}-v1", "lineageId": LINEAGE, "versionNumber": 1, "versionState": "current"})
    for number in range(2, versions + 1):
        save_story_version(
            client, LINEAGE, front_matter_yaml="title: Hello\n", body_markus=f"Version {number}.\n",
            actor="t", change_reason="edit", now=f"2026-10-05T12:0{number}:00Z",
        )


def states(client: FakeAuthoringClient) -> dict[str, tuple[int, str]]:
    return {
        row["id"]: (row["versionNumber"], row["versionState"])
        for row in client.tables["Item"].values()
    }


class PublishKeepsVersionNumbers(unittest.TestCase):
    def test_publish_never_rewrites_version_number(self) -> None:
        client = FakeAuthoringClient()
        make_story(client, versions=3)
        publish_item(client, f"{LINEAGE}-v3", actor="t", now=NOW)
        publish_item(client, f"{LINEAGE}-v1", actor="t", now=NOW)
        self.assertEqual(
            {key: number for key, (number, _state) in states(client).items()},
            {f"{LINEAGE}-v1": 1, f"{LINEAGE}-v2": 2, f"{LINEAGE}-v3": 3},
        )

    def test_published_counter_lives_on_the_published_item(self) -> None:
        client = FakeAuthoringClient()
        make_story(client, versions=3)
        first = publish_item(client, f"{LINEAGE}-v3", actor="t", now=NOW)
        second = publish_item(client, f"{LINEAGE}-v1", actor="t", now=NOW)
        self.assertEqual((first.version_number, second.version_number), (1, 2))
        self.assertEqual(client.tables["PublishedItem"][f"published-{LINEAGE}"]["versionNumber"], 2)

    def test_publishing_leaves_exactly_one_current_record(self) -> None:
        client = FakeAuthoringClient()
        make_story(client, versions=3)
        client.update_record("Item", {"id": f"{LINEAGE}-v1", "versionState": "current"})  # a muddled lineage
        publish_item(client, f"{LINEAGE}-v2", actor="t", now=NOW)
        current = [key for key, (_n, state) in states(client).items() if state == "current"]
        self.assertEqual(current, [f"{LINEAGE}-v2"])


class CurrentAndPublishedAreDifferent(unittest.TestCase):
    def muddled(self) -> FakeAuthoringClient:
        client = FakeAuthoringClient()
        make_story(client, versions=3)
        publish_item(client, f"{LINEAGE}-v1", actor="t", now="2026-10-06T00:00:00Z")
        return client

    def test_latest_is_the_current_record_not_the_highest_number(self) -> None:
        client = self.muddled()
        self.assertEqual(latest_story_version(client, LINEAGE)["id"], f"{LINEAGE}-v1")
        self.assertEqual(current_story_version(client, LINEAGE)["id"], f"{LINEAGE}-v1")

    def test_published_version_is_the_published_source(self) -> None:
        client = self.muddled()
        client.update_record("Item", {"id": f"{LINEAGE}-v3", "versionState": "current", "versionCreatedAt": "2027-01-01T00:00:00Z"})
        self.assertEqual(published_story_version(client, LINEAGE)["id"], f"{LINEAGE}-v1")
        self.assertEqual(current_story_version(client, LINEAGE)["id"], f"{LINEAGE}-v3")

    def test_unpublished_story_has_no_published_version(self) -> None:
        client = FakeAuthoringClient()
        make_story(client, versions=2)
        self.assertIsNone(published_story_version(client, LINEAGE))

    def test_save_builds_on_current_and_still_uses_max_plus_one(self) -> None:
        client = self.muddled()
        record = save_story_version(client, LINEAGE, front_matter_yaml="title: Hello\n", body_markus="Next.\n",
                                    actor="t", change_reason="edit", now="2026-10-07T00:00:00Z")
        self.assertEqual(record["versionNumber"], 4)
        self.assertEqual(record["previousVersionId"], f"{LINEAGE}-v1")
        self.assertEqual(record["id"], f"{LINEAGE}-v4")
        current = [key for key, (_n, state) in states(client).items() if state == "current"]
        self.assertEqual(current, [f"{LINEAGE}-v4"])

    def test_save_skips_ids_already_taken(self) -> None:
        client = self.muddled()
        client.update_record("Item", {"id": f"{LINEAGE}-v2", "versionNumber": 7})
        record = save_story_version(client, LINEAGE, front_matter_yaml="title: Hello\n", body_markus="Next.\n",
                                    actor="t", change_reason="edit", now="2026-10-07T00:00:00Z")
        self.assertEqual(record["versionNumber"], 8)
        self.assertNotIn(record["id"], {f"{LINEAGE}-v1", f"{LINEAGE}-v2", f"{LINEAGE}-v3"})


class RepairMuddledLineage(unittest.TestCase):
    def test_renumbers_by_creation_order_and_leaves_one_current(self) -> None:
        client = FakeAuthoringClient()
        make_story(client, versions=3)
        for number, key in enumerate(("v1", "v2", "v3")):
            client.update_record("Item", {"id": f"{LINEAGE}-{key}", "createdAt": f"2026-10-0{number + 1}T00:00:00Z"})
        # Muddled: duplicate numbers and three current records.
        for key, number in (("v1", 8), ("v2", 1), ("v3", 1)):
            client.update_record("Item", {"id": f"{LINEAGE}-{key}", "versionNumber": number, "versionState": "current"})
        bodies = {row["id"]: row["bodyMarkus"] for row in client.tables["Item"].values()}

        planned = repair_story_versions(client, LINEAGE)
        self.assertTrue(planned)
        self.assertEqual(states(client)[f"{LINEAGE}-v1"][0], 8)  # dry run changed nothing

        repair_story_versions(client, LINEAGE, apply=True)
        self.assertEqual(
            states(client),
            {f"{LINEAGE}-v1": (1, "superseded"), f"{LINEAGE}-v2": (2, "superseded"), f"{LINEAGE}-v3": (3, "current")},
        )
        self.assertEqual(client.tables["Item"][f"{LINEAGE}-v3"]["previousVersionId"], f"{LINEAGE}-v2")
        self.assertEqual({row["id"]: row["bodyMarkus"] for row in client.tables["Item"].values()}, bodies)
        self.assertEqual(repair_story_versions(client, LINEAGE), [])

    def test_published_record_stays_current(self) -> None:
        client = FakeAuthoringClient()
        make_story(client, versions=3)
        for number, key in enumerate(("v1", "v2", "v3")):
            client.update_record("Item", {"id": f"{LINEAGE}-{key}", "createdAt": f"2026-10-0{number + 1}T00:00:00Z"})
        publish_item(client, f"{LINEAGE}-v2", actor="t", now=NOW)
        repair_story_versions(client, LINEAGE, apply=True)
        self.assertEqual(states(client)[f"{LINEAGE}-v2"], (2, "current"))
        self.assertEqual(states(client)[f"{LINEAGE}-v3"], (3, "superseded"))


class SetSlugRedirects(unittest.TestCase):
    def setUp(self) -> None:
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.client = FakeAuthoringClient()
        settings = MarkusProjectorSettings(theme=DEFAULT_THEME, sections=())
        self.redirects = FakeRedirectStore()
        self.store = RecordingWriter(Path(self.work.name))
        self.context = ProjectionContext(
            source=PublishedContentSource(self.client),
            projector=MarkusSiteProjector(settings, read_static_files(None, DEFAULT_THEME)),
            writer=self.store,
            redirect_store=self.redirects,
        )

    def pages(self) -> set[str]:
        return {key for op, key in self.store.operations if op == "put"} - {
            key for op, key in self.store.operations if op == "delete"
        }

    def set_slug(self, flags: list[str]) -> None:
        def run_projection(task):
            project(self.context, task["itemId"])
            return {"ok": True}

        with mock.patch("papyrus_content.story_commands.create_authoring_client", return_value=(self.client, {})), \
                mock.patch("papyrus_content.projection_trigger.projection_enabled", return_value=True), \
                mock.patch("papyrus_content.projection_trigger.trigger_projection", side_effect=run_projection), \
                contextlib.redirect_stdout(io.StringIO()):
            stories_set_slug(flags)

    def test_set_slug_uses_the_published_text_redirects_and_removes_the_old_page(self) -> None:
        make_story(self.client, versions=3)
        publish_item(self.client, f"{LINEAGE}-v1", actor="t", now=NOW)
        project(self.context, f"{LINEAGE}-v1")
        old_pages = self.pages()
        self.assertTrue(any("hello" in key for key in old_pages))
        # A different version goes live later (its projection state is remembered under another id).
        publish_item(self.client, f"{LINEAGE}-v2", actor="t", now=NOW)

        self.set_slug(["--story", LINEAGE, "--slug", "better-name", "--force"])

        published = self.client.tables["PublishedItem"][f"published-{LINEAGE}"]
        self.assertEqual(published["sourceItemId"], f"{LINEAGE}-v2")
        self.assertIn("Version 2.", published["bodyMarkus"])
        self.assertEqual(published["slug"], "better-name")
        self.assertEqual({row["slug"] for row in self.client.tables["Item"].values()}, {"better-name"})
        pages = self.pages()
        self.assertTrue(any("better-name" in key for key in pages))
        self.assertFalse(any("hello" in key for key in pages), pages)
        self.assertEqual(self.redirects.mapping.get("/articles/hello.html"), "/articles/better-name.html")
        self.assertEqual([key for key in self.store._state if key.startswith("_papyrus/items/")], [
            f"_papyrus/items/{LINEAGE}-v2.json"
        ])

    def test_set_slug_on_a_stale_record_id_still_targets_the_published_record(self) -> None:
        make_story(self.client, versions=3)
        publish_item(self.client, f"{LINEAGE}-v3", actor="t", now=NOW)
        project(self.context, f"{LINEAGE}-v3")
        self.set_slug(["--story", f"{LINEAGE}-v1", "--slug", "better-name", "--force"])
        self.assertEqual(self.client.tables["PublishedItem"][f"published-{LINEAGE}"]["sourceItemId"], f"{LINEAGE}-v3")
        self.assertIn("Version 3.", self.client.tables["PublishedItem"][f"published-{LINEAGE}"]["bodyMarkus"])
        self.assertEqual(self.redirects.mapping.get("/articles/hello.html"), "/articles/better-name.html")


class StaleSiblingState(SetSlugRedirects):
    """A draft slug's page and state left behind under an older version id while a newer version is published (Distinctive's Wemby ruling)."""

    OLD_PAGE = "articles/draft-x.html"

    def stale_site(self) -> None:
        make_story(self.client, versions=2)
        self.client.update_record("Item", {"id": f"{LINEAGE}-v1", "slug": "draft-x"})
        publish_item(self.client, f"{LINEAGE}-v1", actor="t", now=NOW)
        project(self.context, f"{LINEAGE}-v1")
        old_state = self.store.get(item_state_key(f"{LINEAGE}-v1"))
        old_page = self.store.get(self.OLD_PAGE)
        self.assertIsNotNone(old_page)
        self.client.update_record("Item", {"id": f"{LINEAGE}-v2", "slug": "in-re"})
        publish_item(self.client, f"{LINEAGE}-v2", actor="t", now=NOW)
        project(self.context, f"{LINEAGE}-v2")
        # What the older release left: the old version's page and state, and no redirect.
        self.store.put(self.OLD_PAGE, old_page)
        self.store.put(item_state_key(f"{LINEAGE}-v1"), old_state)
        self.redirects.mapping.clear()
        own = json.loads(self.store.get(item_state_key(f"{LINEAGE}-v2")))
        own["formerPageKeys"] = []  # the older release never recorded the move
        self.store.put(item_state_key(f"{LINEAGE}-v2"), json.dumps(own).encode("utf-8"))

    def assert_fixed(self) -> None:
        self.assertIsNone(self.store.get(self.OLD_PAGE))
        self.assertIsNotNone(self.store.get("articles/in-re.html"))
        self.assertEqual(self.redirects.mapping.get("/articles/draft-x.html"), "/articles/in-re.html")
        self.assertIsNone(self.store.get(item_state_key(f"{LINEAGE}-v1")))

    def test_project_removes_and_redirects_the_stale_page_even_when_the_item_has_its_own_state(self) -> None:
        self.stale_site()
        project(self.context, f"{LINEAGE}-v2")
        self.assert_fixed()

    def test_full_projection_removes_and_redirects_it(self) -> None:
        self.stale_site()
        project_all(self.context)
        self.assert_fixed()

    def test_reconcile_removes_and_redirects_it(self) -> None:
        self.stale_site()
        reconcile(self.context)
        self.assert_fixed()


if __name__ == "__main__":
    unittest.main()
