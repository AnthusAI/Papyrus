"""The wiki-sync stage holds a first run, or one unlike the site's history, for a person (preview_gate.py, PPY-84b0dd). Synthetic data only."""

from __future__ import annotations

import json

import pytest
from moto import mock_aws

from .. import review_requests
from .fakes import make_run
from .ledger import FAILED
from .preview_gate import HELD, load_history
from .stages import run_stage


@pytest.fixture(autouse=True)
def aws(monkeypatch):
    for name, value in {"AWS_ACCESS_KEY_ID": "t", "AWS_SECRET_ACCESS_KEY": "t", "AWS_DEFAULT_REGION": "us-east-1"}.items():
        monkeypatch.setenv(name, value)
    with mock_aws():
        yield


def plan(**kinds):
    pages = [
        {"action": "create", "section": "wiki", "slug": f"{kind}-{n}", "kind": "entity", "entityKind": kind, "title": f"Title {kind} {n}", "note": ""}
        for kind, count in kinds.items()
        for n in range(count)
    ]
    return {"mode": "dry-run", "counts": {}, "pages": pages, "retired": [], "warnings": [], "written": {}}


def commands(shell, prefix):
    return [call for call in shell.calls if call[: len(prefix)] == prefix]


def wiki_stage(tmp_path, kinds, execution, shell_of=None):
    run, shell = make_run(tmp_path / execution, execution=execution)
    shell.wiki_plan = plan(**kinds)
    return run, shell


def applied(shell):
    return [call for call in commands(shell, ["papyrus", "knowledge", "wiki", "sync"]) if "--apply" in call]


def requests(run):
    return [review_requests.read_review(row) for row in run.services.record_client({}).list_records("ReviewRequest")]


def answer(run, request_id, decision, by="a-person"):
    review_requests.answer_review(run.services.record_client({}), request_id, decision=decision, by=by)


def test_a_first_run_that_would_write_pages_is_held_and_writes_nothing(tmp_path):
    run, shell = wiki_stage(tmp_path, {"personauthor": 40, "maker": 3}, "manual-1")
    assert run_stage("wiki-sync", run) == 0
    assert not applied(shell) and not commands(shell, ["papyrus", "knowledge", "wiki", "publish"])
    [request] = requests(run)
    assert request["mode"] == "hard_gate" and request["state"] == "open" and request["raisedBy"] == "knowledge-run"
    assert "First knowledge run for shipped" in request["reason"] and "entity/personauthor:create 40" in request["ask"]
    assert request["subject"]["type"] == "batch"
    details = run.ledger.table.get_item(Key={"publication": "shipped", "runKey": "2026-W44#manual-1#wiki-sync"})["Item"]["details"]
    assert details["status"] == "held" and details["reason"] == "first_run" and details["requestId"] == request["id"]
    assert [entry["outcome"] for entry in load_history(run.state)] == [HELD]
    assert json.loads(run.state.read_text("runs/2026-W44/wiki-sync-preview.json"))["plan"]["pages"]  # the plan is kept, so the hold is resumable


def test_a_held_execution_does_not_project(tmp_path):
    run, shell = wiki_stage(tmp_path, {"maker": 3}, "manual-1")
    assert run_stage("wiki-sync", run) == 0 and run_stage("projection", run) == 0
    assert not commands(shell, ["papyrus", "ops", "content", "project"])


def test_the_hold_applies_to_its_own_execution_only(tmp_path):
    held, _ = wiki_stage(tmp_path, {"maker": 3}, "manual-1")
    assert run_stage("wiki-sync", held) == 0
    later, shell = wiki_stage(tmp_path, {}, "manual-2")
    later.state, later.services = held.state, held.services  # the same publication's state and data API
    assert run_stage("wiki-sync", later) == 0 and run_stage("projection", later) == 0
    assert commands(shell, ["papyrus", "ops", "content", "project"])


def test_a_run_that_would_write_nothing_is_never_held_and_joins_the_history(tmp_path):
    run, shell = wiki_stage(tmp_path, {}, "manual-1")
    assert run_stage("wiki-sync", run) == 0
    assert applied(shell) and not requests(run)
    assert [entry["outcome"] for entry in load_history(run.state)] == ["written"]


def test_the_same_plan_waits_on_one_request_until_a_person_accepts_it_and_then_goes_through(tmp_path):
    first, _ = wiki_stage(tmp_path, {"maker": 12}, "manual-1")
    assert run_stage("wiki-sync", first) == 0
    second, shell = wiki_stage(tmp_path, {"maker": 12}, "manual-2")
    second.state, second.services = first.state, first.services
    assert run_stage("wiki-sync", second) == 0 and not applied(shell)
    [request] = requests(first)  # raised once, however many runs found the plan waiting
    answer(first, request["id"], "approve")
    third, shell = wiki_stage(tmp_path, {"maker": 12}, "manual-3")
    third.state, third.services = first.state, first.services
    assert run_stage("wiki-sync", third) == 0
    assert applied(shell) and commands(shell, ["papyrus", "knowledge", "wiki", "publish"])
    assert {entry["outcome"] for entry in load_history(third.state)} == {"approved", "written"}


def test_an_accepted_first_run_teaches_the_comparison_so_a_similar_next_run_goes_through_and_a_surge_is_held(tmp_path):
    first, _ = wiki_stage(tmp_path, {"maker": 20}, "manual-1")
    assert run_stage("wiki-sync", first) == 0
    answer(first, requests(first)[0]["id"], "approve")
    similar, shell = wiki_stage(tmp_path, {"maker": 22}, "manual-2")
    similar.state, similar.services = first.state, first.services
    assert run_stage("wiki-sync", similar) == 0 and applied(shell)
    surge, shell = wiki_stage(tmp_path, {"maker": 22, "personauthor": 900}, "manual-3")
    surge.state, surge.services = first.state, first.services
    assert run_stage("wiki-sync", surge) == 0 and not applied(shell)
    held = [request for request in requests(first) if request["state"] == "open"]
    assert len(held) == 1 and "unlike this site's earlier runs" in held[0]["reason"] and "entity/personauthor:create would write 900" in held[0]["ask"]


def test_a_rejected_plan_stays_held_and_asks_nobody_again(tmp_path):
    first, _ = wiki_stage(tmp_path, {"maker": 12}, "manual-1")
    assert run_stage("wiki-sync", first) == 0
    answer(first, requests(first)[0]["id"], "reject")
    again, shell = wiki_stage(tmp_path, {"maker": 12}, "manual-2")
    again.state, again.services = first.state, first.services
    assert run_stage("wiki-sync", again) == 0 and not applied(shell)
    assert len(requests(first)) == 1
    details = again.ledger.table.get_item(Key={"publication": "shipped", "runKey": "2026-W44#manual-2#wiki-sync"})["Item"]["details"]
    assert details["reason"] == "rejected_plan"


def test_an_agents_answer_does_not_open_the_gate(tmp_path):
    first, _ = wiki_stage(tmp_path, {"maker": 12}, "manual-1")
    assert run_stage("wiki-sync", first) == 0
    answer(first, requests(first)[0]["id"], "approve", by="agent:editor")
    again, shell = wiki_stage(tmp_path, {"maker": 12}, "manual-2")
    again.state, again.services = first.state, first.services
    assert run_stage("wiki-sync", again) == 0 and not applied(shell)


def test_a_different_plan_replaces_the_open_request_of_an_older_one(tmp_path):
    first, _ = wiki_stage(tmp_path, {"maker": 12}, "manual-1")
    assert run_stage("wiki-sync", first) == 0
    newer, _ = wiki_stage(tmp_path, {"maker": 15}, "manual-2")
    newer.state, newer.services = first.state, first.services
    assert run_stage("wiki-sync", newer) == 0
    states = sorted(request["state"] for request in requests(first))
    assert states == ["open", "withdrawn"]


def test_a_hold_that_cannot_be_shown_to_anyone_fails_the_stage_so_the_alarm_reaches_a_person(tmp_path):
    run, shell = wiki_stage(tmp_path, {"maker": 12}, "manual-1")

    class Broken:
        def get_record(self, *args):
            return None

        def list_records(self, *args):
            return []

        def create_record(self, *args):
            raise RuntimeError("the data API is not reachable")

    run.services.client = Broken()
    assert run_stage("wiki-sync", run) == 1
    assert run.ledger.status("wiki-sync") == FAILED and not applied(shell)
