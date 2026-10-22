"""The reader feedback export: reader comments, with the rating each one explains, as JSON Lines for the Cyclotron loop.

A reader's comment is a steering signal. When it was written at rating time it carries the rating it explains
(``ratingContext``), and the export puts that text rationale next to the vote. Records are attributed by ``readerId``
(the public random id) and carry ``source: "reader"``, so the loop can keep them apart from editor signals. Nothing here
calls Cyclotron and nothing runs in a reader request: ``papyrus reader feedback export --since <time>`` is a pull the
loop makes when it is ready.

Each line is one JSON object::

    {"schema": "papyrus.reader-feedback/v1", "source": "reader", "status": "active", "commentId": "...", "readerId": "...",
     "subject": "<item key or submission id>", "subjectKind": "item" | "submission", "parentId": null,
     "rating": {"dimension": "real", "value": 4} | null, "rationale": "...", "createdAt": "...", "updatedAt": "..."}

A comment that was hidden or deleted after it was exported comes out once more as ``"status": "retracted"`` with no text, so a
consumer that ingested the earlier line can drop it. A line is emitted for a comment whose ``updatedAt`` is after ``--since``;
the consumer keeps the greatest ``updatedAt`` it has seen as the next ``--since``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

SCHEMA = "papyrus.reader-feedback/v1"
SOURCE = "reader"
SUBMISSION_SUBJECT = re.compile(r"sub-[0-9a-f]{24}")
LIST_COMMENTS_QUERY = """
query ListReaderComments($limit: Int, $nextToken: String) {
  listReaderComments(limit: $limit, nextToken: $nextToken) {
    items { id subjectKey readerId body parentId ratingContext state editedAt deletedAt createdAt updatedAt }
    nextToken
  }
}
"""


def parsed_context(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if isinstance(value, Mapping) and isinstance(value.get("dimension"), str) and isinstance(value.get("value"), int):
        return {"dimension": value["dimension"], "value": value["value"]}
    return None


def feedback_record(comment: Mapping[str, Any]) -> dict[str, Any]:
    subject = comment["subjectKey"]
    record: dict[str, Any] = {
        "schema": SCHEMA,
        "source": SOURCE,
        "status": "active" if comment.get("state") == "visible" else "retracted",
        "commentId": comment["id"],
        "readerId": comment["readerId"],
        "subject": subject,
        "subjectKind": "submission" if SUBMISSION_SUBJECT.fullmatch(subject) else "item",
        "parentId": comment.get("parentId") or None,
        "createdAt": comment["createdAt"],
        "updatedAt": comment.get("updatedAt") or comment["createdAt"],
    }
    if record["status"] == "active":
        record["rating"] = parsed_context(comment.get("ratingContext"))
        record["rationale"] = comment["body"]
    return record


def feedback_records(comments: Iterable[Mapping[str, Any]], since: str | None = None) -> Iterator[dict[str, Any]]:
    """Records for comments updated after ``since`` (an ISO time; every comment when ``None``), oldest update first."""
    records = [feedback_record(comment) for comment in comments]
    wanted = [record for record in records if since is None or record["updatedAt"] > since]
    yield from sorted(wanted, key=lambda record: (record["updatedAt"], record["commentId"]))


def encode_lines(records: Iterable[Mapping[str, Any]]) -> str:
    return "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n" for record in records)


def list_comments(client: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    next_token = None
    while True:
        result = client.graphql(LIST_COMMENTS_QUERY, {"limit": 500, "nextToken": next_token})
        page = result.get("listReaderComments") or {}
        rows.extend(item for item in page.get("items") or [] if item)
        next_token = page.get("nextToken")
        if not next_token:
            return rows
