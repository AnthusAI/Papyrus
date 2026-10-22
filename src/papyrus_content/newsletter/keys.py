"""The site's newsletter key (an SSM SecureString) and the two keys derived from it."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

HKDF_SALT = b"papyrus-newsletter"
_cache: dict[str, "Keys"] = {}


@dataclass(frozen=True)
class Keys:
    hash: bytes
    token: bytes


def hkdf_sha256(secret: bytes, info: bytes, length: int = 32, salt: bytes = HKDF_SALT) -> bytes:
    """RFC 5869 extract-and-expand with SHA-256 (``length`` up to 255 * 32 bytes)."""
    pseudo_random_key = hmac.new(salt, secret, hashlib.sha256).digest()
    output, block = b"", b""
    counter = 1
    while len(output) < length:
        block = hmac.new(pseudo_random_key, block + info + bytes([counter]), hashlib.sha256).digest()
        output += block
        counter += 1
    return output[:length]


def derive_keys(secret: str) -> Keys:
    if len(secret) < 32:
        raise ValueError("The newsletter key is too short.")
    material = secret.encode("utf-8")
    return Keys(hash=hkdf_sha256(material, b"hash"), token=hkdf_sha256(material, b"token"))


def load_keys(parameter_name: str, ssm_client: Any = None) -> Keys:
    """Read the parameter once per container. The value is never logged or returned."""
    cached = _cache.get(parameter_name)
    if cached is not None:
        return cached
    if ssm_client is None:
        import boto3

        ssm_client = boto3.client("ssm")
    value = ssm_client.get_parameter(Name=parameter_name, WithDecryption=True)["Parameter"]["Value"]
    keys = derive_keys(value)
    _cache[parameter_name] = keys
    return keys
