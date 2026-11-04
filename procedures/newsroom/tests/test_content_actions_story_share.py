"""The content-actions front door of share links (features_backend/story-share-links.feature): who may call what, and what a stranger is told."""

from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import pytest

from papyrus_content.publishing import ItemFields, save_item
from procedures.newsroom.tests.standard_frontend_support import ProjectedSite

HANDLER_PATH = Path(__file__).resolve().parents[3] / "amplify/functions/content-actions/handler.py"
specification = importlib.util.spec_from_file_location("content_actions_handler_share", HANDLER_PATH)
handler_module = importlib.util.module_from_spec(specification)
specification.loader.exec_module(handler_module)

NOW = "2026-11-04T12:00:00Z"
EDITOR = {"sub": "sub-editor", "issuer": "https://idp.example", "username": "ed", "claims": {"cognito:groups": ["editor"], "email": "ed@example.invalid"}}
READER = {"sub": "sub-reader", "issuer": "https://idp.example", "username": "rd", "claims": {"cognito:groups": ["reader"]}}
GUEST = {"cognitoIdentityId": "us-east-1:guest", "userArn": "arn:aws:sts::000000000000:assumed-role/guest/x", "cognitoIdentityAuthType": "unauthenticated"}


@pytest.fixture()
def world():
    site = ProjectedSite("sectioned")
    save_item(site.client, ItemFields(type="article", slug="handler-draft", section="essays", front_matter_yaml="title: Handler draft\ndate: 2026-11-01\n", body_markus="Handler words.\n", aliases=[], id="item-essays-handler-draft"), actor="w", now=NOW)
    with mock.patch.object(handler_module, "create_authoring_client", return_value=(site.client, {})), \
         mock.patch.object(handler_module, "projection_configured", return_value=True), \
         mock.patch("papyrus_content.projection.runtime.load_projector", return_value=site.projector):
        yield site
    site.cleanup()


def call(field, payload, identity):
    return handler_module.handler({"fieldName": field, "arguments": {"input": json.dumps(payload)}, "identity": identity}, None)


LINEAGE = "item-essays-handler-draft"


def make(identity=EDITOR, **payload):
    return call("createStoryShare", {"lineageId": LINEAGE, **payload}, identity)


def test_an_editor_makes_a_link_and_the_token_is_only_in_the_response(world):
    out = io.StringIO()
    with redirect_stdout(out):
        made = make(viewers="anyone", expiresInDays=7)
    token = made["path"].rsplit("/", 1)[1]
    assert made["ok"] is True and made["path"] == f"/api/share/{token}" and len(token) == 43
    assert token not in json.dumps(world.client.tables) and token not in out.getvalue()
    from datetime import datetime, timedelta, timezone

    expires = datetime.strptime(made["share"]["expiresAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert made["share"]["viewers"] == "anyone" and timedelta(days=6, hours=23) < expires - datetime.now(timezone.utc) <= timedelta(days=7, minutes=1)


@pytest.mark.parametrize("identity", [READER, GUEST, None, {"sub": "s", "claims": {"cognito:groups": ["editor"]}}])
def test_a_caller_who_is_not_staff_cannot_make_list_or_revoke(world, identity):
    assert make(identity)["ok"] is False
    assert call("listStoryShares", {"lineageId": LINEAGE}, identity)["ok"] is False
    assert call("revokeStoryShare", {"lineageId": LINEAGE, "shareId": "x"}, identity)["ok"] is False
    assert "StoryShare" not in world.client.tables or not world.client.tables["StoryShare"]


def test_a_stranger_opens_a_link_with_a_guest_identity_and_a_signed_in_link_needs_staff(world):
    open_token = make(viewers="anyone")["path"].rsplit("/", 1)[1]
    closed_token = make(viewers="signed-in")["path"].rsplit("/", 1)[1]
    assert call("viewStoryShare", {"token": open_token}, GUEST)["state"] == "ok"
    assert call("viewStoryShare", {"token": open_token}, None)["state"] == "ok"
    assert call("viewStoryShare", {"token": closed_token}, GUEST) == {"state": "sign-in"}
    assert call("viewStoryShare", {"token": closed_token}, READER) == {"state": "unavailable"}
    assert call("viewStoryShare", {"token": closed_token}, EDITOR)["state"] == "ok"


def test_listing_and_revoking_through_the_front_door(world):
    token = make()["path"].rsplit("/", 1)[1]
    listed = call("listStoryShares", {"lineageId": LINEAGE}, EDITOR)
    assert listed["ok"] and len(listed["shares"]) == 1 and token not in json.dumps(listed)
    revoked = call("revokeStoryShare", {"lineageId": LINEAGE, "shareId": listed["shares"][0]["shareId"]}, EDITOR)
    assert revoked["ok"] and revoked["changed"] is True
    assert call("viewStoryShare", {"token": token}, GUEST) == {"state": "unavailable"}


def test_a_failure_while_drawing_tells_a_stranger_nothing_and_does_not_log_the_token(world):
    token = make()["path"].rsplit("/", 1)[1]
    out = io.StringIO()
    with redirect_stdout(out), mock.patch("papyrus_content.story_share_view.render_story_page", side_effect=RuntimeError(f"boom {token}")):
        assert call("viewStoryShare", {"token": token}, GUEST) == {"state": "unavailable"}
    assert token not in out.getvalue()


def test_a_story_the_public_site_cannot_draw_is_refused_when_the_link_is_made(world):
    save_item(world.client, ItemFields(type="article", slug="_hidden", section="essays", front_matter_yaml=None, body_markus="x\n", aliases=[], id="item-hidden"), actor="w", now=NOW)
    refused = call("createStoryShare", {"lineageId": "item-hidden"}, EDITOR)
    assert refused["ok"] is False and "no page on the public site" in refused["errors"][0]["message"]


def test_a_site_without_public_pages_says_so_plainly(world):
    with mock.patch.object(handler_module, "projection_configured", return_value=False):
        refused = make()
    assert refused["ok"] is False and "not available on this site" in refused["errors"][0]["message"]


def test_the_expiry_must_be_one_of_the_buttons(world):
    for bad in (0, 31, 3650, "never", None):
        assert make(expiresInDays=bad)["ok"] is False


def test_publishing_through_the_front_door_ends_the_link(world):
    token = make()["path"].rsplit("/", 1)[1]
    published = call("publishItem", {"id": LINEAGE}, EDITOR)
    assert published["ok"] is True
    answer = call("viewStoryShare", {"token": token}, GUEST)
    assert answer["state"] == "published" and answer["address"].startswith("https://ledger.example.org/essays/")


def test_spiking_through_the_front_door_ends_the_link(world):
    token = make()["path"].rsplit("/", 1)[1]
    call("moveStoryStage", {"lineageId": LINEAGE, "stage": "spiked"}, EDITOR)
    assert call("viewStoryShare", {"token": token}, GUEST) == {"state": "unavailable"}
    assert call("listStoryShares", {"lineageId": LINEAGE}, EDITOR)["shares"][0]["state"] == "ended"
