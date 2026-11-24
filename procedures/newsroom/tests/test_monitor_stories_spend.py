"""Monitor stories under the spend ledger (src/papyrus_content/monitor_stories_spend.py, features_backend/monitoring/monitor-stories-spend.feature, PPY-45c2ef):
the site's policy is read as the procedure runner reads it, and the router's and the story worker's roles hold exactly what that and the ledger need."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_monitoring_router as tr  # noqa: E402
from monitor_stories_spend_fixture import SiteOfRecord, monitor_stories_spend  # noqa: E402
from test_monitor_stories_queue import FakeSqs, plan, work  # noqa: E402
from test_monitoring_packs import PACKS_ON, RouterModel, pack_world, FilingRecorder  # noqa: E402
from test_monitoring_stories import PUBLICATION, fake_idea_sink, iam_auth, quiet_gate, router  # noqa: E402,F401  (the autouse fixtures of the daily task's tests)

from papyrus_content import spend_ledger  # noqa: E402
from papyrus_content.agent_policy import PolicyNotLocated  # noqa: E402
from papyrus_content.ideas import story_plan  # noqa: E402
from papyrus_content.monitor_stories_spend import DRAFTING_RESPONSIBILITY, drafting_spend, site_policy_from_bucket  # noqa: E402
from papyrus_content.spend_brake_test import HaltableTable, UnreadableTable  # noqa: E402

GRAPHQL_ROOT = re.compile(r"^\s*(?:query|mutation)\b[^{]*\{\s*(\w+)", re.S)


class RecordingSiteApi:
    """A site's API that has never saved an agent policy, recording the root field of every request."""

    def __init__(self):
        self.fields = set()

    def graphql(self, query, variables=None):
        kind, field = ("Mutation" if query.lstrip().startswith("mutation") else "Query"), GRAPHQL_ROOT.match(query).group(1)
        self.fields.add((kind, field))
        return {field: None}


def statements_of_role(role):
    return tr._template()["Resources"][role]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]


def appsync_fields(statements):
    resources = [resource[1] if isinstance(resource, tuple) else resource for statement in statements if statement["Action"] == "appsync:GraphQL"
                 for resource in (statement["Resource"] if isinstance(statement["Resource"], list) else [statement["Resource"]])]
    return {tuple(match) for resource in resources for match in re.findall(r"apis/\*/types/(Query|Mutation)/fields/(\w+)$", resource)}


def test_the_policy_is_read_from_the_publications_site_bucket_and_a_site_with_none_saved_has_every_agent_off():
    api = RecordingSiteApi()
    site = site_policy_from_bucket(s3=object())({"publicationId": PUBLICATION, "tenantId": "alpha", "siteBucket": "site-bucket"}, api)
    assert site.tenant_id == "alpha" and site.state.version == 0 and site.state.document["agents"] == {}
    assert api.fields == {("Query", "getSiteDocument")}


def test_a_publication_on_a_site_with_no_tenant_is_counted_as_its_own_site_with_the_default_budget():
    api = RecordingSiteApi()
    site = site_policy_from_bucket(s3=object())({"publicationId": PUBLICATION}, api)
    assert site.tenant_id == f"publication:{PUBLICATION}" and site.state.version == 0 and site.state.document["agents"] == {}
    assert api.fields == set()   # no policy to read: nothing is asked of the site


@pytest.mark.parametrize("entry, missing", [({"tenantId": "alpha"}, "siteBucket"), ({"siteBucket": "site-bucket"}, "tenantId")])
def test_a_publication_that_does_not_say_where_its_site_is_cannot_be_counted(entry, missing):
    with pytest.raises(PolicyNotLocated, match=missing):
        site_policy_from_bucket(s3=object())({"publicationId": PUBLICATION, **entry}, RecordingSiteApi())


def test_both_roles_may_read_the_site_policy_and_the_story_worker_may_write_only_the_ledgers_rows():
    asked = {("Query", "getSiteDocument"), ("Query", "getSiteDocumentVersion")}   # SiteCatalogue's two reads (a saved policy reads its version row too)
    worker, router_statements = statements_of_role("StoryWorkerRole"), statements_of_role("RouterRole")
    assert asked <= appsync_fields(worker) and asked <= appsync_fields(router_statements)
    for statements in (worker, router_statements):
        [body] = [statement for statement in statements if statement["Sid"] == "SiteAgentPolicyBody"]
        assert body["Action"] == "s3:GetObject" and body["Resource"][1] == "arn:${AWS::Partition}:s3:::*/tenants/*/site/agents/*"
    [ledger] = [statement for statement in worker if statement["Sid"] == "SpendLedger"]
    assert set(ledger["Action"]) == {"dynamodb:UpdateItem", "dynamodb:PutItem", "dynamodb:GetItem"}
    assert ledger["Condition"] == {"ForAllValues:StringLike": {"dynamodb:LeadingKeys": ["SPEND#*"]}}


def test_a_model_without_a_price_makes_every_call_unpriced_never_free():
    run = {"model": "a-model-with-no-price", "usage": {"calls": 3, "costUsd": 0.0}}
    spend = drafting_spend("run-1", run)
    assert (spend.cost_usd, spend.calls, spend.unpriced_calls) == (None, 3, 3)


@pytest.fixture
def world_of_two(monkeypatch):
    FilingRecorder(monkeypatch)
    return pack_world(2, lively=(1,))


def test_a_step_whose_spend_could_not_be_counted_is_counted_when_its_message_comes_again(world_of_two, monkeypatch):
    client = world_of_two
    table, store = router(settings={PUBLICATION: PACKS_ON})
    sqs, ledger = FakeSqs(), HaltableTable()
    spend = monitor_stories_spend(ledger=ledger)
    plan(store, client, sqs, spend=spend)
    real_count = type(spend).count

    def failing_count(self, *args, **kwargs):
        raise spend_ledger.SpendError("the ledger is throttled")

    monkeypatch.setattr(type(spend), "count", failing_count)
    _, failures = work(store, client, RouterModel(), sqs.sent[:1], spend=spend)
    assert len(failures) == 1   # the step's work is done and kept; the message comes again for the count
    monkeypatch.setattr(type(spend), "count", real_count)
    lines, failures = work(store, client, RouterModel(), sqs.sent[:1], receives=2, spend=spend)
    assert not failures and [line["storyStep"] for line in lines if "storyStep" in line] == ["already"]
    held = spend_ledger.spent(ledger, tenant_id="example-tenant", scope=f"ai:{DRAFTING_RESPONSIBILITY}", period="month", moment=spend.clock())
    assert held.calls > 0
    work(store, client, RouterModel(), sqs.sent[:1], receives=3, spend=spend)   # once more: the marker keeps it counted once
    assert spend_ledger.spent(ledger, tenant_id="example-tenant", scope=f"ai:{DRAFTING_RESPONSIBILITY}", period="month", moment=spend.clock()) == held


def test_a_step_that_cannot_read_the_ledger_drafts_nothing_and_is_tried_again(world_of_two):
    client = world_of_two
    table, store = router(settings={PUBLICATION: PACKS_ON})
    sqs = FakeSqs()
    plan(store, client, sqs)
    model = RouterModel()
    _, failures = work(store, client, model, sqs.sent[:1], spend=monitor_stories_spend(ledger=UnreadableTable()))
    assert len(failures) == 1 and model.order == []
    plan_id = sqs.sent[0]["body"]["planId"]
    assert store.get_any("hn", story_plan.done_key(PUBLICATION, plan_id, 1)) is None   # not done: the queue delivers it again


def test_the_site_policy_is_read_once_for_each_brake_check():
    site = SiteOfRecord()
    spend = monitor_stories_spend(site=site)
    stop, located = spend.stop_before_paid_work({"publicationId": PUBLICATION}, object(), DRAFTING_RESPONSIBILITY)
    assert stop is None and located.tenant_id == "example-tenant" and site.reads == 1
