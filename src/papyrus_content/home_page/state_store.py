"""Where the home-page task keeps what it carries from one run to the next: the private state, and the list of rows that changed.

Both live in the projection lock table (hash key ``publication``), the table every projection lease already uses, under keys of their own, so a
site needs no new table and no new permission beyond ``GetItem`` and ``UpdateItem`` that its content-actions function already has:

* ``home-page-state#<scope>``: the header (``fingerprint``, ``snapshotSha`` and a digest of every entry), written last, so a run that stopped half
  way leaves a header that does not match and the next run reads the corpus once;
* ``home-page-state#<scope>#<digit>``: sixteen shards of the standings by the first hex digit of the public key, each a compressed JSON object,
  written only when its content changed. A shard is limited by the item size of DynamoDB (400 KB), which holds roughly 190,000 References in all;
  a state that does not fit is not saved and the task reads the corpus each time, as it did before;
* ``home-page-dirty#<scope>``: the string set ``ids`` the stream trigger adds the id of each changed Reference to, and ``messageSeq``, a counter the
  trigger raises for a changed Message. The task reads them, does the work and takes out exactly what it read, so a change that lands meanwhile stays
  for the next run;
* ``home-page-full#<scope>``: ``seq``, raised by the trigger when a window held more changes than one item can list (a mass import): the next run
  reads the corpus once.

``amplify/plugins/home-page/function/handler.py`` writes the dirty and full items with the same names; ``handler_test.py`` proves the two agree.
"""

from __future__ import annotations

import hashlib
import json
import zlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .export import Standing
from .incremental import StoredState

STATE_PREFIX = "home-page-state#"
DIRTY_PREFIX = "home-page-dirty#"
FULL_PREFIX = "home-page-full#"
SHARDS = "0123456789abcdef"
CONDITION_FAILED = "ConditionalCheckFailedException"


def state_key(scope: str) -> str:
    return f"{STATE_PREFIX}{scope}"


def shard_key(scope: str, digit: str) -> str:
    return f"{STATE_PREFIX}{scope}#{digit}"


def dirty_key(scope: str) -> str:
    return f"{DIRTY_PREFIX}{scope}"


def full_key(scope: str) -> str:
    return f"{FULL_PREFIX}{scope}"


def _is_condition_failure(error: Exception) -> bool:
    return getattr(error, "response", {}).get("Error", {}).get("Code") == CONDITION_FAILED


def _bytes_of(value: Any) -> bytes:
    return bytes(value.value) if hasattr(value, "value") else bytes(value)


def _shard_digit(key: str) -> str:
    return key[:1] if key[:1] in SHARDS else "0"


def entries_digest(entries: Mapping[str, Standing]) -> str:
    material = json.dumps({key: standing.to_json() for key, standing in sorted(entries.items())}, separators=(",", ":"))
    return hashlib.sha256(material.encode()).hexdigest()


class MemoryStateStore:
    """The state in memory: what a test (and a one-off run that has nowhere to keep it) uses."""

    def __init__(self) -> None:
        self.state: StoredState | None = None
        self.saves = 0

    def load(self) -> StoredState | None:
        return self.state

    def save(self, state: StoredState) -> None:
        self.state = state
        self.saves += 1


class DynamoStateStore:
    """The state in the projection lock table, in shards."""

    def __init__(self, table: Any, scope: str) -> None:
        self.table, self.scope = table, scope
        self._shards: dict[str, bytes] = {}

    def load(self) -> StoredState | None:
        header = self.table.get_item(Key={"publication": state_key(self.scope)}, ConsistentRead=True).get("Item")
        if not header:
            return None
        entries: dict[str, Standing] = {}
        self._shards = {}
        for digit in SHARDS:
            item = self.table.get_item(Key={"publication": shard_key(self.scope, digit)}, ConsistentRead=True).get("Item")
            if not item:
                continue
            blob = _bytes_of(item["entries"])
            self._shards[digit] = blob
            entries.update({key: Standing.from_json(value) for key, value in json.loads(zlib.decompress(blob)).items()})
        if entries_digest(entries) != header.get("entriesDigest"):
            return None
        return StoredState(fingerprint=str(header["fingerprint"]), snapshot_sha=str(header["snapshotSha"]), entries=entries)

    def save(self, state: StoredState) -> None:
        grouped: dict[str, dict[str, list[Any]]] = {digit: {} for digit in SHARDS}
        for key, standing in state.entries.items():
            grouped[_shard_digit(key)][key] = standing.to_json()
        for digit, content in grouped.items():
            blob = zlib.compress(json.dumps(content, sort_keys=True, separators=(",", ":")).encode(), 6)
            if self._shards.get(digit) == blob or (not content and digit not in self._shards):
                continue
            self.table.put_item(Item={"publication": shard_key(self.scope, digit), "entries": blob})
            self._shards[digit] = blob
        self.table.put_item(
            Item={
                "publication": state_key(self.scope),
                "fingerprint": state.fingerprint,
                "snapshotSha": state.snapshot_sha,
                "entriesDigest": entries_digest(state.entries),
            }
        )


@dataclass(frozen=True)
class DirtyBatch:
    """What changed since the last run, as the stream trigger recorded it."""

    ids: frozenset[str] = frozenset()
    message_seq: int = 0
    full_seq: int = 0

    @property
    def full(self) -> bool:
        return self.full_seq > 0

    @property
    def messages(self) -> bool:
        return self.message_seq > 0


@dataclass
class DirtyStore:
    """Reads the list of changed rows and, once the run has succeeded, takes out exactly the entries it read."""

    table: Any
    scope: str
    reads: int = field(default=0, init=False)

    def read(self) -> DirtyBatch:
        dirty = self.table.get_item(Key={"publication": dirty_key(self.scope)}, ConsistentRead=True).get("Item") or {}
        full = self.table.get_item(Key={"publication": full_key(self.scope)}, ConsistentRead=True).get("Item") or {}
        self.reads += 1
        return DirtyBatch(
            ids=frozenset(str(identifier) for identifier in dirty.get("ids") or ()),
            message_seq=int(dirty.get("messageSeq") or 0),
            full_seq=int(full.get("seq") or 0),
        )

    def acknowledge(self, batch: DirtyBatch) -> None:
        if batch.ids:
            self.table.update_item(Key={"publication": dirty_key(self.scope)}, UpdateExpression="DELETE ids :read", ExpressionAttributeValues={":read": set(batch.ids)})
        if batch.messages:
            self._clear(dirty_key(self.scope), "messageSeq", batch.message_seq)
        if batch.full:
            self._clear(full_key(self.scope), "seq", batch.full_seq)

    def _clear(self, key: str, attribute: str, seen: int) -> None:
        try:
            self.table.update_item(
                Key={"publication": key},
                UpdateExpression=f"REMOVE {attribute}",
                ConditionExpression=f"{attribute} = :seen",
                ExpressionAttributeValues={":seen": seen},
            )
        except Exception as error:  # noqa: BLE001 - botocore ClientError; a counter raised since we read it stays for the next run
            if not _is_condition_failure(error):
                raise
