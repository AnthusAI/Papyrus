"""The Item change feed's normalization and wake requests (the behaviour is in features_backend/agents/item-change-feed.feature)."""
import json

import pytest

from papyrus_content import agent_wakes, item_change_feed as feed

SITE = feed.Site(publication_id="sample", appsync_endpoint="https://example123456789012345678.appsync-api.us-east-1.amazonaws.com/graphql",
                 tenant_id="alpha", site_bucket="bucket", openai_key_parameter=None)


def story(version=3, stage="idea", **fields):
    return {"id": f"s-v{version}", "lineageId": "s", "versionNumber": version, "type": "story", "stage": stage, "versionCreatedAt": "2026-11-18T09:00:00Z",
            "versionCreatedBy": "ada", "metadata": "{}", **fields}


def step(state="open", *, at="2026-11-18T10:00:00Z", created=None, key="illustration"):
    entry = {"at": at, "state": state, "actorKind": "agent", "actorLabel": "automation:illustrate"}
    return {"id": f"step-s-{key}-v2", "type": "sub-task", "status": state, "parentLineageId": "s", "versionCreatedAt": created or at,
            "metadata": json.dumps({"checklist": {"stepKey": key, "entry": entry}})}


def names(changes):
    return [(change.change, change.what) for change in changes]


def test_first_version_is_created_and_enters_its_stage():
    assert names(feed.changes_of(None, story(1, "idea"), "INSERT")) == [("version_created", "version_created"), ("stage_entered", "stage_entered.idea")]


def test_a_later_version_is_only_created():
    assert names(feed.changes_of(None, story(4, "idea"), "INSERT")) == [("version_created", "version_created")]


def test_a_stage_field_change_in_place_is_a_stage_entry_by_a_person_unless_the_move_is_recorded():
    [change] = feed.changes_of(story(), story(stage="draft"), "MODIFY")
    assert (change.what, change.actor_kind, change.actor_label, change.attributes["from"]) == ("stage_entered.draft", "person", None, "idea")
    move = {"at": "t", "from": "idea", "to": "draft", "by": "automation:writer"}
    [change] = feed.changes_of(story(), story(stage="draft", metadata=json.dumps({"stageMoves": [move]})), "MODIFY")
    assert (change.actor_kind, change.actor_label) == ("agent", "automation:writer")


def test_a_stale_record_of_an_earlier_move_is_not_the_writer_of_this_one():
    move = {"at": "t", "from": "idea", "to": "draft", "by": "automation:writer"}
    old = story(stage="idea", metadata=json.dumps({"stageMoves": [move]}))
    new = story(stage="draft", metadata=json.dumps({"stageMoves": [move]}))   # the console changed the field and left the record alone
    [change] = feed.changes_of(old, new, "MODIFY")
    assert change.actor_kind == "person"


@pytest.mark.parametrize("old,new", [(story(), story(versionState="superseded")), (story(stage="idea"), story(stage="idea", metadata='{"a": 1}'))])
def test_other_updates_are_no_change(old, new):
    assert feed.changes_of(old, new, "MODIFY") == []


def test_a_removed_row_is_no_change():
    assert feed.changes_of(story(), None, "REMOVE") == []


def test_a_step_state_change_is_a_change_and_a_note_or_a_supersede_is_not():
    [change] = feed.changes_of(None, step("done"), "INSERT")
    assert (change.change, change.lineage, change.attributes["step"], change.attributes["state"], change.actor_kind) == ("step_changed", "s", "illustration", "done", "agent")
    assert feed.changes_of(None, step("done", at="2026-11-18T09:00:00Z", created="2026-11-18T10:00:00Z"), "INSERT") == []
    assert feed.changes_of(step("open"), step("done"), "MODIFY") == []


def test_an_agents_own_change_never_wakes_that_agent():
    [change] = feed.changes_of(None, step("done"), "INSERT")
    assert feed.is_own_change(change, "illustrate") and not feed.is_own_change(change, "other")


def listener(agent="fact-check", paid=True, **filter_):
    return {"agent": agent, "procedure": f"story.{agent.replace('-', '_')}", "paid": paid, "serialBy": "subject", "filter": filter_}


def test_a_wake_request_is_a_wake_the_queue_can_carry():
    [change] = feed.changes_of(story(), story(stage="draft"), "MODIFY")
    request = feed.wake_request(change, listener("fact-check"), SITE)
    wake = agent_wakes.wake_of(request)
    assert wake["key"] == "fact-check|s|s-v3|stage_entered.draft" and wake["agent"] == "fact-check" and wake["subject"] == "s"
    assert request["tenantId"] == "alpha" and request["siteBucket"] == "bucket" and "openaiKeyParameter" not in request
    assert request["trigger"]["paid"] is True and request["trigger"]["actorKind"] == "person" and request["trigger"]["automationId"] == "fact-check"
    assert json.loads(agent_wakes.message_body(request))["wake"] == wake


def test_wakes_follow_the_filter_and_leave_out_the_agent_that_wrote():
    index = {"changes": {"Item/stage_entered": [listener("a", stage="draft"), listener("b", stage="review"), listener("c")]}}
    [change] = feed.changes_of(story(), story(stage="draft"), "MODIFY")
    assert [agent_wakes.wake_of(request)["agent"] for request in feed.wakes_for(change, index, SITE)] == ["a", "c"]
    move = {"at": "t", "from": "idea", "to": "draft", "by": "automation:c"}
    [own] = feed.changes_of(story(), story(stage="draft", metadata=json.dumps({"stageMoves": [move]})), "MODIFY")
    assert [agent_wakes.wake_of(request)["agent"] for request in feed.wakes_for(own, index, SITE)] == ["a"]


def test_a_filter_on_a_field_the_change_lacks_does_not_match():
    index = {"changes": {"Item/version_created": [listener("a", step="illustration")]}}
    [change] = feed.changes_of(None, story(4), "INSERT")
    assert feed.wakes_for(change, index, SITE) == [] and feed.wakes_for(change, None, SITE) == []


def test_the_site_is_read_from_the_environment():
    site = feed.Site.from_environment({"PAPYRUS_AGENT_PUBLICATION_ID": " sample ", "PAPYRUS_GRAPHQL_ENDPOINT": "https://x", "PAPYRUS_TENANT_ID": "alpha", "PAPYRUS_SITE_BUCKET": "b"})
    assert (site.publication_id, site.tenant_id, site.site_bucket, site.openai_key_parameter) == ("sample", "alpha", "b", None)


NO_GATE = type("Open", (), {"person_acted": staticmethod(lambda **found: False), "release": staticmethod(lambda request, send: (send(request), {"status": "sent"})[1])})()


def test_the_handler_sends_through_the_wake_queue_and_reports_a_failed_record():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "amplify/functions/item-change-feed/handler.py"
    spec = importlib.util.spec_from_file_location("item_change_feed_handler", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from boto3.dynamodb.types import TypeSerializer

    serializer = TypeSerializer()
    image = {name: serializer.serialize(value) for name, value in story(4).items()}
    event = {"Records": [{"eventName": "INSERT", "dynamodb": {"SequenceNumber": "7", "NewImage": image}}]}
    environment = {"PAPYRUS_AGENT_PUBLICATION_ID": "sample", "PAPYRUS_GRAPHQL_ENDPOINT": SITE.appsync_endpoint, "PAPYRUS_TENANT_ID": "alpha", "PAPYRUS_SITE_BUCKET": "bucket"}
    index = type("Index", (), {"document": staticmethod(lambda: {"changes": {"Item/version_created": [listener("fact-check")]}})})()
    sent = []
    assert module.handler(event, index=index, send=sent.append, environment=environment, gate=NO_GATE) == {"batchItemFailures": []}
    assert [agent_wakes.wake_of(request)["key"] for request in sent] == ["fact-check|s|s-v4|version_created"]

    def refuse(request):
        raise OSError("queue unavailable")

    assert module.handler(event, index=index, send=refuse, environment=environment, gate=NO_GATE) == {"batchItemFailures": [{"itemIdentifier": "7"}]}
    assert module.handler({"Records": []}, index=index, send=refuse, environment=environment) == {"batchItemFailures": []}


# --- a rating changed in place (PPY-e3bb2b) --------------------------------------------------------------------------------------------------------


def rated(stars, at="2026-11-18T12:00:00Z", by="ada", **fields):
    return story(stage="published", **({"starRating": stars, "starRatedAt": at, "starRatedBy": by} if stars else {}), **fields)


def test_a_rating_set_in_place_is_a_change_named_by_its_stars_and_its_moment():
    [change] = feed.changes_of(rated(None), rated(4), "MODIFY")
    assert (change.change, change.what, change.actor_kind, change.at) == ("rated", "rated.4.2026-11-18T12:00:00Z", "person", "2026-11-18T12:00:00Z")
    assert (change.attributes["stars"], change.attributes["previousStars"], change.attributes["stage"]) == (4, None, "published")


def test_rating_again_is_a_new_key_and_the_same_record_twice_is_the_same_key():
    first = feed.changes_of(rated(3, at="2026-11-18T12:00:00Z"), rated(4, at="2026-11-18T12:01:00Z"), "MODIFY")[0]
    again = feed.changes_of(rated(3, at="2026-11-18T12:00:00Z"), rated(4, at="2026-11-18T12:01:00Z"), "MODIFY")[0]
    other = feed.changes_of(rated(4, at="2026-11-18T12:01:00Z"), rated(3, at="2026-11-18T12:02:00Z"), "MODIFY")[0]
    assert first.what == again.what and first.what != other.what


def test_clearing_a_rating_is_a_change_and_a_rating_by_an_agent_names_the_agent():
    [cleared] = feed.changes_of(rated(4), story(stage="published", updatedAt="2026-11-18T13:00:00Z"), "MODIFY")
    assert cleared.what == "rated.cleared.2026-11-18T13:00:00Z" and cleared.attributes["stars"] is None
    [by_agent] = feed.changes_of(rated(None), rated(3, by="automation:rate"), "MODIFY")
    assert (by_agent.actor_kind, by_agent.actor_label) == ("agent", "automation:rate")


def test_a_new_version_that_carries_the_rating_over_and_an_unchanged_rating_are_no_rating_change():
    assert [change.change for change in feed.changes_of(None, rated(4), "INSERT")] == ["version_created"]
    assert feed.changes_of(rated(4), rated(4, updatedAt="2026-11-18T14:00:00Z"), "MODIFY") == []


def test_the_wake_of_a_rating_says_why_in_words_and_never_wakes_the_agent_that_rated():
    index = {"changes": {"Item/rated": [{"agent": "announce", "procedure": "announce_story", "paid": False, "serialBy": "agent", "filter": {"stage": "published"}},
                                        {"agent": "rate", "procedure": "rate_items", "paid": True, "serialBy": "agent", "filter": {}}]}}
    [change] = feed.changes_of(rated(None), rated(3, by="automation:rate"), "MODIFY")
    [request] = feed.wakes_for(change, index, SITE)
    assert request["wakeKey"] == "announce|s|s-v3|rated.3.2026-11-18T12:00:00Z"
    assert "rated 3 stars" in request["trigger"]["summary"] and request["input"]["stars"] == 3
    [draft_rating] = feed.changes_of(story(stage="copywriting"), story(stage="copywriting", starRating=3, starRatedAt="t", starRatedBy="ada"), "MODIFY")
    assert [wake["wakeKey"].split("|")[0] for wake in feed.wakes_for(draft_rating, index, SITE)] == ["rate"]   # the announce agent listens for published Stories only
