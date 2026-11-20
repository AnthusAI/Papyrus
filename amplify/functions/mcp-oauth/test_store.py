import importlib.util
import os
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("mcp_store", Path(__file__).with_name("store.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Kms:
    def __init__(self): self.keys = {}
    def generate_data_key(self, *, EncryptionContext, **kwargs):
        data_key, blob = os.urandom(32), os.urandom(32)
        self.keys[blob] = (data_key, EncryptionContext.copy())
        return {"Plaintext": data_key, "CiphertextBlob": blob}
    def decrypt(self, *, CiphertextBlob, EncryptionContext, **kwargs):
        key, expected = self.keys[CiphertextBlob]
        if expected != EncryptionContext: raise ValueError("context mismatch")
        return {"Plaintext": key}


class Dynamo:
    def __init__(self): self.items = {}
    def put_item(self, *, Item, **kwargs): self.items[Item["pk"]["S"]] = Item
    def get_item(self, *, Key, **kwargs): return {"Item": self.items.get(Key["pk"]["S"])}


def test_large_credentials_round_trip_and_are_bound_to_site():
    kms, dynamo = Kms(), Dynamo()
    store = module.DynamoGrantStore(dynamo, kms, "table", "key", "https://one.example")
    value = {"version": 0, "expires": 100, "principal": {"accessToken": "jwt" * 2000}}
    assert store.create("grant", value)
    assert store.get("grant") == value
    assert "jwt" not in str(dynamo.items)
    other = module.DynamoGrantStore(dynamo, kms, "table", "key", "https://two.example")
    with pytest.raises(ValueError, match="context mismatch"):
        other.get("grant")


def test_rotation_transaction_contract_and_consistent_tombstone_read():
    from unittest.mock import Mock
    dynamo, kms = Mock(), Kms()
    store = module.DynamoGrantStore(dynamo, kms, 'table', 'key', 'https://site.example')
    value = {'version': 4, 'expires': 6000, 'storage_expiry': 7000, 'principal': {'idToken': 'secret'}}
    assert store.rotate('grant', 3, value, 'digest')
    request = dynamo.transact_write_items.call_args.kwargs
    grant, spent = [action['Put'] for action in request['TransactItems']]
    assert grant['TableName'] == spent['TableName'] == 'table'
    assert grant['ConditionExpression'] == '#v = :v'
    assert grant['ExpressionAttributeValues'] == {':v': {'N': '3'}}
    assert grant['Item']['version'] == {'N': '4'}
    assert spent['ConditionExpression'] == 'attribute_not_exists(pk)'
    assert spent['Item'] == {'pk': {'S': 'spent#grant#digest'}, 'expiresAt': {'N': '6000'}}
    assert 'secret' not in str(request)
    dynamo.get_item.return_value = {'Item': spent['Item']}
    assert store.is_spent('grant', 'digest')
    dynamo.get_item.assert_called_once_with(TableName='table', Key={'pk': {'S': 'spent#grant#digest'}}, ConsistentRead=True)


def test_transaction_retries_only_contention():
    from unittest.mock import Mock
    class Failure(Exception):
        def __init__(self, code, reasons=None):
            self.response = {'Error': {'Code': code}}
            if reasons is not None: self.response['CancellationReasons'] = [{'Code': value} for value in reasons]
    dynamo = Mock()
    store = module.DynamoGrantStore(dynamo, Kms(), 'table', 'key', 'site')
    value = {'version': 2, 'expires': 100}
    dynamo.transact_write_items.side_effect = Failure('TransactionCanceledException', ['ConditionalCheckFailed', 'None'])
    assert not store.rotate('grant', 1, value, 'digest')
    dynamo.transact_write_items.side_effect = Failure('TransactionCanceledException', ['TransactionConflict', 'None'])
    assert not store.rotate('grant', 1, value, 'digest')
    for error in (Failure('TransactionCanceledException', ['ProvisionedThroughputExceeded', 'None']), Failure('TransactionCanceledException'), Failure('InternalServerError')):
        dynamo.transact_write_items.side_effect = error
        with pytest.raises(Failure): store.rotate('grant', 1, value, 'digest')
