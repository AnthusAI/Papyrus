"""The reader privacy scan: nothing that identifies a person may appear in projected pages or snapshot files.

Person ids are random UUIDs, the same shape as a ``readerId``, so the scan allows exactly the reader ids that
profiles publish on purpose and fails on every other UUID, on any ``ss1_`` or ``ssdev_`` site subject, on any
email address and on any ``person`` id spelling.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

SITE_SUBJECT = re.compile(r"ss(?:1|dev)_[A-Za-z0-9_-]{8,}")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]*[A-Za-z][A-Za-z0-9-]*\.)+[A-Za-z]{2,}")
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
PERSON_ID = re.compile(r"person[-_ ]?id|\bperson[-_][A-Za-z0-9-]{6,}|\bprs_[A-Za-z0-9]+", re.IGNORECASE)


def identity_leaks(text: str, allowed_reader_ids: Iterable[str] = ()) -> list[str]:
    allowed = {reader_id.lower() for reader_id in allowed_reader_ids}
    leaks = [match.group(0) for pattern in (SITE_SUBJECT, EMAIL, PERSON_ID) for match in pattern.finditer(text)]
    leaks += [match.group(0) for match in UUID.finditer(text) if match.group(0).lower() not in allowed]
    return leaks


def scan_files(files: Mapping[str, bytes | str], allowed_reader_ids: Iterable[str] = ()) -> dict[str, list[str]]:
    """The leaks per file name; empty when the output is clean."""
    allowed = list(allowed_reader_ids)
    found: dict[str, list[str]] = {}
    for name, body in files.items():
        text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
        leaks = identity_leaks(text, allowed)
        if leaks:
            found[name] = leaks
    return found
