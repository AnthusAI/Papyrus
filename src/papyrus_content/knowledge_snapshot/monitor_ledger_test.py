from __future__ import annotations

import json

import pytest

from .monitor_ledger import IMPORT_VERSION, LEDGER_SCHEMA, MonitorLedger, record_hash
from .monitor_records import MonitorRecord


def record(name: str = "tuned", *, author: str = "org", bases=(), **details) -> MonitorRecord:
    body = {"modelId": f"{author}/{name}", "author": author, "createdAt": "2026-10-14T08:00:00Z", "license": "apache-2.0", "pipelineTag": "text-to-speech", "likes": 10, "downloads": 100,
            "baseModels": [{"modelId": base, "relation": relation} for base, relation in bases], **details}
    return MonitorRecord(f"reference-{author}-{name}", f"lineage-{author}-{name}", "huggingface", f"https://huggingface.co/{author}/{name}", f"{author}/{name}", "2026-10-14T08:00:00Z", body)


def test_the_hash_covers_what_the_import_reads_and_nothing_else():
    base = record_hash(record())
    assert record_hash(record()) == base
    assert record_hash(record(likes=9000, downloads=5, createdAt="2026-10-15T00:00:00Z", tags=["x"])) == base  # counters and dates are not imported
    assert record_hash(record(license="mit")) != base
    assert record_hash(record(pipelineTag="image-classification")) != base
    assert record_hash(record(author="other")) != base
    assert record_hash(record(bases=[("org/base", "finetune")])) != base
    assert record_hash(record(bases=[("org/base", "finetune")])) != record_hash(record(bases=[("org/base", "quantized")]))
    assert record_hash(record(bases=[("a/b", "finetune"), ("c/d", "merge")])) == record_hash(record(bases=[("c/d", "merge"), ("a/b", "finetune")]))


def test_a_generic_licence_is_not_an_entity_so_it_does_not_change_the_hash():
    assert record_hash(record(license="other")) == record_hash(record(license="unknown"))


def test_the_ledger_round_trips_and_a_missing_file_is_an_empty_ledger(tmp_path):
    path = tmp_path / "corpus" / "ledger.json"
    assert MonitorLedger.read(path).entries == {} and MonitorLedger.read(None).entries == {}
    ledger = MonitorLedger().after_import([record("a"), record("b")], {"reference-org-a": [], "reference-org-b": ["x/y", "x/y"]})
    ledger.write(path)
    assert not list(path.parent.glob("*.tmp"))
    raw = json.loads(path.read_text())
    assert raw["schema"] == LEDGER_SCHEMA and set(raw["records"]) == {"reference-org-a", "reference-org-b"}
    again = MonitorLedger.read(path)
    assert again.entries == ledger.entries and again.entries["reference-org-b"]["unplacedBases"] == ["x/y"]


@pytest.mark.parametrize("text", ["not json", "[]", '{"schema": 99, "records": {}}', '{"schema": 1}', '{"schema": 1, "records": {"a": {}}}'])
def test_a_file_that_is_not_a_ledger_is_an_error_and_never_silently_emptied(tmp_path, text):
    path = tmp_path / "ledger.json"
    path.write_text(text)
    with pytest.raises(ValueError, match="not a monitor import ledger"):
        MonitorLedger.read(path)


def test_new_changed_and_newly_placeable_records_are_the_ones_to_import():
    unchanged, changed, waiting, fresh = record("unchanged"), record("changed"), record("waiting", bases=[("elsewhere/gone", "adapter")]), record("fresh")
    ledger = MonitorLedger().after_import([unchanged, changed, waiting], {unchanged.reference_id: [], changed.reference_id: [], waiting.reference_id: ["elsewhere/gone"]})
    edited = record("changed", license="mit")
    nothing_placed = lambda model: False
    assert [r.reference_id for r in ledger.changed([unchanged, edited, waiting, fresh], nothing_placed)] == [edited.reference_id, fresh.reference_id]
    assert [r.reference_id for r in ledger.changed([unchanged, waiting], lambda model: model == "elsewhere/gone")] == [waiting.reference_id]  # its base model reached the map


def test_after_an_import_the_ledger_holds_exactly_the_current_records():
    kept, left, new = record("kept"), record("left"), record("new")
    ledger = MonitorLedger().after_import([kept, left], {kept.reference_id: [], left.reference_id: []})
    after = ledger.after_import([kept, new], {new.reference_id: ["a/b"]})  # `kept` was skipped, `left` left the window
    assert set(after.entries) == {kept.reference_id, new.reference_id}
    assert after.entries[kept.reference_id] == ledger.entries[kept.reference_id]
    assert after.entries[new.reference_id] == {"hash": record_hash(new), "unplacedBases": ["a/b"]}


def test_the_import_version_is_part_of_the_hash(monkeypatch):
    from . import monitor_ledger

    before = record_hash(record())
    monkeypatch.setattr(monitor_ledger, "IMPORT_VERSION", IMPORT_VERSION + 1)
    assert record_hash(record()) != before
