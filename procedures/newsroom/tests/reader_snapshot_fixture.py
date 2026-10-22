"""Prints the snapshot files of a fixture site with votes and profiles as JSON, for the TypeScript privacy scan (scripts/test-reader-snapshot-privacy.ts)."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from papyrus_content.reader_steering.snapshot import (  # noqa: E402
    BOARD_FILE,
    ITEMS_FILE,
    READERS_FILE,
    SUBMISSIONS_FILE,
    KarmaWeights,
    comments_key,
    SnapshotSettings,
    build_snapshot,
    encoded,
)

NOW = 1_800_000_000.0
READER_IDS = [str(uuid.UUID(int=number)) for number in (1, 2, 3)]
SITE_SUBJECT = "ss1_" + "A" * 43
PERSON_ID = str(uuid.UUID(int=9))


def main() -> None:
    profiles = [
        {"id": SITE_SUBJECT, "siteSubject": SITE_SUBJECT, "readerId": reader_id, "handle": f"reader-{number}", "email": "reader@example.test", "personId": PERSON_ID, "karma": 0}
        for number, reader_id in enumerate(READER_IDS)
    ]
    votes = [
        {"subjectKey": "item-one", "readerId": reader_id, "dimension": dimension, "value": 1 if dimension == "up" else 4, "voterRole": "reader", "createdAt": "2026-10-21T10:00:00Z"}
        for reader_id in READER_IDS
        for dimension in ("up", "real")
    ]
    submissions = [
        {
            "id": "sub-" + "a" * 24, "canonicalUrl": "https://example.com/post", "domain": "example.com", "title": "A small tool", "kind": "link",
            "note": "Worked well", "readerId": READER_IDS[0], "state": "pending", "similar": [], "createdAt": "2026-10-21T09:00:00Z",
            "signals": '[{"detector":"buy-now"}]', "extractionState": "pending", "siteSubject": SITE_SUBJECT, "email": "reader@example.test",
        }
    ]
    comments = [
        {
            "id": "cmt-" + "b" * 32, "subjectKey": "item-one", "readerId": READER_IDS[1], "body": "The benchmarks held up.", "state": "visible",
            "createdAt": "2026-10-21T09:30:00.000Z", "ratingContext": '{"dimension":"real","value":4}', "signals": "[]",
            "siteSubject": SITE_SUBJECT, "email": "reader@example.test",
        }
    ]
    result = build_snapshot(
        votes,
        profiles,
        published_at={"item-one": "2026-10-20T10:00:00Z"},
        now_seconds=NOW,
        settings=SnapshotSettings(dimensions=("real",), karma=KarmaWeights()),
        submitter_of=lambda subject: READER_IDS[0],
        submissions=submissions,
        comments=comments,
    )
    files = {ITEMS_FILE: result.items, BOARD_FILE: result.board, READERS_FILE: result.readers, SUBMISSIONS_FILE: result.submissions, **{key: result.comments[subject] for subject in result.comments for key in [comments_key(subject)]}}
    print(json.dumps({"readerIds": READER_IDS, "files": {name: encoded(payload).decode("utf-8") for name, payload in files.items()}}))


main()
