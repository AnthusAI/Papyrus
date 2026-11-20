#!/usr/bin/env python3
"""Print one shard's share of the test files given on standard input, dealt out by how long each is known to take.

The dealing is the one the backend features use (behave_side_by_side.deal_out_evenly): slowest first, always to the shard
with the least so far, so no shard is left holding all the slow files. A file the seconds list does not name counts as a
quick one. The shards together print exactly the files given, none dropped and none repeated.

Usage:  printf '%s\n' scripts/test-*.ts | python3 infra/pipeline/deal_out_test_files.py --shard 0 --of 3 --seconds infra/pipeline/ts-test-seconds.json
        python3 infra/pipeline/deal_out_test_files.py --record-seconds-from shard-0.log shard-1.log shard-2.log --seconds infra/pipeline/ts-test-seconds.json
The second form rewrites the seconds list from the output of `node --test --test-reporter=spec`; run it when the slow tests change.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from behave_side_by_side import FEWEST_SECONDS_WORTH_LISTING, deal_out_evenly  # noqa: E402

A_TEST_FILE_AND_ITS_MILLISECONDS = re.compile(r"[✔✖] (\S+\.(?:ts|mts|cjs|mjs)) \((\d+(?:\.\d+)?)ms\)")


def seconds_each_test_file_took(spec_reporter_output: str) -> dict[str, float]:
    return {
        test_file: float(milliseconds) / 1000
        for test_file, milliseconds in A_TEST_FILE_AND_ITS_MILLISECONDS.findall(spec_reporter_output)
    }


def seconds_of_slow_test_files(seconds_by_test_file: dict[str, float]) -> dict[str, int]:
    return {
        test_file: round(seconds)
        for test_file, seconds in sorted(seconds_by_test_file.items())
        if seconds >= FEWEST_SECONDS_WORTH_LISTING
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard", type=int)
    parser.add_argument("--of", type=int, dest="shard_count")
    parser.add_argument("--seconds", type=Path, required=True)
    parser.add_argument("--record-seconds-from", type=Path, nargs="+")
    options = parser.parse_args()
    if options.record_seconds_from:
        seconds_by_test_file: dict[str, float] = {}
        for log_path in options.record_seconds_from:
            seconds_by_test_file.update(seconds_each_test_file_took(log_path.read_text(encoding="utf-8")))
        options.seconds.write_text(json.dumps(seconds_of_slow_test_files(seconds_by_test_file), indent=2) + "\n", encoding="utf-8")
        return 0
    if options.shard_count is None or options.shard is None or not 0 <= options.shard < options.shard_count:
        print("--shard must be from 0 to one less than --of", file=sys.stderr)
        return 1
    test_files = [line.strip() for line in sys.stdin if line.strip()]
    seconds_by_test_file = json.loads(options.seconds.read_text(encoding="utf-8"))
    print("\n".join(sorted(deal_out_evenly(test_files, options.shard_count, seconds_by_test_file)[options.shard])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
