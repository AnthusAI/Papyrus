from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}
        self.put_keys: list[str] = []
        self.page_size = 1000

    def list_objects_v2(self, *, Bucket: str, Prefix: str, ContinuationToken: str | None = None) -> dict[str, Any]:
        keys = sorted(key for key in self.objects if key.startswith(Prefix))
        start = int(ContinuationToken) if ContinuationToken else 0
        page = keys[start : start + self.page_size]
        truncated = start + self.page_size < len(keys)
        response: dict[str, Any] = {"Contents": [{"Key": key} for key in page], "IsTruncated": truncated}
        if truncated:
            response["NextContinuationToken"] = str(start + self.page_size)
        return response

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        return {"Metadata": dict(self.objects[Key]["Metadata"])}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str, CacheControl: str, Metadata: dict[str, str]) -> None:
        self.objects[Key] = {"Body": Body, "ContentType": ContentType, "CacheControl": CacheControl, "Metadata": dict(Metadata)}
        self.put_keys.append(Key)

    def delete_objects(self, *, Bucket: str, Delete: dict[str, Any]) -> None:
        for entry in Delete["Objects"]:
            self.objects.pop(entry["Key"], None)
