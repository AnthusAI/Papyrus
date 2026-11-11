"""The writing resolver: the publication's writing guidelines with a section's laid over them (rules in ``layering.py``, fields in ``document.py``)."""
from __future__ import annotations

from .layering import resolve_guidelines
from .store import GuidelineStore


def resolve_writing(store: GuidelineStore, section: str | None = None) -> dict:
    return resolve_guidelines(store, "writing", section)
