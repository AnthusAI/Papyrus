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
