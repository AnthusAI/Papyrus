"""Email address normalization, validation and the subscriber id (``hid``)."""

from __future__ import annotations

import hashlib
import hmac
import re

MAXIMUM_ADDRESS_CHARACTERS = 254
MAXIMUM_LOCAL_CHARACTERS = 64
HID_CHARACTERS = 32

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_LOCAL = r"[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
_ADDRESS = re.compile(rf"{_LOCAL}@{_LABEL}(?:\.{_LABEL})+")


def normalize(address: str) -> str:
    """Trim and lowercase the whole address, so one mailbox has one subscriber id."""
    return address.strip().lower()


def is_valid(address: object) -> bool:
    """True for a plain, normalized address of the form local part, at sign, domain. Anything else is not mail we can send to."""
    if not isinstance(address, str) or not 0 < len(address) <= MAXIMUM_ADDRESS_CHARACTERS:
        return False
    if address != normalize(address):
        return False
    local, _, _domain = address.partition("@")
    if len(local) > MAXIMUM_LOCAL_CHARACTERS:
        return False
    return _ADDRESS.fullmatch(address) is not None


def hmac_hex(key: bytes, value: str) -> str:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def hid(hash_key: bytes, address: str) -> str:
    """The subscriber id: hex(HMAC-SHA256(hashKey, normalized address))[:32]."""
    return hmac_hex(hash_key, normalize(address))[:HID_CHARACTERS]


def ip_hash(hash_key: bytes, ip: str) -> str:
    """Addresses of visitors are only ever stored or counted hashed with the site's hash key."""
    return hmac_hex(hash_key, "ip:" + ip)[:HID_CHARACTERS]
