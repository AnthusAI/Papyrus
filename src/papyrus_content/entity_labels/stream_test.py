"""The stream consumer: DynamoDB stream records in, label rows out."""
from __future__ import annotations

from papyrus_content.entity_labels.fakes import FakeSite
from papyrus_content.entity_labels.stream import events_from_stream, handle_changes

NOW = "2026-11-15T12:00:00Z"


def image(**fields):
    def typed(value):
        if isinstance(value, list):
            return {"L": [{"S": item} for item in value]}
        return {"S": value}
    return {name: typed(value) for name, value in fields.items()}


def record(event, new=None, old=None):
    return {"eventName": event, "dynamodb": {"SequenceNumber": "1", **({"NewImage": new} if new else {}), **({"OldImage": old} if old else {})}}


def test_a_new_concept_in_the_stream_gets_its_language_and_its_names():
    site = FakeSite()
    site.add_node("c1", "editor_concept--human-oversight", "Human oversight", aliases=["human control"])
    new = image(id="c1-v1", lineageId="c1", versionState="current", nodeKey="editor_concept--human-oversight", displayName="Human oversight", aliases=["human control"])
    totals = handle_changes(events_from_stream([record("INSERT", new=new)]), site, now=NOW)
    assert totals["nodes"] == 1 and totals["created"] == 3 and totals["language"] == 1
    assert site.tables["SemanticNode"]["c1-v1"]["language"] == "en"


def test_a_change_that_is_not_the_concepts_text_does_nothing_and_a_removed_concept_loses_its_primary_rows():
    site = FakeSite()
    site.add_node("c1", "editor_concept--a", "A")
    old = image(id="c1-v1", lineageId="c1", versionState="current", nodeKey="editor_concept--a", displayName="A", language="en")
    new = {**old, "authorityScore": {"S": "1"}}
    assert handle_changes(events_from_stream([record("MODIFY", new=new, old=old)]), site, now=NOW)["nodes"] == 0
    handle_changes(events_from_stream([record("INSERT", new=old)]), site, now=NOW)
    assert site.tables["EntityLabel"]
    handle_changes(events_from_stream([record("REMOVE", old=old)]), site, now=NOW)
    assert not site.tables["EntityLabel"]


def test_the_consumer_bundles_humanus_because_reading_the_primary_language_checks_the_tag_against_its_language_packs():
    from pathlib import Path

    folder = Path(__file__).resolve().parents[3] / "amplify" / "functions" / "entity-label-sync"
    assert any(line.startswith("humanus") for line in (folder / "requirements.txt").read_text().splitlines())
    assert "ENTITY_LABEL_SYNC_REQUIREMENTS" in (folder / "wire.ts").read_text()
