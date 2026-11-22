from __future__ import annotations

import pytest
from botocore.exceptions import ClientError

from papyrus_content.agent_policy.dynamo_catalogue import DynamoCatalogueTable


def failed_condition():
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "no"}}, "PutItem")


class FakeTable:
    name = "versions"

    def __init__(self, fail=False):
        self.fail, self.calls = fail, []
        self.meta = type("Meta", (), {"client": self})()

    def put_item(self, **arguments):
        self.calls.append(("put", arguments))
        if self.fail:
            raise failed_condition()

    def update_item(self, **arguments):
        self.calls.append(("update", arguments))
        if self.fail:
            raise failed_condition()

    def describe_table(self, TableName):
        return {"Table": {"GlobalSecondaryIndexes": [{"IndexName": "gsi-other", "KeySchema": [{"AttributeName": "tenantId"}]},
                                                      {"IndexName": "gsi-by-document", "KeySchema": [{"AttributeName": "documentId"}, {"AttributeName": "version"}]}]}}

    def query(self, **arguments):
        self.calls.append(("query", arguments))
        return {"Items": [{"id": "alpha#agents#3", "version": 3}]}


def test_creating_an_existing_row_is_a_key_error_and_never_overwrites():
    table = FakeTable(fail=True)
    with pytest.raises(KeyError):
        DynamoCatalogueTable({"SiteDocumentVersion": table}).create("SiteDocumentVersion", {"id": "alpha#agents#1", "note": None})
    assert table.calls[0][1]["ConditionExpression"] == "attribute_not_exists(id)" and "note" not in table.calls[0][1]["Item"]


def test_moving_the_pointer_is_conditional_on_the_version_it_started_from():
    table = FakeTable()
    assert DynamoCatalogueTable({"SiteDocument": table}).update_if("SiteDocument", "alpha#agents", {"currentVersion": 2}, {"currentVersion": 1}) is True
    arguments = table.calls[0][1]
    assert arguments["ConditionExpression"] == "#e0 = :e0" and arguments["ExpressionAttributeValues"][":e0"] == 1 and arguments["ExpressionAttributeValues"][":c0"] == 2
    assert DynamoCatalogueTable({"SiteDocument": FakeTable(fail=True)}).update_if("SiteDocument", "x", {"a": 1}, {"a": 0}) is False


def test_the_latest_version_is_read_from_the_index_that_has_the_document_key():
    table = FakeTable()
    assert DynamoCatalogueTable({"SiteDocumentVersion": table}).latest_version("alpha#agents") == {"id": "alpha#agents#3", "version": 3}
    assert table.calls[0][1]["IndexName"] == "gsi-by-document" and table.calls[0][1]["Limit"] == 1 and table.calls[0][1]["ScanIndexForward"] is False
