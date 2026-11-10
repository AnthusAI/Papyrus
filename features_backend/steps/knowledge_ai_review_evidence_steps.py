from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.knowledge_cloud import ai_review as review  # noqa: E402
from papyrus_content.knowledge_cloud.ai_review_test import ACTOR, NOW, Model, node, typed_of  # noqa: E402
from papyrus_content.knowledge_cloud.stages_test import review_with_many_entities  # noqa: E402


@given('the source says "{text}"')
def step_source(context, text):
    context.source = text


@given('the extractor proposed the entity "{name}"')
def step_entity(context, name):
    context.nodes, context.answers = [node(name)], {}
    context.typed = typed_of(context.source, name)


@given('the AI reviewer accepts "{name}" quoting "{quote}" and says it is about it')
def step_accepts_about(context, name, quote):
    context.answers[name] = {"verdict": "accept", "evidence": [quote], "about": True}


@given('the AI reviewer accepts "{name}" quoting "{quote}" and says it is not about it')
def step_accepts_not_about(context, name, quote):
    context.answers[name] = {"verdict": "accept", "evidence": [quote], "about": False}


@when("the entities are reviewed")
def step_review(context):
    context.patches, context.decisions = review.review_entities(context.nodes, context.typed, lambda n: [], Model(context.answers), ACTOR, now=NOW, vocabulary={})


@then("nothing was accepted")
def step_nothing(context):
    assert context.patches == []


@then('"{name}" was accepted')
def step_accepted(context, name):
    assert [(p["expected"]["id"], p["expected"]["status"]) for p in context.patches] == [(f"n-{name}", "accepted")]


def decision_of(context, name):
    return next(d for d in context.decisions if d.subject.endswith(f": {name}"))


@then('the decision for "{name}" was refused because the thing is named in passing')
def step_refused(context, name):
    decision = decision_of(context, name)
    assert (decision.verdict, decision.applied, decision.gate) == ("unsure", False, review.GATE_PASSING_MENTION)


@then('the decision for "{name}" records that the quote names the thing and is about it')
def step_recorded(context, name):
    decision = decision_of(context, name)
    assert decision.applied and decision.to_dict()["gate"] == review.GATE_ABOUT_THE_THING


@given("the review needs {entities:d} calls for entities, {clusters:d} for clusters and {relations:d} for relations")
def step_needs(context, entities, clusters, relations):
    context.needs = {"entities": entities, "clusters": clusters, "relations": relations}


@when("the ceiling is {budget:d} calls")
def step_ceiling(context, budget):
    context.shares = review.fair_shares(context.needs, budget)


@then("entities are owed {entities:d} calls, clusters {clusters:d} calls and relations {relations:d} calls")
def step_owed(context, entities, clusters, relations):
    assert context.shares == {"entities": entities, "clusters": clusters, "relations": relations}, context.shares


@given("the extractor proposed forty-five concepts, one new cluster and one proposed relation are waiting, and the ceiling is {calls:d} calls")
def step_stage(context, calls):
    context.ceiling = calls


@when("the review runs over those candidates")
def step_stage_runs(context):
    import pytest
    from moto import mock_aws

    work = Path(tempfile.mkdtemp())
    context.tmp_dirs.append(work)
    monkeypatch = pytest.MonkeyPatch()
    for name, value in {"AWS_ACCESS_KEY_ID": "t", "AWS_SECRET_ACCESS_KEY": "t", "AWS_DEFAULT_REGION": "us-east-1"}.items():
        monkeypatch.setenv(name, value)
    try:
        with mock_aws():
            context.budget = review_with_many_entities(work, monkeypatch, context.ceiling)
    finally:
        monkeypatch.undo()


@then("the review log says it needed {entities:d} calls for entities, {clusters:d} for clusters and {relations:d} for relations")
def step_log_needed(context, entities, clusters, relations):
    assert context.budget["needed"] == {"entities": entities, "clusters": clusters, "relations": relations}, context.budget


@then("the review log says it used 1 call for each of entities, clusters and relations")
def step_log_used(context):
    assert context.budget["used"] == {"entities": 1, "clusters": 1, "relations": 1}, context.budget


@given("the topic model proposed clusters in two runs, an earlier one and the latest")
def step_two_runs(context):
    from papyrus_content.knowledge_cloud.ai_review_test import cluster

    context.cluster_proposals = [cluster("earlier", run="aaa", as_of="2026-11-09"), cluster("latest", run="bbb", as_of="2026-11-10")]


@given("the earlier run's clusters are still waiting as proposed")
def step_earlier_waiting(context):
    assert all(row["status"] == "proposed" for row in context.cluster_proposals)


@when("the clusters are reviewed")
def step_clusters_reviewed(context):
    context.offered = review.cluster_candidates(context.cluster_proposals, lambda ids: ["x"] * 4)


@then("only the latest run's clusters are sent to the reviewer, and the earlier run's are not")
def step_only_latest(context):
    assert [entry["proposal"]["graphEntityId"] for entry in context.offered.values()] == ["latest"]


@then("the call budget for clusters counts only the latest run's clusters")
def step_budget_latest(context):
    assert review.calls_needed(len(context.offered), review.CLUSTER_BATCH_SIZE) == 1
