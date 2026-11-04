"""Share a Story by URL (features_backend/story-share-links.feature, docs/story-share-links.md): the rules, the page, the pictures and the attacks."""

from __future__ import annotations

import copy
import hashlib
import json
import re

import pytest

from papyrus_content.projection.source import PublishedContentSource
from papyrus_content.publishing import ItemFields, publish_item, save_item
from papyrus_content.story_reporting import save_story_version
from papyrus_content.story_share_render import DRAFT_TITLE_PREFIX, BAND_ATTRIBUTE
from papyrus_content.story_share_view import check_shareable, view_media, view_share
from papyrus_content.story_shares import (
    ANONYMOUS,
    DEFAULT_EXPIRY_DAYS,
    EXPIRY_DAYS,
    MAX_SHARE_EVENTS,
    ShareRefused,
    Viewer,
    create_share,
    end_shares,
    hash_token,
    list_shares,
    new_token,
    revoke_share,
    story_events,
    viewer_from_identity,
    well_formed,
)
from procedures.newsroom.tests.standard_frontend_support import ProjectedSite

EDITOR = Viewer(signed_in=True, groups=("editor",), sub="sub-editor", label="Ed Itor")
ADMIN = Viewer(signed_in=True, groups=("admin",), sub="sub-admin", label="Ad Min")
READER = Viewer(signed_in=True, groups=("reader",), sub="sub-reader", label="Rea Der")
NOW = "2026-11-04T12:00:00Z"
LATER = "2026-11-06T12:00:00Z"
UNAVAILABLE = {"state": "unavailable"}


def add_story(site: ProjectedSite, slug: str, body: str, *, section: str = "essays") -> str:
    item_id = f"item-{section}-{slug}"
    save_item(site.client, ItemFields(type="article", slug=slug, section=section, front_matter_yaml=f"title: Draft {slug}\ndate: 2026-11-01\n", body_markus=body, aliases=[], id=item_id), actor="writer", now=NOW)
    return item_id


@pytest.fixture()
def site():
    projected = ProjectedSite("sectioned")
    yield projected
    projected.cleanup()


def share(site, lineage, *, viewers="anyone", version=None, days=30, actor=EDITOR, now=NOW):
    return create_share(site.client, lineage, viewers=viewers, version_number=version, expires_in_days=days, actor=actor, now=now)


def view(site, token, viewer=ANONYMOUS, now=NOW):
    return view_share(site.client, token, viewer, projector=site.projector, now=now)


def media(site, token, reference, viewer=ANONYMOUS, now=NOW):
    return view_media(site.client, token, viewer, reference, projector=site.projector, now=now)


# ------------------------------------------------------------------ the token


def test_a_token_is_at_least_256_bits_and_only_its_hash_is_stored(site):
    lineage = add_story(site, "tokens", "Words.\n")
    made = share(site, lineage)
    token = made["token"]
    assert well_formed(token) and len(token) >= 43  # 43 URL-safe characters carry 256 bits
    assert new_token() != new_token()
    rows = site.client.tables["StoryShare"]
    assert list(rows) == [hash_token(token)] and rows[hash_token(token)]["tokenHash"] == hashlib.sha256(token.encode()).hexdigest()
    stored = json.dumps(rows) + json.dumps(site.client.tables.get("Item", {}))
    assert token not in stored
    assert token not in json.dumps(made["share"])
    assert "tokenHash" not in made["share"] and "id" not in made["share"]


def test_listing_never_shows_the_token_or_its_hash(site):
    lineage = add_story(site, "listing", "Words.\n")
    made = share(site, lineage)
    listed = list_shares(site.client, lineage, actor=EDITOR, now=NOW)
    assert len(listed) == 1 and listed[0]["shareId"] == made["share"]["shareId"]
    text = json.dumps(listed)
    assert made["token"] not in text and hash_token(made["token"]) not in text


# ------------------------------------------------------------------ the page


def test_a_stranger_sees_the_public_layout_labelled_draft(site):
    lineage = add_story(site, "hello", "A draft sentence about rivers.\n")
    token = share(site, lineage)["token"]
    answer = view(site, token)
    assert answer["state"] == "ok"
    page = answer["html"]
    assert "A draft sentence about rivers." in page
    assert 'class="markus-site-masthead"' in page and "Example Ledger" in page  # the site's own masthead, not a console
    assert f"<title>{DRAFT_TITLE_PREFIX}Draft hello" in page and answer["title"].startswith("DRAFT: ")
    band = re.search(rf"<div class=\"papyrus-share-band\"[^>]*{BAND_ATTRIBUTE}>(.*?)</div>", page, re.S)
    assert band and "DRAFT" in band.group(1) and "<svg" in band.group(1)  # the word and an icon: never colour alone
    assert page.index("papyrus-share-band") < page.index('<main id="main">')
    assert 'name="robots" content="noindex, nofollow"' in page and 'name="referrer" content="no-referrer"' in page
    assert 'rel="canonical"' not in page and "og:url" not in page and "application/ld+json" not in page and 'rel="alternate"' not in page
    assert "var(--papyrus-ink" in page  # the band takes the site's own tokens
    # the site's stylesheets and links are the public site's, because this page is served from another origin
    assert 'href="https://ledger.example.org/css/site-theme.css' in page and 'href="https://ledger.example.org/essays/"' in page
    assert "Not published." in page
    assert "markus-page-actions" not in page and "View as Markdown" not in page  # the Markdown twin of a draft does not exist on the public site


def test_the_draft_band_is_the_same_for_a_signed_in_link(site):
    lineage = add_story(site, "members", "Members only.\n")
    token = share(site, lineage, viewers="signed-in")["token"]
    page = view(site, token, EDITOR)["html"]
    assert BAND_ATTRIBUTE in page and "signed-in newsroom members only" in page


def test_a_shared_page_has_no_analytics_and_no_consent_banner():
    settings = json.loads(json.dumps(__import__("procedures.newsroom.tests.standard_frontend_support", fromlist=["x"]).fixture_settings("sectioned")))
    settings["chrome"] = {"ga_measurement_id": "G-ABCDE12345", "consent_mode": {}}
    projected = ProjectedSite(settings=settings, content=__import__("procedures.newsroom.tests.standard_frontend_support", fromlist=["x"]).FIXTURES / "sectioned" / "content")
    try:
        published = projected.projector  # the site itself does carry analytics on its public pages
        assert "googletagmanager" in projected.text("about/index.html")
        lineage = add_story(projected, "tracked", "No tracking.\n")
        token = share(projected, lineage)["token"]
        page = view(projected, token)["html"]
        for forbidden in ("googletagmanager", "gtag(", "dataLayer", "papyrus-consent", "papyrusConsent"):
            assert forbidden not in page
        assert published._settings.chrome.ga_measurement_id == "G-ABCDE12345"  # the live projector was not changed
    finally:
        projected.cleanup()


def test_rendering_writes_nothing_to_the_live_site(site):
    lineage = add_story(site, "quiet", "Quiet.\n")
    before_tree, before_writes = site.digests(), len(site.writer.__dict__.get("calls", []) or [])
    token = share(site, lineage)["token"]
    view(site, token)
    media(site, token, "/assets/nothing.png")
    assert site.digests() == before_tree
    assert len(site.writer.__dict__.get("calls", []) or []) == before_writes


def test_a_shared_story_is_not_listed_anywhere_on_the_site(site):
    lineage = add_story(site, "secret-draft", "Hidden.\n")
    token = share(site, lineage)["token"]
    view(site, token)
    for key, content in site.tree.items():
        assert b"secret-draft" not in content and b"Draft secret-draft" not in content, key
        assert token.encode() not in content, key


# ------------------------------------------------------------------ who can open it


@pytest.mark.parametrize(
    "token",
    ["", " ", "x", "a" * 42, "a" * 44, "a" * 43 + "\n", "../" * 20, "%2e%2e%2f" * 5, "a" * 10_000, None, 5, {"$ne": ""}, "é" * 43, "a" * 42 + "/", "a" * 41 + "\x00a", "ａ" * 43],
)
def test_a_wrong_or_tricky_token_answers_exactly_like_a_missing_one(site, token):
    lineage = add_story(site, "wrong", "Words.\n")
    share(site, lineage)
    assert view(site, token) == UNAVAILABLE
    assert media(site, token, "/assets/a.png") == UNAVAILABLE


def test_unknown_expired_and_revoked_links_are_indistinguishable(site):
    lineage = add_story(site, "same", "Words.\n")
    expiring = share(site, lineage, days=7)
    revoked = share(site, lineage)
    revoke_share(site.client, lineage, revoked["share"]["shareId"], actor=EDITOR, now=NOW)
    unknown = new_token()
    answers = [view(site, unknown), view(site, revoked["token"]), view(site, expiring["token"], now="2026-11-12T12:00:00Z")]
    assert answers == [UNAVAILABLE, UNAVAILABLE, UNAVAILABLE]
    assert view(site, expiring["token"], now="2026-11-10T12:00:00Z")["state"] == "ok"  # still inside seven days


def test_expiry_is_a_choice_of_7_30_or_90_days_with_30_the_default(site):
    lineage = add_story(site, "expiry", "Words.\n")
    assert EXPIRY_DAYS == (7, 30, 90) and DEFAULT_EXPIRY_DAYS == 30
    for days, expires in ((7, "2026-11-11T12:00:00Z"), (30, "2026-12-04T12:00:00Z"), (90, "2027-02-02T12:00:00Z")):
        assert share(site, lineage, days=days)["share"]["expiresAt"] == expires
    for bad in (0, 1, 31, 365, None, "30", -7, 10**9):
        with pytest.raises(ShareRefused):
            share(site, lineage, days=bad)


def test_a_signed_in_link_sends_a_stranger_to_sign_in_and_turns_away_a_non_editor(site):
    lineage = add_story(site, "members", "Members only.\n")
    token = share(site, lineage, viewers="signed-in")["token"]
    assert view(site, token, ANONYMOUS) == {"state": "sign-in"}
    assert view(site, token, READER) == UNAVAILABLE  # signed in, not staff: no more detail than a stranger gets
    assert view(site, token, Viewer(signed_in=True, groups=(), sub="x"))["state"] == "unavailable"
    assert view(site, token, EDITOR)["state"] == "ok" and view(site, token, ADMIN)["state"] == "ok"
    assert media(site, token, "/assets/a.png", READER) == UNAVAILABLE and media(site, token, "/assets/a.png", ANONYMOUS) == UNAVAILABLE
    # a wrong token on a signed-in link never says "sign in": that would tell a stranger a link exists
    assert view(site, new_token(), ANONYMOUS) == UNAVAILABLE


def test_the_viewer_comes_only_from_the_backend_identity():
    assert viewer_from_identity(None) == ANONYMOUS
    assert viewer_from_identity({"cognitoIdentityId": "guest", "userArn": "arn"}) == ANONYMOUS  # a guest identity-pool call has no sub or issuer
    assert viewer_from_identity({"sub": "s", "issuer": "https://idp", "groups": ["editor"]}).is_staff
    assert viewer_from_identity({"sub": "s", "issuer": "https://idp", "claims": {"cognito:groups": "[admin Google_1]"}}).is_staff
    assert not viewer_from_identity({"sub": "s", "issuer": "https://idp", "groups": ["reader"]}).is_staff
    assert not viewer_from_identity({"sub": "s", "groups": ["editor"]}).signed_in  # no issuer: not a user pool identity


def test_only_an_editor_or_admin_can_make_list_or_revoke(site):
    lineage = add_story(site, "roles", "Words.\n")
    for who in (ANONYMOUS, READER, Viewer(signed_in=True, groups=(), sub="s")):
        with pytest.raises(ShareRefused):
            share(site, lineage, actor=who)
        with pytest.raises(ShareRefused):
            list_shares(site.client, lineage, actor=who)
        with pytest.raises(ShareRefused):
            revoke_share(site.client, lineage, "anything", actor=who)
    made = share(site, lineage, actor=ADMIN)
    with pytest.raises(ShareRefused):
        revoke_share(site.client, lineage, made["share"]["shareId"], actor=READER)
    assert view(site, made["token"])["state"] == "ok"  # the refused revoke changed nothing


# ------------------------------------------------------------------ which version, which Story


def test_current_follows_new_versions_and_a_pinned_version_stays_put(site):
    lineage = add_story(site, "versions", "First words.\n")
    following = share(site, lineage)["token"]
    pinned = share(site, lineage, version=1)["token"]
    assert "First words." in view(site, following)["html"] and "Version 1" in view(site, pinned)["html"]
    save_story_version(site.client, lineage, front_matter_yaml="title: Draft versions\ndate: 2026-11-01\n", body_markus="Second words.\n", actor="writer", change_reason="edit", now=LATER)
    now_page, pinned_page = view(site, following, now=LATER)["html"], view(site, pinned, now=LATER)["html"]
    assert "Second words." in now_page and "First words." not in now_page and "Version 2" in now_page and "follows new versions" in now_page
    assert "First words." in pinned_page and "Second words." not in pinned_page  # a pinned link does not show other versions
    assert "follows new versions" not in pinned_page


def test_a_pinned_link_cannot_name_a_version_the_story_does_not_have(site):
    lineage = add_story(site, "short", "Words.\n")
    with pytest.raises(ShareRefused):
        share(site, lineage, version=7)
    with pytest.raises(ShareRefused):
        create_share(site.client, "no-such-story", actor=EDITOR, now=NOW)


def test_a_token_opens_only_its_own_story_never_another_or_a_published_page(site):
    mine = add_story(site, "mine", "Mine only.\n")
    other = add_story(site, "other", "Other draft body.\n")
    token = share(site, mine)["token"]
    page = view(site, token)["html"]
    assert "Mine only." in page and "Other draft body." not in page
    assert "Slow Water" not in page.split("<main")[1].split("</main>")[0]  # a published Story's text is not in the draft's main column
    # the record names one lineage; changing nothing else, a second token for the other Story opens only that one
    assert "Other draft body." in view(site, share(site, other)["token"])["html"]
    assert site.client.tables["StoryShare"][hash_token(token)]["storyLineageId"] == mine


def test_a_share_page_has_no_editorial_notes_reviews_messages_votes_or_stars(site):
    lineage = add_story(site, "private", "Public words.\n")
    row = site.client.tables["Item"][lineage]
    row["metadata"] = json.dumps({"stageMoves": [{"note": "EDITORIAL-NOTE-SECRET"}], "outline": {"by": "a"}})
    row["editorial"] = json.dumps({"notes": "EDITORIAL-NOTE-SECRET"})
    row["starRating"] = 5
    site.client.tables.setdefault("Message", {})["m1"] = {"id": "m1", "content": "MESSAGE-SECRET", "threadId": lineage}
    site.client.tables.setdefault("ReviewRequest", {})["r1"] = {"id": "r1", "subject": json.dumps({"id": lineage}), "ask": "REVIEW-SECRET"}
    token = share(site, lineage)["token"]
    page = view(site, token)["html"]
    for secret in ("EDITORIAL-NOTE-SECRET", "MESSAGE-SECRET", "REVIEW-SECRET", "starRating", "stageMoves"):
        assert secret not in page
    assert "Public words." in page
    reads = [call for call in site.client.calls if call[0] in ("get", "list", "list_by_index")]
    assert not any(call[1] in ("Message", "ReviewRequest", "MessageThread", "ModelAttachment") for call in reads)


def test_a_spiked_story_ends_its_links(site):
    lineage = add_story(site, "spike", "Words.\n")
    token = share(site, lineage)["token"]
    assert view(site, token)["state"] == "ok"
    site.client.tables["Item"][lineage]["stage"] = "spiked"
    assert view(site, token) == UNAVAILABLE
    with pytest.raises(ShareRefused):
        share(site, lineage)
    assert end_shares(site.client, lineage, "spiked", now=LATER) == 1
    assert view(site, token) == UNAVAILABLE


def test_publishing_ends_its_links_and_the_old_address_points_at_the_published_page(site):
    lineage = add_story(site, "goes-live", "Words.\n")
    token = share(site, lineage)["token"]
    other = share(site, lineage, viewers="signed-in")["token"]
    publish_item(site.client, lineage, actor="editor", now=LATER)  # publishing itself ends the links
    assert [row["state"] for row in list_shares(site.client, lineage, actor=EDITOR, now=LATER)] == ["ended", "ended"]
    assert end_shares(site.client, lineage, "published", now=LATER) == 0  # and ending again changes nothing
    answer = view(site, token, now=LATER)
    assert answer == {"state": "published", "address": "https://ledger.example.org/essays/goes-live/"}
    assert view(site, other, ANONYMOUS, now=LATER) == {"state": "sign-in"}  # the sign-in rule still comes first
    assert view(site, other, READER, now=LATER) == UNAVAILABLE
    assert "html" not in answer and "Words." not in json.dumps(answer)
    kinds = [event["kind"] for event in story_events(site.client, lineage)]
    assert kinds.count("ended") == 2


def test_even_before_the_hook_runs_a_link_made_before_publishing_does_not_show_the_draft(site):
    lineage = add_story(site, "lazy", "Words.\n")
    token = share(site, lineage)["token"]
    publish_item(site.client, lineage, actor="editor", now=LATER)
    assert view(site, token, now=LATER)["state"] == "published"  # checked when opened, not only when published


def test_a_later_draft_of_a_published_story_can_be_shared_but_the_published_version_cannot(site):
    lineage = "item-essays-fords"
    published_version = site.client.tables["Item"][lineage]["versionNumber"]
    with pytest.raises(ShareRefused):
        share(site, lineage, version=published_version)
    save_story_version(site.client, lineage, front_matter_yaml="title: Fords again\ndate: 2026-01-01\n", body_markus="A newer draft of a live story.\n", actor="writer", change_reason="edit", now=LATER)
    token = share(site, lineage, now=LATER)["token"]
    assert "A newer draft of a live story." in view(site, token, now=LATER)["html"]


def test_a_story_with_no_public_page_is_refused_when_the_link_is_made(site):
    lineage = "item-ghost"
    save_item(site.client, ItemFields(type="article", slug="_ghost", section="essays", front_matter_yaml=None, body_markus="x\n", aliases=[], id=lineage), actor="writer", now=NOW)
    with pytest.raises(ShareRefused):
        check_shareable(site.client, lineage, None, projector=site.projector)


# ------------------------------------------------------------------ pictures


def add_picture_story(site, body):
    lineage = add_story(site, "pictured", body)
    site.client.tables.setdefault("MediaAsset", {})["media-1"] = {
        "id": "media-1", "itemId": lineage, "type": "image", "role": "body", "sortKey": "1", "alt": "A river",
        "storagePath": "media/assets/pictured/river.png", "metadata": json.dumps({"srcPath": "assets/pictured/river.png"}),
    }
    return lineage


def test_pictures_load_through_the_links_own_route_not_the_consoles_or_the_public_sites(site):
    lineage = add_picture_story(site, "![A river](assets/pictured/river.png)\n\n![Elsewhere](/assets/responsive/x-640.webp)\n\n![Far away](https://images.example.net/far.png)\n")
    token = share(site, lineage)["token"]
    page = view(site, token)["html"]
    route = f"/api/share/{token}/media?u="
    assert f'src="{route}assets%2Fpictured%2Friver.png"' in page and f'src="{route}%2Fassets%2Fresponsive%2Fx-640.webp"' in page
    assert 'src="https://images.example.net/far.png"' in page  # someone else's picture is left alone
    original = media(site, token, "assets/pictured/river.png")
    assert original == {"state": "ok", "source": "media", "storagePath": "media/assets/pictured/river.png"}
    assert media(site, token, "/assets/responsive/x-640.webp") == {"state": "ok", "source": "site", "url": "https://ledger.example.org/assets/responsive/x-640.webp"}


def test_a_token_never_reaches_another_storys_pictures_or_any_other_path(site):
    mine = add_picture_story(site, "![A river](assets/pictured/river.png)\n")
    other = add_story(site, "elsewhere", "![Theirs](assets/elsewhere/theirs.png)\n")
    site.client.tables["MediaAsset"]["media-2"] = {"id": "media-2", "itemId": other, "type": "image", "role": "body", "sortKey": "1", "alt": "Theirs",
                                                   "storagePath": "media/assets/elsewhere/theirs.png", "metadata": json.dumps({"srcPath": "assets/elsewhere/theirs.png"})}
    site.client.tables["MediaAsset"]["media-3"] = {"id": "media-3", "itemId": "someone-elses-secret", "type": "image", "role": "body", "sortKey": "1", "alt": "S",
                                                   "storagePath": "media/assets/secret/plan.png", "metadata": json.dumps({"srcPath": "assets/secret/plan.png"})}
    token = share(site, mine)["token"]
    other_token = share(site, other)["token"]
    assert media(site, other_token, "assets/elsewhere/theirs.png")["state"] == "ok"
    attacks = [
        "assets/elsewhere/theirs.png",            # another Story's picture, with this Story's token
        "assets/secret/plan.png",                  # a MediaAsset of an unrelated item
        "media/assets/pictured/river.png",         # the storage key instead of the address the page used
        "assets/pictured/../elsewhere/theirs.png",
        "../../media/assets/secret/plan.png",
        "assets/pictured/river.png/../../secret/plan.png",
        "/assets/pictured/river.png",              # a different spelling of the same file
        "assets%2Fpictured%2Friver.png",
        "assets/pictured/river.png?x=1",
        "assets/pictured/river.png\x00.png",
        "assets\\pictured\\river.png",
        "https://ledger.example.org/../../etc/passwd",
        "https://evil.example.net/x.png",
        "//evil.example.net/x.png",
        "file:///etc/passwd",
        "http://169.254.169.254/latest/meta-data/",
        "",
        " ",
        None,
        7,
        ["assets/pictured/river.png"],
        "a" * 5000,
    ]
    for attack in attacks:
        assert media(site, token, attack) == UNAVAILABLE, attack
    assert media(site, token, "assets/pictured/river.png")["state"] == "ok"


def test_a_pinned_links_pictures_are_that_versions_pictures_only(site):
    lineage = add_picture_story(site, "![A river](assets/pictured/river.png)\n")
    pinned = share(site, lineage, version=1)["token"]
    save_story_version(site.client, lineage, front_matter_yaml="title: Draft pictured\ndate: 2026-11-01\n", body_markus="![Another](assets/pictured/lake.png)\n", actor="w", change_reason="e", now=LATER)
    new_version = max(site.client.tables["Item"].values(), key=lambda row: row.get("versionNumber") or 0)["id"]
    site.client.tables["MediaAsset"]["media-4"] = {"id": "media-4", "itemId": new_version, "type": "image", "role": "body", "sortKey": "1", "alt": "L",
                                                   "storagePath": "media/assets/pictured/lake.png", "metadata": json.dumps({"srcPath": "assets/pictured/lake.png"})}
    following = share(site, lineage, now=LATER)["token"]
    assert media(site, pinned, "assets/pictured/river.png", now=LATER)["state"] == "ok"
    assert media(site, pinned, "assets/pictured/lake.png", now=LATER) == UNAVAILABLE
    assert media(site, following, "assets/pictured/lake.png", now=LATER)["state"] == "ok"
    assert media(site, following, "assets/pictured/river.png", now=LATER) == UNAVAILABLE


def test_media_stops_when_the_link_does(site):
    lineage = add_picture_story(site, "![A river](assets/pictured/river.png)\n")
    made = share(site, lineage)
    assert media(site, made["token"], "assets/pictured/river.png")["state"] == "ok"
    revoke_share(site.client, lineage, made["share"]["shareId"], actor=EDITOR, now=NOW)
    assert media(site, made["token"], "assets/pictured/river.png") == UNAVAILABLE
    assert media(site, made["token"], "assets/pictured/river.png", now="2027-01-01T00:00:00Z") == UNAVAILABLE


# ------------------------------------------------------------------ the record on the Story


def test_creating_opening_and_revoking_are_recorded_on_the_story_without_personal_data(site):
    lineage = add_story(site, "recorded", "Words.\n")
    made = share(site, lineage)
    view(site, made["token"])
    view(site, made["token"])
    revoke_share(site.client, lineage, made["share"]["shareId"], actor=EDITOR, now=LATER)
    events = story_events(site.client, lineage)
    assert [event["kind"] for event in events] == ["created", "opened", "revoked"]  # an open is recorded once a day; the count is on the link
    assert events[0]["by"] == "Ed Itor" and events[0]["viewers"] == "anyone" and events[0]["version"] == "current"
    assert set(events[1]) == {"at", "kind", "shareId"} and events[1]["at"] == "2026-11-04"  # a day, nothing about who
    listed = list_shares(site.client, lineage, actor=EDITOR, now=LATER)[0]
    assert listed["openCount"] == 2 and listed["lastOpenedOn"] == "2026-11-04" and listed["state"] == "revoked" and listed["createdBy"] == "Ed Itor"
    stored = json.dumps(site.client.tables["StoryShare"])
    for personal in ("ip", "address", "agent", "referer", "cookie"):
        assert personal not in set(re.findall(r"[a-z]+", stored.lower())) - {"createdby"}, personal


def test_the_event_list_stays_inside_the_record_size(site):
    lineage = add_story(site, "busy", "Words.\n")
    for index in range(MAX_SHARE_EVENTS + 20):
        share(site, lineage, now=f"2026-11-04T12:{index % 60:02d}:{index // 60:02d}Z")
    assert len(story_events(site.client, lineage)) == MAX_SHARE_EVENTS


def test_revoking_twice_changes_nothing_and_an_unknown_link_is_refused(site):
    lineage = add_story(site, "twice", "Words.\n")
    made = share(site, lineage)
    assert revoke_share(site.client, lineage, made["share"]["shareId"], actor=EDITOR, now=NOW)["changed"] is True
    assert revoke_share(site.client, lineage, made["share"]["shareId"], actor=EDITOR, now=NOW)["changed"] is False
    with pytest.raises(ShareRefused):
        revoke_share(site.client, lineage, "nonexistent", actor=EDITOR, now=NOW)
    other = add_story(site, "elsewhere", "Words.\n")
    with pytest.raises(ShareRefused):  # a link of one Story cannot be revoked through another
        revoke_share(site.client, other, made["share"]["shareId"], actor=EDITOR, now=NOW)


def test_the_listing_says_who_made_each_link_who_can_view_what_it_shows_when_it_expires_and_when_it_was_opened(site):
    lineage = add_story(site, "details", "Words.\n")
    share(site, lineage, viewers="signed-in", version=1, days=90, actor=ADMIN)
    row = list_shares(site.client, lineage, actor=EDITOR, now=NOW)[0]
    assert (row["createdBy"], row["viewers"], row["version"], row["expiresAt"], row["state"], row["lastOpenedOn"]) == ("Ad Min", "signed-in", 1, "2027-02-02T12:00:00Z", "active", None)
    assert list_shares(site.client, lineage, actor=EDITOR, now="2027-03-01T00:00:00Z")[0]["state"] == "expired"


def test_the_site_index_the_page_is_drawn_against_is_only_published_content(site):
    lineage = add_story(site, "indexed", "Words.\n")
    index = PublishedContentSource(site.client).site_index()
    assert all(summary.item_id != lineage for summary in index.items)
    token = share(site, lineage)["token"]
    assert view_share(site.client, token, ANONYMOUS, projector=site.projector, now=NOW, site_index=lambda: copy.copy(index))["state"] == "ok"
