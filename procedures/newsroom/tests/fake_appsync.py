"""An in-memory AppSync endpoint for the request meter and batched-read tests: it answers get and index queries (aliased or not), pages index
queries by `limit` and `nextToken`, and records every request it receives (one entry per HTTP request, the way AppSync bills)."""
from __future__ import annotations

import json
import re
from typing import Any

FIELD = re.compile(r"(?:(\w+)\s*:\s*)?\b(get\w+|list\w+)\(([^)]*)\)\s*\{")


class FakeAppSync:
    def __init__(self, gets: dict[str, dict[str, dict]] | None = None, indexes: dict[str, dict[str, list[dict]]] | None = None) -> None:
        self.gets = gets or {}          # {"getReference": {id: row}}
        self.indexes = indexes or {}    # {"listSemanticRelationsBySubjectState": {key: [rows]}}
        self.requests: list[str] = []   # the query text of each request

    # http.client.HTTPSConnection stand-in -----------------------------------------------------
    def connection_factory(self, *_args: Any, **_kwargs: Any) -> "FakeAppSync":
        return self

    def request(self, _method: str, _path: str, body: bytes, headers: dict) -> None:
        self._payload = json.loads(body)

    def getresponse(self) -> "FakeAppSync":
        query, variables = self._payload["query"], self._payload.get("variables") or {}
        self.requests.append(query)
        data: dict[str, Any] = {}
        for alias, field, arguments in FIELD.findall(query):
            args = dict(re.findall(r"(\w+):\s*(\$?\w+)", arguments))
            resolved = {name: variables.get(value[1:]) if value.startswith("$") else value for name, value in args.items()}
            if field.startswith("get"):
                data[alias or field] = (self.gets.get(field) or {}).get(resolved["id"])
            else:
                key_name = next((name for name in resolved if name not in ("limit", "nextToken", "sortDirection")), None)
                rows = list((self.indexes.get(field) or {}).get(resolved[key_name] if key_name else "") or [])
                limit = int(resolved.get("limit") or 100)
                start = int(resolved.get("nextToken") or 0)
                page = rows[start:start + limit]
                more = start + limit < len(rows)
                data[alias or field] = {"items": page, "nextToken": str(start + limit) if more else None}
        self._body = json.dumps({"data": data})
        return self

    status, reason = 200, "OK"

    def read(self) -> bytes:
        return self._body.encode()

    def close(self) -> None:
        pass
