from papyrus_content.reference_reads import DeferredRows, reference_by_token, targeted_scope
from papyrus_content.reference_reads_testing import list_by_index_from_records


class Client:
    def __init__(self):
        self.listed = []
        self.tables = {
            "Reference": [{"id": "a-v1", "lineageId": "a", "versionState": "superseded", "corpusId": "c", "externalItemId": "item-a"},
                          {"id": "a-v2", "lineageId": "a", "versionState": "current", "corpusId": "c", "externalItemId": "item-a"},
                          {"id": "b", "lineageId": "b", "versionState": "current", "corpusId": "c", "externalItemId": "item-b"}],
            "ReferenceAttachment": [{"id": "x", "referenceLineageId": "a"}, {"id": "y", "referenceLineageId": "b"}],
            "SemanticRelation": [], "KnowledgeCorpus": [{"id": "c"}],
        }

    def list_records(self, model):
        self.listed.append(model)
        return self.tables[model]

    def list_by_index(self, index_name, key_value, *, limit=100, sort_eq=None):
        return list_by_index_from_records(lambda m: self.tables[m], index_name, key_value, sort_eq)

    def get_record(self, model, record_id):
        return next((row for row in self.tables[model] if row["id"] == record_id), None)


def test_a_token_finds_every_version_by_lineage_and_one_row_by_id():
    client = Client()
    assert {row["id"] for row in reference_by_token(client, "a")} == {"a-v1", "a-v2"}
    assert [row["id"] for row in reference_by_token(client, "a-v2")] == ["a-v2"]
    assert [row["id"] for row in reference_by_token(client, "item-b")] == ["b"]   # an item id, found in each corpus by key condition
    assert reference_by_token(client, "nothing") == []
    assert "Reference" not in client.listed and "ReferenceAttachment" not in client.listed


def test_deferred_rows_read_nothing_until_looked_at():
    calls = []
    rows = DeferredRows(lambda: calls.append(1) or [{"id": 1}, {"id": 2}])
    assert calls == [] and not rows.loaded
    assert len(rows) == 2 and [row["id"] for row in rows] == [1, 2] and calls == [1]


def test_targeted_scope_is_none_without_names_and_reads_only_named_rows():
    client = Client()
    assert targeted_scope(client) is None
    scope = targeted_scope(client, reference_ids=["a"])
    assert {row["id"] for row in scope["references"]} == {"a-v1", "a-v2"}
    assert [row["id"] for row in scope["attachments"]] == ["x"]
    assert client.listed == []
