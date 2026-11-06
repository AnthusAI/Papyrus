"""Steps for features_backend/reference-page-titles.feature. In memory: no site, no AWS, no network, no model."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "procedures" / "newsroom" / "tests", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from test_reference_titles import ADDRESS, CORPUS, SETTINGS, Site, explored, preview_row, reference  # noqa: E402
from papyrus_content import reference_titles as titles  # noqa: E402
from papyrus_content import references_titles as repair  # noqa: E402
from papyrus_content.home_page.export import public_reference  # noqa: E402
from papyrus_content.link_exploration import Exploration  # noqa: E402
from papyrus_content.reference_curation_store import card_id  # noqa: E402
from papyrus_content.reference_images import attach_preview, preview_attachment_id  # noqa: E402

NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)
HANDLER = importlib.util.spec_from_file_location("home_page_trigger_handler", REPO_ROOT / "amplify" / "plugins" / "home-page" / "function" / "handler.py")
TRIGGER = importlib.util.module_from_spec(HANDLER)
HANDLER.loader.exec_module(TRIGGER)


@given("a site with References titled with their own address, one with a stored page title, one with only a capture card, one with nothing stored, and one titled by an editor")
def _(context):
    context.stored, context.card, context.bare = reference("a"), reference("b", status="accepted"), reference("c")
    context.editor = reference("d", title="Already titled")
    card = {"id": card_id(context.card), "metadata": json.dumps({"kind": "reference-curation", "page": {"title": "From the capture card"}})}
    context.site = Site([context.stored, context.card, context.bare, context.editor], {
        preview_attachment_id(context.stored): preview_row(context.stored, title="From the preview"),
        card_id(context.card): card,
        preview_attachment_id(context.bare): preview_row(context.bare, description="no title here")})
    context.pages_read, context.output, context.errors, context.new = [], "", "", None
    environment = mock.patch.dict("os.environ", {}, clear=False)   # the command selects the signed-in lane in the environment; undo that after the scenario
    environment.start()
    context.add_cleanup(environment.stop)


def preview_a_new_reference(context, title, page_title):
    context.new = reference("n", title=title)
    context.new_site = Site([context.new])
    attach_preview(context.new_site, context.new, exploration=explored(title=page_title), now=lambda: NOW, log=lambda line: None)


@when('a new Reference titled with its address gets its link preview from a page titled "{page_title}"')
def _(context, page_title):
    preview_a_new_reference(context, ADDRESS, page_title)


@when('a new Reference titled "{title}" gets its link preview from a page titled "{page_title}"')
def _(context, title, page_title):
    preview_a_new_reference(context, title, page_title)


@then('the new Reference is titled "{title}"')
def _(context, title):
    assert context.new_site.rows[context.new["id"]]["title"] == title


@then("the new Reference is titled with its address")
def _(context):
    assert titles.is_address(context.new_site.rows[context.new["id"]]["title"])


def run(context, *flags, explorer=None):
    out, errors, real = io.StringIO(), io.StringIO(), sys.stderr
    sys.stderr = errors
    context.pages_read = []

    def reading(address, **options):
        context.pages_read.append(address)
        return explorer(address, **options)
    try:
        context.code = repair.command(["--corpus-key", "demo", *flags], client=context.site, out=out, explorer=reading if explorer else None, sleep=lambda seconds: None)
    finally:
        sys.stderr = real
    context.output, context.errors = out.getvalue(), errors.getvalue()


@when("the title repair runs")
def _(context):
    run(context)


@when("the title repair runs with write")
def _(context):
    run(context, "--write")


@when('the title repair runs with write and fetch and the page is titled "{title}"')
def _(context, title):
    run(context, "--write", "--fetch", explorer=lambda address, **options: explored(title=title))


@when("the title repair runs with write and fetch and the page is blocked")
def _(context):
    run(context, "--write", "--fetch", explorer=lambda address, **options: Exploration(False, address, failure="blocked"))


@then("no title was written and no page was read")
def _(context):
    assert context.site.updates == [] and context.site.actions == [] and context.pages_read == [], (context.site.updates, context.pages_read)


@then("the repair counted {fixable:d} fixable from stored titles and {fetch:d} that would need a fetch")
def _(context, fixable, fetch):
    assert f"would_set {fixable}" in context.output and f"would_fetch {fetch}" in context.output, context.output


def title_of(context, row):
    return context.site.rows[row["id"]]["title"]


@then('the Reference with a stored page title is titled "{title}"')
def _(context, title):
    assert title_of(context, context.stored) == title


@then('the Reference with a capture card is titled "{title}"')
def _(context, title):
    assert title_of(context, context.card) == title


@then('the Reference with nothing stored is titled "{title}"')
def _(context, title):
    assert title_of(context, context.bare) == title


@then("the Reference with nothing stored is still titled with its address")
def _(context):
    assert titles.is_address(title_of(context, context.bare))


@then("the Reference titled by an editor is untouched")
def _(context):
    assert title_of(context, context.editor) == "Already titled" and all(update["id"] != context.editor["id"] for update in context.site.updates)


@then("only the Reference with nothing stored had its page read")
def _(context):
    assert context.pages_read == [context.bare["sourceUri"]], context.pages_read


@then("the repair said the page was not readable and what the card shows instead")
def _(context):
    assert "page not readable: blocked" in context.output and "the card shows 'labs.example.org: c csa research note" in context.output, context.output


@given('the preview of the Reference with nothing stored names the site "{name}"')
def _(context, name):
    context.site.attachments[preview_attachment_id(context.bare)] = preview_row(context.bare, siteName=name)


@when("the public card of the Reference with nothing stored is built")
def _(context):
    row = {**context.bare, "lineageId": context.bare["lineageId"], "curationActorKind": "human"}
    context.card_title = public_reference(row, None, context.site.attachments[preview_attachment_id(context.bare)], {}, SETTINGS)["title"]


@then('the card title is a readable name starting with "{prefix}"')
def _(context, prefix):
    assert context.card_title.startswith(prefix), context.card_title


@then("the card title is not a web address")
def _(context):
    assert not titles.is_address(context.card_title)


def stream(old, new):
    return {"eventName": "MODIFY", "dynamodb": {"Keys": {"id": {"S": "reference-x-v1"}}, "OldImage": old, "NewImage": new}}


@then("a title change on an accepted Reference rebuilds the public page")
def _(context):
    accepted = {"curationStatus": {"S": "accepted"}}
    assert TRIGGER.record_changed(stream({**accepted, "title": {"S": ADDRESS}}, {**accepted, "title": {"S": "AI Coding Assistants as Attack Surface"}}))


@then("a title change on a pending Reference nobody has predicted rebuilds nothing, because the first prediction is the change that shows it")
def _(context):
    pending = {"curationStatus": {"S": "pending"}}
    assert not TRIGGER.record_changed(stream({**pending, "title": {"S": ADDRESS}}, {**pending, "title": {"S": "A page title"}}))
    predicted = {**pending, "predictedAcceptProbability": {"N": "0.9"}, "predictionDecidedAt": {"S": "2026-11-05T00:00:00Z"}}
    assert TRIGGER.record_changed(stream(pending, {**predicted, "title": {"S": "A page title"}})), "the first prediction makes the card appear, title included"
