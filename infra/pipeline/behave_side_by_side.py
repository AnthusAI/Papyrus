#!/usr/bin/env python3
"""Run behave feature files in several processes at once, one per processor, and fail when any of them fails.

The feature files come on standard input, one path per line. Process N takes every Nth file, so together the processes run
exactly the files given, none dropped and none repeated. Each process's output is held and printed whole when all have
finished, so the log reads as if the processes had run one after another. Every other argument is handed to behave as given.

Usage:  find features_backend -name '*.feature' | sort | python infra/pipeline/behave_side_by_side.py --tags=~@live-agent
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time


def feature_files_for_each_process(feature_files: list[str], process_count: int) -> list[list[str]]:
    shares = [feature_files[process_index::process_count] for process_index in range(process_count)]
    return [share for share in shares if share]


def run_side_by_side(feature_files: list[str], behave_arguments: list[str], process_count: int) -> int:
    shares = feature_files_for_each_process(feature_files, process_count)
    started_at = time.monotonic()
    output_files = [tempfile.TemporaryFile(mode="w+") for _ in shares]
    running = [
        subprocess.Popen(
            [sys.executable, "-m", "behave", *behave_arguments, *share],
            stdout=output_file,
            stderr=subprocess.STDOUT,
        )
        for share, output_file in zip(shares, output_files)
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
    return 1 if failed_process_count else 0


def main() -> int:
    feature_files = [line.strip() for line in sys.stdin if line.strip()]
    if not feature_files:
        print("no feature files were given on standard input")
        return 1
    return run_side_by_side(feature_files, sys.argv[1:], os.cpu_count() or 1)


if __name__ == "__main__":
    sys.exit(main())
