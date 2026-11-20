#!/usr/bin/env python3
"""Run behave feature files in several processes at once, one per processor, and fail when any of them fails.

The feature files come on standard input, one path per line. With `--shard N --of M` only this shard's share of them is run.
Files are dealt out by how long each is known to take (backend-feature-seconds.json, beside this file), slowest first and
always to whoever has the least so far, so that no shard and no process is left holding all the slow ones. A file the list
does not name counts as a quick one. However the seconds change, the shards together run exactly the files given, none
dropped and none repeated, and so do the processes of one shard.

Each process's output is held and printed whole when all have finished, so the log reads as if the processes had run one
after another. Every other argument is handed to behave as given.

Usage:  find features_backend -name '*.feature' | sort | python infra/pipeline/behave_side_by_side.py --shard 0 --of 3 --tags=~@live-agent
        find features_backend -name '*.feature' | sort | python infra/pipeline/behave_side_by_side.py --record-seconds --tags=~@live-agent
The second form also measures every feature and rewrites backend-feature-seconds.json; run it when the slow features change.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SECONDS_OF_KNOWN_SLOW_FEATURES_PATH = Path(__file__).resolve().parent / "backend-feature-seconds.json"
SECONDS_A_FEATURE_NOT_LISTED_COUNTS_AS = 1
FEWEST_SECONDS_WORTH_LISTING = 4


def seconds_of_known_slow_features() -> dict[str, float]:
    return json.loads(SECONDS_OF_KNOWN_SLOW_FEATURES_PATH.read_text(encoding="utf-8"))


def deal_out_evenly(feature_files: list[str], share_count: int, seconds_by_feature_file: dict[str, float]) -> list[list[str]]:
    def seconds_of(feature_file: str) -> float:
        return seconds_by_feature_file.get(feature_file, SECONDS_A_FEATURE_NOT_LISTED_COUNTS_AS)

    shares: list[list[str]] = [[] for _ in range(share_count)]
    seconds_in_each_share = [0.0] * share_count
    for feature_file in sorted(feature_files, key=lambda path: (-seconds_of(path), path)):
        share_with_the_least = seconds_in_each_share.index(min(seconds_in_each_share))
        shares[share_with_the_least].append(feature_file)
        seconds_in_each_share[share_with_the_least] += seconds_of(feature_file)
    return shares


def feature_files_for_each_process(feature_files: list[str], process_count: int, seconds_by_feature_file: dict[str, float]) -> list[list[str]]:
    return [share for share in deal_out_evenly(feature_files, process_count, seconds_by_feature_file) if share]


def seconds_each_feature_took(behave_json_report_paths: list[str]) -> dict[str, float]:
    seconds_by_feature_file: dict[str, float] = {}
    for report_path in behave_json_report_paths:
        for feature in json.loads(Path(report_path).read_text(encoding="utf-8") or "[]"):
            seconds_by_feature_file[feature["location"].split(":")[0]] = sum(
                step.get("result", {}).get("duration", 0)
                for element in feature.get("elements", [])
                for step in element.get("steps", [])
            )
    return seconds_by_feature_file


def write_seconds_of_slow_features(seconds_by_feature_file: dict[str, float]) -> None:
    slow_features = {
        feature_file: round(seconds)
        for feature_file, seconds in sorted(seconds_by_feature_file.items())
        if seconds >= FEWEST_SECONDS_WORTH_LISTING
    }
    SECONDS_OF_KNOWN_SLOW_FEATURES_PATH.write_text(json.dumps(slow_features, indent=2) + "\n", encoding="utf-8")


def run_side_by_side(
    feature_files: list[str],
    behave_arguments: list[str],
    process_count: int,
    seconds_by_feature_file: dict[str, float] | None = None,
    record_seconds: bool = False,
) -> int:
    shares = feature_files_for_each_process(feature_files, process_count, seconds_by_feature_file or {})
    started_at = time.monotonic()
    output_files = [tempfile.TemporaryFile(mode="w+") for _ in shares]
    report_directory = tempfile.TemporaryDirectory()
    report_paths = [str(Path(report_directory.name) / f"process-{number}.json") for number in range(len(shares))]
    running = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "behave",
                *behave_arguments,
                *(["-f", "json", "-o", report_path, "-f", "pretty"] if record_seconds else []),
                *share,
            ],
            stdout=output_file,
            stderr=subprocess.STDOUT,
        )
        for share, output_file, report_path in zip(shares, output_files, report_paths)
    ]
    for process in running:
        process.wait()
    outputs = []
    for output_file in output_files:
        output_file.seek(0)
        outputs.append(output_file.read())
        output_file.close()
    failed_process_count = 0
    for process_number, (process, share, output) in enumerate(zip(running, shares, outputs), start=1):
        print(f"::group::behave process {process_number} of {len(shares)}: {len(share)} feature files, exit {process.returncode}")
        print(output)
        print("::endgroup::")
        if process.returncode != 0:
            failed_process_count += 1
    seconds = round(time.monotonic() - started_at)
    print(f"{len(feature_files)} feature files in {len(shares)} processes took {seconds}s; {failed_process_count} processes failed")
    if failed_process_count:
        for process, output in zip(running, outputs):
            if process.returncode != 0:
                print(output)
    if record_seconds:
        write_seconds_of_slow_features(seconds_each_feature_took(report_paths))
        print(f"rewrote {SECONDS_OF_KNOWN_SLOW_FEATURES_PATH}")
    report_directory.cleanup()
    return 1 if failed_process_count else 0


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--shard", type=int)
    parser.add_argument("--of", type=int, dest="shard_count")
    parser.add_argument("--record-seconds", action="store_true")
    options, behave_arguments = parser.parse_known_args()
    feature_files = [line.strip() for line in sys.stdin if line.strip()]
    if not feature_files:
        print("no feature files were given on standard input")
        return 1
    seconds_by_feature_file = seconds_of_known_slow_features()
    if options.shard_count:
        if options.shard is None or not 0 <= options.shard < options.shard_count:
            print(f"--shard must be from 0 to {options.shard_count - 1}")
            return 1
        feature_files = deal_out_evenly(feature_files, options.shard_count, seconds_by_feature_file)[options.shard]
        print(f"shard {options.shard} of {options.shard_count} runs {len(feature_files)} feature files:")
        print("\n".join(sorted(feature_files)))
    return run_side_by_side(feature_files, behave_arguments, os.cpu_count() or 1, seconds_by_feature_file, options.record_seconds)


if __name__ == "__main__":
    sys.exit(main())
