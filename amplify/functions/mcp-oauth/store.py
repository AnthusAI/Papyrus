"""Encrypted DynamoDB grant records with conditional updates."""
import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class DynamoGrantStore:
    def __init__(self, dynamodb, kms, table, key_id, site):
        self.dynamodb, self.kms, self.table, self.key_id, self.site = dynamodb, kms, table, key_id, site

    def _seal(self, key, value):
        plaintext = json.dumps(value, separators=(",", ":")).encode()
        if len(plaintext) > 65536:
            raise ValueError("Grant record too large")
        context = {"site": self.site, "grant": key}
        result = self.kms.generate_data_key(KeyId=self.key_id, KeySpec="AES_256", EncryptionContext=context)
        nonce = os.urandom(12)
        aad = json.dumps(context, sort_keys=True, separators=(",", ":")).encode()
        ciphertext = AESGCM(result["Plaintext"]).encrypt(nonce, plaintext, aad)
        return json.dumps({"key": base64.b64encode(result["CiphertextBlob"]).decode(),
                           "nonce": base64.b64encode(nonce).decode(),
                           "data": base64.b64encode(ciphertext).decode()}, separators=(",", ":"))

    def _item(self, key, value):
        return {"pk": {"S": key}, "version": {"N": str(value["version"])},
                "expiresAt": {"N": str(value["expires"])}, "sealed": {"S": self._seal(key, value)}}

    @staticmethod
    def _conditional_failure(error):
        return getattr(error, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException"

    def create(self, key, value):
        try:
            self.dynamodb.put_item(TableName=self.table, Item=self._item(key, value), ConditionExpression="attribute_not_exists(pk)")
            return True
        except Exception as error:
            if self._conditional_failure(error):
                return False
            raise

    def get(self, key):
        item = self.dynamodb.get_item(TableName=self.table, Key={"pk": {"S": key}}, ConsistentRead=True).get("Item")
        if item is None:
            return None
        envelope = json.loads(item["sealed"]["S"])
        context = {"site": self.site, "grant": key}
        data_key = self.kms.decrypt(KeyId=self.key_id, CiphertextBlob=base64.b64decode(envelope["key"], validate=True),
                                    EncryptionContext=context)["Plaintext"]
        aad = json.dumps(context, sort_keys=True, separators=(",", ":")).encode()
        plaintext = AESGCM(data_key).decrypt(base64.b64decode(envelope["nonce"], validate=True),
                                             base64.b64decode(envelope["data"], validate=True), aad)
        value = json.loads(plaintext)
        if value["version"] != int(item["version"]["N"]):
            raise ValueError("Grant version mismatch")
        return value

    def replace(self, key, version, value):
        try:
            self.dynamodb.put_item(TableName=self.table, Item=self._item(key, value),
                                   ConditionExpression="#v = :v", ExpressionAttributeNames={"#v": "version"},
                                   ExpressionAttributeValues={":v": {"N": str(version)}})
            return True
        except Exception as error:
            if self._conditional_failure(error):
                return False
            raise
