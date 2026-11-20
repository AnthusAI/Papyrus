"""The unit tests run as several CI jobs, and together the jobs run every test file exactly once."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("repository_root_conftest", ROOT / "conftest.py")
root_conftest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(root_conftest)

TEST_FILES = [f"procedures/newsroom/tests/test_subject_{number}.py" for number in range(200)] + [
    f"src/papyrus_content/subject_{number}_test.py" for number in range(200)
]


def test_every_test_file_falls_to_exactly_one_shard():
    for shard_count in (1, 2, 3, 5):
        for test_file in TEST_FILES:
            assert 0 <= root_conftest.shard_that_runs(test_file, shard_count) < shard_count


def test_two_shards_each_take_about_half_the_files():
    files_in_the_first_shard = sum(root_conftest.shard_that_runs(test_file, 2) == 0 for test_file in TEST_FILES)
    assert 150 <= files_in_the_first_shard <= 250


def collected_test_ids(*extra_arguments: str) -> set[str]:
    listing = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "procedures/newsroom/tests/test_reuse_green_tests.py",
         "procedures/newsroom/tests/test_feature_organization.py", "procedures/newsroom/tests/test_behave_side_by_side.py",
         "procedures/newsroom/tests/test_unit_test_shards.py", "procedures/newsroom/tests/test_cli_publish_guards.py",
         "procedures/newsroom/tests/test_reconcile_plugin_guard.py", *extra_arguments],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout
    return {line for line in listing.splitlines() if "::" in line}


def test_the_shards_of_a_real_run_share_no_test_and_miss_none():
    every_test = collected_test_ids()
    first_shard, second_shard = collected_test_ids("--shard", "0/2"), collected_test_ids("--shard", "1/2")
    assert every_test and first_shard and second_shard
    assert first_shard | second_shard == every_test
    assert first_shard & second_shard == set()


def test_the_workflow_runs_every_shard_it_names():
    unit_job = yaml.safe_load((ROOT / ".github/workflows/tests.yml").read_text())["jobs"]["python-unit"]
    shards = unit_job["strategy"]["matrix"]["shard"]
    unit_step = unit_job["steps"][-1]
    assert shards == list(range(int(unit_step["env"]["SHARDS"])))
    assert '--shard "$SHARD/$SHARDS"' in unit_step["run"]
    assert unit_job["needs"] == "reuse"
