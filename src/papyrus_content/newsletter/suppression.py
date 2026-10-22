"""What the sender imports: ``is_suppressed(hid)``. Reads the table named by ``TABLE_NAME`` unless given a store."""

from __future__ import annotations

import os

from . import records
from .store import Store

_default: Store | None = None


def default_store() -> Store:
    global _default
    if _default is None:
        _default = Store(os.environ["TABLE_NAME"])
    return _default


def is_suppressed(hid: str, store: Store | None = None) -> bool:
    """True when the address must never be mailed (a permanent bounce, a complaint or a manual suppression)."""
    return records.get_suppression(store or default_store(), hid) is not None
