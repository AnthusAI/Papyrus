from __future__ import annotations

import re

import pytest

from .export import public_key
from .settings import HomePageSettings, ThreadsSettings
from .threads import HandleLookup, anchor_of, clean_text, collect_threads, opaque_key, public_message

PROFILE = "profile-1"
THREAD_ID = "thread-1"
UUID_TEXT = "-".join(["123e4567", "e89b", "12d3", "a456", "426614174000"])
SETTINGS = HomePageSettings(threads=ThreadsSettings(enabled=True))


class Client:
    def __init__(self, threads, messages, profiles=None):
        self.threads, self.messages, self.profiles, self.profile_reads = threads, messages, profiles or {}, []

    def list_by_index(self, index, key, *, limit=100):
        if index == "messageThreadsByKindAndUpdatedAt":
            return [thread for thread in self.threads if thread["threadKind"] == key]
        assert index == "messagesByThreadAndSequence"
        return [message for message in self.messages if message["threadId"] == key]

    def get_record(self, model, record_id):
        assert model == "UserProfile"
        self.profile_reads.append(record_id)
        return self.profiles.get(record_id)


def comment(number, text="Hello", **more):
    return {"id": f"m-{number}", "threadId": THREAD_ID, "sequenceNumber": number, "messageKind": "comment", "status": "active", "role": "human",
            "content": text, "createdAt": f"2026-10-0{number}T00:00:00.000Z", "authorUserProfileId": PROFILE, **more}


def thread(**more):
    return {"id": THREAD_ID, "threadKind": "reference_conversation", "status": "active", "title": "A title", "primaryAnchorKey": "reference#lineage-1", **more}


REFERENCES = {public_key("lineage-1"): "A Reference"}


def test_clean_text_keeps_line_breaks_and_drops_html_emails_and_uuids():
    text = f"Line one <b>bold</b>\n\nLine two a@b.test {UUID_TEXT} end"
    cleaned = clean_text(text)
    assert cleaned.startswith("Line one bold\n\nLine two")
    assert "@" not in cleaned and "<b>" not in cleaned and not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}", cleaned)
    assert clean_text("   ") is None and clean_text("<br>") is None


@pytest.mark.parametrize("override", [{"status": "deleted"}, {"status": "hidden"}, {"messageKind": "system_event"}, {"deletedAt": "2026-10-02T00:00:00Z"}, {"content": ""}])
def test_a_message_that_is_not_an_active_undeleted_comment_is_omitted(override):
    assert public_message(comment(1, **override), HandleLookup(Client([], [])), SETTINGS) is None


def test_a_public_message_has_only_the_public_fields_and_a_hashed_key():
    client = Client([], [], {PROFILE: {"id": PROFILE, "publicHandle": "ryan"}})
    message = public_message(comment(1, editedAt="2026-10-01T01:00:00Z", authorSub="sub-1", authorLabel="x@y.test"), HandleLookup(client), SETTINGS)
    assert list(message) == ["key", "at", "edited", "text", "author"]
    assert message["key"] == opaque_key("m-1") and message["edited"] is True and message["author"] == {"handle": "ryan"}


def test_authors_without_a_valid_handle_get_the_label_and_machines_get_ai():
    handles = HandleLookup(Client([], [], {PROFILE: {"publicHandle": "someone@example.test"}}))
    assert public_message(comment(1), handles, SETTINGS)["author"] == {"label": "Editor"}
    assert public_message(comment(2, role="assistant"), handles, SETTINGS)["author"] == {"label": "AI"}
    assert public_message(comment(3, authorUserProfileId=None), handles, SETTINGS)["author"] == {"label": "Editor"}


def test_authors_none_reads_no_profile_and_uses_the_configured_label():
    client = Client([], [], {PROFILE: {"publicHandle": "ryan"}})
    settings = HomePageSettings(threads=ThreadsSettings(enabled=True, authors="none", anonymous_label="Staff"))
    assert public_message(comment(1), HandleLookup(client), settings)["author"] == {"label": "Staff"}
    assert client.profile_reads == []


def test_a_profile_is_read_once_per_run():
    client = Client([], [], {PROFILE: {"publicHandle": "ryan"}})
    handles = HandleLookup(client)
    handles.handle_of(PROFILE)
    handles.handle_of(PROFILE)
    assert client.profile_reads == [PROFILE]


def test_anchors_need_a_public_reference_or_a_published_story():
    assert anchor_of(thread(), REFERENCES, None) == {"kind": "reference", "key": public_key("lineage-1"), "title": "A Reference"}
    assert anchor_of(thread(primaryAnchorKey="reference#other"), REFERENCES, None) is None
    assert anchor_of(thread(primaryAnchorKey=None), REFERENCES, None) is None
    story = thread(threadKind="story_conversation", primaryAnchorKey="item#story-1")
    assert anchor_of(story, REFERENCES, None) is None
    assert anchor_of(story, REFERENCES, lambda lineage: {"url": "/s/", "title": "S"} if lineage == "story-1" else None) == {"kind": "story", "url": "/s/", "title": "S"}
    assert anchor_of(story, REFERENCES, lambda lineage: None) is None
    assert anchor_of(thread(primaryAnchorKey="item#story-1"), REFERENCES, lambda lineage: {"url": "/s/", "title": "S"}) is None


def test_collect_threads_keeps_only_active_threads_with_public_messages():
    client = Client(
        [thread(), thread(id="t-2", status="archived"), thread(id="t-3", primaryAnchorKey="reference#other"), thread(id="t-4")],
        [comment(1), comment(2, "gone", status="deleted"), {**comment(1), "threadId": "t-2"}, {**comment(1), "threadId": "t-3"}, {**comment(1, status="deleted"), "threadId": "t-4"}],
    )
    found = collect_threads(client, REFERENCES, SETTINGS)
    assert [entry["key"] for entry in found] == [opaque_key(THREAD_ID)]
    assert [message["text"] for message in found[0]["messages"]] == ["Hello"]
    assert found[0]["title"] == "A title"


def test_an_empty_title_falls_back_to_the_anchor_title_and_threads_sort_by_latest_message():
    client = Client(
        [thread(title=""), thread(id="t-2", title="Later")],
        [comment(1), {**comment(5), "threadId": "t-2"}],
    )
    found = collect_threads(client, REFERENCES, SETTINGS)
    assert [entry["title"] for entry in found] == ["Later", "A Reference"]
