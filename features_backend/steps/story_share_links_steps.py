"""Share a Story by URL (features_backend/story-share-links.feature). Real code, a fixture site, an in-memory data API."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import story_share_commands  # noqa: E402
from papyrus_content.operator_errors import OperatorError  # noqa: E402
from papyrus_content.publishing import publish_item  # noqa: E402
from papyrus_content.story_reporting import move_story_stage, save_story_version  # noqa: E402
from papyrus_content.story_share_render import BAND_ATTRIBUTE  # noqa: E402
from papyrus_content.story_shares import ANONYMOUS, ShareRefused, hash_token, list_shares, revoke_share, story_events  # noqa: E402
from procedures.newsroom.tests.standard_frontend_support import ProjectedSite  # noqa: E402
from procedures.newsroom.tests.test_story_shares import EDITOR, LATER, NOW, READER, add_story, media, share, view  # noqa: E402

UNAVAILABLE = {"state": "unavailable"}
READER_NO_RIGHTS = READER


def token_of(context, name="main"):
    return context.tokens[name]


@given("a site with a published Story and an editor")
def site(context):
    context.site = ProjectedSite("sectioned")
    context.add_cleanup(context.site.cleanup)
    context.tokens, context.answers, context.refused = {}, {}, None


@given('a draft Story "Lower fords" that is not published')
def draft(context):
    context.lineage = add_story(context.site, "lower-fords", "The river negotiates with the valley.\n")


@given("the editor shares the draft with anyone with the link")
def share_anyone(context):
    made = share(context.site, context.lineage)
    context.tokens["main"], context.share_id = made["token"], made["share"]["shareId"]


@given("the editor shares the draft with only people signed in to the newsroom")
def share_signed_in(context):
    context.tokens["main"] = share(context.site, context.lineage, viewers="signed-in")["token"]


@given("the editor shares the current version, and also shares version 1 only")
def share_two(context):
    context.tokens["current"] = share(context.site, context.lineage)["token"]
    context.tokens["pinned"] = share(context.site, context.lineage, version=1)["token"]


@when("a stranger opens the link")
def stranger_opens(context):
    context.digests_before, context.calls_before = context.site.digests(), len(context.site.client.calls)
    context.answer = view(context.site, token_of(context))


@when("a signed-in reader without editor rights opens the link")
def reader_opens(context):
    context.answer = view(context.site, token_of(context), READER_NO_RIGHTS)


@when("a signed-in editor opens the link")
def editor_opens(context):
    context.answer = view(context.site, token_of(context), EDITOR)


@then("the page is the site's own public layout with the draft's text")
def public_layout(context):
    page = context.answer["html"]
    assert context.answer["state"] == "ok" and 'class="markus-site-masthead"' in page and "Example Ledger" in page
    assert "The river negotiates with the valley." in page


@then("the page carries a DRAFT band with an icon and the word DRAFT")
def band(context):
    page = context.answer["html"]
    start = page.index(BAND_ATTRIBUTE)
    band_html = page[start : page.index("</div>", start)]
    assert "<svg" in band_html and ">DRAFT<" in band_html


@then('the page title starts with "DRAFT: "')
def draft_title(context):
    assert context.answer["title"].startswith("DRAFT: ") and "<title>DRAFT: " in context.answer["html"]


@then("the page asks not to be indexed and has no canonical address, analytics or consent banner")
def no_index(context):
    page = context.answer["html"]
    assert 'content="noindex, nofollow"' in page
    for absent in ('rel="canonical"', "og:url", "application/ld+json", "googletagmanager", "papyrus-consent"):
        assert absent not in page, absent


@then("they are sent to sign in")
def sent_to_sign_in(context):
    assert context.answer == {"state": "sign-in"}


@then("they are told the link is not available")
def told_unavailable(context):
    assert context.answer == UNAVAILABLE


@when("the editor saves a second version")
def second_version(context):
    save_story_version(context.site.client, context.lineage, front_matter_yaml="title: Lower fords\n", body_markus="A second version, written later.\n", actor="writer", change_reason="edit", now=LATER)


@then("the link for the current version shows the second version")
def current_shows_second(context):
    page = view(context.site, context.tokens["current"], now=LATER)["html"]
    assert "A second version, written later." in page


@then("the link for version 1 still shows the first version only")
def pinned_shows_first(context):
    page = view(context.site, context.tokens["pinned"], now=LATER)["html"]
    assert "The river negotiates with the valley." in page and "A second version" not in page


@when("the editor makes links lasting 7, 30 and 90 days")
def lasting(context):
    context.made = {days: share(context.site, context.lineage, days=days)["share"]["expiresAt"] for days in (7, 30, 90)}


@then("each link ends exactly that many days after it was made")
def ends_after(context):
    assert context.made == {7: "2026-11-11T12:00:00Z", 30: "2026-12-04T12:00:00Z", 90: "2027-02-02T12:00:00Z"}


@then("a link with no expiry choice lasts 30 days")
def default_thirty(context):
    from papyrus_content.story_shares import create_share

    made = create_share(context.site.client, context.lineage, actor=EDITOR, now=NOW)
    assert made["share"]["expiresAt"] == "2026-12-04T12:00:00Z"


@then("a link that lasts 365 days or forever is refused")
def never_refused(context):
    for bad in (365, None, "never", 0):
        try:
            share(context.site, context.lineage, days=bad)
        except ShareRefused:
            continue
        raise AssertionError(f"{bad!r} was accepted")


@when("the editor revokes it")
def revokes(context):
    revoke_share(context.site.client, context.lineage, context.share_id, actor=EDITOR, now=NOW)


@when("a link was made that has since expired")
def expired_link(context):
    context.tokens["expired"] = share(context.site, context.lineage, days=7)["token"]
    context.later = "2026-12-01T00:00:00Z"


@then("the revoked link, the expired link and a link that never existed all give the same plain answer")
def indistinguishable(context):
    from papyrus_content.story_shares import new_token

    answers = [view(context.site, context.tokens["main"], now=context.later), view(context.site, context.tokens["expired"], now=context.later), view(context.site, new_token(), now=context.later)]
    assert answers == [UNAVAILABLE] * 3


@when("the Story that was shared is published")
def published(context):
    publish_item(context.site.client, context.lineage, actor="editor", now=LATER)


@then("the old link shows a plain page that links to the published address")
def old_link_notice(context):
    context.answer = view(context.site, token_of(context), now=LATER)
    assert context.answer == {"state": "published", "address": "https://ledger.example.org/essays/lower-fords/"}


@then("the draft text is not in that answer")
def no_draft_text(context):
    assert "negotiates" not in json.dumps(context.answer)


@when("the Story that was shared is spiked")
def spiked(context):
    move_story_stage(context.site.client, context.lineage, "spiked", actor="editor", now=LATER)


@then('the old link gives the plain "not available" answer')
def plain_unavailable(context):
    assert view(context.site, token_of(context), now=LATER) == UNAVAILABLE


@given("the draft has a picture and another Story has a picture of its own")
def pictures(context):
    context.site.client.tables["Item"][context.lineage]["bodyMarkus"] = "![A river](assets/lower-fords/river.png)\n"
    other = add_story(context.site, "other-draft", "![Theirs](assets/other-draft/theirs.png)\n")
    tables = context.site.client.tables.setdefault("MediaAsset", {})
    for identifier, item, path in (("m1", context.lineage, "assets/lower-fords/river.png"), ("m2", other, "assets/other-draft/theirs.png")):
        tables[identifier] = {"id": identifier, "itemId": item, "type": "image", "role": "body", "sortKey": "1", "alt": "x", "storagePath": f"media/{path}", "metadata": json.dumps({"srcPath": path})}


@when("a stranger asks the link for the draft's picture")
def ask_picture(context):
    context.answer = media(context.site, token_of(context), "assets/lower-fords/river.png")


@then("the picture is found")
def picture_found(context):
    assert context.answer == {"state": "ok", "source": "media", "storagePath": "media/assets/lower-fords/river.png"}


@when("a stranger asks the link for the other Story's picture, a parent path, an encoded path or another host")
def ask_attacks(context):
    attacks = ["assets/other-draft/theirs.png", "assets/lower-fords/../other-draft/theirs.png", "../../media/assets/other-draft/theirs.png", "assets%2Fother-draft%2Ftheirs.png", "https://evil.example.net/theirs.png", "//evil.example.net/x.png"]
    context.attack_answers = [media(context.site, token_of(context), attack) for attack in attacks]


@then('every one of them gets the plain "not available" answer')
def attacks_refused(context):
    assert context.attack_answers == [UNAVAILABLE] * 6


@when("a reader without editor rights tries to share the draft")
def reader_shares(context):
    try:
        share(context.site, context.lineage, actor=READER)
    except ShareRefused as refusal:
        context.refused = str(refusal)


@then("it is refused and no link exists")
def refused_none(context):
    assert context.refused and not context.site.client.tables.get("StoryShare")


@when("a stranger with no sign-in tries to list or revoke links")
def stranger_manages(context):
    context.refusals = []
    for attempt in (lambda: list_shares(context.site.client, context.lineage, actor=ANONYMOUS), lambda: revoke_share(context.site.client, context.lineage, "x", actor=ANONYMOUS)):
        try:
            attempt()
        except ShareRefused as refusal:
            context.refusals.append(str(refusal))


@then("it is refused too")
def refused_too(context):
    assert len(context.refusals) == 2


@when("a stranger opens the link twice on the same day")
def opens_twice(context):
    view(context.site, token_of(context))
    view(context.site, token_of(context))


@then("the Story's record shows the link was made, opened that day and revoked")
def story_record(context):
    assert [event["kind"] for event in story_events(context.site.client, context.lineage)] == ["created", "opened", "revoked"]


@then("the record names no address, agent or identity for the stranger")
def no_personal(context):
    opened = [event for event in story_events(context.site.client, context.lineage) if event["kind"] == "opened"][0]
    assert set(opened) == {"at", "kind", "shareId"} and opened["at"] == NOW[:10]


@then("the editor's list shows who made the link, who can view, what it shows, when it expires and when it was last opened but never the token")
def editors_list(context):
    row = list_shares(context.site.client, context.lineage, actor=EDITOR, now=NOW)[0]
    assert row["createdBy"] == "Ed Itor" and row["viewers"] == "anyone" and row["version"] == "current" and row["expiresAt"] and row["lastOpenedOn"] == NOW[:10]
    text = json.dumps(row)
    assert token_of(context) not in text and hash_token(token_of(context)) not in text


@then("nothing was written to the live site's output")
def nothing_written(context):
    opened = context.site.client.calls[context.calls_before:]
    assert not [call for call in opened if call[0] in ("create", "update", "delete", "upsert") and call[1] not in ("StoryShare", "Item")]
    assert context.site.digests() == context.digests_before
    assert not any(token_of(context).encode() in content for content in context.site.tree.values())


@then("no page, listing, feed or sitemap of the site mentions the draft or the link")
def not_listed(context):
    for key, content in context.site.tree.items():
        assert b"lower-fords" not in content, key


@given("the draft has an editorial note, a review request, a message and a star rating")
def private_working(context):
    row = context.site.client.tables["Item"][context.lineage]
    row["metadata"] = json.dumps({"stageMoves": [{"note": "PRIVATE-NOTE"}]})
    row["starRating"] = 5
    context.site.client.tables.setdefault("Message", {})["m"] = {"id": "m", "content": "PRIVATE-MESSAGE"}
    context.site.client.tables.setdefault("ReviewRequest", {})["r"] = {"id": "r", "ask": "PRIVATE-REVIEW"}


@then("none of those appear in the page and none were read to make it")
def private_absent(context):
    page = context.answer["html"]
    assert not any(secret in page for secret in ("PRIVATE-NOTE", "PRIVATE-MESSAGE", "PRIVATE-REVIEW", "starRating"))
    assert not [call for call in context.site.client.calls if call[1] in ("Message", "ReviewRequest", "MessageThread")]


class Recorder:
    endpoint = "https://appsync.example/graphql"

    def __init__(self):
        self.calls = []

    def graphql(self, document, variables):
        self.calls.append(json.loads(variables["input"]))
        return {"createStoryShare": json.dumps({"ok": True, "path": "/api/share/" + "T" * 43, "share": {"shareId": "a", "version": 2, "expiresAt": "x"}})}


def run_command(context, flags, signed_in=True):
    context.recorder, context.output, context.error = Recorder(), [], None
    with mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=signed_in), \
         mock.patch.object(story_share_commands, "create_authoring_client", return_value=(context.recorder, {})), \
         mock.patch.object(story_share_commands, "_origin", return_value="https://console.example.org"), \
         mock.patch("builtins.print", side_effect=lambda *args, **_: context.output.append(" ".join(str(arg) for arg in args))):
        try:
            story_share_commands.stories_share(flags)
        except (ValueError, OperatorError) as error:
            context.error = error


@when('an editor runs "stories share --story <lineage> --signed-in --expires 7 --version 2" while signed in')
def cli_share(context):
    run_command(context, ["--story", "lineage-1", "--signed-in", "--expires", "7", "--version", "2"])


@then("the newsroom is asked for a signed-in link on version 2 lasting 7 days and the URL is printed once")
def cli_asked(context):
    assert context.recorder.calls == [{"lineageId": "lineage-1", "viewers": "signed-in", "expiresInDays": 7, "version": 2}]
    assert sum("https://console.example.org/api/share/" in line for line in context.output) == 1


@when('an editor runs "stories share --story <lineage> --expires 365"')
def cli_never(context):
    run_command(context, ["--story", "lineage-1", "--expires", "365"])


@then("the command is refused before the newsroom is asked")
def cli_refused(context):
    assert isinstance(context.error, ValueError) and context.recorder.calls == []


@when('an editor runs "stories share --story <lineage> --dry-run"')
def cli_dry(context):
    run_command(context, ["--story", "lineage-1", "--dry-run"])


@then("the newsroom is not asked")
def cli_not_asked(context):
    assert context.recorder.calls == [] and context.error is None
