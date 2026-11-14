"""Retry memory: a Reference (or pack) whose draft was rejected is written again only when the newsroom learns something new about it
(docs/idea-context-packs.md, "More than a summary"; ticket PPY-3ccdcb).

A rejected draft files nothing, so nothing marks the Reference as drafted, and without a memory every run would write it again, pay for the model twice
(the draft and the point check) and, because the queue is ordered best first, possibly spend the whole run on the same few References while others wait.
The memory is a record of what was rejected and against which connections:

* single item, subject ``reference:<lineage id>``: the connections are the ones ``connections.Connections`` holds: the accept reason's text, each comment's
  text, each related Reference with how it is linked (a suggested link that an editor confirms is a new connection), and each editors' explanation.
* pack, subject ``pack:<signal>:<anchor>``: the accepted References in the pack, each comment's text, each link between two members with how it is linked,
  and each editors' explanation on a link.

``new_connections`` is the whole rule: a subject is written again only if it has a connection its last rejection was not made against. There is no
count, no window and no delay: a connection that disappears does not matter, one that appears does, and a subject nobody adds to is left alone for as long
as that is true. Only a rejection of the draft is remembered (citation rules, the point check's verdict, or a writer with no point to make). A model or
transport error says nothing about the Reference, so it is not remembered and the next run tries again.

Where the memory lives is the caller's: a dict (tests), files under the ideas directory (the CLI) or the router's own table (the Lambda).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

ALREADY_REJECTED = "already_rejected"   # the skip reason: rejected before, and nothing new is known about it
REMEMBERED_REASONS = ("citation_check_failed", "point_check_failed", "no_point_offered")


def digest(text: Any) -> str:
    return hashlib.sha256(" ".join(str(text or "").split()).encode()).hexdigest()[:12]


def single_subject(lineage_id: str) -> str:
    return f"reference:{lineage_id}"


def pack_subject(signal: str, anchor: str) -> str:
    return f"pack:{signal}:{anchor}"


def single_keys(connections: Any) -> frozenset[str]:
    """The connections of one Reference (a ``connections.Connections``) as stable keys."""
    from . import connections as rules

    known = connections.by_handle()
    keys = set()
    if connections.rating is not None:
        keys.add(f"stars:{connections.rating}")   # a changed rating is something new the newsroom knows: a rejected idea is written again
    for entry in connections.entries:
        if entry.kind == rules.ACCEPT_REASON:
            keys.add(f"acceptReason:{digest(entry.grounding)}")
        elif entry.kind == rules.MESSAGE:
            keys.add(f"message:{digest(entry.grounding)}")
        elif entry.kind == rules.NEIGHBOUR:
            keys.add(f"neighbour:{entry.reference.lineage_id}:{entry.reference.provenance}")
        elif entry.kind == rules.EDITORS_EXPLANATION:
            about = known.get(entry.about)
            keys.add(f"explanation:{about.reference.lineage_id if about is not None else entry.about}:{digest(entry.grounding)}")
    return frozenset(keys)


def pack_keys(pack: Any, ids: Mapping[str, str]) -> frozenset[str]:
    """The connections of a pack as stable keys. ``ids`` maps a pack handle to the id the citation check records (``pack_stories.PackHandles.ids``)."""
    keys = {f"reference:{lineage}" for lineage in pack.accepted_lineage_ids}
    keys.update(f"stars:{lineage}:{rating['editorStars']}" for lineage, rating in zip(pack.accepted_lineage_ids, pack.references) if rating.get("editorStars"))
    keys.update(f"message:{digest(row.get('text'))}" for row in pack.messages)
    for row in pack.edges:
        first, second = ids.get(str(row.get("from")), str(row.get("from"))), ids.get(str(row.get("to")), str(row.get("to")))
        keys.add(f"link:{first}>{second}:{row.get('provenance')}")
        explanation = row.get("editorsExplanation")
        if isinstance(explanation, Mapping) and explanation.get("text"):
            keys.add(f"explanation:{first}>{second}:{digest(explanation['text'])}")
    return frozenset(keys)


def new_connections(keys: Iterable[str], remembered: Mapping[str, Any] | None) -> list[str]:
    """Connections that exist now and were not there at the last rejection; everything, when nothing was rejected before."""
    known = set((remembered or {}).get("connections") or [])
    return sorted(set(keys) - known)


def is_waiting(keys: Iterable[str], remembered: Mapping[str, Any] | None) -> bool:
    """True when the subject was rejected and nothing new is known about it."""
    return remembered is not None and not new_connections(keys, remembered)


def rejection(subject: str, *, run_id: str, at: str, reasons: Sequence[str], keys: Iterable[str], remembered: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """What to remember: this rejection's reasons, and every connection it was made against (the earlier ones too, so one that comes back is not new)."""
    return {
        "subject": subject, "rejectedAt": at, "runId": run_id, "reasons": sorted(set(reasons)),
        "connections": sorted(set(keys) | set((remembered or {}).get("connections") or [])),
        "rejections": int((remembered or {}).get("rejections") or 0) + 1,
    }


class RetryMemory(Protocol):
    def recall(self, subject: str) -> Mapping[str, Any] | None: ...

    def remember(self, subject: str, record: Mapping[str, Any]) -> None: ...


class DictMemory:
    """In memory; tests use it, and a caller may seed ``records``."""

    def __init__(self, records: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self.records: dict[str, dict[str, Any]] = {key: dict(value) for key, value in (records or {}).items()}

    def recall(self, subject: str) -> Mapping[str, Any] | None:
        return self.records.get(subject)

    def remember(self, subject: str, record: Mapping[str, Any]) -> None:
        self.records[subject] = dict(record)


class CallbackMemory:
    """The router's: two functions over its table."""

    def __init__(self, recall: Callable[[str], Mapping[str, Any] | None], remember: Callable[[str, Mapping[str, Any]], None]) -> None:
        self._recall, self._remember = recall, remember

    def recall(self, subject: str) -> Mapping[str, Any] | None:
        return self._recall(subject)

    def remember(self, subject: str, record: Mapping[str, Any]) -> None:
        self._remember(subject, record)


class JsonMemory:
    """Files under ``<ideas directory>/rejected/``, one per subject (the CLI's, beside its ideas and run ledgers)."""

    def __init__(self, store: Any) -> None:
        self.directory = Path(store.root) / "rejected"

    def path(self, subject: str) -> Path:
        return self.directory / f"{digest(subject)}.json"

    def recall(self, subject: str) -> Mapping[str, Any] | None:
        path = self.path(subject)
        if not path.is_file():
            return None
        try:
            found = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return None
        return found if isinstance(found, dict) and found.get("subject") == subject else None

    def remember(self, subject: str, record: Mapping[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path(subject).write_text(json.dumps(dict(record), indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def sort_key(publication_id: str, subject: str) -> str:
    """The router table's sort key for one subject's memory."""
    return f"IDEA_REJECTED#{publication_id}#{hashlib.sha256(subject.encode()).hexdigest()[:24]}"
