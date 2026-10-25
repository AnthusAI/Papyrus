from __future__ import annotations

import json
from datetime import date

import pytest

from .corpus_export import render_record, write_export
from .monitor_records import (
    biblicus_record_id,
    load_monitor_records,
    parse_sources,
    read_records,
    record_as_item,
    record_entities,
    record_summary,
    write_records,
)

CORPUS = "knowledge-corpus-shipped"
AS_OF = date(2026, 10, 19)
HUB = "https://huggingface.co"


def details(model_id: str, **overrides) -> dict:
    return {
        "modelId": model_id, "author": model_id.split("/")[0], "createdAt": "2026-10-14T08:00:00.000Z", "pipelineTag": "text-to-speech",
        "tags": ["license:apache-2.0"], "license": "apache-2.0", "libraryName": "transformers", "likes": 40, "downloads": 1200,
        "baseModels": [{"modelId": "org/base", "relation": "finetune"}], **overrides,
    }


def reference(model_id: str, created: str = "2026-10-14T08:00:00.000Z", **overrides) -> dict:
    slug = model_id.replace("/", "--")
    return {
        "id": f"reference-{slug}", "lineageId": f"lineage-{slug}", "versionState": "current", "corpusId": CORPUS, "curationStatus": "pending",
        "sourceUri": f"{HUB}/{model_id}", "title": f"{model_id}: text-to-speech model", "sourcePublishedAt": created, **overrides,
    }


def provenance(reference_row: dict, body: dict | None, imported: str = "2026-10-15T00:00:00Z") -> dict:
    metadata = {"monitorId": "huggingface", "sourceId": "x", **({"details": body} if body else {})}
    return {"predicate": "ingestion_rationale", "relationState": "current", "subjectKind": "message", "objectKind": "reference", "importedAt": imported,
            "objectLineageId": reference_row["lineageId"], "metadata": json.dumps(metadata)}


class FakeBackend:
    def __init__(self, references: list[dict], relations: list[dict]) -> None:
        self.references, self.relations, self.queries = references, relations, []

    def list_records(self, model_name: str) -> list[dict]:
        assert model_name == "Reference"
        return self.references

    def list_semantic_relations_by_object_state(self, state: str) -> list[dict]:
        self.queries.append(state)
        lineage = state.split("#")[1]
        return [row for row in self.relations if row["objectLineageId"] == lineage]


def load(backend: FakeBackend, **options):
    return load_monitor_records(backend, corpus_id=CORPUS, sources=("huggingface",), as_of=AS_OF, **options)


def test_only_sources_that_are_supported_are_accepted():
    assert parse_sources("huggingface, huggingface") == ("huggingface",)
    assert parse_sources("") == ()
    with pytest.raises(ValueError, match="Unsupported monitor source 'rss'"):
        parse_sources("rss")


def test_a_delivered_model_is_a_record_with_the_hub_fields_from_its_provenance_relation():
    row = reference("org/tuned")
    records, warnings = load(FakeBackend([row], [provenance(row, details("org/tuned"))]))
    [one] = records
    assert warnings == []
    assert (one.model_id, one.url, one.created_at, one.state) == ("org/tuned", f"{HUB}/org/tuned", "2026-10-14T08:00:00Z", "pending")
    assert one.details["baseModels"] == [{"modelId": "org/base", "relation": "finetune"}]


def test_a_rejected_reference_a_foreign_corpus_and_other_sites_are_left_out_but_pending_and_accepted_count():
    rows = [
        reference("org/pending"),
        reference("org/accepted", curationStatus="accepted"),
        reference("org/rejected", curationStatus="rejected"),
        reference("org/declined", curationStatus="declined"),
        reference("org/elsewhere", corpusId="knowledge-corpus-other"),
        reference("org/old", versionState="superseded"),
        {**reference("org/news"), "sourceUri": "https://example.test/news"},
    ]
    records, _ = load(FakeBackend(rows, [provenance(row, details(row["title"].split(":")[0])) for row in rows]))
    assert sorted(record.model_id for record in records) == ["org/accepted", "org/pending"]


def test_the_window_is_the_source_date_so_a_backfill_has_history_and_old_models_do_not_count():
    rows = [reference("org/new", "2026-10-18T00:00:00Z"), reference("org/year", "2025-10-27T00:00:00Z"), reference("org/ancient", "2025-01-01T00:00:00Z"), reference("org/future", "2026-12-01T00:00:00Z")]
    records, _ = load(FakeBackend(rows, [provenance(row, details(row["title"].split(":")[0])) for row in rows]))
    assert [record.model_id for record in records] == ["org/new", "org/year"]
    narrow, _ = load(FakeBackend(rows, [provenance(row, details(row["title"].split(":")[0])) for row in rows]), weeks=4)
    assert [record.model_id for record in narrow] == ["org/new"]


def test_a_new_revision_of_a_model_replaces_the_older_details_and_the_newest_records_win_the_limit():
    row = reference("org/tuned")
    backend = FakeBackend([row], [provenance(row, details("org/tuned", likes=5), "2026-10-15T00:00:00Z"), provenance(row, details("org/tuned", likes=50), "2026-10-17T00:00:00Z")])
    [one], _ = load(backend)
    assert one.details["likes"] == 50
    many = [reference(f"org/m{number}", f"2026-10-{10 + number:02d}T00:00:00Z") for number in range(5)]
    kept, warnings = load(FakeBackend(many, []), limit=2)
    assert [record.model_id for record in kept] == ["org/m4", "org/m3"] and any("only the newest 2" in warning for warning in warnings)


def test_a_reference_delivered_before_details_rode_on_the_relation_still_counts_with_its_title_date_and_author():
    row = reference("org/early")
    [one], warnings = load(FakeBackend([row], [provenance(row, None)]))
    assert (one.model_id, one.details["author"], one.details["baseModels"]) == ("org/early", "org", [])
    assert any("no Hub details" in warning for warning in warnings)


def test_the_records_file_round_trips(tmp_path):
    row = reference("org/tuned")
    records, _ = load(FakeBackend([row], [provenance(row, details("org/tuned"))]))
    write_records(tmp_path / "run" / "monitor-records.json", records, as_of=AS_OF, sources=("huggingface",))
    assert read_records(tmp_path / "run" / "monitor-records.json") == records
    (tmp_path / "bad.json").write_text("{}")
    with pytest.raises(ValueError, match="is not a monitor records file"):
        read_records(tmp_path / "bad.json")


def test_the_structured_fields_give_the_entities_and_one_factual_line():
    row = reference("org/tuned")
    [one], _ = load(FakeBackend([row], [provenance(row, details("org/tuned"))]))
    assert record_entities(one) == [("model", "org/tuned"), ("maker", "org"), ("licence", "apache-2.0"), ("task", "text-to-speech")]
    assert record_summary(one) == (
        "org/tuned is a text-to-speech model by org, released 2026-10-14. License apache-2.0. 40 likes, 1200 downloads. Built on org/base (finetune)."
    )
    other = reference("org/plain")
    [bare], _ = load(FakeBackend([other], [provenance(other, details("org/plain", license="other", pipelineTag=None, baseModels=[]))]))
    assert [kind for kind, _name in record_entities(bare)] == ["model", "maker"]  # "other" is no licence worth an entity


def test_as_an_item_a_record_is_dated_has_the_hub_card_for_its_address_and_is_marked():
    row = reference("org/tuned")
    [one], _ = load(FakeBackend([row], [provenance(row, details("org/tuned"))]))
    item = record_as_item(one)
    assert (item.kind, item.is_record, item.key, item.item_id, item.url, item.published_at) == ("monitor-record", True, "lineage-org--tuned", "reference-org--tuned", f"{HUB}/org/tuned", "2026-10-14T08:00:00Z")


def test_the_corpus_document_carries_the_source_date_and_the_structured_line_never_card_text(tmp_path):
    row = reference("org/tuned")
    [one], _ = load(FakeBackend([row], [provenance(row, details("org/tuned"))]))
    document = render_record(one)
    assert document.file == "record-reference-org--tuned.md" and document.biblicus_id == biblicus_record_id("reference-org--tuned")
    assert "kind: monitor-record" in document.text and "papyrus_record_id: reference-org--tuned" in document.text
    assert "published_at: '2026-10-14T08:00:00Z'" in document.text or 'published_at: "2026-10-14T08:00:00Z"' in document.text or "published_at: 2026-10-14T08:00:00Z" in document.text
    assert "# org/tuned" in document.text and "Built on org/base (finetune)." in document.text
    out = tmp_path / "papyrus"
    counts = write_export([], out, [document])
    assert counts == {"items": 0, "removed": 0, "undated": 0, "records": 1}
    assert write_export([], out, []) == {"items": 0, "removed": 1, "undated": 0}  # a record no longer delivered leaves the corpus
    assert not list(out.glob("*.md"))
