"""Fail when pilot-specific identifiers appear in application logic.

Papyrus is a general-purpose newsroom: corpus keys, domains, developer paths and
model names belong in configuration and publication folders, not in code.
Files that still carry identifiers are recorded in pilot_identifier_baseline.json
with their current match count; a file may never exceed its baseline count and
the baseline only shrinks.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = Path(__file__).with_name("pilot_identifier_baseline.json")

PILOT_IDENTIFIER_PATTERN = re.compile(
    r"AI-ML-research|AI-ML-journalism|threat-intelligence|p\.apyr\.us|/Users/|gpt-5"
)

ALLOWED_PATH_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"^corpora/",
        r"^publications/",
        r"^config/",
        r"^docs/",
        r"^project/",
        r"^pods/",
        r"^features(_backend)?/",
        r"^public/",
        r"^procedures/guards/",
        r"(^|/)tests?/",
        r"_test\.py$",
        r"(^|/)test[-_][^/]*$",
        r"\.test\.[a-z]+$",
        r"\.md$",
        r"^package-lock\.json$",
        r"^poetry\.lock$",
        r"^\.env\.example$",
        r"(^|/)anthus_sites\.json$",  # the Anthus site registry is configuration data (site addresses), mirrored from anthus-footer
    )
)

SCANNED_SUFFIXES = {".py", ".ts", ".tsx", ".mjs", ".cjs", ".js", ".tac", ".rs", ".sh", ".yml", ".yaml", ".json"}


def tracked_files() -> list[str]:
    output = subprocess.run(
        ["git", "ls-files"], cwd=REPOSITORY_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return output.splitlines()


def count_pilot_identifiers(relative_path: str) -> int:
    path = REPOSITORY_ROOT / relative_path
    if path.suffix not in SCANNED_SUFFIXES or not path.is_file():
        return 0
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return 0
    return len(PILOT_IDENTIFIER_PATTERN.findall(text))


def collect_violations() -> dict[str, int]:
    violations: dict[str, int] = {}
    for relative_path in tracked_files():
        if any(pattern.search(relative_path) for pattern in ALLOWED_PATH_PATTERNS):
            continue
        match_count = count_pilot_identifiers(relative_path)
        if match_count:
            violations[relative_path] = match_count
    return violations


def main(argv: list[str]) -> int:
    violations = collect_violations()
    if "--write-baseline" in argv:
        BASELINE_PATH.write_text(json.dumps(violations, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Wrote baseline for {len(violations)} files.")
        return 0
    baseline: dict[str, int] = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    failures = [
        f"{path}: {count} pilot identifiers (baseline {baseline.get(path, 0)})"
        for path, count in sorted(violations.items())
        if count > baseline.get(path, 0)
    ]
    stale_baseline_entries = sorted(path for path in baseline if path not in violations)
    if stale_baseline_entries:
        failures.extend(
            f"{path}: clean now, remove it from {BASELINE_PATH.name}" for path in stale_baseline_entries
        )
    if failures:
        print("Pilot identifiers found in application logic. Move them to configuration:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"OK: {len(violations)} files remain in the baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
