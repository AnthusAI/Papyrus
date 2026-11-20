import json
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEAL_OUT_TEST_FILES = REPOSITORY_ROOT / "infra" / "pipeline" / "deal_out_test_files.py"
TEST_FILES = [f"scripts/test-{name}.ts" for name in ("slowest", "slow", "quick-a", "quick-b", "quick-c", "quick-d")]


def share_of(shard: int, shard_count: int, seconds_path: Path) -> list[str]:
    finished = subprocess.run(
        [sys.executable, str(DEAL_OUT_TEST_FILES), "--shard", str(shard), "--of", str(shard_count), "--seconds", str(seconds_path)],
        input="\n".join(TEST_FILES) + "\n",
        capture_output=True,
        text=True,
        check=True,
    )
    return finished.stdout.split()


def test_the_shards_together_run_every_file_once_and_the_slow_files_are_kept_apart(tmp_path):
    seconds_path = tmp_path / "seconds.json"
    seconds_path.write_text(json.dumps({"scripts/test-slowest.ts": 300, "scripts/test-slow.ts": 290}))
    shares = [share_of(shard, 2, seconds_path) for shard in range(2)]
    assert sorted(shares[0] + shares[1]) == sorted(TEST_FILES)
    slow_files = {"scripts/test-slowest.ts", "scripts/test-slow.ts"}
    assert [len(set(share) & slow_files) for share in shares] == [1, 1]


def test_seconds_are_recorded_from_the_spec_reporter_output(tmp_path):
    log_path = tmp_path / "shard.log"
    log_path.write_text(
        "2026-11-20T18:50:00Z ✔ scripts/test-slowest.ts (300123.4ms)\n"
        "2026-11-20T18:50:01Z ✔ scripts/test-quick-a.ts (812.0ms)\n"
        "2026-11-20T18:50:02Z ✖ amplify/functions/thing/handler.test.mjs (4500ms)\n",
        encoding="utf-8",
    )
    seconds_path = tmp_path / "seconds.json"
    subprocess.run(
        [sys.executable, str(DEAL_OUT_TEST_FILES), "--record-seconds-from", str(log_path), "--seconds", str(seconds_path)],
        check=True,
    )
    assert json.loads(seconds_path.read_text()) == {
        "amplify/functions/thing/handler.test.mjs": 4,
        "scripts/test-slowest.ts": 300,
    }


def test_every_listed_typescript_test_file_still_exists():
    listed = json.loads((REPOSITORY_ROOT / "infra" / "pipeline" / "ts-test-seconds.json").read_text())
    assert [test_file for test_file in listed if not (REPOSITORY_ROOT / test_file).exists()] == []
