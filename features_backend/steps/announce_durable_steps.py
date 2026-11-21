"""The announce agent's durable triggers (features_backend/announcements/announce-durable-triggers.feature, announce-agent-definition.feature).

The pieces are the real ones: the shipped core definition, the listener index written from it, the Item change feed, the wake message and the runner's reading of it, and
the worker (``list_cadence.story_wake``) over the real Announcement and Delivery records on their in-memory backend and the real list settings store. What is stood in
for is the world: the Item table's stream (a batch the scenario writes), the FIFO queue (``change_feed_fakes.FakeQueue``), the run record that claims a wake key, and the
published copy of a Story, which the scenario says is live or not. Nothing is sent, nothing touches AWS."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests", Path(__file__).resolve().parent):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import agent_wakes, item_change_feed  # noqa: E402
from papyrus_content.agent_definitions import definition as agent_definition  # noqa: E402
from papyrus_content.announcements.link_reads import StoryRef  # noqa: E402
from papyrus_content.change_feed_fakes import BUCKET, ENDPOINT, TENANT, FakeQueue, FakeSqs, deploy as deploy_index, open_index  # noqa: E402
from papyrus_content.list_cadence import story_wake  # noqa: E402
from papyrus_content.list_cadence.announce import Candidate  # noqa: E402
from papyrus_content.localize.dispatch import decode_image  # noqa: E402

ACCOUNT, BY = "mom-sending", "announce"


def draft(lists, candidates, notes=()):
    return f"For {', '.join(list_id for list_id, _ in lists)}: " + ", ".join(candidate.story.lineage_id for candidate in candidates)

SHIPPED = agent_definition.load_sets(agent_definition.CORE_DIRECTORY)


def _row(lineage, stage, stars=None, at=None, by="ada", version=3):
    row = {"id": f"{lineage}-v{version}", "lineageId": lineage, "versionNumber": version, "versionState": "current", "versionCreatedAt": "2026-11-16T09:00:00Z",
           "versionCreatedBy": "ada", "type": "article", "stage": stage, "section": "science", "language": "en", "updatedAt": "2026-11-18T09:00:00Z", "metadata": json.dumps({})}
    if stars:
        row.update(starRating=stars, starRatedAt=at, starRatedBy=by)
    return row


def _deliver(context, *records):
    """One stream batch through the Item change feed into the site's wake queue, as the feed's handler builds it."""
    context.sequence = getattr(context, "sequence", 0)
    batch = []
    for name, old, new in records:
        context.sequence += 1
        batch.append(_record(name, old, new, context.sequence))
    context.last_batch = batch
    sqs = FakeSqs({agent_wakes.queue_name(context.site_id): context.feed_queue})
    site = item_change_feed.Site(publication_id=context.site_id, appsync_endpoint=ENDPOINT, tenant_id=TENANT, site_bucket=BUCKET)
    context.answer = item_change_feed.handle(batch, decode=decode_image, listeners=context.index.document, send=agent_wakes.wake_sender(sqs), site=site)
    return context.answer


def _record(name, old, new, sequence):
    from papyrus_content.change_feed_fakes import stream_record

    return stream_record(name, old, new, sequence)


def _redeliver(context):
    context.sequence -= len(context.last_batch)
    return _deliver(context, *[(record["eventName"], decode_image(record["dynamodb"].get("OldImage")), decode_image(record["dynamodb"].get("NewImage"))) for record in context.last_batch])


@given("the shipped announce agent is deployed with its wake queue and its listener index")
def deployed(context):
    context.feed_queue, context.world, context.claims, context.taken, context.runs = FakeQueue(), {}, set(), 0, []
    context.site_id = "sample"
    open_index(context)
    deploy_index(context, [SHIPPED.get("announce")])


def _world(context, lineage, **fields):
    context.world[lineage] = {**context.world.get(lineage, {"live": False, "stars": 0}), **fields}


@given('the Story "{lineage}" is a draft that nobody has rated')
def draft_story(context, lineage):
    _world(context, lineage, live=False, stars=0)


@given('the Story "{lineage}" is live and rated {stars:d} stars')
def live_rated(context, lineage, stars):
    _world(context, lineage, live=True, stars=stars)


@when('a person publishes the Story "{lineage}"')
def publish(context, lineage):
    """The publish writes the Story's own record: its stage becomes published. That is the whole of what it does for the announcement."""
    _world(context, lineage, live=True)
    stars = context.world[lineage]["stars"]
    _deliver(context, ("MODIFY", _row(lineage, "copywriting", stars or None), _row(lineage, "published", stars or None)))


@when('a person rates the live Story "{lineage}" {stars:d} stars')
def rate(context, lineage, stars):
    context.minutes = getattr(context, "minutes", 0) + 1
    before = context.world[lineage]["stars"]
    _world(context, lineage, stars=stars)
    _deliver(context, ("MODIFY", _row(lineage, "published", before or None), _row(lineage, "published", stars, f"2026-11-18T12:{context.minutes:02d}:00Z")))


@when('a person rates the draft Story "{lineage}" {stars:d} stars')
def rate_draft(context, lineage, stars):
    _deliver(context, ("MODIFY", _row(lineage, "copywriting"), _row(lineage, "copywriting", stars, "2026-11-18T12:00:00Z")))


@when('the Story "{lineage}" is unpublished before the agent wakes')
def unpublished(context, lineage):
    _world(context, lineage, live=False)


@given("the announcement settings give the email channel a window of {window:d} minutes with a lock lead of {lead:d} minutes for a Story that went live")
def email_window(context, window, lead):
    context.edit_settings = {"editWindows": [{"kind": "story_published", "channel": "email", "windowMinutes": window, "lockLeadMinutes": lead}]}


@then('the email Delivery is released at "{release}" and locks at "{lock}", and so is the Announcement')
def email_released(context, release, lock):
    (row,) = [delivery for delivery in context.backend.rows("Delivery") if delivery["channel"] == "email"]
    (announcement,) = context.backend.rows("AnnouncementDecision")
    assert (row["releaseAt"], row["lockAt"], announcement["releaseAt"]) == (release, lock, release), (row["releaseAt"], row["lockAt"], announcement["releaseAt"])


@given("the queue refuses the first wake it is given")
def refuses(context):
    context.feed_queue.refuse_from = 1


@when("the queue accepts wakes again and the stream record is delivered again")
def accepts_again(context):
    context.feed_queue.refuse_from = None
    _redeliver(context)


@when("the stream record is delivered a second time after the queue's window")
def again_after_window(context):
    context.feed_queue.window.clear()
    _redeliver(context)


def _read_story(context):
    def read(lineage):
        state = context.world.get(lineage)
        if not state or not state["live"]:
            return None
        return Candidate(StoryRef(lineage, f"{lineage}-v3", 3), "science", "article", [], state["stars"], True)

    return read


@when("the runner takes every wake on the queue and the announce agent runs each one")
def runner(context):
    for message in context.feed_queue.messages[context.taken:]:
        request = agent_wakes.request_from_event({"Records": [{"eventSource": "aws:sqs", "body": message.body}]})
        if request["wakeKey"] in context.claims:
            context.runs.append(("duplicate", None))   # the run record's own condition: a wake key that has its run starts no second one
            continue
        context.claims.add(request["wakeKey"])
        state = context.lists.read(context.site_id)
        result = story_wake.run_story_wake(request, state, context.announcements, read_story=_read_story(context), draft=draft, policy_rung=lambda _: context.policy_rung,
                                           account_id=ACCOUNT, by=BY, now=context.now, edit_settings=getattr(context, "edit_settings", None))
        context.runs.append((request["wakeKey"], result))
    context.taken = len(context.feed_queue.messages)


@then("the announce agent is listed under {names}")
def listed_under(context, names):
    wanted = [name.strip().strip('"') for name in names.replace(" and ", ",").split(",") if name.strip()]
    document = context.index.document()
    for name in wanted:
        assert any(entry["agent"] == "announce" for entry in document["changes"].get(name, [])), (name, document)


@then('the feed queue holds {count:d} wake for the agent "{agent}"')
@then('the feed queue holds {count:d} wakes for the agent "{agent}"')
def holds(context, count, agent):
    keys = [json.loads(message.body)["wake"] for message in context.feed_queue.messages]
    assert len(keys) == count and all(wake["agent"] == agent for wake in keys), [wake["key"] for wake in keys]


@then('the feed queue holds no wake')
def holds_none(context):
    assert context.feed_queue.messages == [], [json.loads(message.body)["wake"]["key"] for message in context.feed_queue.messages]


@then('the feed queue\'s wake key is "{key}"')
def key_is(context, key):
    assert json.loads(context.feed_queue.messages[0].body)["wake"]["key"] == key, json.loads(context.feed_queue.messages[0].body)["wake"]["key"]


@then("the batch reports nothing failed")
def batch_ok(context):
    assert context.answer["batchItemFailures"] == [], context.answer


@then("the announce agent ran {count:d} time")
@then("the announce agent ran {count:d} times")
def ran(context, count):
    assert len([run for run in context.runs if run[0] != "duplicate"]) == count, context.runs


@then("the other wakes were duplicates and started nothing")
def duplicates(context):
    assert any(run[0] == "duplicate" for run in context.runs) or len(context.runs) == 1, context.runs


@then('the announce agent\'s last run made nothing and gave the reason code "{code}"')
def made_nothing_code(context, code):
    result = context.runs[-1][1]
    assert result.outcome is None and result.code == code, (result.reason, result.code)


@then('the announce agent\'s last run made the Announcement "{key}" because the page went live')
def made_live(context, key):
    result = context.runs[-1][1]
    assert result.outcome and result.outcome.created and result.outcome.announcement["dedupeKey"] == key, result
    assert result.outcome.announcement["trigger"] == story_wake.PAGE_LIVE, result.outcome.announcement


@then('the announce agent\'s last run made the Announcement "{key}" because the rating changed')
def made_rated(context, key):
    result = context.runs[-1][1]
    assert result.outcome and result.outcome.created and result.outcome.announcement["dedupeKey"] == key, result
    assert result.outcome.announcement["trigger"] == story_wake.RATING_CHANGED, result.outcome.announcement


@then('the announce agent\'s last run found the Announcement "{key}" already decided and made no other')
def found_decided(context, key):
    result = context.runs[-1][1]
    assert result.outcome and not result.outcome.created and result.outcome.announcement["dedupeKey"] == key, result
    assert result.reason == "already decided for this Story", result.reason


# --- the shipped definition -------------------------------------------------------------------------------------------------------------------------


def _listens(context, kind, change, field, value):
    entries = [entry for entry in SHIPPED.get("announce").data["wakes"]["changes"] if (entry["kind"], entry["change"]) == (kind, change)]
    assert entries and entries[0].get("filter", {}).get(field) == value, entries


@then('the definition "{name}" listens for the Item change "{change}" with the filter "{field}" "{value}"')
def listens(context, name, change, field, value):
    assert name == "announce"
    _listens(context, "Item", change, field, value)


@then('the definition "{name}" listens for the Delivery change "{change}"')
def listens_for_delivery(context, name, change):
    assert any(entry["kind"] == "Delivery" and entry["change"] == change for entry in context.loaded.get(name).data["wakes"]["changes"])


@then('the definition "{name}" listens for no other change')
def listens_for_no_other(context, name):
    assert {(entry["kind"], entry["change"]) for entry in context.loaded.get(name).data["wakes"]["changes"]} == {("Item", "stage_entered"), ("Item", "rated"), ("Delivery", "approved")}
    assert "schedule" not in context.loaded.get(name).data["wakes"]


@then('the procedure "{kind}" is registered with its file')
def procedure_registered(context, kind):
    from papyrus_content.procedure_registry import discover_procedure_files, load_registry_config

    config = load_registry_config()
    assert config["procedures"][kind] in discover_procedure_files(), config["procedures"].get(kind)
    assert config["procedureMetadata"][kind]["title"]


@then('the definition "{name}" names the procedure "{kind}"')
def names_procedure(context, name, kind):
    assert context.loaded.get(name).data["procedure"] == kind


# --- a publish writes only its own record ---------------------------------------------------------------------------------------------------------


@given("a site whose content-actions function publishes pages, with the old call's environment still set")
def publishing_site(context):
    from papyrus_content.publish_trigger_test import ITEM, OLD_ENVIRONMENT, Backend

    context.publisher = Backend(projection=True)
    context.publisher.environment.update(OLD_ENVIRONMENT)
    context.publisher.save()
    context.publisher.client.calls.clear()
    context.item_id = ITEM


@when("the editor publishes an article")
def editor_publishes(context):
    context.publication = context.publisher.action("publishItem", {"id": context.item_id})


@then("the publish succeeded and the page is live")
def publish_live(context):
    assert context.publication["ok"] is True and context.publication["live"] is True, context.publication


@then("the publish invoked neither the newsletter function nor the notifications function")
def invoked_nothing(context):
    from papyrus_content.publish_trigger_test import OLD_ENVIRONMENT

    assert not set(context.publisher.invoked_functions()) & set(OLD_ENVIRONMENT.values()), context.publisher.invoked_functions()


@then("the publish wrote only the Story's own records and its published copy")
def wrote_own(context):
    from papyrus_content.publish_trigger_test import PUBLISH_MODELS

    written = {model for _, model, _ in context.publisher.client.write_calls()}
    assert written and written <= PUBLISH_MODELS, written
    assert not any(model in ("AnnouncementDecision", "Delivery") for _, model, _ in context.publisher.client.calls)


@then("the content-actions function has no call to the newsletter or the notifications function and no swallowed error for one")
def no_call(context):
    import importlib.util

    assert importlib.util.find_spec("papyrus_content.publish_alerts") is None
    source = (REPO_ROOT / "amplify" / "functions" / "content-actions" / "handler.py").read_text()
    for name in ("announce_published", "publish_alerts", "PAPYRUS_NEWSLETTER_FUNCTION", "PAPYRUS_NOTIFICATIONS_FUNCTION", "item_published_announce_failed"):
        assert name not in source, name


@then("the newsletter and notifications plugins give the content-actions function no name and no grant to invoke them")
def no_grant(context):
    for plugin in ("newsletter", "notifications"):
        source = (REPO_ROOT / "amplify" / "plugins" / plugin / "papyrus.plugin.ts").read_text()
        assert "contentActions" not in source and "NEWSLETTER_FUNCTION_ENV" not in source and "NOTIFICATIONS_FUNCTION_ENV" not in source, plugin
