#!/usr/bin/env python3
"""Reuse a green `tests` run when the code under test is byte-identical (same git tree).

The tests workflow runs on a pull request, on develop after the merge, on the release pull request and again on main inside
stack-deploy. When the tree being tested equals the tree of an earlier successful run, the heavy jobs are skipped and the run says which
earlier run it relied on. Any doubt (no match, a failed run, a lookup error) means the full suite runs.

Each tests run ends with a job named `tested-tree <sha>` that only succeeds when every test job passed or was itself justified by a reuse,
so the tree a run vouched for can be read back from the jobs API without artifacts.

Usage (from the checkout under test):  python3 infra/pipeline/reuse_green_tests.py
Environment: GH_TOKEN (actions: read), GITHUB_REPOSITORY, GITHUB_RUN_ID, GITHUB_OUTPUT, GITHUB_STEP_SUMMARY.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

WORKFLOW = "tests.yml"
JOB_PREFIX = "tested-tree "
TREE_JOB = re.compile(r"^" + re.escape(JOB_PREFIX) + r"([0-9a-f]{40})$")
TRUSTED_PUSH_BRANCHES = {"develop", "main"}


def is_trusted(run: dict, repo: str) -> bool:
    """Only runs whose workflow file came from this repository: pushes to develop/main, or pull requests from branches in the same repo.

    A fork's pull request runs the fork's copy of the workflow, which could claim any tree.
    """
    if run.get("event") == "push":
        return run.get("head_branch") in TRUSTED_PUSH_BRANCHES
    if run.get("event") == "pull_request":
        head = (run.get("head_repository") or {}).get("full_name")
        return head == repo
    return False


def tree_from_jobs(jobs: list[dict]) -> str | None:
    """The tree a run vouched for: the successful `tested-tree <sha>` job, else None."""
    for job in jobs:
        match = TREE_JOB.match(job.get("name") or "")
        if match and job.get("conclusion") == "success":
            return match.group(1)
    return None


def decide(tree: str, candidates: list[dict], current_run_id: str | int | None = None) -> tuple[dict | None, str]:
    """candidates: [{id, conclusion, tree, url?}], newest first. Returns (the run to reuse or None, why)."""
    if not re.fullmatch(r"[0-9a-f]{40}", tree or ""):
        return None, "no valid tree hash for the code under test"
    seen_failed = False
    for run in candidates:
        if str(run.get("id")) == str(current_run_id):
            continue
        if run.get("tree") != tree:
            continue
        if run.get("conclusion") != "success":
            seen_failed = True
            continue
        return run, f"run {run.get('id')} passed on the same tree"
    if seen_failed:
        return None, "the only runs on this tree did not succeed"
    return None, "no earlier run tested this tree"


def gh_json(*args: str):
    out = subprocess.run(["gh", "api", *args], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def write(path_var: str, text: str) -> None:
    path = os.environ.get(path_var)
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text)


def main() -> int:
    tree = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], check=True, capture_output=True, text=True).stdout.strip()
    reused, why, url = False, "", ""
    try:
        repo, run_id = os.environ["GITHUB_REPOSITORY"], os.environ.get("GITHUB_RUN_ID")
        # Cheap pre-filter: scanning the jobs of every recent run is wasteful, so look newest first and stop at the first match.
        runs = gh_json(f"repos/{repo}/actions/workflows/{WORKFLOW}/runs?status=success&per_page=100")["workflow_runs"]
        match = None
        for run in runs:
            if str(run["id"]) == str(run_id) or not is_trusted(run, repo):
                continue
            jobs = gh_json(f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100")["jobs"]
            candidate = {"id": run["id"], "conclusion": run["conclusion"], "tree": tree_from_jobs(jobs), "url": run["html_url"]}
            match, why = decide(tree, [candidate], run_id)
            if match:
                reused, url = True, match["url"]
                break
        if not reused:
            why = why or "no earlier run tested this tree"
    except Exception as error:  # any lookup problem means: run everything
        why = f"lookup failed, running the full suite ({type(error).__name__}: {error})"
    write("GITHUB_OUTPUT", f"tree={tree}\nreused={'true' if reused else 'false'}\n")
    if reused:
        write("GITHUB_STEP_SUMMARY", f"Reused a green tests run: tree `{tree}` already passed in {url}. The suite was not re-run.\n")
        print(f"Reusing {url} (tree {tree})")
    else:
        write("GITHUB_STEP_SUMMARY", f"Full suite runs: tree `{tree}`. {why}.\n")
        print(f"Running the full suite: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
