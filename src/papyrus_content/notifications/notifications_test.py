"""The notifications adapter on Caducus's in-memory fakes. ``Site`` is also what the Gherkin steps drive."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

import pytest
from caducus.notify.fakes import FakeClock, FakeMailer
from caducus.notify.directory import StaticDirectory
from caducus.notify.queues import MemoryQueues
from caducus.notify.store import MemoryStore

from papyrus_content.notifications import handler as notifications_handler
from papyrus_content.notifications.events import story_published_detail
from papyrus_content.notifications.runtime import Runtime, assemble
from papyrus_content.notifications.settings import Settings

THEME = {"accent": "#aa3300", "text": "#111111", "background": "#ffffff"}


def slug_of(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


class Site:
    """One site's notifications function with its own table, queue, mailer and published items."""

    def __init__(self, site_id: str = "alpha", *, rule: Mapping[str, Any] | None = None, operators: int = 1) -> None:
        self.settings = Settings(
            site_id=site_id,
            site_origin=f"https://{site_id}.example.test",
            base_path="",
            from_name=f"{site_id.title()} News",
            from_address=f"notify@{site_id}.example.test",
            configuration_set=f"papyrus-{site_id}",
            item_url_style="html",
            theme=THEME,
            lists=({"id": "stories", "name": "New stories", "description": "", "rule": dict(rule or {}), "approval": "admin"},),
        )
        self.rows: dict[str, dict[str, Any]] = {}
        self.store, self.queues, self.mailer, self.clock = MemoryStore(), MemoryQueues(), FakeMailer(), FakeClock()
        self.addresses = [f"operator{number}@{site_id}.example.test" for number in range(operators)]
        self.runtime: Runtime = assemble(
            self.settings,
            store=self.store,
            queues=self.queues,
            directory=StaticDirectory(self.addresses, f"recipient-key-{site_id}"),
            mailer=self.mailer,
            read_item=self.rows.get,
            clock=self.clock,
        )

    def add_story(self, title: str, section: str, *, status: str = "published") -> str:
        lineage = f"item-{section}-{slug_of(title)}"
        self.rows["published-" + lineage] = {
            "id": "published-" + lineage,
            "status": status,
            "type": "article",
            "section": section,
            "slug": slug_of(title),
            "title": title,
            "metadata": json.dumps({"frontMatterYaml": f"title: {title}\n"}),
        }
        return lineage

    @staticmethod
    def announcement(lineage: str) -> dict[str, Any]:
        return {
            "task": "story-published",
            "itemId": lineage,
            "lineageId": lineage,
            "eventId": "story.published:" + lineage,
            "publishedItemId": "published-" + lineage,
        }

    def announce(self, lineage: str) -> dict[str, Any]:
        return notifications_handler.route(self.runtime, self.announcement(lineage))

    def publish(self, title: str, section: str) -> dict[str, Any]:
        return self.announce(self.add_story(title, section))

    def deliveries(self) -> list[dict[str, Any]]:
        return [row for (_pk, sk), row in sorted(self.store.items.items()) if sk.startswith("DELIVERY#")]

    def play_queue(self) -> int:
        """Play the email queue through the sender, as SQS would."""
        batch = {
            "Records": [{"messageId": str(number), "body": json.dumps(body)} for number, (_channel, body) in enumerate(self.queues.sent)]
        }
        self.queues.sent.clear()
        result = notifications_handler.email_with(self.runtime, batch)
        assert result == {"batchItemFailures": []}, result
        return len(batch["Records"])


# -- events ---------------------------------------------------------------------------------------------------------------


def test_a_story_becomes_an_event_whose_id_comes_from_the_lineage() -> None:
    site = Site()
    lineage = site.add_story("Rates held steady", "news")
    detail = story_published_detail(
        site.rows["published-" + lineage], event_id="story.published:" + lineage, settings=site.settings, occurred_at="2026-11-09T12:00:00Z"
    )
    assert detail is not None
    assert detail["eventId"] == "story.published:item-news-rates-held-steady"
    assert detail["kind"] == "story.published" and detail["product"] == "papyrus" and detail["site"] == "alpha"
    assert detail["facts"] == {"title": "Rates held steady", "url": "https://alpha.example.test/news/rates-held-steady.html"}


def test_a_rule_that_does_not_match_raises_no_event() -> None:
    site = Site(rule={"sections": ["security"]})
    lineage = site.add_story("Rates held steady", "news")
    assert story_published_detail(site.rows["published-" + lineage], event_id="story.published:x", settings=site.settings, occurred_at="2026-11-09T12:00:00Z") is None


def test_the_deck_becomes_the_summary() -> None:
    site = Site()
    lineage = site.add_story("Rates held steady", "news")
    site.rows["published-" + lineage]["deck"] = "The bank left them alone."
    detail = story_published_detail(site.rows["published-" + lineage], event_id="story.published:x", settings=site.settings, occurred_at="2026-11-09T12:00:00Z")
    assert detail is not None and detail["facts"]["summary"] == "The bank left them alone."


# -- the function ---------------------------------------------------------------------------------------------------------


def test_a_published_story_is_mailed_once_in_the_sites_theme() -> None:
    site = Site()
    answer = site.publish("Rates held steady", "news")
    assert answer["status"] == "accepted" and answer["deliveries"] == 1
    assert site.play_queue() == 1
    (mail,) = site.mailer.calls
    assert mail["to"] == site.addresses[0] and mail["subject"] == "Rates held steady"
    assert "https://alpha.example.test/news/rates-held-steady.html" in mail["html"]
    assert "#aa3300" in mail["html"], "the site's accent colour"
    assert "Alpha News" in mail["text"]
    assert "someone entered this address" not in mail["text"], "the operator notice does not use the sign-up wording"
    assert mail["tags"]["kind"] == "story.published"


def test_the_same_announcement_twice_mails_once() -> None:
    site = Site()
    lineage = site.add_story("Rates held steady", "news")
    assert site.announce(lineage)["status"] == "accepted"
    assert site.announce(lineage)["status"] == "duplicate"
    site.play_queue()
    assert len(site.mailer.calls) == 1


def test_titles_cannot_inject_markup_or_links() -> None:
    site = Site()
    site.publish("<script>alert(1)</script> [x](https://evil.example.test)", "news")
    site.play_queue()
    (mail,) = site.mailer.calls
    assert "<script>" not in mail["html"]
    assert 'href="https://evil.example.test' not in mail["html"], "a title is text, never a link"


def test_a_story_no_list_matches_queues_nothing() -> None:
    site = Site(rule={"sections": ["security"]})
    assert site.publish("Rates held steady", "news") == {"status": "ignored", "reason": "no_matching_list"}
    assert site.queues.sent == [] and site.deliveries() == []


def test_a_story_that_is_no_longer_published_is_ignored() -> None:
    site = Site()
    lineage = site.add_story("Rates held steady", "news", status="unpublished")
    assert site.announce(lineage) == {"status": "ignored", "reason": "not_published"}
    assert notifications_handler.route(site.runtime, {**Site.announcement("item-gone")}) == {"status": "ignored", "reason": "not_published"}


@pytest.mark.parametrize(
    "event_id", ["", "item-1", "story.published:", "story.published:a b", "story.published:" + "x" * 300, "story.published:other"]
)
def test_a_malformed_or_mismatched_event_id_is_refused_without_touching_the_log(event_id: str) -> None:
    site = Site()
    lineage = site.add_story("Rates held steady", "news")
    answer = notifications_handler.route(site.runtime, {**Site.announcement(lineage), "eventId": event_id})
    assert answer == {"status": "ignored", "reason": "bad_event"}
    assert site.store.items == {}


def test_a_non_text_event_id_is_refused() -> None:
    site = Site()
    assert notifications_handler.route(site.runtime, {"task": "story-published", "eventId": 5, "lineageId": "x"})["reason"] == "bad_event"


def test_unknown_events_do_nothing() -> None:
    assert notifications_handler.route(Site().runtime, {"task": "something-else"}) == {"status": "ignored", "reason": "unknown_event"}


def test_sites_do_not_share_data() -> None:
    alpha, beta = Site("alpha"), Site("beta")
    alpha.publish("Rates held steady", "news")
    assert len(alpha.deliveries()) == 1 and beta.deliveries() == [] and beta.store.items == {}


@pytest.mark.parametrize("action", sorted(notifications_handler.public.READER_ACTIONS))
def test_reader_actions_are_unavailable_and_store_nothing(action: str) -> None:
    site = Site()
    answer = notifications_handler.route(site.runtime, {"action": action, "email": "reader@example.test"})
    assert answer == {"statusCode": 503, "body": {"status": "unavailable"}}
    assert site.store.items == {}


def test_every_failure_in_caducus_reaches_lambda_so_it_retries() -> None:
    site = Site()
    lineage = site.add_story("Rates held steady", "news")

    def explode(_id: str) -> None:
        raise RuntimeError("content API down")

    site.runtime.read_item = explode
    with pytest.raises(RuntimeError):
        site.announce(lineage)
