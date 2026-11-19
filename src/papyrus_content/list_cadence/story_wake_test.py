"""The announce agent's worker, the parts that need no site (the behaviour is features_backend/announce-durable-triggers.feature)."""
import json

import pytest

from papyrus_content.agent_gate import run_context
from papyrus_content.agent_policy.resolve import PolicyState
from papyrus_content.announcements.link_reads import StoryRef
from papyrus_content.list_cadence import story_wake as worker
from papyrus_content.list_cadence.announce import Candidate
from papyrus_content.list_cadence.store import ListState


def request(change="stage_entered", stage="published", story="s", version="s-v3", what="stage_entered.published"):
    return {"input": {"story": story, "version": version, "change": change, "what": what, **({"stage": stage} if stage else {})}}


@pytest.mark.parametrize("given, trigger", [(request(), worker.PAGE_LIVE), (request("rated", None, what="rated.4.t"), worker.RATING_CHANGED)])
def test_a_wake_is_the_page_going_live_or_a_rating_change(given, trigger):
    assert worker.story_wake(given) == worker.StoryWake("s", "s-v3", given["input"]["change"], trigger)


@pytest.mark.parametrize("given", [request(stage="draft"), request("version_created", None), request("step_changed", None), request(story=""), request(version="")])
def test_any_other_wake_is_refused_and_nothing_is_made(given):
    with pytest.raises(worker.StoryWakeError):
        worker.story_wake(given)


def test_a_story_that_is_not_live_makes_nothing_and_says_so_with_a_reason_code():
    result = worker.not_live("s")
    assert result.outcome is None and result.declaration() == {"run_outcome": "nothing", "run_outcome_reason": worker.NOT_LIVE_CODE}


def environment(rung="observe", responsibility="announce"):
    return run_context.to_environment("run-1", responsibility, PolicyState(1, {"agents": {"announce": {"rung": rung}}}), None)


class Records:
    """What the tool writes through: the Announcements it would make are recorded, not written."""

    def __init__(self):
        self.made = []

    def announce(self, **arguments):
        self.made.append(arguments)


LISTS = {"everything": {"name": "All", "cadence": "each", "rule": {"sections": [], "types": [], "tags": [], "minStars": 3}, "requireReviewedSource": False,
                        "workingDocument": "delivery", "template": "roundup", "agent": "announce"}}
STORY = Candidate(StoryRef("s", "s-v3", 3), "science", "article", [], 4, True)


def services(candidate=STORY):
    return worker.Services(state=lambda: ListState(1, {"schemaVersion": 1, "lists": LISTS}), announcements=Records(), read_story=lambda lineage: candidate,
                           draft=lambda *_: pytest.fail("a run below prepare writes no words"), account_id="acct")


def test_at_observe_the_tool_makes_nothing_and_says_which_rung_held_it_back():
    given = services()
    output = worker.announce_story("s", "s-v3", "rated", "rated.4.t", environ=environment("observe"), services=given)
    assert (output["run_outcome"], output["run_outcome_reason"], output["created"]) == ("nothing", "no_list_carries_story", False)
    assert given.announcements.made == []


def test_a_story_that_is_not_live_ends_the_run_as_nothing_with_its_reason():
    output = worker.announce_story("s", "s-v3", "stage_entered", "stage_entered.published", "published", environ=environment("prepare"), services=services(None))
    assert (output["run_outcome"], output["run_outcome_reason"]) == ("nothing", worker.NOT_LIVE_CODE)


def test_a_run_that_is_not_an_announce_wake_is_refused_because_the_tool_needs_the_policy_the_runner_read():
    with pytest.raises(worker.StoryWakeError):
        worker.announce_story("s", "s-v3", "rated", environ={}, services=services())
    with pytest.raises(worker.StoryWakeError):
        worker.announce_story("s", "s-v3", "rated", environ=environment(responsibility="rate"), services=services())


def test_real_services_need_the_sites_tenant_and_bucket_from_the_runner_and_never_guess():
    with pytest.raises(worker.StoryWakeError, match="PAPYRUS_TENANT_ID"):
        worker.default_services({})


def test_the_runner_names_the_site_store_in_the_childs_environment_only_when_the_request_does():
    from papyrus_content.procedure_runner import child_environment

    named = child_environment({"appsyncEndpoint": "https://x", "tenantId": "alpha", "siteBucket": "bucket"}, None)
    assert (named["PAPYRUS_TENANT_ID"], named["PAPYRUS_SITE_BUCKET"]) == ("alpha", "bucket")
    bare = child_environment({"appsyncEndpoint": "https://x"}, None)
    assert "PAPYRUS_TENANT_ID" not in bare and "PAPYRUS_SITE_BUCKET" not in bare


def test_a_story_with_no_published_copy_is_not_live():
    from procedures.newsroom.tests.fake_client import FakeAuthoringClient

    assert worker.read_candidate(FakeAuthoringClient(), "s") is None
    client = FakeAuthoringClient()
    client.upsert("PublishedItem", {"id": "published-s", "status": "unpublished", "versionNumber": 2, "metadata": json.dumps({})})
    assert worker.read_candidate(client, "s") is None
