"""Backend features run in one process per processor: the split, the verdict and the workflow wiring.

Nothing here runs behave. features/ci-behave-side-by-side.feature tells the same story in prose.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("behave_side_by_side", ROOT / "infra" / "pipeline" / "behave_side_by_side.py")
side_by_side = importlib.util.module_from_spec(spec)
spec.loader.exec_module(side_by_side)

FEATURE_FILES = [f"features_backend/area/story-{number}.feature" for number in range(10)]


def start_a_stand_in_for_behave(exit_code_for_each_share, started_commands):
    real_popen = subprocess.Popen

    def popen(command, **keywords):
        started_commands.append(command)
        share = [argument for argument in command if argument.endswith(".feature")]
        exit_code = exit_code_for_each_share(share)
        return real_popen([sys.executable, "-c", f"print('ran {len(share)} files'); raise SystemExit({exit_code})"], **keywords)

    return popen


def test_the_processes_together_run_every_file_exactly_once():
    for process_count in (1, 2, 3, 4, 16):
        shares = side_by_side.feature_files_for_each_process(FEATURE_FILES, process_count, {FEATURE_FILES[3]: 120, FEATURE_FILES[7]: 40})
        assert sorted(feature_file for share in shares for feature_file in share) == FEATURE_FILES
        assert len(shares) == min(process_count, len(FEATURE_FILES))


def test_the_shards_together_run_every_backend_feature_exactly_once():
    every_backend_feature = sorted(str(path.relative_to(ROOT)) for path in (ROOT / "features_backend").glob("*/*.feature"))
    shards = side_by_side.deal_out_evenly(every_backend_feature, 3, side_by_side.seconds_of_known_slow_features())
    assert sorted(feature_file for shard in shards for feature_file in shard) == every_backend_feature
    assert all(shards)


def test_the_slow_features_are_spread_and_not_left_to_one_share():
    seconds = {"slow-a.feature": 120, "slow-b.feature": 120, "slow-c.feature": 90}
    quick_features = [f"quick-{number:02}.feature" for number in range(30)]
    shares = side_by_side.deal_out_evenly(list(seconds) + quick_features, 3, seconds)
    assert sorted(len([feature_file for feature_file in share if feature_file in seconds]) for share in shares) == [1, 1, 1]
    seconds_in_each_share = [sum(seconds.get(feature_file, 1) for feature_file in share) for share in shares]
    assert max(seconds_in_each_share) - min(seconds_in_each_share) <= 1


def test_the_same_files_are_dealt_the_same_way_whatever_order_they_arrive_in():
    seconds = {FEATURE_FILES[2]: 50}
    assert side_by_side.deal_out_evenly(FEATURE_FILES, 3, seconds) == side_by_side.deal_out_evenly(FEATURE_FILES[::-1], 3, seconds)


def test_every_feature_the_seconds_list_names_exists():
    listed_features_that_are_gone = sorted(
        feature_file for feature_file in side_by_side.seconds_of_known_slow_features() if not (ROOT / feature_file).is_file()
    )
    assert listed_features_that_are_gone == [], "Remove these from infra/pipeline/backend-feature-seconds.json"


def test_measured_seconds_are_read_from_behave_reports_and_only_slow_features_are_kept(monkeypatch, tmp_path):
    report_path = tmp_path / "process-0.json"
    report_path.write_text(
        """[
          {"location": "features_backend/a/slow.feature:1", "elements": [{"steps": [{"result": {"duration": 30.2}}, {"result": {"duration": 12}}]}]},
          {"location": "features_backend/a/quick.feature:1", "elements": [{"steps": [{"result": {"duration": 0.5}}, {}]}]}
        ]"""
    )
    seconds = side_by_side.seconds_each_feature_took([str(report_path)])
    assert seconds == {"features_backend/a/slow.feature": 42.2, "features_backend/a/quick.feature": 0.5}
    monkeypatch.setattr(side_by_side, "SECONDS_OF_KNOWN_SLOW_FEATURES_PATH", tmp_path / "seconds.json")
    side_by_side.write_seconds_of_slow_features(seconds)
    assert side_by_side.seconds_of_known_slow_features() == {"features_backend/a/slow.feature": 42}


def test_every_process_starts_with_the_same_behave_arguments(monkeypatch, capsys):
    started_commands = []
    monkeypatch.setattr(side_by_side.subprocess, "Popen", start_a_stand_in_for_behave(lambda share: 0, started_commands))
    assert side_by_side.run_side_by_side(FEATURE_FILES, ["--tags=~@live-agent"], process_count=4) == 0
    assert len(started_commands) == 4
    for command in started_commands:
        assert command[:4] == [sys.executable, "-m", "behave", "--tags=~@live-agent"]
    printed = capsys.readouterr().out
    assert printed.count("::group::behave process") == 4
    assert "10 feature files in 4 processes" in printed and "0 processes failed" in printed


def test_one_failing_process_fails_the_whole_run_and_its_output_is_printed_again(monkeypatch, capsys):
    started_commands = []
    fails_when_it_holds_the_second_file = lambda share: 1 if FEATURE_FILES[1] in share else 0
    monkeypatch.setattr(side_by_side.subprocess, "Popen", start_a_stand_in_for_behave(fails_when_it_holds_the_second_file, started_commands))
    assert side_by_side.run_side_by_side(FEATURE_FILES, [], process_count=2) == 1
    printed = capsys.readouterr().out
    assert "1 processes failed" in printed
    assert printed.count("ran 5 files") == 3


def test_no_feature_files_is_a_failure_and_not_a_quiet_pass(monkeypatch, capsys):
    monkeypatch.setattr(side_by_side.sys, "stdin", iter([]))
    assert side_by_side.main() == 1


def test_each_behave_shard_hands_every_backend_feature_to_the_side_by_side_runner_and_names_its_shard():
    jobs = yaml.safe_load((ROOT / ".github/workflows/tests.yml").read_text())["jobs"]
    shard_step = jobs["python-behave"]["steps"][-1]
    assert "find features_backend -name '*.feature'" in shard_step["run"]
    assert 'infra/pipeline/behave_side_by_side.py --shard "$SHARD" --of "$SHARDS" --tags=~@live-agent' in shard_step["run"]
    assert int(shard_step["env"]["SHARDS"]) == len(jobs["python-behave"]["strategy"]["matrix"]["shard"])
