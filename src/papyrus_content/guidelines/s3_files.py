"""The guideline document files in the function that serves the door: S3 directly, with the function's own role (PPY-8d41d7).

The command line moves a document through the ModelAttachment upload and download slots (``store.ModelAttachmentFiles``), which are presigned by another
function and need the person's own session. The image-service function has no such session, so it reads and writes the one file itself, in the payload
bucket, and writes the ``ModelAttachment`` row that names it. Its role may touch only ``newsroom/payloads/item/``; this class refuses any other path before
asking S3, so a mistake here fails with a plain error and not with an access-denied from the bucket.

``boto3`` is imported when a file is first touched, so importing this module needs nothing outside the standard library.
"""
from __future__ import annotations

import os
from typing import Any

PAYLOAD_PREFIX = "newsroom/payloads/item/"
BUCKET_VARIABLES = ("papyrusMedia_BUCKET_NAME", "PAPYRUS_MEDIA_BUCKET_NAME", "STORAGE_BUCKET_NAME", "AMPLIFY_STORAGE_BUCKET_NAME")


def bucket_from(env: Any) -> str:
    for name in BUCKET_VARIABLES:
        if str(env.get(name) or "").strip():
            return str(env[name]).strip()
    raise RuntimeError("The payload bucket is not named in this function's environment.")


class S3DocumentFiles:
    """``DocumentFiles`` (store.py) over S3 and the site's own data API."""

    def __init__(self, client: Any, *, bucket: str | None = None, s3: Any = None, env: Any = None):
        self.client = client
        self._bucket = bucket
        self._s3 = s3
        self._env = os.environ if env is None else env

    @property
    def bucket(self) -> str:
        if not self._bucket:
            self._bucket = bucket_from(self._env)
        return self._bucket

    @property
    def s3(self) -> Any:
        if self._s3 is None:
            import boto3

            self._s3 = boto3.client("s3")
        return self._s3

    @staticmethod
    def _path(attachment: dict) -> str:
        path = str(attachment.get("storagePath") or "")
        if not path.startswith(PAYLOAD_PREFIX) or ".." in path:
            raise ValueError(f"Guideline documents live under {PAYLOAD_PREFIX}; refused {path!r}.")
        return path

    def put(self, attachment: dict, body: bytes) -> dict:
        path = self._path(attachment)
        self.s3.put_object(Bucket=self.bucket, Key=path, Body=body, ContentType=attachment.get("mediaType") or "application/json")
        self.client.create_record("ModelAttachment", attachment)   # the file first, so a failed row never names a file that is not there
        return attachment

    def get(self, attachment: dict) -> bytes | None:
        path = self._path(attachment)
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=path)["Body"].read()
        except Exception as error:   # a missing key is the one expected failure; anything else is raised for the caller to log
            if type(error).__name__ == "NoSuchKey" or getattr(error, "response", {}).get("Error", {}).get("Code") == "NoSuchKey":
                return None
            raise
