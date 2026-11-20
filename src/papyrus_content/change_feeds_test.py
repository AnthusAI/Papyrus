"""The other tables' change feeds: normalization, who is woken and the relay (the behaviour is in features_backend/agents/change-feeds.feature)."""
import json
from types import SimpleNamespace

import pytest

from papyrus_content import agent_listeners, change_feed_relay, change_feeds as feeds
from papyrus_content.change_vocabulary import CHANGES, FEED_TABLES, known

SITE = feeds.Site(publication_id="sample", appsync_endpoint="https://example123456789012345678.appsync-api.us-east-1.amazonaws.com/graphql", tenant_id="alpha", site_bucket="bucket")


def reference(version=1, **fields):
    return {"id": f"r-v{version}", "lineageId": "r", "versionNumber": version, "versionCreatedBy": "ada", "versionCreatedAt": "2026-11-18T09:00:00Z", "corpusId": "c",
            "curationStatus": "pending", **fields}


def names(changes):
    return [(change.change, change.what) for change in changes]


def test_the_vocabulary_has_a_normalizer_for_every_feed_table():
    for table in FEED_TABLES:
        assert known(table, CHANGES[table][0])
    assert not known("Reference", "ready") and not known("Story", "created")


def test_a_new_reference_is_created_and_a_reference_arriving_accepted_is_also_accepted():
    assert names(feeds.changes_of("Reference", None, reference(), "INSERT")) == [("created", "created")]
    assert names(feeds.changes_of("Reference", None, reference(curationStatus="accepted"), "INSERT")) == [("created", "created"), ("accepted", "accepted")]
    assert feeds.changes_of("Reference", None, reference(2), "INSERT") == []   # a later version is not a creation


def test_accepting_a_reference_names_who_did_it():
    new = reference(curationStatus="accepted", curationStatusUpdatedBy="ada", curationActorKind="human", curationStatusUpdatedAt="2026-11-18T10:00:00Z")
    [change] = feeds.changes_of("Reference", reference(), new, "MODIFY")
    assert (change.change, change.actor_kind, change.actor_label, change.at, change.lineage, change.version) == ("accepted", "person", "ada", "2026-11-18T10:00:00Z", "r", "r-v1")
    assert change.as_dict()["table"] == "Reference" and change.as_dict()["kind"] == "Reference"
    assert feeds.changes_of("Reference", new, {**new, "title": "x"}, "MODIFY") == []   # already accepted: nothing changed


def test_a_machine_that_accepts_is_an_agent_whichever_prefix_it_wrote():
    for label in ("automation:rate", "agent:rate"):
        [change] = feeds.changes_of("Reference", reference(), reference(curationStatus="accepted", curationStatusUpdatedBy=label), "MODIFY")
        assert (change.actor_kind, change.actor_label) == ("agent", "automation:rate")
    [change] = feeds.changes_of("Reference", reference(), reference(curationStatus="accepted", curationStatusUpdatedBy="cyclotron", curationActorKind="cyclotron"), "MODIFY")
    assert change.actor_kind == "agent"


def test_a_star_rating_is_a_change_with_its_value_in_the_key_and_the_same_rating_is_not():
    [change] = feeds.changes_of("Reference", reference(), reference(starRating=4, starRatedBy="ada"), "MODIFY")
    assert (change.change, change.what, change.attributes["stars"]) == ("rated", "rated.4", 4)
    assert feeds.changes_of("Reference", reference(starRating=4), reference(starRating=4, title="t"), "MODIFY") == []
    [again] = feeds.changes_of("Reference", reference(starRating=4), reference(starRating=2), "MODIFY")
    assert again.what == "rated.2" and again.attributes["previousStars"] == 4


def test_recapturing_needs_an_earlier_capture():
    assert feeds.changes_of("Reference", reference(), reference(retrievedAt="2026-11-18T08:00:00Z"), "MODIFY") == []   # the first capture is not a re-capture
    [change] = feeds.changes_of("Reference", reference(retrievedAt="2026-11-17T08:00:00Z"), reference(retrievedAt="2026-11-18T08:00:00Z"), "MODIFY")
    assert change.what == "recaptured.2026-11-18T08:00:00Z"
    [by_hash] = feeds.changes_of("Reference", reference(contentHash="aaa"), reference(contentHash="bbb"), "MODIFY")
    assert by_hash.what == "recaptured.bbb"


def review(state="answered", **fields):
    return {"id": "rr-1", "subject": json.dumps({"type": "story", "id": "s"}), "mode": "soft_review", "reason": "why", "raisedBy": "agent:copy-edit", "state": state,
            "answer": json.dumps({"decision": "approve", "by": "ada", "at": "2026-11-18T10:00:00Z"}), **fields}


def test_an_answer_is_addressed_to_the_agent_that_asked_and_only_when_it_is_new():
    [change] = feeds.changes_of("ReviewRequest", review("open"), review(), "MODIFY")
    assert (change.change, change.only_for, change.lineage, change.version, change.actor_kind, change.actor_label) == ("answered", "copy-edit", "s", "rr-1", "person", "ada")
    assert change.attributes["decision"] == "approve"
    assert feeds.changes_of("ReviewRequest", review(), review(updatedAt="later"), "MODIFY") == []
    assert feeds.changes_of("ReviewRequest", review("open"), review("open"), "MODIFY") == []
    assert feeds.changes_of("ReviewRequest", None, review("timed_out"), "INSERT") == []


def test_a_request_raised_by_nobody_has_nobody_waiting():
    assert feeds.changes_of("ReviewRequest", review("open"), review(raisedBy=None), "MODIFY") == []


def thread(**fields):
    return {"id": "t-1", "primaryAnchorKind": "item", "primaryAnchorId": "s-v3", "primaryAnchorLineageId": "s", "threadKind": "story", **fields}


def message(**fields):
    return {"id": "m-1", "threadId": "t-1", "messageKind": "comment", "status": "active", "authorLabel": "ada", "role": "human", "createdAt": "2026-11-18T11:00:00Z", **fields}


def test_a_comment_is_a_posted_message_and_nothing_else_is():
    [change] = feeds.changes_of("Message", None, message(), "INSERT")
    assert (change.change, change.id, change.version, change.actor_kind, change.at) == ("posted", "m-1", "m-1", "person", "2026-11-18T11:00:00Z")
    assert feeds.changes_of("Message", None, message(messageKind="console_chat_turn"), "INSERT") == []
    assert feeds.changes_of("Message", message(), message(content="edited"), "MODIFY") == []   # an edit is not a post
    assert feeds.changes_of("Message", None, message(threadId=None), "INSERT") == []
    [machine] = feeds.changes_of("Message", None, message(role="assistant", authorLabel="automation:copy-edit"), "INSERT")
    assert (machine.actor_kind, machine.actor_label) == ("agent", "automation:copy-edit")


def agents(*rows):
    listeners = {}
    for agent, kind, change, flt in rows:
        listeners.setdefault(f"{kind}/{change}", []).append({"agent": agent, "procedure": f"p.{agent}", "paid": False, "serialBy": "subject", "filter": flt})
    return {"schemaVersion": 1, "changes": listeners}


def wakes(change, index, thread_of=lambda _id: None):
    return feeds.wakes_for(change, index, SITE, thread_of=thread_of)


def test_a_posted_message_is_placed_on_its_subject_and_wakes_that_subjects_listeners():
    index = agents(("story-agent", "Message", "posted", {"subjectKind": "Story"}), ("reference-agent", "Message", "posted", {"subjectKind": "Reference"}))
    [change] = feeds.changes_of("Message", None, message(), "INSERT")
    [wake] = wakes(change, index, lambda thread_id: thread())
    assert wake["wakeKey"] == "story-agent|s|m-1|posted"
    assert wake["input"]["subject"] == {"kind": "Story", "id": "s"} and "story" not in wake["input"]
    assert wake["trigger"]["actorKind"] == "person" and wake["trigger"]["event"] == "message.posted"


def test_the_thread_is_read_only_when_someone_listens():
    asked = []
    [change] = feeds.changes_of("Message", None, message(), "INSERT")
    assert wakes(change, agents(("a", "Reference", "accepted", {})), lambda thread_id: asked.append(thread_id)) == []
    assert asked == []
    wakes(change, agents(("a", "Message", "posted", {})), lambda thread_id: asked.append(thread_id) or thread())
    assert asked == ["t-1"]


def test_a_thread_without_an_anchor_is_its_own_subject():
    [change] = feeds.changes_of("Message", None, message(), "INSERT")
    [wake] = wakes(change, agents(("a", "Message", "posted", {})), lambda thread_id: None)
    assert wake["wakeKey"] == "a|t-1|m-1|posted" and wake["input"]["subject"] == {"kind": "thread", "id": "t-1"}


def test_an_answer_wakes_only_the_agent_that_asked_and_only_if_it_listens():
    [change] = feeds.changes_of("ReviewRequest", review("open"), review(), "MODIFY")
    index = agents(("copy-edit", "ReviewRequest", "answered", {}), ("other", "ReviewRequest", "answered", {}))
    assert [wake["actorLabel"] for wake in wakes(change, index)] == ["automation:copy-edit"]
    assert wakes(change, agents(("other", "ReviewRequest", "answered", {}))) == []


def test_an_agents_own_write_does_not_wake_it():
    own = review(answer=json.dumps({"decision": "approve", "by": "automation:copy-edit", "at": "t"}))
    [change] = feeds.changes_of("ReviewRequest", review("open"), own, "MODIFY")
    assert wakes(change, agents(("copy-edit", "ReviewRequest", "answered", {}))) == []
    [accepted] = feeds.changes_of("Reference", reference(), reference(curationStatus="accepted", curationStatusUpdatedBy="automation:rate"), "MODIFY")
    index = agents(("rate", "Reference", "accepted", {}), ("announce", "Reference", "accepted", {}))
    assert [wake["actorLabel"] for wake in wakes(accepted, index)] == ["automation:announce"]


def localization(state="wanted", **fields):
    return {"id": "g#zh", "languageGroupId": "g", "language": "zh", "sourceVersionId": "g-v4", "sourceVersionNumber": 4, "state": state, "requestedBy": "ada",
            "requestedAt": "2026-11-18T09:00:00Z", **fields}


def test_a_translation_is_wanted_each_time_it_is_asked_for():
    [change] = feeds.changes_of("LocalizationRequest", None, localization(), "INSERT")
    assert (change.what, change.lineage, change.version) == ("wanted.zh.2026-11-18T09:00:00Z", "g", "g-v4")
    assert feeds.changes_of("LocalizationRequest", localization(), localization(), "MODIFY") == []
    assert feeds.changes_of("LocalizationRequest", localization(), localization("started"), "MODIFY") == []
    [again] = feeds.changes_of("LocalizationRequest", localization("failed"), localization(requestedAt="2026-11-18T12:00:00Z"), "MODIFY")
    assert again.what.endswith("2026-11-18T12:00:00Z")


def delivery(state="drafted", revision=1, **fields):
    return {"id": "a#email#x#g1", "announcementId": "a", "channel": "email", "accountId": "x", "state": state, "revision": revision, "mode": "automatic", "approval": "soft",
            "history": json.dumps([{"at": "2026-11-18T09:00:00Z", "by": "automation:announce", "state": state, "note": "drafted"}]), **fields}


def test_a_delivery_changing_state_is_a_change_and_one_that_does_not_is_not():
    [created] = feeds.changes_of("Delivery", None, delivery(), "INSERT")
    assert (created.what, created.version, created.actor_kind, created.actor_label, created.attributes["from"]) == ("state_changed.drafted", "1", "agent", "automation:announce", None)
    [sent] = feeds.changes_of("Delivery", delivery(), delivery("sent", 2), "MODIFY")
    assert (sent.what, sent.attributes["from"], sent.attributes["state"]) == ("state_changed.sent", "drafted", "sent")
    assert feeds.changes_of("Delivery", delivery(), delivery(revision=2, counts="{}"), "MODIFY") == []


def test_a_removed_row_is_no_change_for_any_table():
    for table in FEED_TABLES:
        assert feeds.changes_of(table, {"id": "x"}, None, "REMOVE") == []


def test_streams_name_their_table_and_nothing_else_is_guessed():
    streams = feeds.Streams.from_environment({feeds.STREAMS_ENVIRONMENT: json.dumps([{"stream": "arn:one", "table": "Reference"}])})
    assert streams.table_of({"eventSourceARN": "arn:one"}) == "Reference"
    with pytest.raises(feeds.UnknownStream):
        streams.table_of({"eventSourceARN": "arn:other"})
    with pytest.raises(ValueError):
        feeds.Streams.from_environment({})
    with pytest.raises(ValueError):
        feeds.Streams.from_environment({feeds.STREAMS_ENVIRONMENT: json.dumps([{"stream": "arn:x", "table": "Item"}])})


def test_the_relay_hands_over_the_batch_and_returns_the_feeds_failures():
    seen = []
    environment = {change_feed_relay.FUNCTION_ENVIRONMENT: "feed", change_feed_relay.STREAMS_ENVIRONMENT: json.dumps(["arn:message"])}
    batch = {"Records": [{"eventName": "INSERT", "eventSourceARN": "arn:message"}, {"eventName": "INSERT", "eventSourceARN": "arn:reference"}]}
    failures = change_feed_relay.relay(batch, environment=environment, invoke=lambda name, payload: seen.append((name, json.loads(payload))) or {"batchItemFailures": [{"itemIdentifier": "7"}]})
    assert failures == [{"itemIdentifier": "7"}]
    assert seen == [("feed", {"Records": [{"eventName": "INSERT", "eventSourceARN": "arn:message"}]})], "only the streams the reader hands over"


def test_the_relay_has_nobody_to_tell_before_the_agents_stack_exists_and_nothing_to_tell_about_an_empty_batch():
    def never(*_):
        raise AssertionError("invoked")
    assert change_feed_relay.relay({"Records": [{"eventSourceARN": "arn:a"}]}, environment={}, invoke=never) == []
    environment = {change_feed_relay.FUNCTION_ENVIRONMENT: "feed", change_feed_relay.STREAMS_ENVIRONMENT: json.dumps(["arn:a"])}
    assert change_feed_relay.relay({"Records": []}, environment=environment, invoke=never) == []
    assert change_feed_relay.relay({"Records": [{"eventSourceARN": "arn:b"}]}, environment=environment, invoke=never) == []
