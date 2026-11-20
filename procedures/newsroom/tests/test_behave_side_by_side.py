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
        shares = side_by_side.feature_files_for_each_process(FEATURE_FILES, process_count)
        assert sorted(feature_file for share in shares for feature_file in share) == FEATURE_FILES
        assert len(shares) == min(process_count, len(FEATURE_FILES))


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


def test_each_behave_shard_hands_its_files_to_the_side_by_side_runner():
    jobs = yaml.safe_load((ROOT / ".github/workflows/tests.yml").read_text())["jobs"]
    shard_command = jobs["python-behave"]["steps"][-1]["run"]
    assert "find features_backend -name '*.feature'" in shard_command
    assert "infra/pipeline/behave_side_by_side.py --tags=~@live-agent" in shard_command
