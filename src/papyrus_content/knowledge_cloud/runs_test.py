import json

import pytest
from moto import mock_aws

from .config import STAGES
from .cost_test import aws, run_all  # noqa: F401 - the fixture sets the AWS environment and the mock
from .fakes import make_run
from .runs import clock, group_runs, knowledge_runs


def test_the_runs_command_lists_each_run_with_its_stages_cost_and_duration(tmp_path):
    run, _shell = make_run(tmp_path)
    run_all(run)
    lines: list[str] = []
    knowledge_runs(["--site", "shipped"], table=run.ledger.table, out=lines.append)
    text = "\n".join(lines)
    assert "2026-W44  manual-1  succeeded" in text and "total $" in text
    for stage in STAGES:
        assert stage in text
    assert "projection" in text.splitlines()[-1]


def test_last_limits_the_runs_newest_first_and_json_is_machine_readable(tmp_path):
    first, _ = make_run(tmp_path / "a", execution="manual-1")
    run_all(first)
    second, _ = make_run(tmp_path / "b", execution="manual-2")
    run_all(second)
    out: list[str] = []
    knowledge_runs(["--site", "shipped", "--last", "1", "--json"], table=first.ledger.table, out=out.append)
    runs = json.loads(out[0])
    assert len(runs) == 1 and runs[0]["totalUsd"] > 0 and runs[0]["status"] == "succeeded" and set(runs[0]["stages"]) == set(STAGES)
    assert len(group_runs(__import__("papyrus_content.knowledge_cloud.ledger", fromlist=["query_rows"]).query_rows(first.ledger.table, "shipped"))) == 2


def test_arguments_are_checked():
    with pytest.raises(ValueError, match="--site"):
        knowledge_runs([], table=object())
    with pytest.raises(ValueError, match="--last"):
        knowledge_runs(["--site", "x", "--last", "0"], table=object())


def test_an_empty_ledger_says_so(tmp_path):
    run, _ = make_run(tmp_path)
    out: list[str] = []
    knowledge_runs(["--site", "another"], table=run.ledger.table, out=out.append)
    assert out == ["No runs in the ledger."]


def test_durations_read_as_minutes():
    assert (clock(None), clock(42), clock(754)) == ("-", "42s", "12m34s")
