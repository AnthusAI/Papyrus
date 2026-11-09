"""Which References a topic run looks at: one corpus, a window of SOURCE dates, read through the date index.

``listReferencesByCorpusAndSourcePublishedAt`` (partition corpusId, sort sourcePublishedAt) hands back only the rows whose source date is inside the
window, newest first, one page at a time. Nothing outside the window is read and the table is never scanned. The index cannot say more than
that, so the other choices are made on each returned page: only the current version of a Reference, its vote (default accepted and pending; a
rejected or archived Reference is left out unless the caller asks for rejected), the section its vote was filed under, and the monitor that
delivered it. A Reference with no source date, or with a source date that is not ISO text, is not in the index and is not seen.

``max_references`` is a safety stop and nothing else: when the read reaches it, reading stops, the run is marked ``stopped`` and says so in its
warnings and in the log. It is never applied quietly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

from papyrus_content import request_meter
from papyrus_content.reference_policy import normalize_reference_curation_status

from .windows import Window

INDEX = "referencesByCorpusAndSourcePublishedAt"
DEFAULT_STATES = ("accepted", "pending")
LOG = logging.getLogger("papyrus.topics")


@dataclass(frozen=True)
class Selection:
    """The References chosen for one window, and what the read did."""
    rows: tuple[dict, ...]
    read: int                      # rows the index returned
    stopped: bool = False          # the safety stop (max_references) ended the read early
    warnings: tuple[dict, ...] = field(default_factory=tuple)


def keeps(row: dict, states: Iterable[str], section_id: str | None, monitor: str | None) -> bool:
    if row.get("versionState") not in (None, "current"):
        return False
    if normalize_reference_curation_status(row.get("curationStatus")) not in states:
        return False
    if section_id and row.get("curationSectionId") != section_id:
        return False
    if monitor and row.get("discoveredByMonitorId") != monitor:
        return False
    return True


def select_references(client: Any, corpus_id: str, window: Window, *, states: Iterable[str] = DEFAULT_STATES, section_id: str | None = None,
                      monitor: str | None = None, max_references: int | None = None) -> Selection:
    wanted = tuple(states)
    rows: list[dict] = []
    read = 0
    stopped = False
    with request_meter.model("Reference"):
        for row in client.iterate_index_range(INDEX, corpus_id, window.low, window.high):
            read += 1
            if keeps(row, wanted, section_id, monitor):
                rows.append(row)
            if max_references and len(rows) >= max_references:
                stopped = True
                break
    request_meter.add_units(read)   # the rows read justify the pages asked for
    warnings: tuple[dict, ...] = ()
    if stopped:
        message = (f"Stopped after {len(rows)} References because max_references is {max_references}. "
                   f"The window {window.low[:10]} to {window.high[:10]} has more; the newest {len(rows)} are used.")
        LOG.warning("topics: %s", message)
        warnings = ({"code": "max_references_reached", "message": message},)
    return Selection(rows=tuple(rows), read=read, stopped=stopped, warnings=warnings)
