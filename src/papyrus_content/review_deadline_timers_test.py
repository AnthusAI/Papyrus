import json

import pytest

from papyrus_content import follow_up_timers as fu
from papyrus_content.follow_up_timers_test import Api
from papyrus_content.review_deadline_timers import OWNER, PROCEDURE_KEY, ReviewDeadlineTimerError, ReviewDeadlineTimers

ENDPOINT = "https://abcdefghijklmnopqrstuvwxyz.appsync-api.us-east-1.amazonaws.com/graphql"
ENVIRONMENT = {"PAPYRUS_AGENT_PUBLICATION_ID": "Site", "PAPYRUS_AWS_ACCOUNT_ID": "123456789012", "AWS_REGION": "us-east-1",
               "PAPYRUS_TENANT_ID": "site", "PAPYRUS_SITE_BUCKET": "site-bucket"}


def timers(api):
    return ReviewDeadlineTimers.from_environment(ENVIRONMENT, appsync_endpoint=ENDPOINT, client=api)


def test_a_due_time_sets_one_entry_whose_wake_names_the_request_and_its_deadline():
    api = Api()
    key = timers(api).sync({"id": "rr-1", "dueAt": "2026-11-20T09:00:00Z"})
    assert key == fu.follow_up_key(OWNER, "rr-1", "2026-11-20T09:00:00Z")
    (entry,) = api.entries.values()
    assert entry["Name"] == fu.entry_name("ReviewRequest", "rr-1") and entry["ScheduleExpression"] == "at(2026-11-20T09:00:00)"
    request = json.loads(entry["Target"]["Input"])["request"]
    assert request["procedureKey"] == PROCEDURE_KEY and request["input"] == {"reviewRequestId": "rr-1", "dueAt": "2026-11-20T09:00:00Z"}
    assert (request["tenantId"], request["siteBucket"], request["appsyncEndpoint"]) == ("site", "site-bucket", ENDPOINT)
    assert request["trigger"]["waitingFor"] == "deadline"


def test_no_due_time_deletes_the_entry_and_the_overdue_request_carries_the_same_key():
    api = Api()
    deadline_timers = timers(api)
    row = {"id": "rr-1", "dueAt": "2026-11-20T09:00:00Z"}
    key = deadline_timers.sync(row)
    assert deadline_timers.wake_request(row)["wakeKey"] == key
    assert deadline_timers.sync({"id": "rr-1", "dueAt": None}) is None and api.entries == {}


def test_the_site_must_be_named_to_build_the_timers():
    with pytest.raises(ReviewDeadlineTimerError, match="PAPYRUS_AWS_ACCOUNT_ID"):
        ReviewDeadlineTimers.from_environment({**ENVIRONMENT, "PAPYRUS_AWS_ACCOUNT_ID": ""}, appsync_endpoint=ENDPOINT)
