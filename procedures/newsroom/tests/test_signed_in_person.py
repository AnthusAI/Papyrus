"""A console review names the signed-in person from their own profile, never from the request (src/papyrus_content/signed_in_person.py,
features_backend/stories/published-reviewer.feature). The backend is a fake; the content-actions handler is loaded from its file."""

from __future__ import annotations

import json
from unittest.mock import patch

from papyrus_content import story_checklist as checklist
from papyrus_content.publishing import publish_item, published_item_id_for
from papyrus_content.signed_in_person import profile_display_name
from papyrus_content.story_reporting import create_story
from procedures.newsroom.tests.fake_client import FakeAuthoringClient
from procedures.newsroom.tests.tenant_support import dedicated_call
from procedures.newsroom.tests.test_story_checklist import load_handler

SIGNED_IN_SUB = "4a1b2c3d-0000-4000-8000-000000000001"
SIGNED_IN_EVENT = {"identity": {"sub": SIGNED_IN_SUB, "issuer": "https://cognito.example.test", "username": SIGNED_IN_SUB}}


def newsroom_with_profile(display_name: str | None = "Ana Reviewer", *, identity_status: str = "active", merged_into: dict | None = None) -> FakeAuthoringClient:
    profiles = [{"id": "profile-ana", "displayName": display_name, **({"mergedIntoProfileId": merged_into["id"]} if merged_into else {})}]
    if merged_into:
        profiles.append(merged_into)
    return FakeAuthoringClient({
        "UserIdentity": [{"id": "identity-ana", "userProfileId": "profile-ana", "cognitoSub": SIGNED_IN_SUB, "status": identity_status}],
        "UserProfile": profiles,
    })


def review_in_the_console(client, lineage: str, **extra_arguments) -> dict:
    handler = load_handler()
    with dedicated_call(), patch.object(handler, "create_authoring_client", lambda *_args, **_kwargs: (client, None)):
        return handler.set_story_step_action({"lineageId": lineage, "stepKey": "review_people", "state": "done", "note": "Read it as a reader", **extra_arguments},
                                             SIGNED_IN_EVENT)


def review_step(client, lineage: str) -> dict:
    return {row["stepKey"]: row for row in checklist.read_steps(client, lineage)}["review_people"]


def test_a_console_review_is_recorded_under_the_signed_in_persons_profile_name_and_published_as_the_reviewer():
    client = newsroom_with_profile()
    story = create_story(client, title="A Story", section_key=None, actor="AI", item_type="article")
    assert review_in_the_console(client, story["lineageId"])["ok"]
    assert (review_step(client, story["lineageId"])["actorLabel"], review_step(client, story["lineageId"])["actorSub"]) == ("Ana Reviewer", SIGNED_IN_SUB)
    publish_item(client, story["id"], actor="editor", approved_by=SIGNED_IN_SUB)
    metadata = json.loads(client.get_record("PublishedItem", published_item_id_for(story["lineageId"]))["metadata"])
    assert metadata["reviewedBy"]["name"] == "Ana Reviewer"


def test_a_name_in_the_request_is_never_the_signed_in_persons_name():
    client = newsroom_with_profile()
    story = create_story(client, title="A Story", section_key=None, actor="AI", item_type="article")
    assert review_in_the_console(client, story["lineageId"], actorLabel="Somebody Else")["ok"]
    assert review_step(client, story["lineageId"])["actorLabel"] == "Ana Reviewer"


def test_with_no_profile_name_the_person_is_recorded_under_their_username_which_is_never_published():
    client = newsroom_with_profile(display_name=None)
    story = create_story(client, title="A Story", section_key=None, actor="AI", item_type="article")
    assert review_in_the_console(client, story["lineageId"], actorLabel="Somebody Else")["ok"]
    assert review_step(client, story["lineageId"])["actorLabel"] == SIGNED_IN_SUB
    publish_item(client, story["id"], actor="editor", approved_by=SIGNED_IN_SUB)
    assert "reviewedBy" not in json.loads(client.get_record("PublishedItem", published_item_id_for(story["lineageId"]))["metadata"])


def test_the_profile_name_follows_a_merge_and_ignores_an_inactive_identity():
    merged = newsroom_with_profile(display_name="Old Name", merged_into={"id": "profile-ana-kept", "displayName": "Ana Reviewer"})
    assert profile_display_name(merged, SIGNED_IN_SUB) == "Ana Reviewer"
    assert profile_display_name(newsroom_with_profile(identity_status="disabled"), SIGNED_IN_SUB) is None
    assert profile_display_name(newsroom_with_profile(display_name="   "), SIGNED_IN_SUB) is None
    assert profile_display_name(newsroom_with_profile(), "another-sub") is None
