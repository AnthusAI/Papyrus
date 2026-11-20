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


def test_the_consumer_reads_the_primary_language_from_the_settings_row_not_through_humanus():
    from pathlib import Path

    import papyrus_content.entity_labels.stream as stream

    assert stream.site_primary_language(FakeSite(primary="es-419")) == "es-419"
    source = Path(stream.__file__).read_text(encoding="utf-8")
    assert "editorial_languages" not in source and "primary_language()" not in source   # Humanus is not in the consumer's bundle, so nothing here may need it


def test_every_api_field_the_consumer_is_allowed_to_call_exists_in_the_schema_and_covers_what_it_calls():
    """The consumer's IAM grant names AppSync fields; a field renamed in the schema leaves the grant stale and every batch fails with 'Permission denied'."""
    import re
    from pathlib import Path

    from papyrus_content.graphql_authoring import INDEX_DEFINITIONS

    root = Path(__file__).resolve().parents[3]
    wire = (root / "amplify" / "functions" / "entity-label-sync" / "wire.ts").read_text(encoding="utf-8")
    schema = (root / "amplify" / "data" / "schema.ts").read_text(encoding="utf-8")
    granted = re.findall(r'"(?:Query|Mutation)/fields/(\w+)"', wire)
    queries = set(re.findall(r'queryField\("(\w+)"\)', schema))
    for field in granted:
        if field.startswith("list"):
            assert field in queries, f"{field} is granted but the schema has no such query"
    assert INDEX_DEFINITIONS["entityLabelsByEntity"]["field"] in granted   # LabelStore.of_entity, which the consumer reads each concept's rows with
