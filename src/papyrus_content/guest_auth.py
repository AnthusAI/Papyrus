"""Guest (Cognito identity pool, unauthenticated) read access for reader builds.

PublishedItem and PublishedMediaAsset are guest-readable and ``media/*`` is
guest-readable in storage, so a static reader build can export published
content with no stored credentials. Only ``export-published`` may use this
lane; every other command refuses it.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .env import PAPYRUS_ROOT, amplify_outputs_path

GUEST_AUTH_ENVIRONMENT_VARIABLE = "PAPYRUS_GRAPHQL_AUTH"
GUEST_AUTH_VALUE = "guest"
CREDENTIAL_REFRESH_MARGIN = timedelta(seconds=60)


@dataclass(frozen=True)
class GuestConfiguration:
    endpoint: str
    identity_pool_id: str
    bucket: str | None
    region: str


def guest_auth_requested(auth_option: Any = None) -> bool:
    explicit = auth_option if isinstance(auth_option, str) else ""
    configured = explicit or os.environ.get(GUEST_AUTH_ENVIRONMENT_VARIABLE, "")
    return configured.strip().lower() == GUEST_AUTH_VALUE


def refuse_guest_auth(command_label: str) -> None:
    if os.environ.get(GUEST_AUTH_ENVIRONMENT_VARIABLE, "").strip().lower() == GUEST_AUTH_VALUE:
        raise ValueError(
            f"{GUEST_AUTH_ENVIRONMENT_VARIABLE}=guest is read-only and only valid for "
            f"'content export-published'; refusing '{command_label}'."
        )


def _read_amplify_outputs() -> dict[str, Any]:
    path = amplify_outputs_path()
    if not path.is_absolute():
        path = PAPYRUS_ROOT / path
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _region_from_endpoint(endpoint: str) -> str | None:
    match = re.search(r"\.appsync-api\.([a-z0-9-]+)\.amazonaws\.com", urllib.parse.urlparse(endpoint).netloc)
    return match.group(1) if match else None


def resolve_guest_configuration(explicit_bucket: str | None = None) -> GuestConfiguration:
    outputs = _read_amplify_outputs()
    endpoint = os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT", "").strip() or str((outputs.get("data") or {}).get("url") or "")
    identity_pool_id = os.environ.get("PAPYRUS_IDENTITY_POOL_ID", "").strip() or str(
        (outputs.get("auth") or {}).get("identity_pool_id") or ""
    )
    storage = outputs.get("storage") or {}
    bucket = (
        explicit_bucket
        or os.environ.get("PAPYRUS_MEDIA_BUCKET", "").strip()
        or storage.get("bucket_name")
        or None
    )
    region = (
        os.environ.get("AWS_REGION", "").strip()
        or str(outputs.get("aws_region") or "")
        or _region_from_endpoint(endpoint)
        or (identity_pool_id.split(":")[0] if ":" in identity_pool_id else "")
    )
    missing = [
        name
        for name, value in (
            ("PAPYRUS_GRAPHQL_ENDPOINT (or data.url)", endpoint),
            ("PAPYRUS_IDENTITY_POOL_ID (or auth.identity_pool_id)", identity_pool_id),
            ("AWS_REGION (or aws_region)", region),
        )
        if not value
    ]
    if missing:
        raise ValueError("Guest auth is missing: " + ", ".join(missing) + ".")
    return GuestConfiguration(endpoint=endpoint, identity_pool_id=identity_pool_id, bucket=bucket, region=region)


class GuestSession:
    def __init__(self, configuration: GuestConfiguration, *, identity_client: Any = None) -> None:
        self.configuration = configuration
        self._identity_client = identity_client
        self._credentials: dict[str, Any] | None = None

    def _client(self) -> Any:
        if self._identity_client is None:
            import boto3
            from botocore import UNSIGNED
            from botocore.config import Config

            self._identity_client = boto3.client(
                "cognito-identity",
                region_name=self.configuration.region,
                config=Config(signature_version=UNSIGNED),
            )
        return self._identity_client

    def credentials(self) -> dict[str, Any]:
        current = self._credentials
        if current is not None and current["Expiration"] - datetime.now(timezone.utc) > CREDENTIAL_REFRESH_MARGIN:
            return current
        client = self._client()
        identity_id = client.get_id(IdentityPoolId=self.configuration.identity_pool_id)["IdentityId"]
        issued = client.get_credentials_for_identity(IdentityId=identity_id)["Credentials"]
        expiration = issued.get("Expiration") or datetime.now(timezone.utc) + timedelta(hours=1)
        self._credentials = {
            "AccessKeyId": issued["AccessKeyId"],
            "SecretKey": issued["SecretKey"],
            "SessionToken": issued["SessionToken"],
            "Expiration": expiration,
        }
        return self._credentials

    def appsync_headers(self, body: bytes) -> dict[str, str]:
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        from botocore.credentials import Credentials

        granted = self.credentials()
        frozen = Credentials(granted["AccessKeyId"], granted["SecretKey"], granted["SessionToken"])
        request = AWSRequest(
            method="POST",
            url=self.configuration.endpoint,
            data=body,
            headers={
                "content-type": "application/json",
                "host": urllib.parse.urlparse(self.configuration.endpoint).netloc,
            },
        )
        SigV4Auth(frozen, "appsync", self.configuration.region).add_auth(request)
        return {str(key): str(value) for key, value in request.headers.items()}

    def s3_client(self) -> Any:
        import boto3

        granted = self.credentials()
        return boto3.client(
            "s3",
            region_name=self.configuration.region,
            aws_access_key_id=granted["AccessKeyId"],
            aws_secret_access_key=granted["SecretKey"],
            aws_session_token=granted["SessionToken"],
        )
