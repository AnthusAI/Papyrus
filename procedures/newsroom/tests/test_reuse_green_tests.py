"""Reusing a green tests run on an identical tree: the decision, the trust filter and the workflow wiring.

Nothing here calls GitHub. features/ci-reuse-green-tests.feature tells the same story in prose.
"""
from __future__ import annotations

import importlib.util
import threading
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("reuse", ROOT / "infra" / "pipeline" / "reuse_green_tests.py")
reuse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reuse)

TREE = "a" * 40
OTHER = "b" * 40


def run(id, tree, conclusion="success"):
    return {"id": id, "tree": tree, "conclusion": conclusion, "url": f"https://x/{id}"}


def test_match_found_reuses_newest_green_run_on_the_same_tree():
    match, _ = reuse.decide(TREE, [run(3, OTHER), run(2, TREE), run(1, TREE)], current_run_id=9)
    assert match["id"] == 2


def test_no_match_runs_everything():
    match, why = reuse.decide(TREE, [run(1, OTHER)], current_run_id=9)
    assert match is None and "no earlier run" in why


def test_failed_run_on_the_same_tree_is_never_reused():
    match, why = reuse.decide(TREE, [run(1, TREE, "failure"), run(2, TREE, "cancelled")], current_run_id=9)
    assert match is None and "did not succeed" in why


def test_a_green_run_after_a_failed_one_on_the_same_tree_is_reused():
    match, _ = reuse.decide(TREE, [run(2, TREE, "failure"), run(1, TREE)], current_run_id=9)
    assert match["id"] == 1


def test_the_current_run_is_never_its_own_match():
    assert reuse.decide(TREE, [run(9, TREE)], current_run_id="9")[0] is None


def test_no_candidates_and_bad_tree_run_everything():
    assert reuse.decide(TREE, [])[0] is None
    assert reuse.decide("", [run(1, TREE)])[0] is None
    assert reuse.decide("not-a-hash", [run(1, "not-a-hash")])[0] is None


def test_lookup_error_runs_everything(monkeypatch, tmp_path):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_RUN_ID", "9")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    def boom(*args):
        raise RuntimeError("api down")

    monkeypatch.setattr(reuse, "gh_json", boom)
    monkeypatch.chdir(ROOT)
    assert reuse.main() == 0
    assert "reused=false" in out.read_text()


def test_every_earlier_run_is_looked_up_side_by_side_and_the_newest_match_wins(monkeypatch, tmp_path):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_RUN_ID", "9")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(ROOT)
    tree_under_test = reuse.subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"], check=True, capture_output=True, text=True
    ).stdout.strip()
    tree_each_run_vouched_for = {9: tree_under_test, 5: OTHER, 4: tree_under_test, 3: tree_under_test, 2: tree_under_test}
    job_lookups_in_flight, most_job_lookups_at_once = 0, 0
    lookup_count_lock = threading.Lock()
    every_lookup_has_started = threading.Barrier(3, timeout=10)

    def github(path):
        nonlocal job_lookups_in_flight, most_job_lookups_at_once
        if "/workflows/" in path:
            return {
                "workflow_runs": [
                    {"id": run_id, "conclusion": "success", "event": "push", "head_branch": "develop", "html_url": f"https://x/{run_id}"}
                    for run_id in (9, 5, 4, 3)
                ]
                + [{"id": 2, "conclusion": "success", "event": "push", "head_branch": "feature", "html_url": "https://x/2"}]
            }
        run_id = int(path.split("/runs/")[1].split("/")[0])
        with lookup_count_lock:
            job_lookups_in_flight += 1
            most_job_lookups_at_once = max(most_job_lookups_at_once, job_lookups_in_flight)
        every_lookup_has_started.wait()
        with lookup_count_lock:
            job_lookups_in_flight -= 1
        return {"jobs": [{"name": f"tested-tree {tree_each_run_vouched_for[run_id]}", "conclusion": "success"}]}

    monkeypatch.setattr(reuse, "gh_json", github)
    assert reuse.main() == 0
    assert "reused=true" in out.read_text()
    assert most_job_lookups_at_once == 3


def test_tree_comes_only_from_a_successful_tested_tree_job():
    ok = {"name": f"tested-tree {TREE}", "conclusion": "success"}
    assert reuse.tree_from_jobs([{"name": "ts", "conclusion": "success"}, ok]) == TREE
    assert reuse.tree_from_jobs([{"name": f"tested-tree {TREE}", "conclusion": "skipped"}]) is None
    assert reuse.tree_from_jobs([{"name": f"tested-tree {TREE}", "conclusion": "failure"}]) is None
    assert reuse.tree_from_jobs([{"name": "tested-tree zzz", "conclusion": "success"}]) is None


def test_fork_pull_requests_and_other_branches_are_not_trusted():
    repo = "o/r"
    assert reuse.is_trusted({"event": "push", "head_branch": "develop"}, repo)
    assert reuse.is_trusted({"event": "push", "head_branch": "main"}, repo)
    assert not reuse.is_trusted({"event": "push", "head_branch": "feature"}, repo)
    assert reuse.is_trusted({"event": "pull_request", "head_repository": {"full_name": repo}}, repo)
    assert not reuse.is_trusted({"event": "pull_request", "head_repository": {"full_name": "fork/r"}}, repo)
    assert not reuse.is_trusted({"event": "workflow_dispatch"}, repo)


def test_workflow_wiring():
    tests = yaml.safe_load((ROOT / ".github/workflows/tests.yml").read_text())
    jobs = tests["jobs"]
    shards = ("ts-check", "ts-build", "ts-misc", "ts-test", "python-checks", "python-unit", "python-behave")
    for name in shards:
        assert jobs[name]["needs"] == "reuse"
        assert jobs[name]["if"] == "needs.reuse.outputs.reused != 'true'"
    # `ts` and `python` stay as aggregates: they wait for every shard, so each keeps its name and fails if any shard fails.
    assert set(jobs["ts"]["needs"]) == {"reuse", "ts-check", "ts-build", "ts-misc", "ts-test"}
    assert set(jobs["python"]["needs"]) == {"reuse", "python-checks", "python-unit", "python-behave"}
    for name in ("ts", "python"):
        assert "needs.reuse.outputs.reused != 'true'" in jobs[name]["if"] and "!cancelled()" in jobs[name]["if"]
    assert set(jobs["record"]["needs"]) == {"reuse", "ts", "python"}
    assert jobs["record"]["name"].startswith("tested-tree ")
    assert jobs["reuse"]["permissions"] == {"contents": "read", "actions": "read"}
    assert tests["concurrency"]["group"] == "tests-${{ github.workflow }}-${{ github.ref }}"
    deploy = yaml.safe_load((ROOT / ".github/workflows/stack-deploy.yml").read_text())["jobs"]
    assert deploy["tests"]["permissions"]["actions"] == "read"
    assert "tests" in deploy["deploy"]["needs"]
