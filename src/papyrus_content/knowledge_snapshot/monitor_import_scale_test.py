"""How many backend requests the record import costs at the size of Shipped's first real run (3,709 Hub models), counted, not timed.

AppSync answers in tens to hundreds of milliseconds per request, so the number of requests is what a run costs. ``Backend`` keeps rows in
dictionaries with the state indexes and counts the requests the real client would make (a list is a request per page of 100, an index
query too, a point read or a write one each). The time estimates in docs/knowledge-cloud-run.md come from these counts.

Run ``pytest -s src/papyrus_content/knowledge_snapshot/monitor_import_scale_test.py`` to print them.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from . import commands
from .commands_test import published_row
from .monitor_records import MonitorRecord, write_records

RECORDS, ITEMS, MAKERS, PAGE = 3709, 600, 800, 100
NOW = "2026-10-26T05:00:00Z"


class Backend:
    """Just enough of the authoring client for ``papyrus knowledge publish-run``, with the requests counted the way the real client makes them."""

    def __init__(self, published_rows) -> None:
        self.published_rows = published_rows
        self.rows: dict[str, dict[str, dict]] = defaultdict(dict)
        self.by_subject: dict[str, dict[str, dict]] = defaultdict(dict)
        self.by_object: dict[str, dict[str, dict]] = defaultdict(dict)
        self.requests: Counter = Counter()

    def reset(self) -> Counter:
        counted, self.requests = self.requests, Counter()
        return counted

    def pages(self, rows: int) -> int:
        return max(1, math.ceil(rows / PAGE))

    def list_published_item_summaries(self):
        self.requests["list"] += self.pages(len(self.published_rows))
        return list(self.published_rows)

    def list_records(self, model):
        self.requests["list"] += self.pages(len(self.rows[model]))
        return list(self.rows[model].values())

    def get_record(self, model, record_id):
        self.requests["get"] += 1
        return self.rows[model].get(record_id)

    def create_record(self, model, payload):
        self.requests["write"] += 1
        self._store(model, payload)

    def update_record(self, model, payload):
        self.requests["write"] += 1
        self.rows[model][payload["id"]].update(payload)

    def upsert(self, model, payload):
        (self.update_record if payload["id"] in self.rows[model] else self.create_record)(model, payload)

    def _store(self, model, payload):
        row = dict(payload)
        self.rows[model][row["id"]] = row
        if model == "SemanticRelation":
            self.by_subject[row["subjectStateKey"]][row["id"]] = row
            self.by_object[row["objectStateKey"]][row["id"]] = row

    def list_semantic_relations_by_subject_state(self, state):
        rows = list(self.by_subject[state].values())
        self.requests["index"] += self.pages(len(rows))
        return rows

    def list_semantic_relations_by_object_state(self, state):
        rows = list(self.by_object[state].values())
        self.requests["index"] += self.pages(len(rows))
        return rows


def hub_record(number: int) -> MonitorRecord:
    maker = f"maker{number % MAKERS}"
    name = f"model{number}"
    bases = [{"modelId": f"maker{(number - 7) % MAKERS}/model{number - 7}", "relation": "finetune"}] if number >= 7 and number % 5 == 0 else []
    details = {"modelId": f"{maker}/{name}", "author": maker, "createdAt": "2026-10-14T08:00:00Z", "license": ("apache-2.0", "mit", "cc-by-4.0")[number % 3],
               "pipelineTag": ("text-generation", "text-to-speech", "image-classification", "translation")[number % 4], "likes": number % 50, "downloads": number * 3, "baseModels": bases}
    return MonitorRecord(f"reference-{number}", f"lineage-{number}", "huggingface", f"https://huggingface.co/{maker}/{name}", f"{maker}/{name}", "2026-10-14T08:00:00Z", details)


def site_items():
    return [
        published_row(f"story{number}", "2026-10-13T08:00:00Z", entities=[("task", f"task {number % 40}"), ("maker", f"Lab {number % 90}"), ("concept", f"concept {number % 120}")])
        for number in range(ITEMS)
    ]


def publish(backend, records_file: Path, ledger: Path | None, *flags: str) -> Counter:
    ledger_flags = ["--monitor-ledger", str(ledger)] if ledger else []
    commands.knowledge_publish_run(["--monitor-records", str(records_file), *ledger_flags, "--apply", *flags])
    return backend.reset()


def total(counts: Counter) -> int:
    return sum(counts.values())


@pytest.fixture
def backend(monkeypatch):
    fake = Backend(site_items())
    monkeypatch.setattr(commands, "create_authoring_client", lambda *args, **kwargs: (fake, {}))
    return fake


def test_the_request_counts_of_a_first_import_a_run_with_nothing_new_and_a_run_with_ten_new_records(backend, tmp_path, capsys):
    records = [hub_record(number) for number in range(RECORDS)]
    file = tmp_path / "monitor-records.json"
    write_records(file, records, as_of=__import__("datetime").date(2026, 10, 26), sources=("huggingface",))
    ledger = tmp_path / "monitor-import-ledger.json"

    first = publish(backend, file, ledger)
    nodes, relations = len(backend.rows["SemanticNode"]), len(backend.rows["SemanticRelation"])
    steady = publish(backend, file, ledger)
    steady_again = publish(backend, file, ledger)
    more = [hub_record(number) for number in range(RECORDS, RECORDS + 10)]
    write_records(file, [*records, *more], as_of=__import__("datetime").date(2026, 10, 26), sources=("huggingface",))
    ten = publish(backend, file, ledger)
    full = publish(backend, file, ledger, "--monitor-full")

    report = {"records": RECORDS, "items": ITEMS, "entities": nodes, "relations": relations, "first import": dict(first), "nothing new": dict(steady), "ten new": dict(ten), "--monitor-full": dict(full)}
    with capsys.disabled():
        print("\nmonitor import requests: " + json.dumps(report, indent=1))

    assert nodes > 4000 and relations > 15000
    assert first["write"] >= nodes + relations - 1000  # every entity and link is written once
    # nothing new: the records cost nothing; what is left is the node list, one links query per published item and the front-matter links' point reads
    assert steady["write"] == 0 and steady_again == steady
    assert steady["index"] <= ITEMS
    assert total(steady) < 0.05 * total(first)
    # ten new records: their own entities, links and relations and a handful of reads each, and nothing proportional to the 3,709 already imported
    assert 0 < ten["write"] < 200 and ten["index"] <= ITEMS + 12
    assert total(ten) - total(steady) < 400
    # --monitor-full is the old behaviour: the links of every record are read again
    assert full["index"] > steady["index"] + RECORDS // 2
