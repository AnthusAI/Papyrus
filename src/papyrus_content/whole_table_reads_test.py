"""A new whole-table read fails the build.

`list_records`, `safe_list_records` and `list_published_item_summaries` read EVERY row of a model, one request per 100 rows. Each file's
current call count is recorded in data/whole_table_reads.json (the named sweeps, backfills, one-off operator commands and the older
loops still to be converted). The count may only go down: a file that makes more such calls than it is allowed, or a file that is not
listed, fails here. To add a real sweep, wrap it in `request_meter.sweep("<name>")` and raise its count in the allowlist with the
sweep named in the review; to read a few rows, use an index (`list_by_index`, `index_many`) instead.

Regenerate after removing calls: `PYTHONPATH=src:. python -m papyrus_content.whole_table_reads_test --write`.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
ALLOWLIST = Path(__file__).resolve().parent / "data" / "whole_table_reads.json"
WHOLE_TABLE_METHODS = {"list_records", "safe_list_records", "list_published_item_summaries"}
SCANNED = ("src", "procedures", "infra", "amplify/plugins", "publications", "scripts")


def is_test_file(path: Path) -> bool:
    return path.name.endswith("_test.py") or path.name.startswith("test_") or "tests" in path.parts or path.name == "conftest.py"


def whole_table_reads() -> dict[str, int]:
    counts: dict[str, int] = {}
    for directory in SCANNED:
        for path in sorted((REPOSITORY / directory).rglob("*.py")):
            if is_test_file(path) or "node_modules" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            calls = sum(1 for node in ast.walk(tree)
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in WHOLE_TABLE_METHODS)
            if calls:
                counts[path.relative_to(REPOSITORY).as_posix()] = calls
    return counts


def test_no_new_whole_table_reads_outside_the_allowlist() -> None:
    allowed = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    found = whole_table_reads()
    grown = {path: (allowed.get(path, 0), count) for path, count in found.items() if count > allowed.get(path, 0)}
    assert not grown, (
        "New whole-table reads (list_records / safe_list_records / list_published_item_summaries) in: "
        + "; ".join(f"{path} has {count}, allowed {before}" for path, (before, count) in sorted(grown.items()))
        + ". Read through an index, or make it a named sweep and update src/papyrus_content/data/whole_table_reads.json (see this test's docstring).")


def test_the_allowlist_has_no_slack() -> None:
    """When a conversion removes a whole-table read, the allowlist shrinks with it, so the ratchet never loosens."""
    allowed = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    found = whole_table_reads()
    slack = {path: (count, found.get(path, 0)) for path, count in allowed.items() if found.get(path, 0) < count}
    assert not slack, "Lower these in whole_table_reads.json (run this module with --write): " + "; ".join(
        f"{path} allows {count}, has {now}" for path, (count, now) in sorted(slack.items()))


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        ALLOWLIST.write_text(json.dumps(whole_table_reads(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {ALLOWLIST}")
    else:
        print(json.dumps(whole_table_reads(), indent=2, sort_keys=True))
